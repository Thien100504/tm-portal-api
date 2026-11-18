"""
Coverage boost — targeting specific uncovered branches to push past 80%.
Focuses on: rbac.dependencies, auth.manager (create), project_events handlers,
sprint_events.RabbitMQHandler.handle, notifications.service, projects.manager methods,
dashboard.manager branches.
"""

import uuid
from unittest.mock import MagicMock, patch, AsyncMock
import pytest
from fastapi import HTTPException
from fastapi import BackgroundTasks


# ═══════════════════════════════════════════════════════════════════
# RBAC DEPENDENCIES
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_rbac_require_permission_missing_scope():
    from app.modules.rbac.dependencies import require_permission

    checker = require_permission("task.create")
    db = AsyncMock()
    user = MagicMock()
    with pytest.raises(HTTPException) as exc:
        await checker(workspace_id=None, project_id=None, db=db, current_user=user)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_rbac_require_permission_denied():
    from app.modules.rbac.dependencies import require_permission

    checker = require_permission("task.create")
    db = AsyncMock()
    user = MagicMock()
    user.id = uuid.uuid4()

    with patch("app.modules.rbac.dependencies.rbac_manager") as mock_mgr:
        mock_mgr.check_permission = AsyncMock(return_value=False)
        with pytest.raises(HTTPException) as exc:
            await checker(
                workspace_id=uuid.uuid4(), project_id=None, db=db, current_user=user
            )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_rbac_require_permission_granted():
    from app.modules.rbac.dependencies import require_permission

    checker = require_permission("task.create")
    db = AsyncMock()
    user = MagicMock()
    user.id = uuid.uuid4()

    with patch("app.modules.rbac.dependencies.rbac_manager") as mock_mgr:
        mock_mgr.check_permission = AsyncMock(return_value=True)
        result = await checker(
            workspace_id=uuid.uuid4(), project_id=None, db=db, current_user=user
        )
    assert result is True


# ═══════════════════════════════════════════════════════════════════
# AUTH MANAGER — create user
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_auth_manager_create_user():
    from app.modules.auth.manager import user_manager
    from app.modules.auth.schemas import UserCreate

    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.flush = AsyncMock()

    obj_in = UserCreate(email="new@test.com", password="Secret123!", full_name="Alice")

    with patch("app.modules.auth.manager.get_password_hash", return_value="hashed"):
        await user_manager.create(db, obj_in=obj_in)

    assert db.add.called
    assert db.commit.called


# ═══════════════════════════════════════════════════════════════════
# PROJECT EVENTS — WebSocketHandler + NotificationHandler
# ═══════════════════════════════════════════════════════════════════


def _make_proj_ctx(event_type="project.member_added"):
    from app.events.pipeline import EventContext

    ctx = MagicMock(spec=EventContext)
    ctx.event_type = event_type
    proj = MagicMock()
    proj.id = uuid.uuid4()
    proj.name = "Test Proj"
    ctx.task = proj
    actor = MagicMock()
    actor.id = uuid.uuid4()
    actor.full_name = "Bob"
    ctx.actor = actor
    ctx.extra = {"target_user_id": uuid.uuid4(), "target_user_name": "Charlie"}
    ctx.meta = {}
    ctx.db = AsyncMock()
    ctx.background_tasks = MagicMock(spec=BackgroundTasks)
    return ctx


@pytest.mark.asyncio
async def test_project_websocket_handler():
    from app.events.project_events import WebSocketHandler

    handler = WebSocketHandler()
    ctx = _make_proj_ctx()

    with patch("app.events.project_events.manager") as mock_mgr:
        mock_mgr.broadcast_to_project = AsyncMock()
        await handler.handle(ctx)
    mock_mgr.broadcast_to_project.assert_awaited_once()


@pytest.mark.asyncio
async def test_project_notification_handler_member_added():
    from app.events.project_events import NotificationHandler

    handler = NotificationHandler()
    ctx = _make_proj_ctx("project.member_added")

    with patch("app.events.project_events.notif_svc") as mock_svc:
        mock_svc.create_and_push = AsyncMock()
        await handler.handle(ctx)
    mock_svc.create_and_push.assert_awaited_once()


