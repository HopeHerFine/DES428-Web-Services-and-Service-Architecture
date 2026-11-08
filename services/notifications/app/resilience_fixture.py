"""Synthetic fixtures for real PostgreSQL/HTTP resilience checks.

Only these short-lived fixture containers can write /probe-data. Credentials are
not printed and cleanup deletes only rows/receipt keys listed in the manifest.
"""
import json
import sys
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select, delete, func

from .db import Notification, ProcessedEvent, WriteReceipt, database
from .events import DomainEvent, consume_event
from .settings import Settings
from .smoke_gateway import browser_login

DATA = Path("/probe-data")
MANIFEST = DATA / "credentials.json"


def prepare(sessions):
    if MANIFEST.exists():
        raise RuntimeError("A probe manifest already exists; run cleanup before starting a new probe")
    browser = browser_login("sparkle@example.com")
    jar = next(handler.cookiejar for handler in browser.handlers if hasattr(handler, "cookiejar"))
    token = next(cookie.value for cookie in jar if cookie.name == "notifications_token")
    fixtures = []
    DATA.mkdir(parents=True, exist_ok=True)
    def save():
        MANIFEST.write_text(json.dumps({"token": token, "fixtures": fixtures}))
        MANIFEST.chmod(0o600)
    save()
    for mode in ("lost_reply", "slow_calls", "unavailable", "concurrent", "key_conflict"):
        event_id = "resilience-" + str(uuid4())
        fixture = {"mode": mode, "id": None, "event_id": event_id, "key": "resilience-" + str(uuid4())}
        fixtures.append(fixture)
        save()  # Record ownership before any database mutation, even on setup failure.
        consume_event(sessions, DomainEvent(id=event_id, type="provider.approved", payload={"provider_id": 1}))
        with sessions() as session:
            row = session.scalar(select(Notification).where(Notification.event_id == event_id))
            fixture["id"] = row.id
        save()
    print(json.dumps({"result": "READY", "synthetic_notifications": len(fixtures), "credentials_logged": False}))


def verify(sessions, manifest):
    results = []
    with sessions() as session:
        for fixture in manifest["fixtures"]:
            if fixture["mode"] == "key_conflict":
                row = session.get(Notification, fixture["id"])
                assert row.read_at is None, "Conflicting key must not change another notification"
                continue
            key = "provider:1:" + fixture["key"]
            count = session.scalar(select(func.count()).select_from(WriteReceipt).where(WriteReceipt.key == key))
            row = session.get(Notification, fixture["id"])
            assert count == 1 and row.read_at is not None, f"{fixture['mode']}: expected exactly one committed write receipt"
            receipt = session.get(WriteReceipt, key)
            assert json.loads(receipt.response_json)["id"] == fixture["id"]
            results.append({"case": fixture["mode"], "write_receipts": count, "read_at_recorded": True})
    http = json.loads((DATA / "http-results.json").read_text())
    assert http["result"] == "PASS"
    print(json.dumps({"result": "PASS", "probe": "notifications-resilience", "http": http["cases"],
                      "postgresql": results, "concurrency_requests": 8}))


def cleanup(sessions, manifest):
    ids = [fixture["id"] for fixture in manifest["fixtures"]]
    events = [fixture["event_id"] for fixture in manifest["fixtures"]]
    keys = ["provider:1:" + fixture["key"] for fixture in manifest["fixtures"]]
    with sessions.begin() as session:
        session.execute(delete(WriteReceipt).where(WriteReceipt.key.in_(keys)))
        session.execute(delete(Notification).where(Notification.event_id.in_(events)))
        session.execute(delete(ProcessedEvent).where(ProcessedEvent.id.in_(events)))
    MANIFEST.unlink()
    (DATA / "http-results.json").unlink(missing_ok=True)
    print("Synthetic resilience rows and temporary credentials removed")


def main():
    engine, sessions = database(Settings.from_env().database_url)
    try:
        action = sys.argv[1]
        if action == "prepare":
            prepare(sessions)
        else:
            if not MANIFEST.exists():
                if action == "cleanup":
                    return
                raise RuntimeError("No probe manifest exists")
            manifest = json.loads(MANIFEST.read_text())
            if action == "verify":
                verify(sessions, manifest)
            elif action == "cleanup":
                cleanup(sessions, manifest)
            else:
                raise RuntimeError("Unknown fixture action")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
