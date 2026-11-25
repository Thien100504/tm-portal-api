import uuid
from datetime import UTC

from fastapi import HTTPException
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.base_manager import BaseManager
from app.models.project import Project, ProjectMember
from app.models.rbac import Role
from app.models.workspace import Workspace, WorkspaceMember
from app.modules.projects.schemas import ProjectCreate, ProjectUpdate


class ProjectManager(BaseManager[Project, ProjectCreate, ProjectUpdate]):
    async def get_projects_for_user(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID | None = None,
    ) -> list[Project]:
        query = (
            select(Project)
            .options(
                selectinload(Project.memberships).selectinload(ProjectMember.user),
                selectinload(Project.memberships).selectinload(ProjectMember.role),
            )
            .outerjoin(
                ProjectMember,
                and_(
                    Project.id == ProjectMember.project_id,
                    ProjectMember.is_deleted.is_(False),
                ),
            )
            .outerjoin(
                WorkspaceMember,
                and_(
                    Project.workspace_id == WorkspaceMember.workspace_id,
                    WorkspaceMember.is_deleted.is_(False),
                ),
            )
            .outerjoin(Workspace, Project.workspace_id == Workspace.id)
            .where(
                Project.is_deleted.is_(False),
                (Project.owner_id == user_id)
                | (ProjectMember.user_id == user_id)
                | (WorkspaceMember.user_id == user_id)
                | (Workspace.owner_id == user_id),
            )
            .distinct()
        )
        if workspace_id:
            query = query.where(Project.workspace_id == workspace_id)

        result = await db.execute(query)
        projects = list(result.scalars().all())

        project_ids = [p.id for p in projects]
        if project_ids:
            from sqlalchemy import func

            counts_query = (
                select(ProjectMember.project_id, func.count(ProjectMember.user_id))
                .where(
                    ProjectMember.project_id.in_(project_ids),
                    ProjectMember.is_deleted.is_(False),
                )
                .group_by(ProjectMember.project_id)
            )
            counts_res = await db.execute(counts_query)
            counts_map: dict[uuid.UUID, int] = {r[0]: r[1] for r in counts_res.all()}
        else:
            counts_map = {}

        for p in projects:
            setattr(p, "member_count", counts_map.get(p.id, 0))
            setattr(p, "members", [m for m in p.memberships if not m.is_deleted])

        return projects

    async def attach_member_count(self, db: AsyncSession, project: Project) -> Project:
        from sqlalchemy import func, select

        count = await db.scalar(
            select(func.count(ProjectMember.user_id)).where(
                ProjectMember.project_id == project.id,
                ProjectMember.is_deleted.is_(False),
            )
        )
        setattr(project, "member_count", count)
        setattr(
            project, "members", [m for m in project.memberships if not m.is_deleted]
        )
        return project

    async def get_project_for_user(
        self, db: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID
    ) -> Project | None:
        query = (
            select(Project)
            .options(
                selectinload(Project.memberships).selectinload(ProjectMember.user),
                selectinload(Project.memberships).selectinload(ProjectMember.role),
            )
            .outerjoin(
                ProjectMember,
                and_(
                    Project.id == ProjectMember.project_id,
                    ProjectMember.is_deleted.is_(False),
                ),
            )
            .outerjoin(
                WorkspaceMember,
                and_(
                    Project.workspace_id == WorkspaceMember.workspace_id,
                    WorkspaceMember.is_deleted.is_(False),
                ),
            )
            .outerjoin(Workspace, Project.workspace_id == Workspace.id)
            .where(
                Project.id == project_id,
                Project.is_deleted.is_(False),
                (
                    (Project.owner_id == user_id)
                    | (ProjectMember.user_id == user_id)
                    | (WorkspaceMember.user_id == user_id)
                    | (Workspace.owner_id == user_id)
                ),
            )
            .distinct()
        )
        result = await db.execute(query)
        return result.scalars().first()

    async def get_member(
        self, db: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID
    ) -> ProjectMember | None:
        query = select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
            ProjectMember.is_deleted.is_(False),
        )
        return (await db.execute(query)).scalars().first()

    async def is_workspace_member(
        self, db: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID
    ) -> bool:
        """The workspace owner or an active (not removed) workspace member."""
        owner_id = await db.scalar(
            select(Workspace.owner_id).where(Workspace.id == workspace_id)
        )
        if owner_id == user_id:
            return True
        member = await db.scalar(
            select(WorkspaceMember.user_id).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
                WorkspaceMember.is_deleted.is_(False),
            )
        )
        return member is not None

    async def validate_role(
        self, db: AsyncSession, role_id: uuid.UUID | None, workspace_id: uuid.UUID
    ) -> None:
        """A project member may only get a live project role of this workspace (or a system one)."""
        if role_id is None:
            return
        role = await db.scalar(
            select(Role).where(Role.id == role_id, Role.is_deleted.is_(False))
        )
        if (
            not role
            or role.scope != "project"
            or not (role.is_system_default or role.workspace_id == workspace_id)
        ):
            raise HTTPException(status_code=400, detail="project.invalid_role")

    async def soft_delete(
        self, db: AsyncSession, project: Project, user_id: uuid.UUID
    ) -> None:
        """Mark the project deleted instead of removing it with all its tasks."""
        from datetime import datetime

        project.is_deleted = True
        project.deleted_at = datetime.now(UTC)
        project.deleted_by = user_id
        await db.flush()

    async def create_project_with_owner(
        self, db: AsyncSession, obj_in: ProjectCreate, owner_id: uuid.UUID
    ) -> Project:
        workspace_id = obj_in.workspace_id
        if not workspace_id:
            from app.models.workspace import Workspace

            # Find the user's default personal workspace
            ws_stmt = (
                select(Workspace.id)
                .where(Workspace.owner_id == owner_id, Workspace.type == "personal")
                .limit(1)
            )
            ws_id = (await db.execute(ws_stmt)).scalar_one_or_none()
            if not ws_id:
                ws = Workspace(
                    name="Personal Workspace", type="personal", owner_id=owner_id
                )
                db.add(ws)
                await db.flush()
                ws_id = ws.id
            workspace_id = ws_id

        project_data = obj_in.model_dump()
        project_data["workspace_id"] = workspace_id

        project = Project(**project_data, owner_id=owner_id)
        db.add(project)
        await db.flush()

        member = ProjectMember(
            project_id=project.id, user_id=owner_id, project_role="project_manager"
        )
        db.add(member)
        await db.flush()
        await db.refresh(project)
        return project

    async def add_member(
        self,
        db: AsyncSession,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        project_role: str,
        role_id: uuid.UUID | None = None,
    ) -> ProjectMember | None:
        member = await db.scalar(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id, ProjectMember.user_id == user_id
            )
        )
        if member:  # soft-deleted earlier: reactivate instead of a duplicate key
            member.is_deleted = False
            member.deleted_at = None
            member.telegram_thread_id = None
            member.project_role = project_role
            member.role_id = role_id
        else:
            member = ProjectMember(
                project_id=project_id,
                user_id=user_id,
                project_role=project_role,
                role_id=role_id,
            )
            db.add(member)
        await db.flush()

        # Eager load user relationship for response
        query = (
            select(ProjectMember)
            .options(selectinload(ProjectMember.user), selectinload(ProjectMember.role))
            .where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
        )
        result = await db.execute(query)
        return result.scalars().first()

    async def get_all_members(
        self, db: AsyncSession, project_id: uuid.UUID
    ) -> list[ProjectMember]:
        query = (
            select(ProjectMember)
            .options(selectinload(ProjectMember.user), selectinload(ProjectMember.role))
            .where(
                ProjectMember.project_id == project_id,
                ProjectMember.is_deleted.is_(False),
            )
        )
        result = await db.execute(query)
        return list(result.scalars().all())

    async def update_member(
        self, db: AsyncSession, member: ProjectMember, obj_in: dict
    ) -> ProjectMember | None:
        for field, value in obj_in.items():
            setattr(member, field, value)
        await db.flush()

        query = (
            select(ProjectMember)
            .options(selectinload(ProjectMember.user), selectinload(ProjectMember.role))
            .where(
                ProjectMember.project_id == member.project_id,
                ProjectMember.user_id == member.user_id,
            )
        )
        result = await db.execute(query)
        return result.scalars().first()

    async def remove_member(
        self, db: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID
    ) -> bool:
        member = await self.get_member(db, project_id, user_id)
        if not member:
            return False
        await db.delete(member)
        await db.flush()
        return True


project_manager = ProjectManager(Project)
