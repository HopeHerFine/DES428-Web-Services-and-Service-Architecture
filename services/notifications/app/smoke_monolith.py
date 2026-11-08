"""Drive a real domain change via the monolith API, then check the external inbox DB."""
import json
import os
import secrets
import time
from urllib.request import Request, urlopen
from uuid import uuid4

from sqlalchemy import select

from .db import Notification, database
from .settings import Settings


def main():
    base = os.getenv("MONOLITH_URL", "http://edemand:3000")

    def post(path, body=None, token=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(base + path, data=json.dumps(body or {}).encode(), headers=headers, method="POST")
        with urlopen(request, timeout=15) as response:
            return json.load(response)

    provider = post("/api/auth/provider/register", {
        "email": f"migration-probe-{uuid4()}@example.com", "password": secrets.token_urlsafe(20),
        "name": "Migration integration probe", "company_name": "Synthetic test provider",
    })
    login = post("/api/auth/admin/login", {
        "email": "admin@edemand.test", "password": os.getenv("DEMO_PASSWORD", "eDemand-2026!"),
    })
    approved = post(f"/api/admin/providers/{provider['id']}/approve", token=login["token"])
    assert approved["is_approved"] is True
    engine, sessions = database(Settings.from_env().database_url)
    try:
        deadline = time.monotonic() + 60
        while True:
            with sessions() as session:
                rows = session.scalars(select(Notification).where(
                    Notification.recipient_role == "provider",
                    Notification.recipient_id == str(provider["id"]),
                    Notification.type == "provider_approved",
                )).all()
                if rows:
                    assert len(rows) == 1, f"Expected one approval notification, got {len(rows)}"
                    print(json.dumps({"result": "PASS", "flow": "monolith -> transactional outbox -> RabbitMQ -> PostgreSQL",
                                      "provider_id": provider["id"], "event_id": rows[0].event_id,
                                      "notifications_created": len(rows)}))
                    return
            if time.monotonic() > deadline:
                raise RuntimeError("Provider approval did not reach Notifications; inspect edemand and worker logs")
            time.sleep(1)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
