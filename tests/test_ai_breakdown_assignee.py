import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.ai.service import breakdown_assignee as _breakdown_assignee

OWNER = uuid.uuid4()


def _db(members, workspace_type="team"):
    """members: user ids that are live members of the project."""
    db = MagicMock()

    async def scalar(stmt):
        params = stmt.compile().params
        return next((v for v in params.values() if v in members), None)

    db.scalar = AsyncMock(side_effect=scalar)
    project = SimpleNamespace(workspace_id=uuid.uuid4())
    workspace = SimpleNamespace(type=workspace_type, owner_id=OWNER)
    db.get = AsyncMock(
        side_effect=lambda model, _id: {"Project": project}.get(
            model.__name__, workspace
        )
    )
    return db


def _parent(assignee=None):
    return SimpleNamespace(project_id=uuid.uuid4(), assignee_id=assignee)


@pytest.mark.asyncio
async def test_subtasks_go_to_the_parent_assignee():
    assignee, actor = uuid.uuid4(), uuid.uuid4()
    assert (
        await _breakdown_assignee(_db({assignee, actor}), _parent(assignee), actor)
        == assignee
    )


@pytest.mark.asyncio
async def test_unassigned_parent_falls_back_to_who_asked():
    actor = uuid.uuid4()
    assert await _breakdown_assignee(_db({actor}), _parent(), actor) == actor


@pytest.mark.asyncio
async def test_non_members_are_skipped():
    # e.g. a system admin who is not in the project asks for the breakdown
    actor = uuid.uuid4()
    assert await _breakdown_assignee(_db(set()), _parent(), actor) is None


@pytest.mark.asyncio
async def test_personal_workspace_falls_back_to_its_owner():
    assert await _breakdown_assignee(_db(set(), "personal"), _parent(), None) == OWNER


@pytest.mark.asyncio
async def test_team_workspace_without_candidates_leaves_subtasks_unassigned():
    assert await _breakdown_assignee(_db(set(), "team"), _parent(), None) is None
