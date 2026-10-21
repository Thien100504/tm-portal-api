"""
Event Schemas - data structures of the events.

Uses dataclasses for type safety and easy serialization.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class BaseEvent:
    """
    Base schema for every event in the system.

    Attributes:
        event_id: Unique event ID (UUID)
        event_type: Event type (e.g. "task.created")
        timestamp: When the event happened (UTC)
        source: Where the event comes from (e.g. "api", "worker")
        payload: The event data
        metadata: Extra information (user_id, request_id, ...)
    """

    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    source: str = "api"
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert the event to a dict for serialization."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "source": self.source,
            "payload": self.payload,
            "metadata": self.metadata,
        }


@dataclass
class TaskCreatedEvent(BaseEvent):
    """A new task was created."""

    event_type: str = "task.created"
    source: str = "api"


@dataclass
class TaskUpdatedEvent(BaseEvent):
    """A task was updated (title, description, assignee, ...)."""

    event_type: str = "task.updated"
    source: str = "api"


@dataclass
class TaskCompletedEvent(BaseEvent):
    """A task was moved to done."""

    event_type: str = "task.completed"
    source: str = "api"


@dataclass
class TaskDeletedEvent(BaseEvent):
    """A task was deleted."""

    event_type: str = "task.deleted"
    source: str = "api"


@dataclass
class TaskAssignedEvent(BaseEvent):
    """A task was assigned to a user."""

    event_type: str = "task.assigned"
    source: str = "api"


@dataclass
class TaskOverdueEvent(BaseEvent):
    """A task is past its deadline."""

    event_type: str = "task.overdue"
    source: str = "worker"


@dataclass
class TaskCommentAddedEvent(BaseEvent):
    """A new comment was added to a task."""

    event_type: str = "task.comment_added"
    source: str = "api"
