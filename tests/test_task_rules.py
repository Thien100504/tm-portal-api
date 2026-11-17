"""Task rules: project-scoped references, permissions, soft-delete and notifications."""

import importlib
import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.tasks import schemas
from app.modules.tasks.manager import task_manager

tasks_router = importlib.import_module("app.modules.tasks.router")
FORBIDDEN = HTTPException(status_code=403, detail="project.permission_denied")


def _task(**kw):
    data = {
        "id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
        "workspace_id": uuid.uuid4(),
        "created_by": uuid.uuid4(),
        "is_deleted": False,
        "status": "todo",
        "assignee_id": None,
    }
    data.update(kw)
    return SimpleNamespace(**data)


def _user():
    return SimpleNamespace(id=uuid.uuid4(), system_role="user", full_name="U")


# ── schemas ──────────────────────────────────────────────────────────────────
def test_status_is_validated_and_creation_can_choose_a_column():
    pid = uuid.uuid4()
    assert schemas.TaskCreate(title="t", project_id=pid).status == "todo"
    assert (
        schemas.TaskCreate(title="t", project_id=pid, status="review").status
        == "review"
    )
    with pytest.raises(ValidationError):
        schemas.TaskStatusUpdate(status="foo")


def test_naive_deadlines_become_utc():
    task = schemas.TaskCreate(
        title="t", project_id=uuid.uuid4(), deadline=datetime(2026, 1, 1)
    )
    assert task.deadline.tzinfo is not None
    assert schemas.TaskUpdate(deadline=datetime(2026, 1, 1)).deadline.tzinfo is not None


# ── cross-project references ────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_dependency_on_a_task_of_another_project_is_rejected():
    task = _task()
    db = MagicMock()
    db.get = AsyncMock(return_value=_task())  # another project
    with pytest.raises(HTTPException) as exc:
        await task_manager.add_dependency(db, task, uuid.uuid4())
    assert exc.value.detail == "task.error_invalid_dependency"


@pytest.mark.asyncio
async def test_duplicate_dependency_is_a_conflict():
    task = _task()
    other = _task(project_id=task.project_id)
    db = MagicMock()
    db.get = AsyncMock(return_value=other)
    db.scalar = AsyncMock(return_value=task.id)  # link already exists
    no_cycle = MagicMock()
    no_cycle.scalar.return_value = None
    db.execute = AsyncMock(return_value=no_cycle)
    with pytest.raises(HTTPException) as exc:
        await task_manager.add_dependency(db, task, other.id)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_sprint_of_another_project_is_rejected():
    db = MagicMock()
    db.get = AsyncMock(
        return_value=SimpleNamespace(is_deleted=False, project_id=uuid.uuid4())
    )
    with pytest.raises(HTTPException) as exc:
        await task_manager._check_refs(
            db, uuid.uuid4(), uuid.uuid4(), sprint_id=uuid.uuid4()
        )
    assert exc.value.detail == "task.error_invalid_sprint"


@pytest.mark.asyncio
async def test_non_member_assignee_is_rejected_on_create():
    db = MagicMock()
    db.scalar = AsyncMock(return_value=None)
    with pytest.raises(HTTPException) as exc:
        await task_manager._check_refs(
            db, uuid.uuid4(), uuid.uuid4(), assignee_id=uuid.uuid4()
        )
    assert exc.value.detail == "task.error_assignee_not_member"


@pytest.mark.asyncio
async def test_workspace_epic_is_accepted_for_projects_of_that_workspace():
    ws = uuid.uuid4()
    db = MagicMock()
    db.get = AsyncMock(
        return_value=SimpleNamespace(project_id=None, workspace_id=ws, is_deleted=False)
    )
    await task_manager._check_refs(db, uuid.uuid4(), ws, epic_id=uuid.uuid4())


# ── router permissions ──────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_assign_requires_access_to_the_project():
    with (
        patch.object(task_manager, "get_by_id", new=AsyncMock(return_value=_task())),
        patch.object(
            tasks_router, "get_project_access", new=AsyncMock(side_effect=FORBIDDEN)
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await tasks_router.assign_task(
                uuid.uuid4(),
                schemas.TaskAssign(assignee_id=None),
                MagicMock(),
                MagicMock(),
                _user(),
            )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_deleting_someone_elses_task_needs_the_permission():
    checker = AsyncMock(side_effect=FORBIDDEN)
    with (
        patch.object(task_manager, "get_by_id", new=AsyncMock(return_value=_task())),
        patch.object(
            tasks_router, "require_project_permission", return_value=checker
        ) as perm,
    ):
        with pytest.raises(HTTPException):
            await tasks_router.delete_task(
                uuid.uuid4(), MagicMock(), MagicMock(), _user()
            )
    perm.assert_called_once_with("task.delete")


@pytest.mark.asyncio
async def test_members_cannot_override_rules_by_dragging():
    task = _task()
    me = _user()
    member = SimpleNamespace(project_role="member")
    db = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.commit = AsyncMock()
    with (
        patch.object(task_manager, "get_by_id", new=AsyncMock(return_value=task)),
        patch.object(
            tasks_router,
            "get_project_access",
            new=AsyncMock(return_value=SimpleNamespace(owner_id=uuid.uuid4())),
        ),
        patch.object(
            tasks_router.project_manager,
            "get_member",
            new=AsyncMock(return_value=member),
        ),
        patch.object(
            task_manager, "update_position", new=AsyncMock(return_value=task)
        ) as move,
        patch.object(tasks_router.task_events, "emit", new=AsyncMock()),
    ):
        await tasks_router.update_task_position(
            task.id, schemas.TaskPositionUpdate(status="done"), MagicMock(), db, me
        )
    assert move.await_args.kwargs["override"] is False


# ── notifications ───────────────────────────────────────────────────────────
def test_assigned_and_completed_are_external_only_over_rabbitmq():
    from app.events.task_events import EXTERNAL_ONLY

    assert "inapp" not in EXTERNAL_ONLY["task.assigned"]
    assert "inapp" not in EXTERNAL_ONLY["task.completed"]
    assert EXTERNAL_ONLY["task.unblocked"] == []


@pytest.mark.asyncio
async def test_deleting_a_task_removes_the_links_of_its_subtasks():
    me = _user()
    task = _task(created_by=me.id)
    sub_id = uuid.uuid4()
    statements = []

    async def execute(stmt):
        statements.append(stmt)
        result = MagicMock()
        result.scalars.return_value.all.return_value = [sub_id]
        return result

    db = MagicMock()
    db.execute = execute
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    with (
        patch.object(task_manager, "get_by_id", new=AsyncMock(return_value=task)),
        patch.object(tasks_router, "get_project_access", new=AsyncMock()),
        patch.object(tasks_router.task_events, "emit", new=AsyncMock()),
    ):
        await tasks_router.delete_task(task.id, MagicMock(), db, me)
    delete_stmt = next(
        s for s in statements if str(s).startswith("DELETE FROM task_dependencies")
    )
    params = delete_stmt.compile().params
    assert any(sub_id in v for v in params.values() if isinstance(v, list))
