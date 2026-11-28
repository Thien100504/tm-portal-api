"""Chat deletes wait for the user's own click on a server-issued confirmation card."""

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.modules.ai import chat_router, pending_actions, tools

PROJECT = uuid.uuid4()
SESSION = uuid.uuid4()


def _user():
    return SimpleNamespace(id=uuid.uuid4())


def _task(title, project=PROJECT, deleted=False):
    return SimpleNamespace(
        id=uuid.uuid4(), project_id=project, title=title, is_deleted=deleted
    )


def _call(name, args):
    return {"function": {"name": name, "arguments": json.dumps(args)}}


def _allowed():
    return patch(
        "app.modules.rbac.manager.rbac_manager.check_permission",
        AsyncMock(return_value=True),
    )


# ── the tool only asks ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_tool_stores_a_pending_action_and_deletes_nothing():
    user, db = _user(), AsyncMock()
    keep, other_project = (
        _task("Dữ liệu 1"),
        _task("Không thuộc dự án", project=uuid.uuid4()),
    )
    by_id = {str(keep.id): keep, str(other_project.id): other_project}
    save = AsyncMock(return_value="tok123")
    with (
        _allowed(),
        patch.object(
            tools.task_manager,
            "get_by_id",
            AsyncMock(side_effect=lambda _db, i: by_id.get(str(i))),
        ),
        patch.object(pending_actions, "save", save),
    ):
        out = await tools.dispatch_tool_call(
            _call("delete_tasks", {"task_ids": [str(keep.id), str(other_project.id)]}),
            PROJECT,
            user,
            db,
            session_id=SESSION,
        )

    action = save.await_args.args[0]
    assert action == {
        "kind": "delete_tasks",
        "project_id": str(PROJECT),
        "ids": [str(keep.id)],  # tasks of other projects are left out
        "titles": ["Dữ liệu 1"],
        "user_id": str(user.id),
        "session_id": str(SESSION),
    }
    card = json.loads(out.split("[confirm]")[1].split("[/confirm]")[0])
    assert card == {"token": "tok123", "kind": "delete_tasks", "titles": ["Dữ liệu 1"]}
    assert "do not say it was deleted" in out
    assert keep.is_deleted is False
    db.execute.assert_not_awaited()
    db.commit.assert_not_awaited()


def test_the_model_cannot_skip_the_card():
    schemas = {
        t["function"]["name"]: t["function"]["parameters"] for t in tools.TOOLS_SCHEMA
    }
    assert "confirmed" not in schemas["delete_tasks"]["properties"]
    assert "confirmed" not in schemas["delete_automation"]["properties"]


@pytest.mark.asyncio
async def test_delete_rule_also_waits_for_the_card():
    rule = SimpleNamespace(id=uuid.uuid4(), project_id=PROJECT, name="Auto close")
    save = AsyncMock(return_value="tok")
    delete = AsyncMock()
    with (
        _allowed(),
        patch.object(tools.automation_manager, "get", AsyncMock(return_value=rule)),
        patch.object(tools.automation_manager, "delete", delete),
        patch.object(pending_actions, "save", save),
    ):
        out = await tools.dispatch_tool_call(
            _call("delete_automation", {"rule_id": str(rule.id)}),
            PROJECT,
            _user(),
            AsyncMock(),
            session_id=SESSION,
        )
    assert save.await_args.args[0]["kind"] == "delete_rule"
    assert '"titles": ["Auto close"]' in out
    delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_card_without_delete_permission():
    save = AsyncMock()
    with (
        patch(
            "app.modules.rbac.manager.rbac_manager.check_permission",
            AsyncMock(return_value=False),
        ),
        patch.object(pending_actions, "save", save),
    ):
        out = await tools.dispatch_tool_call(
            _call("delete_tasks", {"task_ids": [str(uuid.uuid4())]}),
            PROJECT,
            _user(),
            AsyncMock(),
            session_id=SESSION,
        )
    assert "task.delete" in out
    save.assert_not_awaited()


# ── the user's click ────────────────────────────────────────────────────────


