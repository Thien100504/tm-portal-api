"""Events package - event-driven messaging over RabbitMQ."""

from app.events.publisher import EventPublisher

__all__ = ["EventPublisher"]
