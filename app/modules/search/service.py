import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.models.workspace import WorkspaceMember


async def global_search(
    db: AsyncSession, q: str, workspace_id: uuid.UUID, user_id: uuid.UUID
):
    # Only the workspace owner and active members can search it
    from app.modules.projects.manager import project_manager

    if not await project_manager.is_workspace_member(db, workspace_id, user_id):
        return {"projects": [], "tasks": [], "users": []}

    search_term = f"%{q}%"

    # 1. Search Projects in the workspace
    project_query = (
        select(Project.id, Project.name)
        .where(
            Project.workspace_id == workspace_id,
            Project.is_deleted.is_(False),
            Project.name.ilike(search_term),
        )
        .limit(5)
    )
    project_rows = await db.execute(project_query)
    projects = [{"id": str(r.id), "name": r.name} for r in project_rows.fetchall()]

    # 2. Search Tasks in the workspace
    task_query = (
        select(Task.id, Task.title, Task.project_id, Project.name.label("project_name"))
        .join(Project, Task.project_id == Project.id)
        .where(
            Project.workspace_id == workspace_id,
            Project.is_deleted.is_(False),
            Task.is_deleted.is_(False),
            Task.title.ilike(search_term),
        )
        .limit(5)
    )
    task_rows = await db.execute(task_query)
    tasks = [
        {
            "id": str(r.id),
            "title": r.title,
            "project_id": str(r.project_id),
            "project_name": r.project_name,
        }
        for r in task_rows.fetchall()
    ]

    # 3. Search Members in the workspace
    user_query = (
        select(User.id, User.full_name, User.email)
        .join(WorkspaceMember, User.id == WorkspaceMember.user_id)
        .where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.is_deleted.is_(False),
            or_(User.full_name.ilike(search_term), User.email.ilike(search_term)),
        )
        .limit(5)
    )
    user_rows = await db.execute(user_query)
    users = [
        {"id": str(r.id), "name": r.full_name, "email": r.email}
        for r in user_rows.fetchall()
    ]

    return {"projects": projects, "tasks": tasks, "users": users}
