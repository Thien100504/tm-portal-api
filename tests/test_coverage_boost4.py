"""
Coverage boost 4 — targets the highest-gap modules:
  - automation/manager.py (CRUD + execute_rules + _check_conditions)
  - admin/manager.py (all methods)
  - auth/dependencies.py (get_current_user paths, get_current_user_from_token)
  - events/task_events.py (all handlers)
  - events/sprint_events.py (all handlers)
  - middleware/request_id.py
  - dashboard/manager.py (get_admin_stats)
  - tasks/router.py (HTTP tests with overridden deps)
"""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import BackgroundTasks

# ─── Helpers ─────────────────────────────────────────────────────────────────


def _make_user(**kw):
    u = MagicMock()
    u.id = kw.get("id", uuid.uuid4())
    u.email = kw.get("email", "user@test.com")
    u.full_name = kw.get("full_name", "Test User")
    u.is_active = kw.get("is_active", True)
    u.system_role = kw.get("system_role", "user")
    u.password_hash = "hashed"
    u.telegram_chat_id = None
    u.created_at = datetime.utcnow()
    return u


def _make_task(**kw):
    t = MagicMock()
    t.id = kw.get("id", uuid.uuid4())
    t.project_id = kw.get("project_id", uuid.uuid4())
    t.title = kw.get("title", "Test Task")
    t.status = kw.get("status", "todo")
    t.priority = kw.get("priority", "medium")
    t.assignee_id = kw.get("assignee_id")
    t.created_by = kw.get("created_by", uuid.uuid4())
    t.is_deleted = False
    return t


def _make_sprint(**kw):
    s = MagicMock()
    s.id = kw.get("id", uuid.uuid4())
    s.project_id = kw.get("project_id", uuid.uuid4())
    s.name = kw.get("name", "Sprint 1")
    s.status = kw.get("status", "planning")
    return s


def _make_rule(**kw):
    r = MagicMock()
    r.id = kw.get("id", uuid.uuid4())
    r.project_id = kw.get("project_id", uuid.uuid4())
    r.name = kw.get("name", "Rule 1")
    r.trigger_event = kw.get("trigger_event", "task.created")
    r.conditions = kw.get("conditions", {})
    r.actions = kw.get("actions", {"type": "set_status"})
    r.is_active = kw.get("is_active", True)
    return r


def _scalars(items=None, first=None):
    sc = MagicMock()
    sc.all.return_value = items if items is not None else []
    sc.first.return_value = first
    r = MagicMock()
    r.scalars.return_value = sc
    r.scalar_one_or_none.return_value = first
    return r


# ═══════════════════════════════════════════════════════════════════
# AUTOMATION MANAGER
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_automation_list_by_project():
    from app.modules.automation.manager import automation_manager

    db = AsyncMock()
    rule = _make_rule()
    db.execute.return_value = _scalars(items=[rule])
    result = await automation_manager.list_by_project(db, uuid.uuid4())
    assert result == [rule]


@pytest.mark.asyncio
async def test_automation_get_found():
    from app.modules.automation.manager import automation_manager

    db = AsyncMock()
    rule = _make_rule()
    db.get = AsyncMock(return_value=rule)
    result = await automation_manager.get(db, rule.id)
    assert result == rule