def _action(user, **over):
    return {
        "kind": "delete_tasks",
        "project_id": str(PROJECT),
        "ids": [str(uuid.uuid4())],
        "titles": ["A"],
        "user_id": str(user.id),
        "session_id": str(SESSION),
        **over,
    }


async def _resolve(user, action, confirm=True):
    db = AsyncMock()
    db.add = MagicMock()
    execute = AsyncMock(return_value={"kind": "delete_tasks", "count": 1})
    with (
        patch.object(
            chat_router.sessions,
            "get_session",
            AsyncMock(return_value=SimpleNamespace(id=SESSION)),
        ),
        patch.object(
            chat_router.pending_actions, "take", AsyncMock(return_value=action)
        ),
        patch.object(chat_router, "execute_pending", execute),
    ):
        result = await chat_router.resolve_chat_action(
            SESSION, "tok", SimpleNamespace(confirm=confirm, lang="vi"), db, user
        )
    return result, execute, db


@pytest.mark.asyncio
async def test_confirming_carries_out_the_delete_and_notes_it():
    user = _user()
    result, execute, db = await _resolve(user, _action(user))
    assert (result.status, result.count) == ("done", 1)
    execute.assert_awaited_once()
    note = db.add.call_args.args[0]
    assert (note.role, note.content) == ("assistant", "Đã xoá 1 task.")


@pytest.mark.asyncio
async def test_cancelling_deletes_nothing():
    user = _user()
    result, execute, _ = await _resolve(user, _action(user), confirm=False)
    assert result.status == "cancelled"
    execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "make",
    [
        lambda user: None,  # expired or already used
        lambda user: _action(_user()),  # someone else's card
        lambda user: _action(
            user, session_id=str(uuid.uuid4())
        ),  # card from another chat
    ],
)
async def test_a_card_works_only_for_its_user_and_chat(make):
    user = _user()
    with pytest.raises(HTTPException) as exc:
        await _resolve(user, make(user))
    assert (exc.value.status_code, exc.value.detail) == (
        404,
        "chatbot.error_action_expired",
    )


@pytest.mark.asyncio
async def test_permission_is_checked_again_on_click():
    with (
        patch(
            "app.modules.rbac.manager.rbac_manager.check_permission",
            AsyncMock(return_value=False),
        ),
        pytest.raises(HTTPException) as exc,
    ):
        await tools.execute_pending(AsyncMock(), _action(_user()), _user())
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_confirmed_delete_is_soft_and_stays_in_the_project():
    user = _user()
    mine, foreign = _task("Mine"), _task("Foreign", project=uuid.uuid4())
    by_id = {str(mine.id): mine, str(foreign.id): foreign}
    db = AsyncMock()
    with (
        _allowed(),
        patch.object(
            tools.task_manager,
            "get_by_id",
            AsyncMock(side_effect=lambda _db, i: by_id.get(str(i))),
        ),
    ):
        result = await tools.execute_pending(
            db, _action(user, ids=[str(mine.id), str(foreign.id)]), user
        )
    assert result == {"kind": "delete_tasks", "count": 1}
    assert mine.is_deleted is True and mine.deleted_by == user.id
    assert foreign.is_deleted is False
    db.commit.assert_awaited()


# ── storage ────────────────────────────────────────────────────────────────


class _FakeRedis:
    store: dict = {}

    async def set(self, key, value, ex=None):
        self.store[key] = (value, ex)

    async def getdel(self, key):
        item = self.store.pop(key, None)
        return item[0] if item else None

    async def aclose(self):
        pass


@pytest.mark.asyncio
async def test_a_token_works_once_and_expires():
    with patch.object(pending_actions.aioredis, "from_url", return_value=_FakeRedis()):
        token = await pending_actions.save({"kind": "delete_tasks"})
        assert _FakeRedis.store[f"ai:pending:{token}"][1] == pending_actions.TTL_SECONDS
        assert await pending_actions.take(token) == {"kind": "delete_tasks"}
        assert await pending_actions.take(token) is None
