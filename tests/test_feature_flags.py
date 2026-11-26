"""require_feature resolves the workspace from epic and automation-rule URLs."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.models.automation import AutomationRule
from app.models.epic import Epic
from app.models.project import Project
from app.models.workspace import Workspace
from app.modules.workspaces.features import require_feature

WS_ID = uuid.uuid4()
PROJECT_ID = uuid.uuid4()


def _db(settings):
    objects = {
        Epic: SimpleNamespace(workspace_id=WS_ID, project_id=None),
        AutomationRule: SimpleNamespace(project_id=PROJECT_ID),
        Project: SimpleNamespace(workspace_id=WS_ID),
        Workspace: SimpleNamespace(settings=settings),
    }
    db = AsyncMock()
    db.get.side_effect = lambda model, _id: objects[model]
    return db


def _request(**path_params):
    return SimpleNamespace(path_params={k: str(v) for k, v in path_params.items()})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("param", "feature"),
    [("epic_id", "enable_epics"), ("rule_id", "enable_automation")],
)
async def test_enabled_feature_passes(param, feature):
    checker = require_feature(feature)
    assert (
        await checker(_request(**{param: uuid.uuid4()}), _db({feature: True})) is True
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("param", "feature"),
    [("epic_id", "enable_epics"), ("rule_id", "enable_automation")],
)
async def test_disabled_feature_is_blocked(param, feature):
    checker = require_feature(feature)
    with pytest.raises(HTTPException) as exc:
        await checker(_request(**{param: uuid.uuid4()}), _db({feature: False}))
    assert exc.value.status_code == 403