@pytest.mark.asyncio
async def test_automation_get_not_found():
    from app.modules.automation.manager import automation_manager

    db = AsyncMock()
    db.get = AsyncMock(return_value=None)
    result = await automation_manager.get(db, uuid.uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_automation_create_valid():
    from app.modules.automation.manager import automation_manager
    from app.modules.automation.schemas import AutomationRuleCreate

    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    mock_result = MagicMock()
    mock_result.scalar_one.return_value = 0
    db.execute = AsyncMock(return_value=mock_result)

    data = AutomationRuleCreate(
        name="Auto assign",
        trigger_event="task.created",
        conditions={},
        actions={"type": "set_status", "status": "in_progress"},
        is_active=True,
    )
    await automation_manager.create(db, uuid.uuid4(), data, uuid.uuid4())
    db.add.assert_called_once()
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_automation_create_invalid_trigger():
    from fastapi import HTTPException

    from app.modules.automation.manager import automation_manager
    from app.modules.automation.schemas import AutomationRuleCreate

    db = AsyncMock()
    data = AutomationRuleCreate(
        name="Bad",
        trigger_event="invalid.event",
        conditions={},
        actions={"type": "set_status"},
        is_active=True,
    )
    with pytest.raises(HTTPException) as exc:
        await automation_manager.create(db, uuid.uuid4(), data, uuid.uuid4())
    assert exc.value.status_code == 400
    assert "trigger" in exc.value.detail


@pytest.mark.asyncio
async def test_automation_create_invalid_action():
    from fastapi import HTTPException

    from app.modules.automation.manager import automation_manager
    from app.modules.automation.schemas import AutomationRuleCreate

    db = AsyncMock()
    data = AutomationRuleCreate(
        name="Bad",
        trigger_event="task.created",
        conditions={},
        actions={"type": "invalid_action"},
        is_active=True,
    )
    with pytest.raises(HTTPException) as exc:
        await automation_manager.create(db, uuid.uuid4(), data, uuid.uuid4())
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_automation_update_name_and_conditions():
    from app.modules.automation.manager import automation_manager
    from app.modules.automation.schemas import AutomationRuleUpdate

    db = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    rule = _make_rule()

    data = AutomationRuleUpdate(name="New Name", conditions={"priority": "high"})
    await automation_manager.update(db, rule, data)
    assert rule.name == "New Name"
    assert rule.conditions == {"priority": "high"}


@pytest.mark.asyncio
async def test_automation_update_invalid_action():
    from fastapi import HTTPException

    from app.modules.automation.manager import automation_manager
    from app.modules.automation.schemas import AutomationRuleUpdate

    db = AsyncMock()
    rule = _make_rule()
    data = AutomationRuleUpdate(actions={"type": "bad_action"})
    with pytest.raises(HTTPException):
        await automation_manager.update(db, rule, data)


@pytest.mark.asyncio
async def test_automation_update_is_active():
    from app.modules.automation.manager import automation_manager
    from app.modules.automation.schemas import AutomationRuleUpdate

    db = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    rule = _make_rule(is_active=True)
    data = AutomationRuleUpdate(is_active=False)
    await automation_manager.update(db, rule, data)
    assert rule.is_active is False


@pytest.mark.asyncio
async def test_automation_toggle():
    from app.modules.automation.manager import automation_manager

    db = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    rule = _make_rule(is_active=True)
    await automation_manager.toggle(db, rule)
    assert rule.is_active is False


@pytest.mark.asyncio
async def test_automation_delete():
    from app.modules.automation.manager import automation_manager

    db = AsyncMock()
    db.delete = AsyncMock()
    db.flush = AsyncMock()
    rule = _make_rule()
    await automation_manager.delete(db, rule)
    db.delete.assert_awaited_once_with(rule)
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_automation_execute_rules_no_rules():
    from app.modules.automation.manager import automation_manager

    db = AsyncMock()
    db.execute.return_value = _scalars(items=[])
    task = _make_task()
    count = await automation_manager.execute_rules(
        db, task.project_id, "task.created", task
    )
    assert count == 0


@pytest.mark.asyncio
async def test_automation_execute_rules_condition_fails():
    from app.modules.automation.manager import automation_manager

    db = AsyncMock()
    rule = _make_rule(conditions={"to_status": "done"}, actions={"type": "set_status"})
    db.execute.return_value = _scalars(items=[rule])
    task = _make_task(status="todo")
    # context doesn't satisfy condition
    count = await automation_manager.execute_rules(
        db,
        task.project_id,
        "task.status_changed",
        task,
        context={"old_status": "todo", "new_status": "in_progress"},
    )
    assert count == 0


@pytest.mark.asyncio
async def test_automation_execute_rules_action_executed():
    from app.modules.automation.manager import automation_manager

    db = AsyncMock()
    db.flush = AsyncMock()
    rule = _make_rule(conditions={}, actions={"type": "set_status", "status": "done"})
    db.execute.return_value = _scalars(items=[rule])
    task = _make_task()

    with patch(
        "app.modules.automation.actions.execute_action",
        new=AsyncMock(return_value=True),
    ):
        count = await automation_manager.execute_rules(
            db, task.project_id, "task.created", task
        )
    assert count == 1


@pytest.mark.asyncio
async def test_automation_execute_rules_action_exception():
    from app.modules.automation.manager import automation_manager

    db = AsyncMock()
    rule = _make_rule(conditions={}, actions={"type": "set_status"})
    db.execute.return_value = _scalars(items=[rule])
    task = _make_task()

    with patch(
        "app.modules.automation.actions.execute_action",
        new=AsyncMock(side_effect=RuntimeError("fail")),
    ):
        count = await automation_manager.execute_rules(
            db, task.project_id, "task.created", task
        )
    assert count == 0


def test_check_conditions_to_status_match():
    from app.modules.automation.manager import _check_conditions

    task = _make_task()
    assert (
        _check_conditions({"to_status": "done"}, task, {"new_status": "done"}) is True
    )


def test_check_conditions_to_status_mismatch():
    from app.modules.automation.manager import _check_conditions

    task = _make_task()
    assert (
        _check_conditions({"to_status": "done"}, task, {"new_status": "todo"}) is False
    )


def test_check_conditions_from_status():
    from app.modules.automation.manager import _check_conditions

    task = _make_task()
    assert (
        _check_conditions({"from_status": "todo"}, task, {"old_status": "todo"}) is True
    )
    assert (
        _check_conditions({"from_status": "todo"}, task, {"old_status": "done"})
        is False
    )


def test_check_conditions_priority():
    from app.modules.automation.manager import _check_conditions

    task = _make_task(priority="high")
    assert _check_conditions({"priority": "high"}, task, {}) is True
    assert _check_conditions({"priority": "low"}, task, {}) is False


def test_check_conditions_to_priority():
    from app.modules.automation.manager import _check_conditions

    task = _make_task()
    ctx = {"new_priority": "high"}
    assert _check_conditions({"to_priority": "high"}, task, ctx) is True
    assert _check_conditions({"to_priority": "low"}, task, ctx) is False


def test_check_conditions_empty():
    from app.modules.automation.manager import _check_conditions

    task = _make_task()
    assert _check_conditions({}, task, {}) is True


# ═══════════════════════════════════════════════════════════════════
# ADMIN MANAGER
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_admin_list_users():
    from app.modules.admin.manager import admin_manager

    db = AsyncMock()
    users = [_make_user(), _make_user()]
    db.execute.return_value = _scalars(items=users)
    result = await admin_manager.list_users(db)
    assert result == users


@pytest.mark.asyncio
async def test_admin_update_user_role_found():
    from app.modules.admin.manager import admin_manager

    db = AsyncMock()
    user = _make_user(system_role="user")
    db.get = AsyncMock(return_value=user)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    await admin_manager.update_user_role(db, user.id, "admin")
    assert user.system_role == "admin"


@pytest.mark.asyncio
async def test_admin_update_user_role_not_found():
    from fastapi import HTTPException

    from app.modules.admin.manager import admin_manager

    db = AsyncMock()
    db.get = AsyncMock(return_value=None)
    with pytest.raises(HTTPException) as exc:
        await admin_manager.update_user_role(db, uuid.uuid4(), "admin")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_admin_update_user_status():
    from app.modules.admin.manager import admin_manager

    db = AsyncMock()
    user = _make_user(is_active=True)
    db.get = AsyncMock(return_value=user)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    await admin_manager.update_user_status(db, user.id, False)
    assert user.is_active is False


@pytest.mark.asyncio
async def test_admin_update_user_status_not_found():
    from fastapi import HTTPException

    from app.modules.admin.manager import admin_manager

    db = AsyncMock()
    db.get = AsyncMock(return_value=None)
    with pytest.raises(HTTPException) as exc:
        await admin_manager.update_user_status(db, uuid.uuid4(), False)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_admin_list_workspaces_empty():
    from app.modules.admin.manager import admin_manager

    db = AsyncMock()
    db.execute.return_value = _scalars(items=[])
    result = await admin_manager.list_workspaces(db)
    assert result == []


@pytest.mark.asyncio
async def test_admin_list_workspaces_with_data():
    from app.modules.admin.manager import admin_manager

    db = AsyncMock()
    ws = MagicMock()
    ws.id = uuid.uuid4()
    ws.name = "My Workspace"
    ws.type = "team"
    ws.created_at = datetime.utcnow()
    ws.owner = _make_user()

    # First execute returns workspace list, subsequent return count aggregates
    call_count = 0

    def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _scalars(items=[ws])
        # Count queries return list of (uuid, int) rows
        mock = MagicMock()
        mock.all.return_value = [(ws.id, call_count - 1)]
        return mock

    db.execute.side_effect = side_effect

    result = await admin_manager.list_workspaces(db)
    assert len(result) == 1
    assert result[0]["name"] == "My Workspace"


@pytest.mark.asyncio
async def test_admin_update_user_profile_not_found():
    from fastapi import HTTPException

    from app.modules.admin.manager import admin_manager

    db = AsyncMock()
    db.get = AsyncMock(return_value=None)
    with pytest.raises(HTTPException) as exc:
        await admin_manager.update_user_profile(db, uuid.uuid4(), full_name="New")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_admin_update_user_profile_email_conflict():
    from fastapi import HTTPException

    from app.modules.admin.manager import admin_manager

    db = AsyncMock()
    user = _make_user()
    db.get = AsyncMock(return_value=user)
    existing = _make_user(email="taken@test.com")
    db.scalar = AsyncMock(return_value=existing)
    with pytest.raises(HTTPException) as exc:
        await admin_manager.update_user_profile(db, user.id, email="taken@test.com")
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_admin_update_user_profile_success():
    from app.modules.admin.manager import admin_manager

    db = AsyncMock()
    user = _make_user()
    db.get = AsyncMock(return_value=user)
    db.scalar = AsyncMock(return_value=None)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    await admin_manager.update_user_profile(
        db, user.id, full_name="New Name", email="new@test.com"
    )
    assert user.full_name == "New Name"
    assert user.email == "new@test.com"


@pytest.mark.asyncio
async def test_admin_reset_password_not_found():
    from fastapi import HTTPException

    from app.modules.admin.manager import admin_manager

    db = AsyncMock()
    db.get = AsyncMock(return_value=None)
    with pytest.raises(HTTPException) as exc:
        await admin_manager.reset_user_password(db, uuid.uuid4(), "NewPass1!")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_admin_reset_password_success():
    from app.modules.admin.manager import admin_manager

    db = AsyncMock()
    user = _make_user()
    db.get = AsyncMock(return_value=user)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    await admin_manager.reset_user_password(db, user.id, "NewSecure1!")
    # Password should be hashed (not stored as plain text)
    assert user.password_hash != "NewSecure1!"


# ═══════════════════════════════════════════════════════════════════
# AUTH DEPENDENCIES
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_current_user_invalid_token():
    from fastapi import HTTPException

    from app.modules.auth.dependencies import get_current_user

    with patch("app.modules.auth.dependencies.decode_token", return_value=None):
        with pytest.raises(HTTPException) as exc:
            await get_current_user(token="bad", db=AsyncMock())
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_wrong_token_type():
    from fastapi import HTTPException

    from app.modules.auth.dependencies import get_current_user

    with (
        patch(
            "app.modules.auth.dependencies.decode_token",
            return_value={"type": "refresh", "sub": str(uuid.uuid4())},
        ),
        pytest.raises(HTTPException) as exc,
    ):
        await get_current_user(token="tok", db=AsyncMock())
    assert exc.value.status_code == 401
    assert "invalid_token" in exc.value.detail


@pytest.mark.asyncio
async def test_get_current_user_blacklisted():
    from fastapi import HTTPException

    from app.modules.auth.dependencies import get_current_user

    user_id = uuid.uuid4()
    payload = {"type": "access", "sub": str(user_id)}

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=b"1")
    mock_redis.aclose = AsyncMock()

    with (
        patch("app.modules.auth.dependencies.decode_token", return_value=payload),
        patch(
            "app.modules.auth.dependencies.aioredis.from_url", return_value=mock_redis
        ),
        pytest.raises(HTTPException) as exc,
    ):
        await get_current_user(token="tok", db=AsyncMock())
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_redis_down_fail_open():
    """Redis down → fail open, continue auth check."""
    from app.modules.auth.dependencies import get_current_user

    user_id = uuid.uuid4()
    user = _make_user(id=user_id)
    payload = {"type": "access", "sub": str(user_id)}

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(side_effect=ConnectionError("down"))
    mock_redis.aclose = AsyncMock()

    db = AsyncMock()
    db.get = AsyncMock(return_value=user)

    with (
        patch("app.modules.auth.dependencies.decode_token", return_value=payload),
        patch(
            "app.modules.auth.dependencies.aioredis.from_url", return_value=mock_redis
        ),
    ):
        result = await get_current_user(token="tok", db=db)
    assert result == user


