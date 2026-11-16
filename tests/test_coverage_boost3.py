"""Final coverage push tests."""

import uuid
from datetime import datetime, timedelta, date
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.exc import OperationalError

import pytest


def _make_user(**kw):
    u = MagicMock()
    u.id = kw.get("id", uuid.uuid4())
    u.system_role = kw.get("system_role", "user")
    return u


# ─── RBACManager: OperationalError + except Exception in update_role ──────────


@pytest.mark.asyncio
async def test_update_role_operational_error():
    from fastapi import HTTPException
    from app.modules.rbac.manager import rbac_manager
    from app.modules.rbac.schemas import RoleUpdate

    db = AsyncMock()
    mock_role = MagicMock()
    mock_role.is_system_default = False
    mock_role.workspace_id = None
    mock_role.name = "Dev"
    mock_role.id = uuid.uuid4()
    db.scalar = AsyncMock(return_value=mock_role)
    db.commit = AsyncMock(side_effect=OperationalError("db", None, None))
    db.rollback = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await rbac_manager.update_role(
            db, uuid.uuid4(), RoleUpdate(name="New"), _make_user(system_role="admin")
        )
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_update_role_unhandled_exception():
    from app.modules.rbac.manager import rbac_manager
    from app.modules.rbac.schemas import RoleUpdate

    db = AsyncMock()
    mock_role = MagicMock()
    mock_role.is_system_default = False
    mock_role.workspace_id = None
    mock_role.name = "Dev"
    mock_role.id = uuid.uuid4()
    db.scalar = AsyncMock(return_value=mock_role)
    db.commit = AsyncMock(side_effect=RuntimeError("crash"))
    db.rollback = AsyncMock()

    with pytest.raises(RuntimeError):
        await rbac_manager.update_role(
            db, uuid.uuid4(), RoleUpdate(name="New"), _make_user(system_role="admin")
        )


# ─── RBACManager: except Exception in update_role_permissions ─────────────────


@pytest.mark.asyncio
async def test_update_role_permissions_operational_error():
    from fastapi import HTTPException
    from app.modules.rbac.manager import rbac_manager
    from app.modules.rbac.schemas import RoleUpdatePermissions

    db = AsyncMock()
    perm_id = uuid.uuid4()
    mock_role = MagicMock()
    mock_role.is_system_default = False
    mock_role.workspace_id = None
    mock_role.permissions = []
    db.scalar = AsyncMock(return_value=mock_role)

    mock_perm = MagicMock()
    mock_sc = MagicMock()
    mock_sc.all.return_value = [mock_perm]
    mock_res = MagicMock()
    mock_res.scalars.return_value = mock_sc
    db.execute = AsyncMock(return_value=mock_res)
    db.commit = AsyncMock(side_effect=OperationalError("db", None, None))
    db.rollback = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await rbac_manager.update_role_permissions(
            db,
            uuid.uuid4(),
            RoleUpdatePermissions(permission_ids=[perm_id]),
            _make_user(system_role="admin"),
        )
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_update_role_permissions_unhandled_exception():
    from app.modules.rbac.manager import rbac_manager
    from app.modules.rbac.schemas import RoleUpdatePermissions

    db = AsyncMock()
    perm_id = uuid.uuid4()
    mock_role = MagicMock()
    mock_role.is_system_default = False
    mock_role.workspace_id = None
    mock_role.permissions = []
    db.scalar = AsyncMock(return_value=mock_role)

    mock_perm = MagicMock()
    mock_sc = MagicMock()
    mock_sc.all.return_value = [mock_perm]
    mock_res = MagicMock()
    mock_res.scalars.return_value = mock_sc
    db.execute = AsyncMock(return_value=mock_res)
    db.commit = AsyncMock(side_effect=RuntimeError("crash"))
    db.rollback = AsyncMock()

    with pytest.raises(RuntimeError):
        await rbac_manager.update_role_permissions(
            db,
            uuid.uuid4(),
            RoleUpdatePermissions(permission_ids=[perm_id]),
            _make_user(system_role="admin"),
        )


# ─── RBACManager: except Exception in delete_role ────────────────────────────


@pytest.mark.asyncio
async def test_delete_role_unhandled_exception():
    from app.modules.rbac.manager import rbac_manager

    db = AsyncMock()
    mock_role = MagicMock()
    mock_role.is_system_default = False
    mock_role.workspace_id = None
    mock_role.is_deleted = False
    db.scalar = AsyncMock(return_value=mock_role)
    db.commit = AsyncMock(side_effect=RuntimeError("crash"))
    db.rollback = AsyncMock()

    with pytest.raises(RuntimeError):
        await rbac_manager.delete_role(
            db, uuid.uuid4(), _make_user(system_role="admin")
        )


# ─── SprintManager: complete_sprint edge cases ───────────────────────────────


@pytest.mark.asyncio
async def test_complete_sprint_next_sprint_no_target_id():
    from fastapi import HTTPException
    from app.modules.sprints.manager import sprint_manager

    db = AsyncMock()
    sprint = MagicMock()
    sprint.status = "active"
    sprint.id = uuid.uuid4()

    mock_sc = MagicMock()
    mock_sc.scalars.return_value.all.return_value = [MagicMock(status="todo")]
    db.execute = AsyncMock(return_value=mock_sc)

    with pytest.raises(HTTPException) as exc:
        await sprint_manager.complete_sprint(db, sprint, "next_sprint", None)
    assert exc.value.status_code == 400
    assert "no_target_sprint" in exc.value.detail


