import json
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import jwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from payment_service.db import Base, Entry, Intent, Outbox, Receipt, database
from payment_service.domain import Event, consume, settle, wallet
from payment_service.main import create_app


@pytest.fixture
def db(tmp_path):
    url = os.getenv("PAYMENTS_TEST_DATABASE_URL", "sqlite:///" + str(tmp_path / "payments.db"))
    if not url.startswith("sqlite:"):
        assert url.rsplit("/", 1)[-1] == "payments_test", "Only a disposable payments_test DB may be reset"
    engine, sessions = database(url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine, sessions
    engine.dispose()


def event(kind="created", order=8001, method="gateway", **changes):
    payload = dict(order_id=order, customer_id=1, provider_id=1, amount_cents=107000,
                   commission_cents=10700, method=method)
    payload.update(changes)
    return Event(id=str(uuid4()), type="billing.booking_" + kind, payload=payload)


def count(sessions, model, **where):
    with sessions() as session:
        return session.scalar(select(func.count()).select_from(model).filter_by(**where))


def test_pay_replay_completion_and_wallet_are_atomic(db):
    _, sessions = db
    created = event()
    assert consume(sessions, created)
    assert not consume(sessions, created)
    first = settle(sessions, 8001, 1, "pay-once")
    assert settle(sessions, 8001, 1, "pay-once") == first
    assert settle(sessions, 8001, 1, "another-click") == first
    done = event("completed")
    assert consume(sessions, done)
    assert not consume(sessions, done)
    consume(sessions, event("completed"))
    assert count(sessions, Entry, kind="charge") == 1
    assert count(sessions, Entry, kind="payout_credit") == 1
    assert count(sessions, Outbox, type="payment.succeeded") == 1
    assert wallet(sessions, 1)["balance_cents"] == 96300
    assert wallet(sessions, 2)["transactions"] == []


def test_cancel_after_pay_refunds_once_even_after_redelivery(db):
    _, sessions = db
    consume(sessions, event())
    settle(sessions, 8001, 1, "pay")
    consume(sessions, event("cancelled"))
    consume(sessions, event("cancelled"))
    consume(sessions, event("completed"))
    assert count(sessions, Entry, kind="refund") == 1
    assert count(sessions, Outbox, type="payment.refunded") == 1
    assert wallet(sessions, 1)["balance_cents"] == 0
    with pytest.raises(HTTPException) as error:
        settle(sessions, 8001, 1, "pay-again")
    assert error.value.status_code == 409


def test_cancel_arrives_before_created_cannot_be_resurrected(db):
    _, sessions = db
    consume(sessions, event("cancelled"))
    consume(sessions, event())
    with pytest.raises(HTTPException):
        settle(sessions, 8001, 1, "pay")
    assert count(sessions, Entry) == 0


def test_completion_before_payment_only_credits_after_payment(db):
    _, sessions = db
    consume(sessions, event("completed"))
    assert wallet(sessions, 1)["balance_cents"] == 0
    settle(sessions, 8001, 1, "pay")
    assert wallet(sessions, 1)["balance_cents"] == 96300


def test_cod_completion_only_adds_commission_once(db):
    _, sessions = db
    consume(sessions, event("completed", method="cod"))
    consume(sessions, event("completed", method="cod"))
    result = wallet(sessions, 1)
    assert result["commission_owed_cents"] == 10700
    assert result["balance_cents"] == 0
    assert len(result["transactions"]) == 1


def test_payload_and_key_conflicts_rollback(db):
    _, sessions = db
    old = event()
    consume(sessions, old)
    conflict = old.model_copy(update={"payload": old.payload.model_copy(update={"amount_cents": 108000})})
    with pytest.raises(ValueError):
        consume(sessions, conflict)
    with pytest.raises(ValueError):
        consume(sessions, event(amount_cents=108000))
    assert count(sessions, Receipt) == 1
    settle(sessions, 8001, 1, "same-key")
    consume(sessions, event(order=8002))
    with pytest.raises(HTTPException) as error:
        settle(sessions, 8002, 1, "same-key")
    assert error.value.status_code == 409
    assert count(sessions, Entry) == 1


def test_api_enforces_identity_ownership_and_input(db):
    engine, sessions = db
    consume(sessions, event())
    def verify(token):
        if token == "forged":
            raise jwt.InvalidTokenError()
        role, user = token.split(":")
        return {"role": role, "legacy_user_id": user}
    with TestClient(create_app(engine, sessions, verify)) as client:
        assert client.get("/api/payments/wallet").status_code == 401
        assert client.get("/api/payments/wallet", headers={"Authorization": "Bearer forged"}).status_code == 401
        assert client.get("/api/payments/wallet", headers={"Authorization": "Bearer customer:1"}).status_code == 403
        assert client.get("/api/payments/intents/8001", headers={"Authorization": "Bearer customer:2"}).status_code == 403
        headers = {"Authorization": "Bearer customer:1", "Idempotency-Key": "api-pay"}
        assert client.post("/api/payments/simulate", headers=headers, json={"order_id": 8001, "customer_id": 2}).status_code == 422
        assert client.post("/api/payments/simulate", headers=headers, json={"order_id": 8001}).status_code == 200
        assert client.get("/api/payments/transactions", headers=headers).json()[0]["kind"] == "charge"
        assert client.get("/api/payments/transactions", headers={"Authorization": "Bearer customer:2"}).json() == []


def test_real_postgres_concurrent_settlement(db):
    engine, sessions = db
    if engine.dialect.name != "postgresql":
        pytest.skip("Row-lock concurrency is verified on PostgreSQL in CI")
    consume(sessions, event())
    consume(sessions, event("completed"))
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda n: settle(sessions, 8001, 1, "click-" + str(n)), range(8)))
    assert all(result["status"] == "succeeded" for result in results)
    assert count(sessions, Entry, kind="charge") == 1
    assert count(sessions, Entry, kind="payout_credit") == 1
    assert wallet(sessions, 1)["balance_cents"] == 96300


def test_real_postgres_cancel_and_pay_race(db):
    engine, sessions = db
    if engine.dialect.name != "postgresql":
        pytest.skip("Row-lock concurrency is verified on PostgreSQL in CI")
    consume(sessions, event())
    def pay():
        try:
            return settle(sessions, 8001, 1, "race")
        except HTTPException as error:
            assert error.status_code == 409
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(pay), pool.submit(consume, sessions, event("cancelled"))]
        for future in futures:
            future.result()
    with sessions() as session:
        intent = session.get(Intent, 8001)
        assert intent.cancelled
        assert intent.status in {"refunded", "cancelled"}
    assert count(sessions, Entry, kind="charge") == count(sessions, Entry, kind="refund")
    assert wallet(sessions, 1)["balance_cents"] == 0