@pytest.mark.asyncio
async def test_get_current_user_no_sub():
    from app.modules.auth.dependencies import get_current_user

    payload = {"type": "access"}
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.aclose = AsyncMock()

    with (
        patch("app.modules.auth.dependencies.decode_token", return_value=payload),
        patch(
            "app.modules.auth.dependencies.aioredis.from_url", return_value=mock_redis
        ),
        pytest.raises(Exception),
    ):
        await get_current_user(token="tok", db=AsyncMock())


@pytest.mark.asyncio
async def test_get_current_user_invalid_uuid():
    from app.modules.auth.dependencies import get_current_user

    payload = {"type": "access", "sub": "not-a-uuid"}
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.aclose = AsyncMock()

    with (
        patch("app.modules.auth.dependencies.decode_token", return_value=payload),
        patch(
            "app.modules.auth.dependencies.aioredis.from_url", return_value=mock_redis
        ),
        pytest.raises(Exception),
    ):
        await get_current_user(token="tok", db=AsyncMock())


@pytest.mark.asyncio
async def test_get_current_user_not_found_in_db():
    from app.modules.auth.dependencies import get_current_user

    user_id = uuid.uuid4()
    payload = {"type": "access", "sub": str(user_id)}
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.aclose = AsyncMock()

    db = AsyncMock()
    db.get = AsyncMock(return_value=None)

    with (
        patch("app.modules.auth.dependencies.decode_token", return_value=payload),
        patch(
            "app.modules.auth.dependencies.aioredis.from_url", return_value=mock_redis
        ),
        pytest.raises(Exception),
    ):
        await get_current_user(token="tok", db=db)


