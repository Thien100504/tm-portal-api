"""
Final coverage push — 10+ statements to cross 80%.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi import BackgroundTasks


# ═══════════════════════════════════════════════════════════════════
# TASK EVENTS — RabbitMQHandler branches (user=None, telegram_chat_id)
# ═══════════════════════════════════════════════════════════════════


def _task_ctx():
    from app.events.pipeline import EventContext

    ctx = MagicMock(spec=EventContext)
    ctx.event_type = "task.updated"
    ctx.skip_external = False
    task = MagicMock()
    task.id = uuid.uuid4()
    task.project_id = uuid.uuid4()
    ctx.task = task
    actor = MagicMock()
    actor.id = uuid.uuid4()
    ctx.actor = actor
    ctx.meta = {}
    ctx.stakeholders = set()
    ctx.background_tasks = MagicMock(spec=BackgroundTasks)
    ctx.background_tasks.add_task = MagicMock()
    ctx.db = AsyncMock()
    return ctx


@pytest.mark.asyncio
async def test_task_rabbitmq_user_not_found():
    """Covers the `if not user: continue` branch (line 173)."""
    from app.events.task_events import RabbitMQHandler

    handler = RabbitMQHandler()
    ctx = _task_ctx()
    uid = uuid.uuid4()
    ctx.stakeholders = {uid}

    project = MagicMock()
    project.telegram_chat_id = None
    ctx.db.get = AsyncMock(side_effect=[project, None])  # user returns None

    with patch("app.events.task_events._publish_sync"):
        await handler.handle(ctx)
    ctx.background_tasks.add_task.assert_not_called()


@pytest.mark.asyncio
async def test_task_rabbitmq_user_with_telegram():
    """Covers `if user.telegram_chat_id` branch (line 191)."""
    from app.events.task_events import RabbitMQHandler

    handler = RabbitMQHandler()
    ctx = _task_ctx()
    uid = uuid.uuid4()
    ctx.stakeholders = {uid}

    project = MagicMock()
    project.telegram_chat_id = None

    user = MagicMock()
    user.id = uid
    user.email = "u@test.com"
    user.telegram_chat_id = "tg123"

    ctx.db.get = AsyncMock(side_effect=[project, user])

    with patch("app.events.task_events._publish_sync"):
        await handler.handle(ctx)
    ctx.background_tasks.add_task.assert_called_once()


@pytest.mark.asyncio
async def test_task_rabbitmq_project_telegram_with_thread():
    """Covers project_chat_id branch + member.telegram_thread_id (lines 212-213)."""
    from app.events.task_events import RabbitMQHandler

    handler = RabbitMQHandler()
    ctx = _task_ctx()
    uid = uuid.uuid4()
    ctx.stakeholders = {uid}

    project = MagicMock()
    project.telegram_chat_id = "chat999"

    user = MagicMock()
    user.id = uid
    user.email = "u@test.com"
    user.telegram_chat_id = None

    member = MagicMock()
    member.telegram_thread_id = "thread42"
    result_mock = MagicMock()
    result_mock.scalars.return_value.first.return_value = member

    ctx.db.get = AsyncMock(side_effect=[project, user])
    ctx.db.execute = AsyncMock(return_value=result_mock)

    with patch("app.events.task_events._publish_sync"):
        await handler.handle(ctx)
    ctx.background_tasks.add_task.assert_called_once()


# ═══════════════════════════════════════════════════════════════════
# SPRINT EVENTS — NotificationHandler (sprint.created is skipped)
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_sprint_notification_handler_not_created():
    """Covers should_run returning False for sprint.created (line 130)."""
    from app.events.sprint_events import NotificationHandler

    handler = NotificationHandler()
    from app.events.pipeline import EventContext

    ctx = MagicMock(spec=EventContext)
    ctx.event_type = "sprint.created"
    result = await handler.should_run(ctx)
    assert result is False


# ═══════════════════════════════════════════════════════════════════
# TASKS MANAGER — update with dict containing sprint_id / epic_id
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_tasks_manager_update_with_schema_sprint():
    """Covers lines 163/165 — update via schema object with sprint_id/epic_id set."""
    from app.modules.tasks.manager import task_manager
    from app.modules.tasks.schemas import TaskUpdate

    db = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value = iter([])
    db.execute = AsyncMock(return_value=result_mock)

    sprint_id = uuid.uuid4()
    epic_id = uuid.uuid4()

    task = MagicMock()
    task.id = uuid.uuid4()
    task.project_id = uuid.uuid4()
    task.parent_task_id = None
    task.deadline = None
    task.sprint_id = None
    task.epic_id = None

    obj_in = TaskUpdate(sprint_id=sprint_id, epic_id=epic_id)

    await task_manager.update(db, db_obj=task, obj_in=obj_in)
    db.flush.assert_awaited()


# ═══════════════════════════════════════════════════════════════════
# AUTOMATION MANAGER — update with invalid action type
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_automation_manager_update_invalid_action():
    """Covers line 94 — invalid action raises 400."""
    from app.modules.automation.manager import AutomationManager
    from app.modules.automation.schemas import AutomationRuleUpdate
    from fastapi import HTTPException

    mgr = AutomationManager()
    db = AsyncMock()

    rule = MagicMock()
    update = AutomationRuleUpdate(actions={"type": "invalid_action_xyz"})

    with pytest.raises(HTTPException) as exc:
        await mgr.update(db, rule, update)
    assert exc.value.status_code == 400
