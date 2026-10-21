"""Unit tests for events/schemas.py — dataclasses, no external deps."""

from app.events.schemas import (
    BaseEvent,
    TaskAssignedEvent,
    TaskCommentAddedEvent,
    TaskCompletedEvent,
    TaskCreatedEvent,
    TaskDeletedEvent,
    TaskOverdueEvent,
    TaskUpdatedEvent,
)


def test_base_event_defaults():
    event = BaseEvent(event_type="test.event")
    assert event.event_type == "test.event"
    assert event.source == "api"
    assert event.payload == {}
    assert event.metadata == {}
    assert event.event_id is not None
    assert event.timestamp is not None


def test_base_event_to_dict():
    event = BaseEvent(event_type="test.event", payload={"key": "value"})
    d = event.to_dict()
    assert d["event_type"] == "test.event"
    assert d["payload"] == {"key": "value"}
    assert "event_id" in d
    assert "timestamp" in d
    assert "source" in d
    assert "metadata" in d


def test_base_event_custom_payload():
    event = BaseEvent(event_type="task.x", payload={"task_id": "abc"}, source="worker")
    assert event.payload["task_id"] == "abc"
    assert event.source == "worker"


def test_base_event_unique_ids():
    e1 = BaseEvent(event_type="x")
    e2 = BaseEvent(event_type="x")
    assert e1.event_id != e2.event_id


def test_task_created_event():
    event = TaskCreatedEvent(payload={"task_id": "1"})
    assert event.event_type == "task.created"
    assert event.source == "api"
    assert event.payload["task_id"] == "1"


def test_task_updated_event():
    event = TaskUpdatedEvent(payload={"task_id": "2", "field": "title"})
    assert event.event_type == "task.updated"


def test_task_completed_event():
    event = TaskCompletedEvent(payload={"task_id": "3"})
    assert event.event_type == "task.completed"


def test_task_deleted_event():
    event = TaskDeletedEvent(payload={"task_id": "4"})
    assert event.event_type == "task.deleted"


def test_task_assigned_event():
    event = TaskAssignedEvent(payload={"task_id": "5", "assignee_id": "u1"})
    assert event.event_type == "task.assigned"


def test_task_overdue_event():
    event = TaskOverdueEvent(payload={"task_id": "6"})
    assert event.event_type == "task.overdue"
    assert event.source == "worker"


def test_task_comment_added_event():
    event = TaskCommentAddedEvent(payload={"task_id": "7", "comment": "hello"})
    assert event.event_type == "task.comment_added"


def test_event_to_dict_all_keys():
    event = TaskCreatedEvent(payload={"x": 1}, metadata={"user_id": "u1"})
    d = event.to_dict()
    assert set(d.keys()) == {
        "event_id",
        "event_type",
        "timestamp",
        "source",
        "payload",
        "metadata",
    }
    assert d["metadata"]["user_id"] == "u1"