@pytest.mark.asyncio
async def test_get_current_user_inactive():
    from fastapi import HTTPException

    from app.modules.auth.dependencies import get_current_user

    user_id = uuid.uuid4()
    user = _make_user(id=user_id, is_active=False)
    payload = {"type": "access", "sub": str(user_id)}
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.aclose = AsyncMock()

    db = AsyncMock()
    db.get = AsyncMock(return_value=user)

    with (
        patch("app.modules.auth.dependencies.decode_token", return_value=payload),
        patch(
            "app.modules.auth.dependencies.aioredis.from_url", return_value=mock_redis
        ),
        pytest.raises(HTTPException) as exc,
    ):
        await get_current_user(token="tok", db=db)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_require_admin_non_admin():
    from fastapi import HTTPException

    from app.modules.auth.dependencies import require_admin

    user = _make_user(system_role="user")
    with pytest.raises(HTTPException) as exc:
        await require_admin(current_user=user)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_require_admin_ok():
    from app.modules.auth.dependencies import require_admin

    user = _make_user(system_role="admin")
    result = await require_admin(current_user=user)
    assert result == user


@pytest.mark.asyncio
async def test_get_current_user_from_token_invalid():
    from fastapi import HTTPException

    from app.modules.auth.dependencies import get_current_user_from_token

    with patch("app.modules.auth.dependencies.decode_token", return_value=None):
        with pytest.raises(HTTPException):
            await get_current_user_from_token("bad", AsyncMock())