@pytest.mark.asyncio
async def test_complete_sprint_next_sprint_completed_target():
    from fastapi import HTTPException
    from app.modules.sprints.manager import sprint_manager

    db = AsyncMock()
    sprint = MagicMock()
    sprint.status = "active"
    sprint.id = uuid.uuid4()

    incomplete_task = MagicMock()
    incomplete_task.status = "todo"

    target_sprint = MagicMock()
    target_sprint.is_deleted = False
    target_sprint.status = "completed"  # already completed
    db.get = AsyncMock(return_value=target_sprint)

    mock_sc = MagicMock()
    mock_sc.scalars.return_value.all.return_value = [incomplete_task]
    db.execute = AsyncMock(return_value=mock_sc)

    with pytest.raises(HTTPException) as exc:
        await sprint_manager.complete_sprint(db, sprint, "next_sprint", uuid.uuid4())
    assert exc.value.status_code == 400
    assert "invalid_target_sprint" in exc.value.detail


# ─── SprintManager: get_burndown ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_burndown_empty_tasks():
    from app.modules.sprints.manager import sprint_manager

    db = AsyncMock()
    sprint = MagicMock()
    sprint.id = uuid.uuid4()

    mock_sc = MagicMock()
    mock_sc.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=mock_sc)

    result = await sprint_manager.get_burndown(db, sprint)
    assert result == []


@pytest.mark.asyncio
async def test_get_burndown_no_start():
    from app.modules.sprints.manager import sprint_manager

    db = AsyncMock()
    sprint = MagicMock()
    sprint.id = uuid.uuid4()
    sprint.started_at = None
    sprint.start_date = None

    task = MagicMock()
    task.estimated_hours = 5.0
    task.status = "todo"

    mock_sc = MagicMock()
    mock_sc.scalars.return_value.all.return_value = [task]
    db.execute = AsyncMock(return_value=mock_sc)

    result = await sprint_manager.get_burndown(db, sprint)
    assert result == []


@pytest.mark.asyncio
async def test_get_burndown_with_data():
    from app.modules.sprints.manager import sprint_manager

    db = AsyncMock()
    sprint = MagicMock()
    sprint.id = uuid.uuid4()
    sprint.started_at = datetime.now() - timedelta(days=2)
    sprint.completed_at = None
    sprint.end_date = None

    done_task = MagicMock()
    done_task.estimated_hours = 4.0
    done_task.status = "done"
    done_task.updated_at = datetime.now() - timedelta(days=1)

    todo_task = MagicMock()
    todo_task.estimated_hours = 6.0
    todo_task.status = "todo"
    todo_task.updated_at = None

    mock_sc = MagicMock()
    mock_sc.scalars.return_value.all.return_value = [done_task, todo_task]
    db.execute = AsyncMock(return_value=mock_sc)

    result = await sprint_manager.get_burndown(db, sprint)
    assert len(result) > 0
    assert "date" in result[0]
    assert "ideal_hours" in result[0]
    assert "remaining_hours" in result[0]


@pytest.mark.asyncio
async def test_get_burndown_with_start_date():
    from app.modules.sprints.manager import sprint_manager

    db = AsyncMock()
    sprint = MagicMock()
    sprint.id = uuid.uuid4()
    sprint.started_at = None
    sprint.start_date = date.today() - timedelta(days=2)
    sprint.completed_at = None
    sprint.end_date = date.today()

    task = MagicMock()
    task.estimated_hours = None  # will use default 1.0
    task.status = "todo"
    task.updated_at = None

    mock_sc = MagicMock()
    mock_sc.scalars.return_value.all.return_value = [task]
    db.execute = AsyncMock(return_value=mock_sc)

    result = await sprint_manager.get_burndown(db, sprint)
    assert len(result) >= 1


# ─── TaskManager: cascade sprint_id to subtasks ──────────────────────────────


@pytest.mark.asyncio
async def test_task_update_cascade_sprint_to_subtasks():
    from app.modules.tasks.manager import task_manager
    from app.modules.tasks.schemas import TaskUpdate

    db = AsyncMock()
    task = MagicMock()
    task.id = uuid.uuid4()
    task.project_id = uuid.uuid4()
    task.parent_task_id = None
    old_sprint_id = uuid.uuid4()
    task.sprint_id = old_sprint_id
    task.epic_id = None
    task.deadline = None

    new_sprint_id = uuid.uuid4()  # different from old

    call_count = 0

    def exec_side(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        mock_sc = MagicMock()
        mock_sc.scalars.return_value.all.return_value = []
        mock_sc.scalar_one_or_none.return_value = task
        return mock_sc

    db.execute = AsyncMock(side_effect=exec_side)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    await task_manager.update(
        db, db_obj=task, obj_in=TaskUpdate(sprint_id=new_sprint_id)
    )
    # Should have called execute for cascade update
    assert call_count >= 1


# ─── TaskManager: check_circular_dependency exception ────────────────────────


@pytest.mark.asyncio
async def test_check_circular_dependency_db_error():
    from fastapi import HTTPException
    from app.modules.tasks.manager import task_manager

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=OperationalError("timeout", None, None))

    with pytest.raises(HTTPException) as exc:
        await task_manager.check_circular_dependency(db, uuid.uuid4(), uuid.uuid4())
    assert exc.value.status_code == 503


# ─── TaskManager: get_impacted_descendants exception ─────────────────────────


@pytest.mark.asyncio
async def test_get_impacted_descendants_db_error():
    from app.modules.tasks.manager import task_manager

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=OperationalError("timeout", None, None))

    result = await task_manager.get_impacted_descendants(db, uuid.uuid4())
    assert result == []
