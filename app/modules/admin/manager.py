import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.modules.auth.security import get_password_hash


class AdminManager:
    async def list_users(self, db: AsyncSession) -> list[User]:
        stmt = select(User).order_by(User.created_at.desc())
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def update_user_role(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        role: str,
        actor_id: uuid.UUID | None = None,
    ) -> User:
        user = await db.get(User, user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="admin.user_not_found"
            )

        # An admin cannot remove their own rights (the system always keeps an admin)
        if user_id == actor_id and role != "admin":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="admin.cannot_modify_self",
            )

        user.system_role = role
        await db.commit()
        await db.refresh(user)
        return user

    async def update_user_status(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        is_active: bool,
        actor_id: uuid.UUID | None = None,
    ) -> User:
        user = await db.get(User, user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="admin.user_not_found"
            )

        if user_id == actor_id and not is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="admin.cannot_modify_self",
            )

        user.is_active = is_active
        await db.commit()
        await db.refresh(user)
        return user

    async def list_workspaces(self, db: AsyncSession) -> list[dict]:
        stmt = (
            select(Workspace)
            .options(selectinload(Workspace.owner))
            .order_by(Workspace.created_at.desc())
        )
        result = await db.execute(stmt)
        ws_list = result.scalars().all()

        if not ws_list:
            return []

        ws_ids = [w.id for w in ws_list]

        # Projects count
        p_counts_stmt = (
            select(Project.workspace_id, func.count(Project.id))
            .where(Project.workspace_id.in_(ws_ids), Project.is_deleted == False)
            .group_by(Project.workspace_id)
        )
        p_counts: dict[uuid.UUID | None, int] = {
            r[0]: r[1] for r in (await db.execute(p_counts_stmt)).all()
        }

        # Tasks count
        t_counts_stmt = (
            select(Project.workspace_id, func.count(Task.id))
            .join(Project, Project.id == Task.project_id)
            .where(
                Project.workspace_id.in_(ws_ids),
                Task.is_deleted == False,
                Project.is_deleted == False,
            )
            .group_by(Project.workspace_id)
        )
        t_counts: dict[uuid.UUID | None, int] = {
            r[0]: r[1] for r in (await db.execute(t_counts_stmt)).all()
        }

        # Members count
        m_counts_stmt = (
            select(WorkspaceMember.workspace_id, func.count(WorkspaceMember.user_id))
            .where(WorkspaceMember.workspace_id.in_(ws_ids))
            .group_by(WorkspaceMember.workspace_id)
        )
        m_counts: dict[uuid.UUID, int] = {
            r[0]: r[1] for r in (await db.execute(m_counts_stmt)).all()
        }

        workspaces = []
        for w in ws_list:
            owner_name = w.owner.full_name if w.owner else "Unknown"
            owner_email = w.owner.email if w.owner else "unknown@example.com"

            workspaces.append(
                {
                    "id": w.id,
                    "name": w.name,
                    "type": w.type,
                    "owner_name": owner_name,
                    "owner_email": owner_email,
                    "projects_count": p_counts.get(w.id, 0),
                    "tasks_count": t_counts.get(w.id, 0),
                    "members_count": m_counts.get(w.id, 0),
                    "created_at": w.created_at,
                }
            )

        return workspaces

    async def update_user_profile(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        full_name: str | None = None,
        email: str | None = None,
    ) -> User:
        user = await db.get(User, user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="admin.user_not_found"
            )
        if full_name is not None:
            user.full_name = full_name
        if email is not None:
            existing = await db.scalar(
                select(User).where(
                    func.lower(User.email) == email.lower(), User.id != user_id
                )
            )
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, detail="admin.email_exists"
                )
            user.email = email
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="admin.email_exists"
            )
        await db.refresh(user)
        return user

    async def reset_user_password(
        self, db: AsyncSession, user_id: uuid.UUID, new_password: str
    ) -> User:
        user = await db.get(User, user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="admin.user_not_found"
            )

        user.password_hash = get_password_hash(new_password)
        await db.commit()
        await db.refresh(user)
        return user


admin_manager = AdminManager()