@pytest.mark.asyncio
async def test_get_current_user_from_token_wrong_type():
    from fastapi import HTTPException

    from app.modules.auth.dependencies import get_current_user_from_token

    with (
        patch(
            "app.modules.auth.dependencies.decode_token",
            return_value={"type": "refresh"},
        ),
        pytest.raises(HTTPException),
    ):
        await get_current_user_from_token("tok", AsyncMock())


@pytest.mark.asyncio
async def test_get_current_user_from_token_no_sub():
    from fastapi import HTTPException

    from app.modules.auth.dependencies import get_current_user_from_token

    with (
        patch(
            "app.modules.auth.dependencies.decode_token",
            return_value={"type": "access"},
        ),
        pytest.raises(HTTPException),
    ):
        await get_current_user_from_token("tok", AsyncMock())


@pytest.mark.asyncio
async def test_get_current_user_from_token_invalid_uuid():
    from fastapi import HTTPException

    from app.modules.auth.dependencies import get_current_user_from_token

    with (
        patch(
            "app.modules.auth.dependencies.decode_token",
            return_value={"type": "access", "sub": "bad-uuid"},
        ),
        pytest.raises(HTTPException),
    ):
        await get_current_user_from_token("tok", AsyncMock())


@pytest.mark.asyncio
async def test_get_current_user_from_token_user_inactive():
    from fastapi import HTTPException

    from app.modules.auth.dependencies import get_current_user_from_token

    user = _make_user(is_active=False)
    db = AsyncMock()
    db.get = AsyncMock(return_value=user)
    with (
        patch(
            "app.modules.auth.dependencies.decode_token",
            return_value={"type": "access", "sub": str(user.id)},
        ),
        pytest.raises(HTTPException),
    ):
        await get_current_user_from_token("tok", db)


@pytest.mark.asyncio
async def test_get_current_user_from_token_success():
    from app.modules.auth.dependencies import get_current_user_from_token

    user = _make_user(is_active=True)
    db = AsyncMock()
    db.get = AsyncMock(return_value=user)
    with patch(
        "app.modules.auth.dependencies.decode_token",
        return_value={"type": "access", "sub": str(user.id)},
    ):
        result = await get_current_user_from_token("tok", db)
    assert result == user


# ═══════════════════════════════════════════════════════════════════
# TASK EVENTS — handlers
# ═══════════════════════════════════════════════════════════════════


def _make_event_ctx(event_type="task.created"):
    from app.events.pipeline import EventContext

    ctx = MagicMock(spec=EventContext)
    ctx.event_type = event_type
    ctx.task = _make_task()
    ctx.actor = _make_user()
    ctx.extra = {}
    ctx.meta = {}
    ctx.skip_external = False
    ctx.stakeholders = set()
    ctx.db = AsyncMock()
    ctx.background_tasks = MagicMock(spec=BackgroundTasks)
    ctx.background_tasks.add_task = MagicMock()
    return ctx


