"""
Coverage boost — targeting remaining ~61 statements to reach 80%.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi import HTTPException, BackgroundTasks


# ═══════════════════════════════════════════════════════════════════
# PROJECTS DEPENDENCIES
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_project_access_not_found():
    from app.modules.projects.dependencies import get_project_access

    db = AsyncMock()
    user = MagicMock()
    user.id = uuid.uuid4()

    with patch("app.modules.projects.dependencies.project_manager") as mock_pm:
        mock_pm.get_project_for_user = AsyncMock(return_value=None)
        with pytest.raises(HTTPException) as exc:
            await get_project_access(uuid.uuid4(), db, user)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_get_project_access_found():
    from app.modules.projects.dependencies import get_project_access

    db = AsyncMock()
    user = MagicMock()
    user.id = uuid.uuid4()
    project = MagicMock()

    with patch("app.modules.projects.dependencies.project_manager") as mock_pm:
        mock_pm.get_project_for_user = AsyncMock(return_value=project)
        result = await get_project_access(uuid.uuid4(), db, user)
    assert result == project


@pytest.mark.asyncio
async def test_require_project_permission_not_found():
    from app.modules.projects.dependencies import require_project_permission

    checker = require_project_permission("task.create")
    db = AsyncMock()
    user = MagicMock()
    user.id = uuid.uuid4()

    with patch("app.modules.projects.dependencies.project_manager") as mock_pm:
        mock_pm.get_project_for_user = AsyncMock(return_value=None)
        with pytest.raises(HTTPException) as exc:
            await checker(uuid.uuid4(), db, user)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_require_project_permission_owner():
    from app.modules.projects.dependencies import require_project_permission

    checker = require_project_permission("task.create")
    db = AsyncMock()
    user = MagicMock()
    user.id = uuid.uuid4()
    project = MagicMock()
    project.owner_id = user.id  # owner bypasses RBAC check

    with patch("app.modules.projects.dependencies.project_manager") as mock_pm:
        mock_pm.get_project_for_user = AsyncMock(return_value=project)
        result = await checker(uuid.uuid4(), db, user)
    assert result == project


@pytest.mark.asyncio
async def test_require_project_permission_denied():
    from app.modules.projects.dependencies import require_project_permission

    checker = require_project_permission("task.create")
    db = AsyncMock()
    user = MagicMock()
    user.id = uuid.uuid4()
    project = MagicMock()
    project.owner_id = uuid.uuid4()  # different from user

    with (
        patch("app.modules.projects.dependencies.project_manager") as mock_pm,
        patch("app.modules.projects.dependencies.rbac_manager") as mock_rbac,
    ):
        mock_pm.get_project_for_user = AsyncMock(return_value=project)
        mock_rbac.check_permission = AsyncMock(return_value=False)
        with pytest.raises(HTTPException) as exc:
            await checker(uuid.uuid4(), db, user)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_require_project_permission_granted():
    from app.modules.projects.dependencies import require_project_permission

    checker = require_project_permission("task.create")
    db = AsyncMock()
    user = MagicMock()
    user.id = uuid.uuid4()
    project = MagicMock()
    project.owner_id = uuid.uuid4()

    with (
        patch("app.modules.projects.dependencies.project_manager") as mock_pm,
        patch("app.modules.projects.dependencies.rbac_manager") as mock_rbac,
    ):
        mock_pm.get_project_for_user = AsyncMock(return_value=project)
        mock_rbac.check_permission = AsyncMock(return_value=True)
        result = await checker(uuid.uuid4(), db, user)
    assert result == project


@pytest.mark.asyncio
async def test_get_project_pm_access():
    from app.modules.projects.dependencies import get_project_pm_access

    db = AsyncMock()
    user = MagicMock()
    user.id = uuid.uuid4()
    project = MagicMock()
    project.owner_id = user.id

    with patch("app.modules.projects.dependencies.project_manager") as mock_pm:
        mock_pm.get_project_for_user = AsyncMock(return_value=project)
        result = await get_project_pm_access(uuid.uuid4(), db, user)
    assert result == project


# ═══════════════════════════════════════════════════════════════════
# DASHBOARD MANAGER — get_personal_stats with actual projects
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_dashboard_personal_stats_with_project_rows():
    from app.modules.dashboard.manager import dashboard_manager

    db = AsyncMock()
    user = MagicMock()
    user_id = uuid.uuid4()
    user.id = user_id

    # All execute calls return empty results (covers the branch where project_rows is empty)
    # To cover the for-loop branch we provide a valid project row
    proj_id = uuid.uuid4()

    # Upcoming task row needs real attribute access
    class TaskRow:
        class Task:
            id = uuid.uuid4()
            title = "Fix bug"
            deadline = None
            priority = "high"
            status = "todo"
            project_id = proj_id

        project_name = "Alpha"

    class ProjRow:
        class Project:
            id = proj_id
            name = "Alpha"

        name = "Developer"

    call_count = [0]

    async def execute_side_effect(q):
        r = MagicMock()
        c = call_count[0]
        call_count[0] += 1
        if c == 0:
            # completed_tasks query
            r.all.return_value = []
        elif c == 1:
            # upcoming_tasks query
            r.all.return_value = []
        elif c == 2:
            # projects query
            r.all.return_value = [ProjRow()]
        else:
            r.all.return_value = []
            r.scalars.return_value.all.return_value = []
        return r

    db.execute = execute_side_effect
    db.scalar = AsyncMock(return_value=2)

    result = await dashboard_manager.get_personal_stats(db, current_user=user)
    assert result is not None


# ═══════════════════════════════════════════════════════════════════
# PROJECTS MANAGER — attach_member_count
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_projects_manager_attach_member_count():
    from app.modules.projects.manager import project_manager

    db = AsyncMock()
    project = MagicMock()
    project.id = uuid.uuid4()
    project.memberships = []
    db.scalar = AsyncMock(return_value=5)

    result = await project_manager.attach_member_count(db, project)
    assert result == project
    assert result.member_count == 5


# ═══════════════════════════════════════════════════════════════════
# NOTIFICATIONS SERVICE — _publish_notification_sync error handling
# ═══════════════════════════════════════════════════════════════════


def test_publish_notification_sync_exception():
    from app.modules.notifications.service import _publish_notification_sync

    with patch(
        "app.modules.notifications.service.EventPublisher",
        side_effect=Exception("conn error"),
    ):
        # Should not raise, just log
        _publish_notification_sync({"user_id": str(uuid.uuid4())})


# ═══════════════════════════════════════════════════════════════════
# SPRINT EVENTS — SprintEventService.emit
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_sprint_event_service_emit():
    from app.events.sprint_events import sprint_events

    db = AsyncMock()
    bg = MagicMock(spec=BackgroundTasks)
    bg.add_task = MagicMock()
    actor = MagicMock()
    actor.id = uuid.uuid4()
    actor.full_name = "Dev"
    sprint = MagicMock()
    sprint.id = uuid.uuid4()
    sprint.project_id = uuid.uuid4()
    sprint.name = "S1"
    sprint.start_date = None
    sprint.end_date = None

    with patch("app.events.sprint_events._pipeline") as mock_pipeline:
        mock_pipeline.run = AsyncMock()
        await sprint_events.emit(db, bg, "sprint.updated", sprint, actor)
    mock_pipeline.run.assert_awaited_once()


# ═══════════════════════════════════════════════════════════════════
# PROJECT EVENTS — ProjectEventService.emit
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_project_event_service_emit():
    from app.events.project_events import project_events

    db = AsyncMock()
    bg = MagicMock(spec=BackgroundTasks)
    actor = MagicMock()
    actor.id = uuid.uuid4()
    actor.full_name = "PM"
    project = MagicMock()
    project.id = uuid.uuid4()
    project.name = "ProjectX"

    with patch("app.events.project_events._pipeline") as mock_pipeline:
        mock_pipeline.run = AsyncMock()
        await project_events.emit(
            db,
            bg,
            "project.member_added",
            project,
            actor,
            extra={"target_user_id": uuid.uuid4()},
        )
    mock_pipeline.run.assert_awaited_once()


# ═══════════════════════════════════════════════════════════════════
# TASK EVENTS — additional branches
# ═══════════════════════════════════════════════════════════════════


def _make_task_ctx(event_type="task.updated"):
    from app.events.pipeline import EventContext

    ctx = MagicMock(spec=EventContext)
    ctx.event_type = event_type
    task = MagicMock()
    task.id = uuid.uuid4()
    task.project_id = uuid.uuid4()
    task.title = "Test Task"
    task.assignee_id = uuid.uuid4()
    task.status = "todo"
    task.priority = "medium"
    ctx.task = task
    actor = MagicMock()
    actor.id = uuid.uuid4()
    actor.full_name = "Dev"
    ctx.actor = actor
    ctx.extra = {}
    ctx.meta = {}
    ctx.db = AsyncMock()
    ctx.background_tasks = MagicMock(spec=BackgroundTasks)
    ctx.background_tasks.add_task = MagicMock()
    return ctx


@pytest.mark.asyncio
async def test_task_stakeholder_handler_deleted():
    from app.events.task_events import StakeholderHandler

    handler = StakeholderHandler()
    ctx = _make_task_ctx("task.deleted")

    await handler.handle(ctx)
    assert ctx.skip_external is True


@pytest.mark.asyncio
async def test_task_stakeholder_handler_with_assignee():
    from app.events.task_events import StakeholderHandler

    handler = StakeholderHandler()
    ctx = _make_task_ctx("task.updated")
    ctx.task.assignee_id = uuid.uuid4()
    ctx.task.created_by = uuid.uuid4()
    ctx.skip_external = False

    await handler.handle(ctx)
    assert len(ctx.stakeholders) >= 1


@pytest.mark.asyncio
async def test_task_rabbitmq_handler_no_skip():
    from app.events.task_events import RabbitMQHandler

    handler = RabbitMQHandler()
    ctx = _make_task_ctx("task.updated")
    ctx.skip_external = False
    ctx.stakeholders = {uuid.uuid4()}
    result = await handler.should_run(ctx)
    assert result is True

    ctx2 = _make_task_ctx("task.updated")
    ctx2.skip_external = True
    ctx2.stakeholders = {uuid.uuid4()}
    result2 = await handler.should_run(ctx2)
    assert result2 is False
