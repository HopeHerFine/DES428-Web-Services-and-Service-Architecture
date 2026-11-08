import json
import sys
from sqlalchemy import select

from app import broker_recovery
from app.db import Base, Notification, ProcessedEvent, database
from app.events import DomainEvent, consume_event
from app.settings import Settings


def test_cleanup_never_removes_unrelated_user_notifications(tmp_path, monkeypatch):
    engine, sessions = database(f"sqlite:///{tmp_path / 'cleanup.db'}")
    Base.metadata.create_all(engine)
    for event_id, recipient in [("owned-event", "probe"), ("owned-sentinel", "probe"), ("real-user-event", "1")]:
        consume_event(sessions, DomainEvent(id=event_id, type="booking.completed", payload={"customer_id": recipient, "order_id": 8001}))
    manifest = tmp_path / "broker.json"
    manifest.write_text(json.dumps({"event_id": "owned-event", "sentinel_id": "owned-sentinel", "published": False}))
    monkeypatch.setattr(broker_recovery, "MANIFEST", manifest)
    monkeypatch.setattr(broker_recovery, "database", lambda url: (engine, sessions))
    monkeypatch.setattr(broker_recovery.Settings, "from_env", lambda: Settings("unused", "unused", "unused", "unused", "unused"))
    monkeypatch.setattr(sys, "argv", ["broker_recovery", "cleanup"])
    broker_recovery.main()
    assert not manifest.exists()
    with sessions() as session:
        remaining = session.scalars(select(Notification)).all()
        assert len(remaining) == 1 and remaining[0].event_id == "real-user-event"
        assert session.get(ProcessedEvent, "real-user-event") is not None
        assert session.get(ProcessedEvent, "owned-event") is None