@pytest.mark.asyncio
async def test_task_metadata_handler_known_event():
    from app.events.task_events import MetadataHandler

    handler = MetadataHandler()
    ctx = _make_event_ctx("task.created")
    await handler.handle(ctx)
    assert "title_key" in ctx.meta
    assert ctx.meta["entity_type"] == "task"


@pytest.mark.asyncio
async def test_task_metadata_handler_unknown_event():
    from app.events.task_events import MetadataHandler

    handler = MetadataHandler()
    ctx = _make_event_ctx("task.unknown")
    await handler.handle(ctx)
    assert ctx.meta["title_key"] == "notification.task.generic"


@pytest.mark.asyncio
async def test_task_metadata_all_event_types():
    from app.events.task_events import MetadataHandler

    handler = MetadataHandler()
    for evt in [
        "task.updated",
        "task.completed",
        "task.assigned",
        "task.commented",
        "task.unblocked",
    ]:
        ctx = _make_event_ctx(evt)
        await handler.handle(ctx)
        assert "title_key" in ctx.meta


@pytest.mark.asyncio
async def test_task_audit_log_handler():
    from app.events.task_events import AuditLogHandler

    handler = AuditLogHandler()
    ctx = _make_event_ctx("task.updated")
    ctx.meta = {"type": "info"}
    await handler.handle(ctx)  # just logs, no assertion needed


@pytest.mark.asyncio
async def test_task_websocket_handler_normal():
    from app.events.task_events import WebSocketHandler

    handler = WebSocketHandler()
    ctx = _make_event_ctx("task.updated")

    with patch("app.events.task_events.manager") as mock_mgr:
        mock_mgr.broadcast_to_project = AsyncMock()
        await handler.handle(ctx)
    mock_mgr.broadcast_to_project.assert_awaited_once()


@pytest.mark.asyncio
async def test_task_websocket_handler_commented():
    from app.events.task_events import WebSocketHandler

    handler = WebSocketHandler()
    ctx = _make_event_ctx("task.commented")

    with patch("app.events.task_events.manager") as mock_mgr:
        mock_mgr.broadcast_to_project = AsyncMock()
        await handler.handle(ctx)
    call_args = mock_mgr.broadcast_to_project.call_args[0]
    assert call_args[1]["entity"] == "comments"


@pytest.mark.asyncio
async def test_task_stakeholder_handler_with_assignee():
    from app.events.task_events import StakeholderHandler

    handler = StakeholderHandler()
    ctx = _make_event_ctx("task.updated")
    assignee_id = uuid.uuid4()
    ctx.task.assignee_id = assignee_id
    ctx.task.created_by = uuid.uuid4()

    await handler.handle(ctx)
    assert assignee_id in ctx.stakeholders


@pytest.mark.asyncio
async def test_task_stakeholder_handler_skip_deleted():
    from app.events.task_events import StakeholderHandler

    handler = StakeholderHandler()
    ctx = _make_event_ctx("task.deleted")
    await handler.handle(ctx)
    assert ctx.skip_external is True


@pytest.mark.asyncio
async def test_task_rabbitmq_handler_skip_when_no_stakeholders():
    from app.events.task_events import RabbitMQHandler

    handler = RabbitMQHandler()
    ctx = _make_event_ctx("task.updated")
    ctx.stakeholders = set()
    assert not await handler.should_run(ctx)


@pytest.mark.asyncio
async def test_task_rabbitmq_handler_runs():
    from app.events.task_events import RabbitMQHandler

    handler = RabbitMQHandler()
    ctx = _make_event_ctx("task.updated")
    user_id = uuid.uuid4()
    ctx.stakeholders = {user_id}
    ctx.meta = {"title_key": "k", "type": "info"}

    user = _make_user(id=user_id)
    project = MagicMock()
    project.telegram_chat_id = None

    ctx.db.get = AsyncMock(
        side_effect=lambda model, uid: project if model.__name__ == "Project" else user
    )

    assert await handler.should_run(ctx)
    await handler.handle(ctx)
    ctx.background_tasks.add_task.assert_called_once()


@pytest.mark.asyncio
async def test_task_events_emit():
    from app.events.task_events import task_events

    db = AsyncMock()
    bg = MagicMock(spec=BackgroundTasks)
    bg.add_task = MagicMock()
    task = _make_task()
    actor = _make_user()

    with (
        patch("app.events.task_events.manager") as mock_mgr,
        patch("app.events.task_events._publish_sync"),
    ):
        mock_mgr.broadcast_to_project = AsyncMock()
        await task_events.emit(db, bg, "task.created", task, actor=actor)


