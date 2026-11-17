"""Epic permissions and validation."""

import importlib
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.epics.manager import epic_manager
from app.modules.epics.schemas import EpicCreate, EpicUpdate

epics_router = importlib.import_module("app.modules.epics.router")


def _user():
    return SimpleNamespace(id=uuid.uuid4())


def _epic(project_id=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        project_id=project_id,
        workspace_id=uuid.uuid4(),
        is_deleted=False,
    )


def test_epic_fields_are_validated():
    ws = uuid.uuid4()
    with pytest.raises(ValidationError):
        EpicCreate(name="e", workspace_id=ws, status="whatever")
    with pytest.raises(ValidationError):
        EpicCreate(name="e", workspace_id=ws, color="red; x")
    with pytest.raises(ValidationError):
        EpicUpdate(name=None)
    assert EpicCreate(name="e", workspace_id=ws, color="#3b82f6").status == "open"


@pytest.mark.asyncio
async def test_removed_members_cannot_list_workspace_epics():
    with patch.object(
        epics_router.project_manager,
        "is_workspace_member",
        new=AsyncMock(return_value=False),
    ):
        with pytest.raises(HTTPException) as exc:
            await epics_router.list_epics(uuid.uuid4(), None, MagicMock(), _user())
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_plain_members_cannot_delete_workspace_epics():
    epic = _epic()
    with (
        patch.object(epic_manager, "get", new=AsyncMock(return_value=epic)),
        patch.object(
            epics_router.rbac_manager,
            "_check_workspace_admin_access",
            new=AsyncMock(return_value=False),
        ),
        patch.object(epic_manager, "soft_delete", new=AsyncMock()) as delete,
    ):
        with pytest.raises(HTTPException) as exc:
            await epics_router.delete_epic(epic.id, MagicMock(), _user())
    assert exc.value.status_code == 403
    delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_workspace_admin_soft_deletes_an_epic():
    epic = _epic()
    me = _user()
    with (
        patch.object(epic_manager, "get", new=AsyncMock(return_value=epic)),
        patch.object(
            epics_router.rbac_manager,
            "_check_workspace_admin_access",
            new=AsyncMock(return_value=True),
        ),
        patch.object(epic_manager, "soft_delete", new=AsyncMock()) as delete,
    ):
        await epics_router.delete_epic(epic.id, MagicMock(), me)
    delete.assert_awaited_once_with(delete.await_args.args[0], epic, me.id)


@pytest.mark.asyncio
async def test_project_epic_uses_the_projects_workspace():
    project = SimpleNamespace(workspace_id=uuid.uuid4())
    epic_in = EpicCreate(name="e", workspace_id=uuid.uuid4(), project_id=uuid.uuid4())
    with (
        patch.object(
            epics_router, "get_project_pm_access", new=AsyncMock(return_value=project)
        ),
        patch.object(epic_manager, "create", new=AsyncMock()) as create,
    ):
        await epics_router.create_epic(epic_in, MagicMock(), _user())
    assert create.await_args.kwargs["obj_in"].workspace_id == project.workspace_id


def test_existing_rows_with_old_values_are_still_listed():
    from datetime import datetime

    from app.modules.epics.schemas import EpicResponse

    row = SimpleNamespace(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        project_id=None,
        name="old",
        description=None,
        color="blue",
        status="planned",
        due_date=None,
        created_at=datetime.now(),
        updated_at=None,
    )
    assert EpicResponse.model_validate(row).color == "blue"


@pytest.mark.asyncio
async def test_soft_delete_keeps_the_row():
    epic = SimpleNamespace(is_deleted=False, deleted_at=None, deleted_by=None)
    db = MagicMock()
    db.flush = AsyncMock()
    user = uuid.uuid4()
    await epic_manager.soft_delete(db, epic, user)
    assert epic.is_deleted and epic.deleted_by == user and epic.deleted_at is not None
    db.delete.assert_not_called()
