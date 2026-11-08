import logging
import time

import pika
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from .db import Base, database
from .events import DomainEvent, consume_event
from .settings import Settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("notifications.worker")
EXCHANGE = "homeservice.events"
QUEUE = "notifications.events"


def main():
    settings = Settings.from_env()
    engine, sessions = database(settings.database_url)
    Base.metadata.create_all(engine)
    if not settings.rabbitmq_url:
        raise RuntimeError("RABBITMQ_URL is required for the worker")
    while True:
        connection = None
        try:
            connection = pika.BlockingConnection(pika.URLParameters(settings.rabbitmq_url))
            channel = connection.channel()
            channel.exchange_declare(exchange=EXCHANGE, exchange_type="topic", durable=True)
            channel.queue_declare(queue="notifications.dead", durable=True)
            channel.queue_declare(queue=QUEUE, durable=True, arguments={
                "x-dead-letter-exchange": "", "x-dead-letter-routing-key": "notifications.dead",
            })
            for kind in DomainEvent.model_fields["type"].annotation.__args__:
                channel.queue_bind(queue=QUEUE, exchange=EXCHANGE, routing_key=kind)
            channel.basic_qos(prefetch_count=1)

            def receive(ch, method, properties, body):
                try:
                    event = DomainEvent.model_validate_json(body)
                    consume_event(sessions, event)
                except (ValidationError, ValueError, KeyError, TypeError):
                    logger.exception("invalid event; dead-lettering")
                    ch.basic_nack(method.delivery_tag, requeue=False)
                except SQLAlchemyError:
                    # Close the connection to requeue unacknowledged messages; the
                    # outer loop backs off rather than repeatedly hot-looping failures.
                    raise
                else:
                    ch.basic_ack(method.delivery_tag)

            channel.basic_consume(queue=QUEUE, on_message_callback=receive)
            channel.start_consuming()
        except (pika.exceptions.AMQPError, SQLAlchemyError, OSError):
            logger.exception("worker disconnected; retrying in 5 seconds")
            time.sleep(5)
        finally:
            if connection and connection.is_open:
                connection.close()


if __name__ == "__main__":
    main()