# ═══════════════════════════════════════════════════════════════════
# SPRINT EVENTS — handlers
# ═══════════════════════════════════════════════════════════════════


def _make_sprint_ctx(event_type="sprint.started"):
    from app.events.pipeline import EventContext

    ctx = MagicMock(spec=EventContext)
    ctx.event_type = event_type
    ctx.task = _make_sprint()  # EventContext uses .task for sprint too
    ctx.actor = _make_user()
    ctx.extra = {}
    ctx.meta = {}
    ctx.skip_external = False
    ctx.stakeholders = set()
    ctx.db = AsyncMock()
    ctx.background_tasks = MagicMock(spec=BackgroundTasks)
    ctx.background_tasks.add_task = MagicMock()
    return ctx


@pytest.mark.asyncio
async def test_sprint_metadata_handler_known():
    from app.events.sprint_events import MetadataHandler

    handler = MetadataHandler()
    for evt in [
        "sprint.started",
        "sprint.completed",
        "sprint.reopened",
        "sprint.created",
    ]:
        ctx = _make_sprint_ctx(evt)
        await handler.handle(ctx)
        assert "title_key" in ctx.meta
        assert ctx.meta["entity_type"] == "sprint"


@pytest.mark.asyncio
async def test_sprint_metadata_handler_unknown():
    from app.events.sprint_events import MetadataHandler

    handler = MetadataHandler()
    ctx = _make_sprint_ctx("sprint.unknown")
    await handler.handle(ctx)
    assert ctx.meta["title_key"] == "notification.sprint.generic"


@pytest.mark.asyncio
async def test_sprint_audit_log_handler():
    from app.events.sprint_events import AuditLogHandler

    handler = AuditLogHandler()
    ctx = _make_sprint_ctx("sprint.started")
    await handler.handle(ctx)  # just logs


@pytest.mark.asyncio
async def test_sprint_websocket_handler():
    from app.events.sprint_events import WebSocketHandler

    handler = WebSocketHandler()
    ctx = _make_sprint_ctx("sprint.started")

    with patch("app.events.sprint_events.manager") as mock_mgr:
        mock_mgr.broadcast_to_project = AsyncMock()
        await handler.handle(ctx)
    mock_mgr.broadcast_to_project.assert_awaited_once()


# ═══════════════════════════════════════════════════════════════════
# MIDDLEWARE — RequestIDMiddleware
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_request_id_middleware_generates_id():
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    from app.middleware.request_id import RequestIDMiddleware

    def homepage(request):
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/", homepage)])
    app.add_middleware(RequestIDMiddleware)

    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "X-Request-ID" in response.headers


@pytest.mark.asyncio
async def test_request_id_middleware_uses_provided_id():
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    from app.middleware.request_id import RequestIDMiddleware

    def homepage(request):
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/path", homepage)])
    app.add_middleware(RequestIDMiddleware)

    client = TestClient(app)
    response = client.get("/path", headers={"X-Request-ID": "my-req-id"})
    assert response.headers["X-Request-ID"] == "my-req-id"


# ═══════════════════════════════════════════════════════════════════
# DASHBOARD MANAGER — get_admin_stats
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_dashboard_admin_stats_non_admin():
    from fastapi import HTTPException

    from app.modules.dashboard.manager import dashboard_manager

    db = AsyncMock()
    user = _make_user(system_role="user")
    with pytest.raises(HTTPException) as exc:
        await dashboard_manager.get_admin_stats(db, user)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_dashboard_admin_stats_ok():
    from app.modules.dashboard.manager import dashboard_manager

    db = AsyncMock()
    user = _make_user(system_role="admin")
    db.scalar = AsyncMock(return_value=5)

    users = [_make_user()]
    db.execute.return_value = _scalars(items=users)

    result = await dashboard_manager.get_admin_stats(db, user)
    assert result.total_users == 5


# ═══════════════════════════════════════════════════════════════════
# TASKS ROUTER — HTTP tests with mocked dependencies
# ═══════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════
# PROJECT EVENTS — handlers
# ═══════════════════════════════════════════════════════════════════


def _make_project_ctx(event_type="project.created"):
    from app.events.pipeline import EventContext

    ctx = MagicMock(spec=EventContext)
    ctx.event_type = event_type
    proj = MagicMock()
    proj.id = uuid.uuid4()
    proj.name = "Test Project"
    proj.workspace_id = uuid.uuid4()
    ctx.task = proj
    ctx.actor = _make_user()
    ctx.extra = {}
    ctx.meta = {}
    ctx.skip_external = False
    ctx.stakeholders = set()
    ctx.db = AsyncMock()
    ctx.background_tasks = MagicMock(spec=BackgroundTasks)
    ctx.background_tasks.add_task = MagicMock()
    return ctx


