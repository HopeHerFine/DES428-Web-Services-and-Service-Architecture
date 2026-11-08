"""Integration probe run inside the Docker network; no auth bypass or HTTP write API."""
import json
import time
from uuid import uuid4

import pika
from sqlalchemy import func, select

from .db import Notification, ProcessedEvent, database
from .settings import Settings
from .worker import EXCHANGE, QUEUE


def main():
    settings = Settings.from_env()
    engine, sessions = database(settings.database_url)
    probe_id = f"smoke:{uuid4()}"
    sentinel_id = f"{probe_id}:sentinel"
    connection = pika.BlockingConnection(pika.URLParameters(settings.rabbitmq_url))
    try:
        channel = connection.channel()
        deadline = time.monotonic() + 60
        while True:
            try:
                result = channel.queue_declare(queue=QUEUE, passive=True)
                if result.method.consumer_count > 0:
                    break
            except pika.exceptions.ChannelClosedByBroker as error:
                if error.reply_code != 404:
                    raise
                channel = connection.channel()
            if time.monotonic() > deadline:
                raise RuntimeError("Notifications consumer did not become ready")
            time.sleep(1)
        channel.confirm_delivery()

        def publish(event_id):
            channel.basic_publish(
                exchange=EXCHANGE, routing_key="booking.completed", mandatory=True,
                properties=pika.BasicProperties(delivery_mode=2, content_type="application/json"),
                body=json.dumps({"id": event_id, "type": "booking.completed", "payload": {
                    "order_id": 8001, "customer_id": probe_id,
                }}),
            )

        for _ in range(8):
            publish(probe_id)
        # With one worker and prefetch=1, this receipt proves earlier duplicates
        # have passed through the consumer, rather than just checking too early.
        publish(sentinel_id)
        deadline = time.monotonic() + 60
        while True:
            with sessions() as session:
                if session.get(ProcessedEvent, sentinel_id) is not None:
                    count = session.scalar(select(func.count()).select_from(Notification).where(
                        Notification.event_id == probe_id,
                    ))
                    assert count == 1, f"Expected one notification, got {count}"
                    row = session.scalar(select(Notification).where(Notification.event_id == probe_id))
                    assert row.recipient_id == probe_id
                    assert row.type == "rating_request"
                    print(json.dumps({"result": "PASS", "event_id": probe_id,
                                      "deliveries": 8, "notifications_created": count,
                                      "storage": "PostgreSQL", "transport": "RabbitMQ"}))
                    break
            if time.monotonic() > deadline:
                raise RuntimeError("Event did not reach PostgreSQL within 60 seconds")
            time.sleep(1)
    finally:
        if connection.is_open:
            connection.close()
        # Delete only synthetic records created by this probe. Real users never
        # have this random smoke recipient ID; normal application data is untouched.
        from sqlalchemy import delete
        with sessions.begin() as session:
            session.execute(delete(Notification).where(Notification.event_id.in_([probe_id, sentinel_id])))
            session.execute(delete(ProcessedEvent).where(ProcessedEvent.id.in_([probe_id, sentinel_id])))
        engine.dispose()


if __name__ == "__main__":
    main()
