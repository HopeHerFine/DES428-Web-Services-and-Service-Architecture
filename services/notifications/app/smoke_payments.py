"""Real browser identities, Booking outbox, Payments PostgreSQL and remote Wallet."""
import argparse
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


def book_gateway(customer):
    service = request(customer, "/api/services/2")
    addresses = request(customer, "/api/customer/addresses")

    for offset in random.sample(range(30, 180), 15):
        day = (date.today() + timedelta(days=offset)).isoformat()
        slots = request(customer, f"/api/providers/1/slots?date={day}&duration={service['duration_min']}")["slots"]
        if slots:
            return request(customer, "/api/bookings", {"provider_id": 1, "address_id": addresses[0]["id"],
                "service_date": day, "starting_time": slots[0], "items": [{"service_id": 2, "quantity": 1}],
                "payment_method": "gateway"})
    raise RuntimeError("No available integration booking slot")


def refund_saga(customer):
    order_id = book_gateway(customer)["order"]["id"]
    booking_path = f"/api/bookings/{order_id}"

    def checkpoint(step, **details):
        print(json.dumps({"probe": "refund-saga", "order_id": order_id, "step": step, **details}), flush=True)

    wait_until(lambda: request(customer, f"/api/payments/intents/{order_id}"), "Saga payment intent")
    checkpoint("intent_ready")
    key = f"saga-payment-{order_id}"
    payment = pay(customer, order_id, key)
    assert pay(customer, order_id, key) == payment
    wait_until(lambda: request(customer, booking_path)["payment_status"] == "paid", "Saga paid projection")
    checkpoint("paid", payment_status="paid", payment_replay_verified=True)

    request(customer, booking_path + "/cancel", {})
    checkpoint("cancellation_requested")
    wait_until(lambda: request(customer, booking_path)["payment_status"] == "refunded", "Saga refund projection")
    rows = request(customer, "/api/customer/transactions")
    amounts = {kind: [row["amount_cents"] for row in rows
                      if row["order_id"] == order_id and row["kind"] == kind]
               for kind in ("charge", "refund")}
    assert len(amounts["charge"]) == len(amounts["refund"]) == 1, amounts
    assert abs(amounts["charge"][0]) == abs(amounts["refund"][0]) > 0, amounts
    checkpoint("refunded", result="PASS", payment_status="refunded", charges=1, refunds=1,
               refund_cents=abs(amounts["refund"][0]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--saga-only", action="store_true", help="Run only the refund flow on disposable demo data")
    if parser.parse_args().saga_only:
        refund_saga(browser_login("nong@example.com"))
        return

    customer = browser_login("nong@example.com")
    provider = browser_login("sparkle@example.com")
    other = browser_login("fixit@example.com")
    baseline = request(provider, "/api/provider/wallet")
    placed = book_gateway(customer)
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

    refund_saga(customer)
    rows = request(customer, "/api/customer/transactions")
    assert sum(row["order_id"] == order_id and row["kind"] == "charge" for row in rows) == 1
    print(json.dumps({"result": "PASS", "probe": "payments-service",
        "flow": "Booking outbox -> RabbitMQ -> Payments PostgreSQL -> payment events -> Booking",
        "remote_wallet": True, "replay_safe": True, "ownership_rejection": 403,
        "forged_token_rejection": 401, "refund_projected": True}))


if __name__ == "__main__":
    main()
