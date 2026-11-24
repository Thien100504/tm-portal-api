"""Access rules of global search and of the AI assistant's tools."""

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.ai import tools
from app.modules.search import service as search_service


@pytest.mark.asyncio
async def test_search_is_empty_for_non_members():
    db = MagicMock()
    db.execute = AsyncMock()
    with patch(
        "app.modules.projects.manager.project_manager.is_workspace_member",
        new=AsyncMock(return_value=False),
    ):
        result = await search_service.global_search(db, "x", uuid.uuid4(), uuid.uuid4())
    assert result == {"projects": [], "tasks": [], "users": []}
    db.execute.assert_not_awaited()


def _call(name, **args):
    return {"function": {"name": name, "arguments": json.dumps(args)}}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name, permission",
    [
        ("delete_tasks", "task.delete"),
        ("create_task", "task.create"),
        ("start_sprint", "sprint.manage"),
        ("delete_automation", "project.settings"),
    ],
)
async def test_assistant_needs_the_same_permission_as_the_user(name, permission):
    user = SimpleNamespace(id=uuid.uuid4())
    check = AsyncMock(return_value=False)
    with patch("app.modules.rbac.manager.rbac_manager.check_permission", new=check):
        result = await tools.dispatch_tool_call(
            _call(name), uuid.uuid4(), user, MagicMock()
        )
    assert permission in result
    assert check.await_args.args[2] == permission


@pytest.mark.asyncio
async def test_read_only_tools_need_no_extra_permission():
    check = AsyncMock(return_value=False)
    db = MagicMock()
    result_rows = MagicMock()
    result_rows.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=result_rows)
    with patch("app.modules.rbac.manager.rbac_manager.check_permission", new=check):
        await tools.dispatch_tool_call(
            _call("list_tasks"), uuid.uuid4(), SimpleNamespace(id=uuid.uuid4()), db
        )
    check.assert_not_awaited()
