from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db import Base, Notification, ProcessedEvent, database
from app.auth import build_verifier
from app.events import DomainEvent, consume_event
from app.main import create_app
from app.settings import Settings


@pytest.fixture
def system(tmp_path, monkeypatch):
    engine, sessions = database(f"sqlite:///{tmp_path / 'notifications.db'}")
    Base.metadata.create_all(engine)
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    settings = Settings("unused", "https://identity.test/realms/homeservice", "notifications", "unused", "")

    # Stub only network key retrieval; exercise the service's real JWT verifier.
    monkeypatch.setattr(jwt.PyJWKClient, "get_signing_key_from_jwt",
                        lambda self, token: SimpleNamespace(key=private.public_key()))
    verifier = build_verifier(settings)

    def token(user="1", role="customer", **overrides):
        payload = {"sub": f"keycloak-{user}", "legacy_user_id": user, "role": role,
                   "iss": settings.issuer, "aud": settings.audience,
                   "exp": datetime.now(timezone.utc) + timedelta(minutes=5)}
        payload.update(overrides)
        return jwt.encode(payload, private, algorithm="RS256")

    with TestClient(create_app(settings, engine, sessions, verifier)) as client:
        yield client, sessions, token


def event(event_id="event-1", **payload):
    return DomainEvent(id=event_id, type="booking.completed",
                       payload={"customer_id": 1, "order_id": 8001, **payload})


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_inbox_ownership_and_mark_read(system):
    client, sessions, token = system
    consume_event(sessions, event())
    response = client.get("/api/notifications", headers=auth(token()))
    assert response.status_code == 200
    row = response.json()[0]
    assert row["order_id"] == 8001
    assert row["read_at"] is None
    assert client.get("/api/notifications", headers=auth(token("2"))).json() == []
    assert client.get("/api/notifications", headers=auth(token(role="provider"))).json() == []
    path = f"/api/notifications/{row['id']}/read"
    assert client.post(path, headers=auth(token("2"))).status_code == 403
    first = client.post(path, headers=auth(token())).json()
    assert first["read_at"] is not None
    assert client.post(path, headers=auth(token())).json()["read_at"] == first["read_at"]
    assert client.post("/api/notifications/999/read", headers=auth(token())).status_code == 404


@pytest.mark.parametrize("kind", ["missing", "forged", "expired", "audience", "issuer"])
def test_auth_rejects_invalid_tokens(system, kind):
    client, _, token = system
    headers = {}
    if kind == "forged":
        headers = auth(jwt.encode({"sub": "1"}, "attacker", algorithm="HS256"))
    elif kind == "expired":
        headers = auth(token(exp=datetime.now(timezone.utc) - timedelta(minutes=1)))
    elif kind == "audience":
        headers = auth(token(aud="other-service"))
    elif kind == "issuer":
        headers = auth(token(iss="https://attacker.test"))
    response = client.get("/api/notifications", headers=headers)
    assert response.status_code == 401


def test_mapping_required(system):
    client, _, token = system
    assert client.get("/api/notifications", headers=auth(token(legacy_user_id=None))).status_code == 403


def test_concurrent_duplicate_event_has_one_effect(system):
    _, sessions, _ = system
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: consume_event(sessions, event()), range(8)))
    assert results.count(True) == 1
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Notification)) == 1
        assert session.scalar(select(func.count()).select_from(ProcessedEvent)) == 1


def test_bad_event_can_be_corrected_and_retried(system):
    _, sessions, _ = system
    with pytest.raises(ValueError):
        consume_event(sessions, event(customer_id=None))
    assert consume_event(sessions, event()) is True


def test_insert_failure_rolls_back_receipt_and_all_recipients(system):
    _, sessions, _ = system
    # A malformed event targets the same recipient as both winner and loser.
    # The notification uniqueness constraint fails after the receipt was flushed.
    broken = DomainEvent(id="bid-1", type="bid.accepted", payload={
        "winner_provider_id": 2, "loser_provider_ids": [2], "job_request_id": 1, "order_id": 8001,
    })
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError):
        consume_event(sessions, broken)
    with sessions() as session:
        assert session.get(ProcessedEvent, "bid-1") is None
        assert session.scalar(select(func.count()).select_from(Notification)) == 0
    broken.payload["loser_provider_ids"] = [3]
    assert consume_event(sessions, broken) is True


@pytest.mark.parametrize("kind,payload,expected", [
    ("provider.approved", {"provider_id": 3}, 1),
    ("review.created", {"provider_id": 2, "rating": 5, "order_id": 8001}, 1),
    ("booking.status_changed", {"actor_role": "provider", "customer_id": 1, "to": "confirmed", "order_id": 8001}, 1),
    ("bid.accepted", {"winner_provider_id": 2, "loser_provider_ids": [3, 4], "job_request_id": 1, "order_id": 8001}, 3),
    ("payment.succeeded", {"provider_id": 2, "amount_cents": 10000, "order_id": 8001}, 1),
])
def test_event_types(system, kind, payload, expected):
    _, sessions, _ = system
    assert consume_event(sessions, DomainEvent(id="typed-1", type=kind, payload=payload))
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Notification)) == expected


def test_health_and_correlation(system):
    client, _, _ = system
    assert client.get("/health").json() == {"status": "ok"}
    response = client.get("/ready", headers={"x-request-id": "demo-123"})
    assert response.status_code == 200
    assert response.headers["x-request-id"] == "demo-123"
