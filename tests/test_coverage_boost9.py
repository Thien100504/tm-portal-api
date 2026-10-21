"""
Final 6 statements to push past 80%.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


# task_events._publish_sync happy path (line 173)
def test_task_publish_sync_success():
    from app.events.task_events import _publish_sync

    mock_pub = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_pub)
    mock_ctx.__exit__ = MagicMock(return_value=False)
    with patch("app.events.task_events.EventPublisher", return_value=mock_ctx):
        _publish_sync("task.updated", {"key": "val"})
    mock_pub.publish.assert_called_once()


# sprint_events._publish_sync happy path (line 37)
def test_sprint_publish_sync_success():
    from app.events.sprint_events import _publish_sync

    mock_pub = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_pub)
    mock_ctx.__exit__ = MagicMock(return_value=False)
    with patch("app.events.sprint_events.EventPublisher", return_value=mock_ctx):
        _publish_sync("sprint.updated", {"key": "val"})
    mock_pub.publish.assert_called_once()


# task_events.emit_direct_notification (line 271)
@pytest.mark.asyncio
async def test_task_emit_direct_notification():
    from app.events.task_events import task_events

    db = AsyncMock()
    uid = uuid.uuid4()

    with patch("app.events.task_events.notif_svc") as mock_svc:
        mock_svc.create_and_push = AsyncMock()
        await task_events.emit_direct_notification(
            db,
            user_id=uid,
            title_key="task.assigned",
            title_params=None,
            message_key="task.assigned.msg",
            message_params=None,
            type="info",
            entity_type="task",
            entity_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
        )
    mock_svc.create_and_push.assert_awaited_once()


# notifications.service line 101 (_publish_notification_sync happy path)
def test_notifications_publish_sync_success():
    from app.modules.notifications.service import _publish_notification_sync

    mock_pub = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_pub)
    mock_ctx.__exit__ = MagicMock(return_value=False)
    with patch(
        "app.modules.notifications.service.EventPublisher", return_value=mock_ctx
    ):
        _publish_notification_sync({"user_id": str(uuid.uuid4()), "title": "Test"})
    mock_pub.publish.assert_called_once()


# auth.dependencies line 89 (get_current_active_user returns current_user)
@pytest.mark.asyncio
async def test_auth_get_current_active_user():
    from app.modules.auth.dependencies import get_current_active_user

    user = MagicMock()
    # get_current_active_user just returns the injected current_user
    result = await get_current_active_user(current_user=user)
    assert result == user
