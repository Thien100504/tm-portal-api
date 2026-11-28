import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.modules.automation.manager import _normalized, automation_manager
from app.modules.automation.schemas import AutomationRuleCreate, AutomationRuleUpdate

PROJECT = uuid.uuid4()
DONE_RULE = dict(
    trigger_event="task.status_changed",
    conditions={"to_status": "done"},
    actions={"type": "add_comment", "value": "Nice!"},
)


def _existing(**overrides):
    fields = dict(
        id=uuid.uuid4(),
        project_id=PROJECT,
        name="Existing",
        is_active=True,
        **DONE_RULE,
    )
    return SimpleNamespace(**{**fields, **overrides})


def _db(existing_rules, active_count=1):
    count = MagicMock()
    count.scalar_one.return_value = active_count
    rules = MagicMock()
    rules.scalars.return_value.all.return_value = existing_rules
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[count, rules])
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    return db


def test_empty_entries_do_not_make_rules_different():
    assert _normalized({"to_status": "done", "priority": None}) == {"to_status": "done"}
    assert _normalized(None) == _normalized({}) == {}


@pytest.mark.asyncio
async def test_identical_rule_is_rejected_even_with_another_name():
    db = _db([_existing(is_active=False)])
    data = AutomationRuleCreate(name="Copy", **DONE_RULE)
    with pytest.raises(HTTPException) as exc:
        await automation_manager.create(db, PROJECT, data, uuid.uuid4())
    assert exc.value.status_code == 409
    assert exc.value.detail == "automation.duplicate_rule"
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_rule_with_another_action_value_is_allowed():
    db = _db([_existing()])
    data = AutomationRuleCreate(
        name="Other",
        **{**DONE_RULE, "actions": {"type": "add_comment", "value": "Done"}},
    )
    await automation_manager.create(db, PROJECT, data, uuid.uuid4())
    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_null_conditions_match_an_empty_condition_set():
    db = _db([_existing(conditions=None)])
    data = AutomationRuleCreate(name="Copy", **{**DONE_RULE, "conditions": {}})
    with pytest.raises(HTTPException):
        await automation_manager.create(db, PROJECT, data, uuid.uuid4())


@pytest.mark.asyncio
async def test_editing_a_rule_into_a_copy_of_another_is_rejected():
    other = _existing()
    rule = _existing(actions={"type": "add_comment", "value": "Old"})
    rules = MagicMock()
    rules.scalars.return_value.all.return_value = [other]
    db = MagicMock()
    db.execute = AsyncMock(return_value=rules)
    db.flush = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        await automation_manager.update(
            db, rule, AutomationRuleUpdate(actions=dict(DONE_RULE["actions"]))
        )
    assert exc.value.detail == "automation.duplicate_rule"
    # the rule itself is excluded from the comparison
    assert "automation_rules.id !=" in str(db.execute.await_args.args[0])
    db.flush.assert_not_awaited()
