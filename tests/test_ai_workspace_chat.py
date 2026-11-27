"""Assistant sidebar: session scope checks and the read-only workspace assistant."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.modules.ai import chat_router, sessions, workspace_chat
from app.modules.ai import llm


def _sql(stmt) -> str:
    return str(
        stmt.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


def _workspace(**settings):
    return SimpleNamespace(id=uuid.uuid4(), name="Team A", settings=settings)


def _db_with(*objects):
    """db.get returns the object whose type name matches the requested model."""
    by_type = {}
    for obj in objects:
        by_type[obj[0]] = obj[1]
    db = AsyncMock()
    db.add = MagicMock()
    db.get.side_effect = lambda model, _id: by_type.get(model.__name__)
    return db


# ── scope checks ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_workspace_is_404():
    db = _db_with()
    with pytest.raises(HTTPException) as exc:
        await sessions.check_scope(
            db, SimpleNamespace(id=uuid.uuid4()), uuid.uuid4(), None
        )
    assert (exc.value.status_code, exc.value.detail) == (404, "workspace.not_found")


@pytest.mark.asyncio
async def test_workspace_chat_needs_workspace_membership():
    ws = _workspace()
    db = _db_with(("Workspace", ws))
    with (
        patch.object(
            sessions.project_manager,
            "is_workspace_member",
            AsyncMock(return_value=False),
        ),
        pytest.raises(HTTPException) as exc,
    ):
        await sessions.check_scope(db, SimpleNamespace(id=uuid.uuid4()), ws.id, None)
    assert (exc.value.status_code, exc.value.detail) == (403, "workspace.access_denied")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "project_found, same_workspace", [(False, True), (True, False)]
)
async def test_project_chat_needs_project_access_in_that_workspace(
    project_found, same_workspace
):
    ws = _workspace()
    project = SimpleNamespace(workspace_id=ws.id if same_workspace else uuid.uuid4())
    db = _db_with(("Workspace", ws))
    with (
        patch.object(
            sessions.project_manager,
            "get_project_for_user",
            AsyncMock(return_value=project if project_found else None),
        ),
        pytest.raises(HTTPException) as exc,
    ):
        await sessions.check_scope(
            db, SimpleNamespace(id=uuid.uuid4()), ws.id, uuid.uuid4()
        )
    assert (exc.value.status_code, exc.value.detail) == (
        403,
        "project.permission_denied",
    )


@pytest.mark.asyncio
async def test_ai_switched_off_in_the_workspace_blocks_the_sidebar():
    ws = _workspace(enable_ai=False)
    db = _db_with(("Workspace", ws))
    with (
        patch.object(
            sessions.project_manager,
            "is_workspace_member",
            AsyncMock(return_value=True),
        ),
        pytest.raises(HTTPException) as exc,
    ):
        await sessions.check_scope(db, SimpleNamespace(id=uuid.uuid4()), ws.id, None)
    assert (exc.value.status_code, exc.value.detail) == (
        403,
        "feature_disabled:enable_ai",
    )


@pytest.mark.asyncio
async def test_someone_elses_session_is_404():
    session = SimpleNamespace(
        user_id=uuid.uuid4(), workspace_id=uuid.uuid4(), project_id=None
    )
    db = _db_with(("AIChatSession", session))
    with pytest.raises(HTTPException) as exc:
        await sessions.get_session(db, uuid.uuid4(), SimpleNamespace(id=uuid.uuid4()))
    assert (exc.value.status_code, exc.value.detail) == (
        404,
        "chatbot.error_session_not_found",
    )


@pytest.mark.asyncio
async def test_old_project_sessions_without_a_workspace_still_open():
    user = SimpleNamespace(id=uuid.uuid4())
    ws_id, project_id = uuid.uuid4(), uuid.uuid4()
    session = SimpleNamespace(user_id=user.id, workspace_id=None, project_id=project_id)
    db = _db_with(("AIChatSession", session))
    check = AsyncMock()
    with (
        patch.object(
            sessions.project_manager,
            "get_project_for_user",
            AsyncMock(return_value=SimpleNamespace(workspace_id=ws_id)),
        ),
        patch.object(sessions, "check_scope", check),
    ):
        assert await sessions.get_session(db, uuid.uuid4(), user) is session
    check.assert_awaited_once_with(db, user, ws_id, project_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("scoped_to_project", [False, True])
async def test_listing_shows_only_the_users_chats_of_that_scope(scoped_to_project):
    user = SimpleNamespace(id=uuid.uuid4())
    ws_id, project_id = uuid.uuid4(), uuid.uuid4()
    db = AsyncMock()
    db.execute.return_value = MagicMock()
    with patch.object(sessions, "check_scope", AsyncMock()):
        await sessions.list_sessions(
            db, user, ws_id, project_id if scoped_to_project else None
        )
    sql = _sql(db.execute.await_args.args[0])
    assert f"ai_chat_sessions.user_id = '{user.id}'" in sql
    if scoped_to_project:
        assert f"ai_chat_sessions.project_id = '{project_id}'" in sql
    else:
        assert f"ai_chat_sessions.workspace_id = '{ws_id}'" in sql
        assert "ai_chat_sessions.project_id IS NULL" in sql
    assert "ORDER BY ai_chat_sessions.updated_at DESC" in sql


@pytest.mark.asyncio
async def test_rename_trims_and_caps_the_title():
    session = SimpleNamespace(title="old")
    db = AsyncMock()
    with patch.object(sessions, "get_session", AsyncMock(return_value=session)):
        await sessions.rename_session(
            db, uuid.uuid4(), SimpleNamespace(id=uuid.uuid4()), "  " + "x" * 300
        )
    assert session.title == "x" * sessions.TITLE_MAX


@pytest.mark.asyncio
async def test_delete_removes_the_session_and_its_messages():
    session = SimpleNamespace(id=uuid.uuid4())
    db = AsyncMock()
    with patch.object(sessions, "get_session", AsyncMock(return_value=session)):
        await sessions.delete_session(db, session.id, SimpleNamespace(id=uuid.uuid4()))
    assert f"ai_chat_messages.session_id = '{session.id}'" in _sql(
        db.execute.await_args.args[0]
    )
    db.delete.assert_awaited_once_with(session)
    db.commit.assert_awaited()


# ── stream routing ─────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("project_scoped", [True, False])
async def test_stream_goes_to_the_assistant_of_the_sessions_scope(project_scoped):
    session = SimpleNamespace(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        project_id=uuid.uuid4() if project_scoped else None,
    )
    project_chat, workspace_chat_fn = MagicMock(), MagicMock()
    with (
        patch.object(
            chat_router.sessions, "get_session", AsyncMock(return_value=session)
        ),
        patch.object(llm, "is_configured", return_value=True),
        patch.object(chat_router.ai_service, "chat_with_project", project_chat),
        patch.object(chat_router, "chat_with_workspace", workspace_chat_fn),
    ):
        await chat_router.stream_chat_reply(
            session.id,
            SimpleNamespace(content="hi", lang="en"),
            AsyncMock(),
            SimpleNamespace(id=uuid.uuid4()),
        )
    assert project_chat.called is project_scoped
    assert workspace_chat_fn.called is not project_scoped


@pytest.mark.asyncio
async def test_stream_refuses_when_ai_is_not_configured():
    session = SimpleNamespace(
        id=uuid.uuid4(), workspace_id=uuid.uuid4(), project_id=None
    )
    with (
        patch.object(
            chat_router.sessions, "get_session", AsyncMock(return_value=session)
        ),
        patch.object(llm, "is_configured", return_value=False),
        pytest.raises(HTTPException) as exc,
    ):
        await chat_router.stream_chat_reply(
            session.id,
            SimpleNamespace(content="hi", lang="en"),
            AsyncMock(),
            SimpleNamespace(id=uuid.uuid4()),
        )
    assert (exc.value.status_code, exc.value.detail) == (
        503,
        "chatbot.error_not_configured",
    )


# ── workspace tools ────────────────────────────────────────────────────


def _project(name):
    return SimpleNamespace(id=uuid.uuid4(), name=name)


def _call(name, **args):
    return {"function": {"name": name, "arguments": json.dumps(args)}}


@pytest.mark.asyncio
async def test_list_tasks_reads_only_the_users_projects_and_applies_filters():
    shop, blog = _project("Shop"), _project("Blog")
    user = SimpleNamespace(id=uuid.uuid4())
    task = SimpleNamespace(
        project_id=shop.id,
        title="VNPay",
        status="todo",
        priority="high",
        deadline=datetime.now(UTC) - timedelta(days=1),
    )
    db = AsyncMock()
    rows = MagicMock()
    rows.all.return_value = [(task, "An")]
    db.execute.return_value = rows

    out = await workspace_chat.dispatch_workspace_tool(
        _call(
            "list_tasks",
            project="shop",
            overdue_only=True,
            assigned_to_me=True,
            limit=500,
        ),
        [shop, blog],
        user,
        db,
    )

    sql = _sql(db.execute.await_args.args[0])
    assert str(shop.id) in sql and str(blog.id) not in sql
    assert f"tasks.assignee_id = '{user.id}'" in sql
    assert "tasks.status != 'done'" in sql
    assert f"LIMIT {workspace_chat.MAX_TASKS}" in sql
    assert out.startswith(
        "- [Shop] VNPay | status: todo | priority: high | assignee: An | deadline: "
    )


@pytest.mark.asyncio
async def test_list_tasks_with_an_unknown_project_points_to_list_projects():
    out = await workspace_chat.dispatch_workspace_tool(
        _call("list_tasks", project="Nope"),
        [_project("Shop")],
        SimpleNamespace(id=uuid.uuid4()),
        AsyncMock(),
    )
    assert "No project matches 'Nope'" in out and "list_projects" in out


@pytest.mark.asyncio
async def test_workspace_chat_cannot_call_project_write_tools():
    out = await workspace_chat.dispatch_workspace_tool(
        _call("delete_tasks", task_ids=["x"], confirmed=True),
        [],
        SimpleNamespace(id=uuid.uuid4()),
        AsyncMock(),
    )
    assert out == "Error: Tool 'delete_tasks' is not available in the workspace chat."


def test_workspace_tools_are_read_only():
    assert {t["function"]["name"] for t in workspace_chat.WORKSPACE_TOOLS} == {
        "list_projects",
        "list_tasks",
    }


@pytest.mark.asyncio
async def test_project_stats_put_the_most_overdue_project_first():
    shop, blog = _project("Shop"), _project("Blog")
    db = AsyncMock()
    counts, sprints = MagicMock(), MagicMock()
    counts.all.return_value = [(shop.id, 10, 9, 0), (blog.id, 5, 1, 3)]
    sprints.all.return_value = [(shop.id, "Sprint 4")]
    db.execute.side_effect = [counts, sprints]

    stats = await workspace_chat.project_stats(db, [shop, blog])

    assert [s["name"] for s in stats] == ["Blog", "Shop"]
    assert workspace_chat._stat_line(stats[1]) == (
        "- Shop: 10 tasks, 9 done (90%), 0 overdue, active sprint: Sprint 4"
    )


@pytest.mark.asyncio
async def test_workspace_chat_prompts_with_the_projects_and_streams_the_reply():
    ws = _workspace()
    session = SimpleNamespace(id=uuid.uuid4(), workspace_id=ws.id)
    db = _db_with(("Workspace", ws))
    history = MagicMock()
    history.scalars.return_value.all.return_value = []
    db.execute.return_value = history
    captured = {}

    async def fake_run_chat(_db, session_id, system_prompt, messages, tools, dispatch):
        captured.update(prompt=system_prompt, tools=tools, session_id=session_id)
        yield "Blog is behind."

    stats = [{"name": "Blog", "total": 5, "done": 1, "overdue": 3, "sprint": None}]
    with (
        patch.object(
            workspace_chat.project_manager,
            "get_projects_for_user",
            AsyncMock(return_value=[]),
        ),
        patch.object(workspace_chat, "project_stats", AsyncMock(return_value=stats)),
        patch.object(workspace_chat, "run_chat", fake_run_chat),
    ):
        out = [
            p
            async for p in workspace_chat.chat_with_workspace(
                db,
                session,
                "Which project is behind?",
                SimpleNamespace(id=uuid.uuid4()),
                lang="en",
            )
        ]

    assert out == ["Blog is behind."]
    assert 'workspace "Team A"' in captured["prompt"]
    assert (
        "- Blog: 5 tasks, 1 done (20%), 3 overdue, active sprint: none"
        in captured["prompt"]
    )
    assert "can only read" in captured["prompt"]
    assert captured["tools"] is workspace_chat.WORKSPACE_TOOLS
    saved = db.add.call_args.args[0]
    assert (saved.role, saved.content) == ("user", "Which project is behind?")
