"""
Event Publisher - sends events to RabbitMQ.

Uses the 'task_manager' topic exchange to route events
to the matching consumers by routing_key.
"""

import json
import logging
from typing import Any

import pika
from pika.exceptions import AMQPConnectionError

from app.config import get_settings
from app.logging_config import correlation_id_var

logger = logging.getLogger(__name__)

EXCHANGE_NAME = "task_manager"
EXCHANGE_TYPE = "topic"


class EventPublisher:
    """
    Publishes events to the RabbitMQ topic exchange.

    Usage:
        publisher = EventPublisher()
        publisher.publish("task.created", {"task_id": "...", "title": "..."})
        publisher.close()

    Or as a context manager:
        with EventPublisher() as publisher:
            publisher.publish("task.created", payload)
    """

    def __init__(self) -> None:
        """Create the publisher and connect to RabbitMQ."""
        self._settings = get_settings()
        self._connection: pika.BlockingConnection | None = None
        self._channel: pika.adapters.blocking_connection.BlockingChannel | None = None

    def _connect(self) -> None:
        """Open the connection and declare the exchange if needed."""
        if self._connection is not None and self._connection.is_open:
            return

        try:
            params = pika.URLParameters(self._settings.RABBITMQ_URL)
            self._connection = pika.BlockingConnection(params)
            self._channel = self._connection.channel()

            # Declare the topic exchange (idempotent)
            self._channel.exchange_declare(
                exchange=EXCHANGE_NAME,
                exchange_type=EXCHANGE_TYPE,
                durable=True,
            )
            logger.info("✅ Connected to RabbitMQ exchange '%s'", EXCHANGE_NAME)
        except AMQPConnectionError as exc:
            logger.error("❌ Could not connect to RabbitMQ: %s", exc)
            raise

    def publish(self, routing_key: str, payload: dict[str, Any]) -> None:
        """
        Publish an event to RabbitMQ.

        Args:
            routing_key: Routing key (e.g. "task.created", "task.updated")
            payload: Event data as a dict, serialized to JSON
        """
        self._connect()

        payload_to_send = dict(payload)
        if "event" not in payload_to_send:
            payload_to_send["event"] = routing_key

        cid = correlation_id_var.get("-")
        if cid != "-":
            payload_to_send["correlation_id"] = cid

        message_body = json.dumps(payload_to_send, default=str, ensure_ascii=False)

        if self._channel is None:
            raise RuntimeError("Channel is not initialized")

        self._channel.basic_publish(
            exchange=EXCHANGE_NAME,
            routing_key=routing_key,
            body=message_body.encode("utf-8"),
            properties=pika.BasicProperties(
                content_type="application/json",
                delivery_mode=2,
                correlation_id=cid,
            ),
        )
        logger.info(
            "📤 Event published | exchange=%s | routing_key=%s",
            EXCHANGE_NAME,
            routing_key,
        )

    def close(self) -> None:
        """Close the RabbitMQ connection."""
        if self._connection and self._connection.is_open:
            self._connection.close()
            logger.info("🔌 RabbitMQ connection closed")

    def __enter__(self) -> "EventPublisher":
        """Context manager support."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Close the connection when leaving the context."""
        self.close()
