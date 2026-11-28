"""Creating and changing tasks needs task.create / task.update, not just project access."""

import importlib
import inspect
import re
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.modules.tasks import schemas
from app.modules.tasks.manager import task_manager

tasks_router = importlib.import_module("app.modules.tasks.router")
FORBIDDEN = HTTPException(status_code=403, detail="project.missing_permission")

REQUIRED = {
    "create_task": "task.create",
    "update_task": "task.update",
    "update_task_status": "task.update",
    "update_task_position": "task.update",
    "assign_task": "task.update",
    "add_dependency": "task.update",
    "remove_dependency": "task.update",
    "request_ai_breakdown": "task.update",
    "request_ai_estimate": "task.update",
    "apply_cascade_deadline": "task.update",
}
READ_OR_COMMENT = ["get_tasks", "get_task", "get_comments", "add_comment"]


@pytest.mark.parametrize("endpoint, code", REQUIRED.items())
def test_changing_endpoints_check_the_task_permission(endpoint, code):
    src = inspect.getsource(getattr(tasks_router, endpoint))
    assert f'require_project_permission("{code}")' in src
    assert "get_project_access(" not in src


@pytest.mark.parametrize("endpoint", READ_OR_COMMENT)
def test_reading_and_commenting_only_need_project_access(endpoint):
    src = inspect.getsource(getattr(tasks_router, endpoint))
    assert "get_project_access(" in src
    assert not re.search(r'require_project_permission\("task\.(create|update)"\)', src)


def _task():
    return SimpleNamespace(id=uuid.uuid4(), project_id=uuid.uuid4(), status="todo")


def _user():
    return SimpleNamespace(id=uuid.uuid4(), system_role="user", full_name="U")


@pytest.mark.asyncio
async def test_member_without_task_create_cannot_create_a_task():
    with (
        patch.object(
            tasks_router,
            "require_project_permission",
            new=MagicMock(return_value=AsyncMock(side_effect=FORBIDDEN)),
        ) as require,
        patch.object(task_manager, "create_task", new=AsyncMock()) as create,
    ):
        with pytest.raises(HTTPException) as exc:
            await tasks_router.create_task(
                schemas.TaskCreate(title="t", project_id=uuid.uuid4()),
                MagicMock(),
                MagicMock(),
                _user(),
            )
    assert exc.value.status_code == 403
    require.assert_called_once_with("task.create")
    create.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("is_pm, allowed", [(False, False), (True, True)])
async def test_status_override_needs_project_settings(is_pm, allowed):
    task = _task()
    db = MagicMock()
    db.flush = AsyncMock()
    with (
        patch.object(task_manager, "get_by_id", new=AsyncMock(return_value=task)),
        patch.object(
            tasks_router,
            "require_project_permission",
            new=MagicMock(return_value=AsyncMock()),
        ),
        patch.object(
            tasks_router.rbac_manager,
            "check_permission",
            new=AsyncMock(return_value=is_pm),
        ),
        patch.object(
            task_manager,
            "update_status",
            new=AsyncMock(side_effect=RuntimeError("moved")),
        ) as move,
    ):
        body = schemas.TaskStatusUpdate(status="done", override=True)
        if allowed:
            with pytest.raises(RuntimeError):
                await tasks_router.update_task_status(
                    task.id, body, MagicMock(), db, _user()
                )
            move.assert_awaited_once()
        else:
            with pytest.raises(HTTPException) as exc:
                await tasks_router.update_task_status(
                    task.id, body, MagicMock(), db, _user()
                )
            assert exc.value.detail == "auth.only_pm_override"
            move.assert_not_awaited()
