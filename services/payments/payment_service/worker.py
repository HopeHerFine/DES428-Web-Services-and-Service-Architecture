"""Durable inbox and confirm-based transactional outbox; reconnect without logging credentials."""
import json
import logging
import os
import time
from pathlib import Path
import pika
from opentelemetry import propagate, trace
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from .db import Base, Outbox, database
from .domain import Event, KINDS, consume
from .telemetry import setup

EXCHANGE = "homeservice.events"
QUEUE = "payments.events"
logger = logging.getLogger("payments-worker")


def topology(channel):
    channel.exchange_declare(exchange=EXCHANGE, exchange_type="topic", durable=True)
    channel.queue_declare(queue="payments.dead", durable=True)
    channel.queue_declare(queue=QUEUE, durable=True, arguments={
        "x-dead-letter-exchange": "", "x-dead-letter-routing-key": "payments.dead"})
    for kind in KINDS:
        channel.queue_bind(queue=QUEUE, exchange=EXCHANGE, routing_key=kind)
    # Declare downstream queue before publishing, so a slow Booking subscriber
    # cannot cause the first settlement/refund to disappear on a new stack.
    channel.queue_declare(queue="booking.payments.dead", durable=True)
    channel.queue_declare(queue="booking.payments", durable=True, arguments={
        "x-dead-letter-exchange": "", "x-dead-letter-routing-key": "booking.payments.dead"})
    for kind in ("payment.succeeded", "payment.refunded"):
        channel.queue_bind(queue="booking.payments", exchange=EXCHANGE, routing_key=kind)


def publish(sessions, channel):
    with sessions.begin() as session:
        rows = session.scalars(select(Outbox).where(Outbox.published.is_(False))
            .order_by(Outbox.sequence).limit(50).with_for_update(skip_locked=True)).all()
        for row in rows:
            channel.basic_publish(exchange=EXCHANGE, routing_key=row.type,
                body=json.dumps({"id": row.id, "type": row.type, "payload": json.loads(row.payload)}),
                properties=pika.BasicProperties(delivery_mode=2, message_id=row.id,
                    content_type="application/json", headers=json.loads(row.trace_headers)), mandatory=True)
            row.published = True


def main():
    logging.basicConfig(level=logging.INFO)
    setup("payments-worker")
    logging.getLogger("pika").setLevel(logging.WARNING)
    engine, sessions = database(os.environ["DATABASE_URL"])
    while True:
        connection = None
        try:
            Base.metadata.create_all(engine)
            connection = pika.BlockingConnection(pika.URLParameters(os.environ["RABBITMQ_URL"]))
            channel = connection.channel()
            topology(channel)
            channel.confirm_delivery()
            channel.basic_qos(prefetch_count=1)
            while connection.is_open:
                method, properties, body = channel.basic_get(QUEUE, auto_ack=False)
                if method:
                    try:
                        event = Event.model_validate_json(body)
                        with trace.get_tracer(__name__).start_as_current_span("consume " + event.type,
                                kind=trace.SpanKind.CONSUMER, context=propagate.extract(properties.headers or {})):
                            applied = consume(sessions, event)
                        channel.basic_ack(method.delivery_tag)
                        logger.info(json.dumps({"service": "payments-worker", "event_id": event.id,
                            "type": event.type, "result": "applied" if applied else "duplicate"}))
                    except (ValidationError, ValueError):
                        logger.warning("Invalid billing event sent to payments.dead")
                        channel.basic_nack(method.delivery_tag, requeue=False)
                publish(sessions, channel)
                Path("/tmp/payments-worker-heartbeat").touch()
                connection.process_data_events(time_limit=0.2)
        except (pika.exceptions.AMQPError, SQLAlchemyError, OSError):
            logger.warning("Payments dependency unavailable; unacknowledged messages retained")
            time.sleep(3)
        finally:
            if connection and connection.is_open:
                connection.close()


if __name__ == "__main__":
    main()
