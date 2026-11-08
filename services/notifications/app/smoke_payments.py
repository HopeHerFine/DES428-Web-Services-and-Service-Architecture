"""Real browser identities, Booking outbox, Payments PostgreSQL and remote Wallet."""
import json
import random
import time
from datetime import date, timedelta
from urllib.error import HTTPError
from urllib.request import Request
from .smoke_gateway import browser_login, request, ORIGIN


def wait_until(check, label):
    deadline = time.monotonic() + 60
    while True:
        try:
            value = check()
            if value:
                return value
        except HTTPError as error:
            if error.code not in {404, 409, 502, 503}:
                raise
        if time.monotonic() > deadline:
            raise RuntimeError("Timed out waiting for " + label)
        time.sleep(1)


def pay(client, order_id, key):
    req = Request(ORIGIN + "/api/payments/simulate", data=json.dumps({"order_id": order_id}).encode(),
        headers={"Origin": ORIGIN, "Content-Type": "application/json", "Idempotency-Key": key})
    with client.open(req, timeout=30) as response:
        return json.load(response)


def main():
    customer = browser_login("nong@example.com")
    provider = browser_login("sparkle@example.com")
    other = browser_login("fixit@example.com")
    baseline = request(provider, "/api/provider/wallet")
    service = request(customer, "/api/services/2")
    addresses = request(customer, "/api/customer/addresses")

    def book(method):
        for offset in random.sample(range(30, 180), 15):
            day = (date.today() + timedelta(days=offset)).isoformat()
            slots = request(customer, f"/api/providers/1/slots?date={day}&duration={service['duration_min']}")["slots"]
            if slots:
                return request(customer, "/api/bookings", {"provider_id": 1, "address_id": addresses[0]["id"],
                    "service_date": day, "starting_time": slots[0], "items": [{"service_id": 2, "quantity": 1}],
                    "payment_method": method})
        raise RuntimeError("No available integration booking slot")

    placed = book("gateway")
    order = placed["order"]
    order_id = order["id"]
    wait_until(lambda: request(customer, f"/api/payments/intents/{order_id}"), "remote payment intent")
    for client, token, expected in ((other, None, 403), (customer, "forged.invalid.token", 401)):
        try:
            request(client, f"/api/payments/intents/{order_id}", token=token)
        except HTTPError as error:
            assert error.code == expected
        else:
            raise AssertionError("Payment ownership/token validation failed")
    first = pay(customer, order_id, "payment-smoke-" + str(order_id))
    assert pay(customer, order_id, "payment-smoke-" + str(order_id)) == first
    assert pay(customer, order_id, "different-click-" + str(order_id)) == first
    wait_until(lambda: request(customer, f"/api/bookings/{order_id}")["payment_status"] == "paid", "Booking paid projection")
    request(provider, f"/api/bookings/{order_id}/confirm", {})
    request(provider, f"/api/bookings/{order_id}/start", {})
    request(provider, f"/api/bookings/{order_id}/complete", {"otp": placed["otp"]})
    earnings = order["total_cents"] - round(order["total_cents"] * order["commission_pct"] / 100)
    wait_until(lambda: request(provider, "/api/provider/wallet")["balance_cents"] ==
        baseline["balance_cents"] + earnings, "provider remote earnings")
    with provider.open(ORIGIN + "/provider/wallet", timeout=30) as response:
        assert "payout_credit" in response.read().decode(), "SSR Wallet did not display remote ledger"

    cancelled = book("gateway")["order"]["id"]
    wait_until(lambda: request(customer, f"/api/payments/intents/{cancelled}"), "second payment intent")
    pay(customer, cancelled, "cancel-pay-" + str(cancelled))
    request(customer, f"/api/bookings/{cancelled}/cancel", {})
    wait_until(lambda: request(customer, f"/api/bookings/{cancelled}")["payment_status"] == "refunded", "refund projection")
    rows = request(customer, "/api/customer/transactions")
    assert sum(row["order_id"] == order_id and row["kind"] == "charge" for row in rows) == 1
    assert sum(row["order_id"] == cancelled and row["kind"] == "refund" for row in rows) == 1
    print(json.dumps({"result": "PASS", "probe": "payments-service",
        "flow": "Booking outbox -> RabbitMQ -> Payments PostgreSQL -> payment events -> Booking",
        "remote_wallet": True, "replay_safe": True, "ownership_rejection": 403,
        "forged_token_rejection": 401, "refund_projected": True}))


if __name__ == "__main__":
    main()