@pytest.mark.asyncio
async def test_project_metadata_handler_known():
    from app.events.project_events import AuditLogHandler

    handler = AuditLogHandler()
    for evt in ["project.member_added", "project.member_removed"]:
        ctx = _make_project_ctx(evt)
        ctx.extra = {"target_user_name": "Alice"}
        await handler.handle(ctx)  # just logs, no assert needed


@pytest.mark.asyncio
async def test_project_metadata_handler_unknown():
    from app.events.project_events import AuditLogHandler

    handler = AuditLogHandler()
    ctx = _make_project_ctx("project.unknown")
    ctx.extra = {}
    await handler.handle(ctx)  # just logs


@pytest.mark.asyncio
async def test_project_audit_log_handler():
    from app.events.project_events import AuditLogHandler

    handler = AuditLogHandler()
    ctx = _make_project_ctx("project.created")
    await handler.handle(ctx)  # just logs


# ═══════════════════════════════════════════════════════════════════
# AUTH MANAGER — additional paths
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_auth_manager_get_by_email_found():
    from app.modules.auth.manager import user_manager

    db = AsyncMock()
    user = _make_user()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = user
    db.execute = AsyncMock(return_value=mock_result)

    result = await user_manager.get_by_email(db, "u@test.com")
    assert result == user


@pytest.mark.asyncio
async def test_auth_manager_get_by_email_not_found():
    from app.modules.auth.manager import user_manager

    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)

    result = await user_manager.get_by_email(db, "nobody@test.com")
    assert result is None


# ═══════════════════════════════════════════════════════════════════
# NOTIFICATIONS SERVICE — additional paths
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_notifications_create_and_push():
    from app.modules.notifications.service import create_and_push

    db = AsyncMock()

    with (
        patch("app.modules.notifications.service._publish_notification_sync"),
        patch("app.modules.notifications.service.push_via_redis", new=AsyncMock()),
    ):
        await create_and_push(
            db,
            user_id=uuid.uuid4(),
            title_key="test.key",
            title_params={},
            message_key="test.msg",
            message_params={},
            type="info",
            entity_type="task",
            entity_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
        )


# ═══════════════════════════════════════════════════════════════════
# PROJECTS MANAGER — additional paths
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_projects_manager_get_by_id_found():
    from app.modules.projects.manager import project_manager

    db = AsyncMock()
    proj = MagicMock()
    proj.id = uuid.uuid4()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = proj
    db.execute = AsyncMock(return_value=result_mock)

    result = await project_manager.get(db, proj.id)
    assert result == proj


@pytest.mark.asyncio
async def test_projects_manager_get_by_id_not_found():
    from app.modules.projects.manager import project_manager

    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=result_mock)

    result = await project_manager.get(db, uuid.uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_projects_manager_get_member():
    from app.modules.projects.manager import project_manager

    db = AsyncMock()
    member = MagicMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.first.return_value = member
    db.execute = AsyncMock(return_value=result_mock)

    result = await project_manager.get_member(db, uuid.uuid4(), uuid.uuid4())
    assert result == member


# ═══════════════════════════════════════════════════════════════════
# SPRINT EVENTS — Notification and RabbitMQ handlers
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_sprint_notification_handler():
    from app.events.sprint_events import NotificationHandler

    handler = NotificationHandler()
    ctx = _make_sprint_ctx("sprint.started")
    ctx.meta = {
        "title_key": "k",
        "message_key": "m",
        "type": "info",
        "title_params": {},
        "message_params": {},
    }

    # db.execute returns a result whose .all() yields member rows
    member_id = uuid.uuid4()
    result_mock = MagicMock()
    result_mock.all.return_value = [(member_id,)]
    ctx.db.execute = AsyncMock(return_value=result_mock)

    with patch("app.events.sprint_events.notif_svc") as mock_svc:
        mock_svc.create_and_push = AsyncMock()
        await handler.handle(ctx)
    mock_svc.create_and_push.assert_awaited_once()


@pytest.mark.asyncio
async def test_sprint_rabbitmq_no_stakeholders():
    from app.events.sprint_events import RabbitMQHandler

    handler = RabbitMQHandler()
    # should_run returns event_type != "sprint.created", so sprint.created is False
    ctx = _make_sprint_ctx("sprint.created")
    assert not await handler.should_run(ctx)
    # and sprint.started is True
    ctx2 = _make_sprint_ctx("sprint.started")
    assert await handler.should_run(ctx2)
