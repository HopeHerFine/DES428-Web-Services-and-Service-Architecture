"""Staged live process-restart checks, coordinated by check-broker-recovery.ps1."""
import json
import logging
import secrets
import sys
import time
from pathlib import Path
from uuid import uuid4
from urllib.request import Request, urlopen

import pika
from sqlalchemy import select, func, delete

from .db import Notification, ProcessedEvent, database
from .settings import Settings
from .worker import EXCHANGE, QUEUE

logging.getLogger("pika").setLevel(logging.WARNING)
MANIFEST = Path("/probe-data/broker-recovery.json")


def post(path, body=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = Request("http://edemand:3000" + path, data=json.dumps(body or {}).encode(), headers=headers)
    with urlopen(request, timeout=15) as response:
        return json.load(response)


def save(manifest):
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest))


def connect(settings):
    params = pika.URLParameters(settings.rabbitmq_url)
    params.connection_attempts = 1
    params.socket_timeout = 3
    params.stack_timeout = 5
    return pika.BlockingConnection(params)


def notification_count(sessions, event_id):
    with sessions() as session:
        return session.scalar(select(func.count()).select_from(Notification).where(Notification.event_id == event_id))


def approval_rows(sessions, provider_id):
    with sessions() as session:
        return session.scalars(select(Notification).where(Notification.recipient_role == "provider",
                               Notification.recipient_id == str(provider_id),
                               Notification.type == "provider_approved")).all()


def wait_for_receipt(sessions, event_id, seconds=90):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        with sessions() as session:
            if session.get(ProcessedEvent, event_id) is not None:
                return
        time.sleep(1)
    raise RuntimeError("Worker did not consume the sentinel after restart")