@pytest.mark.asyncio
async def test_project_notification_handler_member_removed():
    from app.events.project_events import NotificationHandler

    handler = NotificationHandler()
    ctx = _make_proj_ctx("project.member_removed")

    with patch("app.events.project_events.notif_svc") as mock_svc:
        mock_svc.create_and_push = AsyncMock()
        await handler.handle(ctx)
    mock_svc.create_and_push.assert_awaited_once()


@pytest.mark.asyncio
async def test_project_notification_handler_unknown_event():
    from app.events.project_events import NotificationHandler

    handler = NotificationHandler()
    ctx = _make_proj_ctx("project.deleted")

    with patch("app.events.project_events.notif_svc") as mock_svc:
        mock_svc.create_and_push = AsyncMock()
        await handler.handle(ctx)
    mock_svc.create_and_push.assert_not_awaited()


@pytest.mark.asyncio
async def test_project_notification_handler_no_target():
    from app.events.project_events import NotificationHandler

    handler = NotificationHandler()
    ctx = _make_proj_ctx("project.member_added")
    ctx.extra = {}  # no target_user_id
    result = await handler.should_run(ctx)
    assert result is False


@pytest.mark.asyncio
async def test_project_notification_handler_same_user():
    from app.events.project_events import NotificationHandler

    handler = NotificationHandler()
    ctx = _make_proj_ctx("project.member_added")
    ctx.extra = {"target_user_id": ctx.actor.id}  # target == actor
    result = await handler.should_run(ctx)
    assert result is False


# ═══════════════════════════════════════════════════════════════════
# SPRINT EVENTS — RabbitMQHandler.handle
# ═══════════════════════════════════════════════════════════════════


def _make_sprint_ctx(event_type="sprint.updated"):
    from app.events.pipeline import EventContext

    ctx = MagicMock(spec=EventContext)
    ctx.event_type = event_type
    sprint = MagicMock()
    sprint.id = uuid.uuid4()
    sprint.project_id = uuid.uuid4()
    ctx.task = sprint
    actor = MagicMock()
    actor.id = uuid.uuid4()
    actor.full_name = "Dev"
    ctx.actor = actor
    ctx.meta = {"type": "info"}
    ctx.extra = {}
    ctx.db = AsyncMock()
    ctx.background_tasks = MagicMock(spec=BackgroundTasks)
    ctx.background_tasks.add_task = MagicMock()
    return ctx


@pytest.mark.asyncio
async def test_sprint_rabbitmq_handle_with_telegram():
    from app.events.sprint_events import RabbitMQHandler

    handler = RabbitMQHandler()
    ctx = _make_sprint_ctx("sprint.updated")
    project = MagicMock()
    project.telegram_chat_id = "12345"
    project.id = ctx.task.project_id
    ctx.db.get = AsyncMock(return_value=project)

    with patch("app.events.sprint_events._publish_sync"):
        await handler.handle(ctx)
    ctx.background_tasks.add_task.assert_called_once()


@pytest.mark.asyncio
async def test_sprint_rabbitmq_handle_no_project():
    from app.events.sprint_events import RabbitMQHandler

    handler = RabbitMQHandler()
    ctx = _make_sprint_ctx("sprint.updated")
    ctx.db.get = AsyncMock(return_value=None)

    await handler.handle(ctx)
    ctx.background_tasks.add_task.assert_not_called()


@pytest.mark.asyncio
async def test_sprint_rabbitmq_handle_no_telegram():
    from app.events.sprint_events import RabbitMQHandler

    handler = RabbitMQHandler()
    ctx = _make_sprint_ctx("sprint.updated")
    project = MagicMock()
    project.telegram_chat_id = None
    ctx.db.get = AsyncMock(return_value=project)

    await handler.handle(ctx)
    ctx.background_tasks.add_task.assert_not_called()


