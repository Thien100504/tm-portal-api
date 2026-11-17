import uuid
from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project, ProjectMember
from app.models.rbac import Role
from app.models.task import Task, TaskDependency
from app.models.user import User
from app.modules.dashboard.schemas import (
    AdminStats,
    BlockedTask,
    MyTaskStats,
    PersonalStats,
    ProjectProgress,
    RecentUser,
    TasksByStatus,
    TeamMemberWorkload,
    UpcomingTask,
)


class DashboardManager:
    async def get_personal_stats(
        self,
        db: AsyncSession,
        current_user: User,
        workspace_id: uuid.UUID | None = None,
    ) -> PersonalStats:
        user_id = current_user.id
        now = datetime.utcnow()
        week_ago = now - timedelta(days=7)
        next_week = now + timedelta(days=7)

        # ── 1. My task stats ─────────────────────────────────────────────
        base_filter = and_(
            Task.assignee_id == user_id,
            Task.is_deleted.is_(False),
        )

        def build_task_count_query(*extra_filters):
            q = select(func.count(Task.id))
            if workspace_id:
                q = q.join(Project, Task.project_id == Project.id).where(
                    Project.workspace_id == workspace_id
                )
            return q.where(base_filter, *extra_filters)

        todo_count = await db.scalar(build_task_count_query(Task.status == "todo")) or 0
        in_progress_count = (
            await db.scalar(build_task_count_query(Task.status == "in_progress")) or 0
        )
        review_count = (
            await db.scalar(build_task_count_query(Task.status == "review")) or 0
        )
        done_week_count = (
            await db.scalar(
                build_task_count_query(
                    Task.status == "done",
                    Task.updated_at >= week_ago,
                )
            )
            or 0
        )

        # ── 2. Overdue ───────────────────────────────────────────────────
        overdue_count = (
            await db.scalar(
                build_task_count_query(
                    Task.deadline is not None,
                    Task.deadline < now,
                    Task.status != "done",
                )
            )
            or 0
        )

        # ── 3. Upcoming tasks (deadline within the next 7 days) ───────────
        upcoming_q = select(Task, Project.name.label("project_name")).join(
            Project, Task.project_id == Project.id
        )
        if workspace_id:
            upcoming_q = upcoming_q.where(Project.workspace_id == workspace_id)

        upcoming_rows = (
            await db.execute(
                upcoming_q.where(
                    base_filter,
                    Task.deadline.isnot(None),
                    Task.deadline >= now,
                    Task.deadline <= next_week,
                    Task.status != "done",
                )
                .order_by(Task.deadline.asc())
                .limit(5)
            )
        ).all()

        upcoming_tasks = [
            UpcomingTask(
                id=row.Task.id,
                title=row.Task.title,
                deadline=row.Task.deadline,
                priority=row.Task.priority,
                status=row.Task.status,
                project_id=row.Task.project_id,
                project_name=row.project_name,
            )
            for row in upcoming_rows
        ]

        # ── 4. My projects + personal progress ──────────────────────────
        projects_query = (
            select(Project, Role.name)
            .outerjoin(
                ProjectMember,
                and_(
                    ProjectMember.project_id == Project.id,
                    ProjectMember.user_id == user_id,
                    ProjectMember.is_deleted.is_(False),
                ),
            )
            .outerjoin(Role, ProjectMember.role_id == Role.id)
            .where(
                (Project.owner_id == user_id) | (ProjectMember.user_id == user_id),
                Project.is_deleted.is_(False),
            )
            .distinct()
            .order_by(Project.created_at.desc())
        )
        if workspace_id:
            projects_query = projects_query.where(Project.workspace_id == workspace_id)

        project_rows = (await db.execute(projects_query)).all()

        my_projects_count = len(project_rows)
        my_projects: list[ProjectProgress] = []

        for row in project_rows:
            project = row.Project
            role = row.name or "Project Manager"

            my_total = (
                await db.scalar(
                    select(func.count(Task.id)).where(
                        Task.project_id == project.id,
                        Task.assignee_id == user_id,
                        Task.is_deleted.is_(False),
                    )
                )
                or 0
            )
            my_done = (
                await db.scalar(
                    select(func.count(Task.id)).where(
                        Task.project_id == project.id,
                        Task.assignee_id == user_id,
                        Task.status == "done",
                        Task.is_deleted.is_(False),
                    )
                )
                or 0
            )

            my_projects.append(
                ProjectProgress(
                    id=project.id,
                    name=project.name,
                    my_tasks_done=my_done,
                    my_tasks_total=my_total,
                    my_role=role,
                )
            )

        # ── 5. PM extras (workload + blocked) ────────────────────────────
        pm_project_query = (
            select(ProjectMember.project_id)
            .join(Role, ProjectMember.role_id == Role.id)
            .where(
                ProjectMember.user_id == user_id,
                ProjectMember.is_deleted.is_(False),
                Role.name == "Project Manager",
            )
        )
        if workspace_id:
            pm_project_query = pm_project_query.join(
                Project, ProjectMember.project_id == Project.id
            ).where(Project.workspace_id == workspace_id)

        pm_project_ids_rows = (await db.execute(pm_project_query)).scalars().all()

        is_pm = len(pm_project_ids_rows) > 0
        team_workload: list[TeamMemberWorkload] = []
        blocked_tasks: list[BlockedTask] = []

        if is_pm:
            pm_project_ids = list(pm_project_ids_rows)

            member_user_ids_rows = (
                (
                    await db.execute(
                        select(ProjectMember.user_id)
                        .where(
                            ProjectMember.project_id.in_(pm_project_ids),
                            ProjectMember.is_deleted.is_(False),
                        )
                        .distinct()
                    )
                )
                .scalars()
                .all()
            )

            members_rows = (
                (
                    await db.execute(
                        select(User).where(User.id.in_(member_user_ids_rows))
                    )
                )
                .scalars()
                .all()
            )

            for member_user in members_rows:
                m_uid = member_user.id

                ip = (
                    await db.scalar(
                        select(func.count(Task.id)).where(
                            Task.project_id.in_(pm_project_ids),
                            Task.assignee_id == m_uid,
                            Task.status == "in_progress",
                            Task.is_deleted.is_(False),
                        )
                    )
                    or 0
                )
                td = (
                    await db.scalar(
                        select(func.count(Task.id)).where(
                            Task.project_id.in_(pm_project_ids),
                            Task.assignee_id == m_uid,
                            Task.status == "todo",
                            Task.is_deleted.is_(False),
                        )
                    )
                    or 0
                )
                ov = (
                    await db.scalar(
                        select(func.count(Task.id)).where(
                            Task.project_id.in_(pm_project_ids),
                            Task.assignee_id == m_uid,
                            Task.deadline.isnot(None),
                            Task.deadline < now,
                            Task.status != "done",
                            Task.is_deleted.is_(False),
                        )
                    )
                    or 0
                )

                team_workload.append(
                    TeamMemberWorkload(
                        user_id=m_uid,
                        full_name=member_user.full_name,
                        email=member_user.email,
                        in_progress_count=ip,
                        todo_count=td,
                        overdue_count=ov,
                    )
                )

            from sqlalchemy.orm import aliased

            DepTask = aliased(Task, name="dep_task")

            blocked_rows = (
                await db.execute(
                    select(Task, Project.name.label("project_name"))
                    .join(Project, Task.project_id == Project.id)
                    .join(TaskDependency, Task.id == TaskDependency.task_id)
                    .join(
                        DepTask,
                        and_(
                            TaskDependency.depends_on_id == DepTask.id,
                            DepTask.status != "done",
                        ),
                    )
                    .where(
                        Task.project_id.in_(pm_project_ids),
                        Task.status != "done",
                        Task.is_deleted.is_(False),
                    )
                    .distinct()
                    .limit(10)
                )
            ).all()

            for row in blocked_rows:  # type: ignore[assignment]
                blocked_by = (
                    await db.scalar(
                        select(func.count(TaskDependency.depends_on_id))
                        .join(DepTask, TaskDependency.depends_on_id == DepTask.id)
                        .where(
                            TaskDependency.task_id == row.Task.id,
                            DepTask.status != "done",
                        )
                    )
                    or 0
                )
                blocked_tasks.append(
                    BlockedTask(
                        id=row.Task.id,
                        title=row.Task.title,
                        project_id=row.Task.project_id,
                        project_name=row.project_name,
                        blocked_by_count=blocked_by,
                    )
                )

        return PersonalStats(
            my_tasks=MyTaskStats(
                todo=todo_count,
                in_progress=in_progress_count,
                review=review_count,
                done_this_week=done_week_count,
            ),
            overdue_count=overdue_count,
            my_projects_count=my_projects_count,
            upcoming_tasks=upcoming_tasks,
            my_projects=my_projects,
            is_pm=is_pm,
            team_workload=team_workload,
            blocked_tasks=blocked_tasks,
        )

    async def get_admin_stats(self, db: AsyncSession, current_user: User) -> AdminStats:
        if current_user.system_role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="admin.stats_forbidden",
            )

        now = datetime.utcnow()
        week_ago = now - timedelta(days=7)

        total_users = await db.scalar(select(func.count(User.id))) or 0
        active_users = (
            await db.scalar(select(func.count(User.id)).where(User.is_active)) or 0
        )

        total_projects = (
            await db.scalar(
                select(func.count(Project.id)).where(Project.is_deleted.is_(False))
            )
            or 0
        )
        active_projects = (
            await db.scalar(
                select(func.count(Project.id)).where(
                    Project.status == "active", Project.is_deleted.is_(False)
                )
            )
            or 0
        )

        total_tasks = (
            await db.scalar(
                select(func.count(Task.id)).where(Task.is_deleted.is_(False))
            )
            or 0
        )
        todo_count = (
            await db.scalar(
                select(func.count(Task.id)).where(
                    Task.status == "todo", Task.is_deleted.is_(False)
                )
            )
            or 0
        )
        ip_count = (
            await db.scalar(
                select(func.count(Task.id)).where(
                    Task.status == "in_progress", Task.is_deleted.is_(False)
                )
            )
            or 0
        )
        rv_count = (
            await db.scalar(
                select(func.count(Task.id)).where(
                    Task.status == "review", Task.is_deleted.is_(False)
                )
            )
            or 0
        )
        done_count = (
            await db.scalar(
                select(func.count(Task.id)).where(
                    Task.status == "done", Task.is_deleted.is_(False)
                )
            )
            or 0
        )
        done_week = (
            await db.scalar(
                select(func.count(Task.id)).where(
                    Task.status == "done",
                    Task.updated_at >= week_ago,
                    Task.is_deleted.is_(False),
                )
            )
            or 0
        )

        recent_users_rows = (
            (await db.execute(select(User).order_by(User.created_at.desc()).limit(5)))
            .scalars()
            .all()
        )

        return AdminStats(
            total_users=total_users,
            active_users=active_users,
            total_projects=total_projects,
            active_projects=active_projects,
            total_tasks=total_tasks,
            tasks_by_status=TasksByStatus(
                todo=todo_count,
                in_progress=ip_count,
                review=rv_count,
                done=done_count,
            ),
            done_this_week=done_week,
            recent_users=[
                RecentUser(
                    id=u.id,
                    full_name=u.full_name,
                    email=u.email,
                    system_role=u.system_role,
                    created_at=u.created_at,
                )
                for u in recent_users_rows
            ],
        )


dashboard_manager = DashboardManager()