def main():
    settings = Settings.from_env()
    engine, sessions = database(settings.database_url)
    action = sys.argv[1]
    try:
        if action == "prepare":
            if MANIFEST.exists():
                raise RuntimeError("A previous broker probe exists; restore services and run cleanup first")
            provider = post("/api/auth/provider/register", {
                "email": f"broker-recovery-{uuid4()}@example.com", "password": "Demo-" + secrets.token_urlsafe(18),
                "name": "Broker recovery probe", "company_name": "Synthetic integration provider",
            })
            manifest = {"event_id": "broker-recovery-" + str(uuid4()), "sentinel_id": "broker-sentinel-" + str(uuid4()),
                        "provider_id": provider["id"], "published": False, "results": []}
            save(manifest)
            print(json.dumps({"result": "READY", "provider_id": provider["id"]}))
            return
        if not MANIFEST.exists():
            if action == "cleanup":
                return
            raise RuntimeError("No broker recovery probe exists")
        manifest = json.loads(MANIFEST.read_text())
        if action == "queue":
            connection = connect(settings)
            try:
                channel = connection.channel()
                queue = channel.queue_declare(queue=QUEUE, passive=True)
                assert queue.method.consumer_count == 0, "Stop all Notifications consumers before this stage"
                channel.confirm_delivery()
                # Persist ownership before any publish, including a failed halfway publish.
                manifest["published"] = True
                save(manifest)
                for event_id in [manifest["event_id"]] * 8 + [manifest["sentinel_id"]]:
                    channel.basic_publish(exchange=EXCHANGE, routing_key="booking.completed", mandatory=True,
                        properties=pika.BasicProperties(delivery_mode=2, content_type="application/json"),
                        body=json.dumps({"id": event_id, "type": "booking.completed", "payload": {
                            "customer_id": manifest["event_id"], "order_id": 8001,
                        }}))
                assert notification_count(sessions, manifest["event_id"]) == 0
                assert notification_count(sessions, manifest["sentinel_id"]) == 0
                print(json.dumps({"result": "QUEUED", "deliveries": 8, "consumer_count": 0, "effects_before_worker_restart": 0}))
            finally:
                connection.close()
        elif action == "check-queued":
            connection = connect(settings)
            try:
                queue = connection.channel().queue_declare(queue=QUEUE, passive=True)
                assert queue.method.consumer_count == 0
                assert queue.method.message_count >= 9, "Persistent messages did not survive the broker restart"
                assert notification_count(sessions, manifest["event_id"]) == 0
                manifest["results"].append({"case": "queued_messages_survive_broker_restart",
                                            "messages_waiting": queue.method.message_count, "effects_before_worker_restart": 0})
                save(manifest)
                print(json.dumps({"result": "PASS", **manifest["results"][-1]}))
            finally:
                connection.close()
        elif action == "verify-worker":
            wait_for_receipt(sessions, manifest["sentinel_id"])
            count = notification_count(sessions, manifest["event_id"])
            assert count == 1, f"Expected one effect after eight deliveries, got {count}"
            manifest["results"].append({"case": "worker_process_restart", "deliveries": 8, "notifications_created": count})
            save(manifest)
            print(json.dumps({"result": "PASS", **manifest["results"][-1]}))
        elif action == "approve-while-down":
            try:
                connection = connect(settings)
            except (pika.exceptions.AMQPError, OSError):
                pass
            else:
                connection.close()
                raise AssertionError("RabbitMQ is still reachable; stop its process before this stage")
            assert not approval_rows(sessions, manifest["provider_id"])
            admin = post("/api/auth/admin/login", {"email": "admin@edemand.test", "password": "eDemand-2026!"})
            approved = post(f"/api/admin/providers/{manifest['provider_id']}/approve", token=admin["token"])
            assert approved["is_approved"] is True
            manifest["approved_while_down"] = True
            save(manifest)
            assert not approval_rows(sessions, manifest["provider_id"])
            print(json.dumps({"result": "PENDING", "broker_reachable": False, "domain_change_succeeded": True,
                              "notification_effects_while_broker_down": 0}))
        elif action == "verify-outbox":
            assert manifest.get("approved_while_down")
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                rows = approval_rows(sessions, manifest["provider_id"])
                if rows:
                    assert len(rows) == 1
                    with sessions() as session:
                        assert session.get(ProcessedEvent, rows[0].event_id) is not None
                    manifest["results"].append({"case": "monolith_outbox_after_broker_process_restart",
                                                "domain_change_while_broker_down": True, "notifications_created": 1})
                    save(manifest)
                    print(json.dumps({"result": "PASS", "probe": "broker-worker-recovery", "checks": manifest["results"],
                                      "synthetic_provider_id": manifest["provider_id"]}))
                    return
                time.sleep(1)
            raise RuntimeError("The pending monolith event did not reach Notifications after broker restart")
        elif action == "cleanup":
            if manifest.get("published"):
                # A fresh barrier also handles an interrupted partial publish where
                # the original sentinel was never sent. Persist it before publishing.
                barrier = "broker-cleanup-" + str(uuid4())
                manifest.setdefault("cleanup_barriers", []).append(barrier)
                save(manifest)
                connection = connect(settings)
                try:
                    channel = connection.channel()
                    queue = channel.queue_declare(queue=QUEUE, passive=True)
                    assert queue.method.consumer_count > 0, "Restore the worker before fixture cleanup"
                    channel.confirm_delivery()
                    channel.basic_publish(exchange=EXCHANGE, routing_key="booking.completed", mandatory=True,
                        properties=pika.BasicProperties(delivery_mode=2, content_type="application/json"),
                        body=json.dumps({"id": barrier, "type": "booking.completed", "payload": {
                            "customer_id": manifest["event_id"], "order_id": 8001,
                        }}))
                finally:
                    connection.close()
                wait_for_receipt(sessions, barrier, seconds=30)
            events = [manifest["event_id"], manifest["sentinel_id"], *manifest.get("cleanup_barriers", [])]
            with sessions.begin() as session:
                session.execute(delete(Notification).where(Notification.event_id.in_(events)))
                session.execute(delete(ProcessedEvent).where(ProcessedEvent.id.in_(events)))
            MANIFEST.unlink()
            print("Queued synthetic fixtures removed; synthetic provider and its domain approval remain inspectable")
        else:
            raise RuntimeError("Unknown recovery stage")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