# ═══════════════════════════════════════════════════════════════════
# NOTIFICATIONS SERVICE — push_via_redis
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_push_via_redis_success():
    from app.modules.notifications.service import push_via_redis

    mock_client = AsyncMock()
    mock_client.publish = AsyncMock()
    mock_client.aclose = AsyncMock()

    with patch("app.modules.notifications.service.settings") as mock_settings:
        mock_settings.REDIS_URL = "redis://localhost:6379"
        with patch("redis.asyncio.from_url", return_value=mock_client):
            await push_via_redis({"user_id": str(uuid.uuid4()), "title": "Test"})
    mock_client.publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_push_via_redis_no_user_id():
    from app.modules.notifications.service import push_via_redis

    mock_client = AsyncMock()
    mock_client.aclose = AsyncMock()

    with patch("app.modules.notifications.service.settings") as mock_settings:
        mock_settings.REDIS_URL = "redis://localhost:6379"
        with patch("redis.asyncio.from_url", return_value=mock_client):
            await push_via_redis({"title": "No user"})
    mock_client.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_push_via_redis_exception():
    from app.modules.notifications.service import push_via_redis

    with patch("redis.asyncio.from_url", side_effect=Exception("connection refused")):
        # Should not raise, just log warning
        await push_via_redis({"user_id": str(uuid.uuid4())})


# ═══════════════════════════════════════════════════════════════════
# PROJECTS MANAGER — add_member, get_all_members, update_member, remove_member
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_projects_manager_add_member():
    from app.modules.projects.manager import project_manager

    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    member = MagicMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.first.return_value = member
    db.execute = AsyncMock(return_value=result_mock)

    result = await project_manager.add_member(db, uuid.uuid4(), uuid.uuid4(), "member")
    assert result == member


@pytest.mark.asyncio
async def test_projects_manager_get_all_members():
    from app.modules.projects.manager import project_manager

    db = AsyncMock()
    m1, m2 = MagicMock(), MagicMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = [m1, m2]
    db.execute = AsyncMock(return_value=result_mock)

    result = await project_manager.get_all_members(db, uuid.uuid4())
    assert result == [m1, m2]


@pytest.mark.asyncio
async def test_projects_manager_update_member():
    from app.modules.projects.manager import project_manager

    db = AsyncMock()
    db.flush = AsyncMock()
    member = MagicMock()
    member.project_id = uuid.uuid4()
    member.user_id = uuid.uuid4()
    updated = MagicMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.first.return_value = updated
    db.execute = AsyncMock(return_value=result_mock)

    result = await project_manager.update_member(db, member, {"project_role": "viewer"})
    assert result == updated


@pytest.mark.asyncio
async def test_projects_manager_remove_member_found():
    from app.modules.projects.manager import project_manager

    db = AsyncMock()
    db.flush = AsyncMock()
    db.delete = AsyncMock()
    member = MagicMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.first.return_value = member
    db.execute = AsyncMock(return_value=result_mock)

    result = await project_manager.remove_member(db, uuid.uuid4(), uuid.uuid4())
    assert result is True


@pytest.mark.asyncio
async def test_projects_manager_remove_member_not_found():
    from app.modules.projects.manager import project_manager

    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.first.return_value = None
    db.execute = AsyncMock(return_value=result_mock)

    result = await project_manager.remove_member(db, uuid.uuid4(), uuid.uuid4())
    assert result is False


# ═══════════════════════════════════════════════════════════════════
# DASHBOARD MANAGER — get_summary branches (no projects, with projects)
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_dashboard_get_personal_stats_no_projects():
    from app.modules.dashboard.manager import dashboard_manager

    db = AsyncMock()
    user = MagicMock()
    user.id = uuid.uuid4()

    db.scalar = AsyncMock(return_value=0)
    empty_result = MagicMock()
    empty_result.all.return_value = []
    empty_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=empty_result)

    result = await dashboard_manager.get_personal_stats(db, current_user=user)
    assert result is not None


@pytest.mark.asyncio
async def test_dashboard_get_personal_stats_with_workspace():
    from app.modules.dashboard.manager import dashboard_manager

    db = AsyncMock()
    user = MagicMock()
    user.id = uuid.uuid4()
    ws_id = uuid.uuid4()

    db.scalar = AsyncMock(return_value=5)
    empty_result = MagicMock()
    empty_result.all.return_value = []
    empty_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=empty_result)

    result = await dashboard_manager.get_personal_stats(
        db, current_user=user, workspace_id=ws_id
    )
    assert result is not None
