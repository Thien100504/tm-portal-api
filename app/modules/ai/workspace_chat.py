"""
Workspace-wide assistant: answers questions across every project the user can
open in a workspace. It only reads; changes go through a project's chat, where
each write is checked against that project's permissions.
"""

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai import AIChatMessage, AIChatSession
from app.models.project import Project
from app.models.sprint import Sprint
from app.models.task import Task
from app.models.user import User
from app.models.workspace import Workspace
from app.modules.ai.service import CHAT_HISTORY_MESSAGES, reply_language, run_chat
from app.modules.projects.manager import project_manager

MAX_PROJECTS_IN_PROMPT = 30
MAX_TASKS = 50
TASK_STATUSES = ["todo", "in_progress", "review", "done"]

WORKSPACE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_projects",
            "description": "List the projects in this workspace with task counts, overdue tasks and the active sprint.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tasks",
            "description": "Find tasks across the workspace. Combine filters as needed; leave a filter out to not filter on it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "description": "Project name (or part of it) to look in; omit for all projects",
                    },
                    "search": {
                        "type": "string",
                        "description": "Text in the task title",
                    },
                    "status": {"type": "string", "enum": TASK_STATUSES},
                    "overdue_only": {"type": "boolean"},
                    "assigned_to_me": {"type": "boolean"},
                    "limit": {"type": "integer", "description": f"At most {MAX_TASKS}"},
                },
            },
        },
    },
]


async def project_stats(db: AsyncSession, projects: list[Project]) -> list[dict]:
    """Task counts and the active sprint of each project, busiest first."""
    if not projects:
        return []
    ids = [p.id for p in projects]
    now = datetime.now(UTC)
    rows = await db.execute(
        select(
            Task.project_id,
            func.count(Task.id),
            func.count(Task.id).filter(Task.status == "done"),
            func.count(Task.id).filter(
                and_(
                    Task.deadline.isnot(None),
                    Task.deadline < now,
                    Task.status != "done",
                )
            ),
        )
        .where(Task.project_id.in_(ids), Task.is_deleted.is_(False))
        .group_by(Task.project_id)
    )
    counts = {pid: (total, done, overdue) for pid, total, done, overdue in rows.all()}
    sprints = await db.execute(
        select(Sprint.project_id, Sprint.name).where(
            Sprint.project_id.in_(ids),
            Sprint.status == "active",
            Sprint.is_deleted.is_(False),
        )
    )
    active = dict(sprints.all())
    stats = []
    for p in projects:
        total, done, overdue = counts.get(p.id, (0, 0, 0))
        stats.append(
            {
                "name": p.name,
                "total": total,
                "done": done,
                "overdue": overdue,
                "sprint": active.get(p.id),
            }
        )
    stats.sort(key=lambda s: (-s["overdue"], -(s["total"] - s["done"])))
    return stats


def _stat_line(s: dict) -> str:
    pct = round(100 * s["done"] / s["total"]) if s["total"] else 0
    return (
        f"- {s['name']}: {s['total']} tasks, {s['done']} done ({pct}%), "
        f"{s['overdue']} overdue, active sprint: {s['sprint'] or 'none'}"
    )


async def dispatch_workspace_tool(
    tool_call: dict, projects: list[Project], user: User, db: AsyncSession
) -> str:
    name = tool_call.get("function", {}).get("name")
    try:
        args = json.loads(tool_call.get("function", {}).get("arguments") or "{}")
    except json.JSONDecodeError:
        return "Error: Cannot parse parameters."
    if not isinstance(args, dict):
        args = {}

    if name == "list_projects":
        stats = await project_stats(db, projects)
        return "\n".join(_stat_line(s) for s in stats) or "No projects."

    if name == "list_tasks":
        targets = projects
        wanted = str(args.get("project") or "").strip().lower()
        if wanted:
            targets = [p for p in projects if wanted in p.name.lower()]
            if not targets:
                return f"No project matches '{args['project']}'. Call list_projects to see the names."
        if not targets:
            return "No projects."
        names = {p.id: p.name for p in targets}

        query = (
            select(Task, User.full_name)
            .outerjoin(User, Task.assignee_id == User.id)
            .where(Task.project_id.in_(list(names)), Task.is_deleted.is_(False))
        )
        if args.get("search"):
            query = query.where(Task.title.ilike(f"%{args['search']}%"))
        if args.get("status") in TASK_STATUSES:
            query = query.where(Task.status == args["status"])
        if args.get("overdue_only"):
            query = query.where(
                Task.deadline.isnot(None),
                Task.deadline < datetime.now(UTC),
                Task.status != "done",
            )
        if args.get("assigned_to_me"):
            query = query.where(Task.assignee_id == user.id)
        try:
            limit = int(args.get("limit") or 20)
        except (TypeError, ValueError):
            limit = 20
        query = query.order_by(
            Task.deadline.asc().nulls_last(), Task.created_at.desc()
        ).limit(max(1, min(limit, MAX_TASKS)))

        rows = (await db.execute(query)).all()
        if not rows:
            return "No tasks found."
        return "\n".join(
            f"- [{names[t.project_id]}] {t.title} | status: {t.status} | priority: {t.priority}"
            f" | assignee: {assignee or 'unassigned'}"
            f" | deadline: {t.deadline.date().isoformat() if t.deadline else 'none'}"
            for t, assignee in rows
        )

    return f"Error: Tool '{name}' is not available in the workspace chat."


async def chat_with_workspace(
    db: AsyncSession,
    session: AIChatSession,
    user_content: str,
    current_user: User,
    lang: str = "vi",
):
    """Stream the workspace assistant's reply (the caller checked access)."""
    session_id: uuid.UUID = session.id
    db.add(AIChatMessage(session_id=session_id, role="user", content=user_content))
    await db.commit()

    workspace = await db.get(Workspace, session.workspace_id)
    projects = await project_manager.get_projects_for_user(
        db, current_user.id, session.workspace_id
    )
    stats = await project_stats(db, projects)
    shown = stats[:MAX_PROJECTS_IN_PROMPT]
    more = len(stats) - len(shown)

    system_prompt = f"""You are the AI assistant of the workspace "{workspace.name if workspace else ""}" in the TaskManager project management system.
You can see every project the user can open in this workspace.

PROJECTS ({len(stats)}, most overdue first):
{chr(10).join(_stat_line(s) for s in shown) if shown else "No projects yet"}{f"{chr(10)}...and {more} more (call list_projects)" if more else ""}

TOOL USAGE INSTRUCTIONS:
1. Use list_projects and list_tasks to look up anything not listed above. Never invent projects, tasks or people.
2. This workspace chat can only read. To create, change or delete tasks, sprints or rules, tell the user to open that project's chat.
3. Never show raw IDs.

COMMUNICATION INSTRUCTIONS:
- Reply in {reply_language(user_content, lang)} (the language of the user's latest message), even if earlier messages used another language. Be concise, practical and helpful.
- Limit responses to 150 words unless detailed explanation is needed.
- For casual conversation (greetings, jokes, etc.), reply naturally and flexibly.
"""

    history = (
        (
            await db.execute(
                select(AIChatMessage)
                .where(AIChatMessage.session_id == session_id)
                .order_by(AIChatMessage.created_at.desc())
                .limit(CHAT_HISTORY_MESSAGES)
            )
        )
        .scalars()
        .all()
    )

    async def dispatch(tc: dict) -> str:
        return await dispatch_workspace_tool(tc, projects, current_user, db)

    async for piece in run_chat(
        db,
        session_id,
        system_prompt,
        list(reversed(history)),
        WORKSPACE_TOOLS,
        dispatch,
    ):
        yield piece
