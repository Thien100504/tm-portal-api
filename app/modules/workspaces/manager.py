import logging
from sqlalchemy.exc import IntegrityError, OperationalError

logger = logging.getLogger(__name__)
from typing import List, Dict
from uuid import UUID
from datetime import datetime, timedelta, timezone
import secrets

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.project import Project, ProjectMember
from app.models.workspace import Workspace, WorkspaceMember, WorkspaceInvitation
from app.models.user import User
from app.models.rbac import Role
from app.modules.workspaces.schemas import (
    WorkspaceCreate,
    WorkspaceUpdate,
    WorkspaceMemberInvite,
    WorkspaceMemberUpdate,
)
from app.modules.rbac.manager import rbac_manager


class WorkspaceManager:
    async def _check_workspace_owner(
        self, db: AsyncSession, workspace_id: UUID, user_id: UUID
    ) -> Workspace:
        ws = await db.get(Workspace, workspace_id)
        if not ws:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="workspace.not_found"
            )
        if ws.owner_id != user_id:
            # Check if user has workspace.admin permission via RBAC manager
            has_admin = await rbac_manager.check_permission(
                db, user_id, "workspace.admin", workspace_id=workspace_id
            )
            if not has_admin:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="workspace.owner_or_admin_required",
                )
        return ws

    async def _validate_role(
        self, db: AsyncSession, role_id, workspace_id: UUID
    ) -> None:
        """A live workspace-scoped role of this workspace, or a system one."""
        if role_id is None:
            return
        role = await db.scalar(
            select(Role).where(Role.id == role_id, Role.is_deleted.is_(False))
        )
        if (
            not role
            or role.scope != "workspace"
            or not (role.is_system_default or role.workspace_id == workspace_id)
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="workspace.invalid_role"
            )

    @staticmethod
    def _check_target_member(ws: Workspace, user_id: UUID, current_user: User) -> None:
        """Admins cannot change or remove the owner, nor themselves."""
        if user_id == ws.owner_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="workspace.cannot_modify_owner",
            )
        if user_id == current_user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="workspace.cannot_modify_self",
            )

    async def list_workspaces(
        self, db: AsyncSession, current_user: User
    ) -> List[Workspace]:
        # Workspace ids of the projects the user is a member of
        proj_stmt = (
            select(Project.workspace_id)
            .outerjoin(
                ProjectMember,
                and_(
                    ProjectMember.project_id == Project.id,
                    ProjectMember.user_id == current_user.id,
                    ProjectMember.is_deleted.is_(False),
                ),
            )
            .where(
                (Project.owner_id == current_user.id)
                | (ProjectMember.user_id == current_user.id),
                Project.is_deleted.is_(False),
            )
            .distinct()
        )

        result = await db.execute(proj_stmt)
        workspace_ids = [r for r in result.scalars().all() if r is not None]

        # Workspace ids where the user is a WorkspaceMember
        ws_mem_stmt = select(WorkspaceMember.workspace_id).where(
            WorkspaceMember.user_id == current_user.id,
            WorkspaceMember.is_deleted.is_(False),
        )
        ws_mem_res = await db.execute(ws_mem_stmt)
        workspace_ids.extend([r for r in ws_mem_res.scalars().all() if r is not None])

        # Those workspaces, or the ones the user owns
        stmt = (
            select(Workspace)
            .where(
                (Workspace.owner_id == current_user.id)
                | (Workspace.id.in_(workspace_ids))
            )
            .order_by(Workspace.created_at.desc())
        )

        res = await db.execute(stmt)
        return list(res.scalars().all())

    async def create_workspace(
        self, db: AsyncSession, ws_in: WorkspaceCreate, current_user: User
    ) -> Workspace:
        if ws_in.type == "team":
            default_settings = {
                "enable_members": True,
                "enable_sprint": True,
                "enable_epics": True,
                "enable_story_points": True,
                "enable_workload": True,
                "enable_automation": True,
                "enable_ai": True,
                "enable_time_tracking": True,
                "enable_calendar": True,
                "theme": "glass",
            }
        else:
            default_settings = {
                "enable_members": False,
                "enable_sprint": False,
                "enable_epics": False,
                "enable_story_points": False,
                "enable_workload": False,
                "enable_automation": False,
                "enable_ai": True,
                "enable_time_tracking": False,
                "enable_calendar": True,
                "theme": "minimal",
            }

        settings_dict = (
            ws_in.settings.model_dump() if ws_in.settings else default_settings
        )

        db_ws = Workspace(
            name=ws_in.name,
            type=ws_in.type,
            owner_id=current_user.id,
            settings=settings_dict,
        )

        try:
            db.add(db_ws)
            await db.commit()
            await db.refresh(db_ws)
            return db_ws
        except IntegrityError as e:
            await db.rollback()
            logger.warning("Integrity violation: %s", e.orig)
            raise HTTPException(status_code=409, detail="domain.conflict_error")
        except OperationalError:
            await db.rollback()
            logger.exception("DB operational error")
            raise HTTPException(status_code=503, detail="server.db_unavailable")
        except Exception:
            await db.rollback()
            logger.exception("Unexpected error")
            raise

    async def get_workspace(
        self, db: AsyncSession, workspace_id: UUID, current_user: User
    ) -> Workspace:
        ws = await db.get(Workspace, workspace_id)
        if not ws:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="workspace.not_found"
            )

        if ws.owner_id != current_user.id:
            ws_mem_stmt = select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == current_user.id,
                WorkspaceMember.is_deleted.is_(False),
            )
            ws_mem_res = await db.execute(ws_mem_stmt)
            if not ws_mem_res.scalar_one_or_none():
                proj_stmt = (
                    select(Project)
                    .outerjoin(
                        ProjectMember,
                        and_(
                            ProjectMember.project_id == Project.id,
                            ProjectMember.user_id == current_user.id,
                            ProjectMember.is_deleted.is_(False),
                        ),
                    )
                    .where(
                        Project.workspace_id == workspace_id,
                        (Project.owner_id == current_user.id)
                        | (ProjectMember.user_id == current_user.id),
                        Project.is_deleted.is_(False),
                    )
                    .limit(1)
                )

                proj_result = await db.execute(proj_stmt)
                if not proj_result.scalar_one_or_none():
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="workspace.access_denied",
                    )

        return ws

    async def update_workspace(
        self,
        db: AsyncSession,
        workspace_id: UUID,
        ws_in: WorkspaceUpdate,
        current_user: User,
    ) -> Workspace:
        ws = await self._check_workspace_owner(db, workspace_id, current_user.id)

        if ws_in.name is not None:
            ws.name = ws_in.name
        if ws_in.settings is not None:
            ws.settings = ws_in.settings.model_dump()

        try:
            await db.commit()
            await db.refresh(ws)
        except IntegrityError as e:
            await db.rollback()
            logger.warning("Integrity violation: %s", e.orig)
            raise HTTPException(status_code=409, detail="domain.conflict_error")
        except OperationalError:
            await db.rollback()
            logger.exception("DB operational error")
            raise HTTPException(status_code=503, detail="server.db_unavailable")
        except Exception:
            await db.rollback()
            logger.exception("Unexpected error")
            raise

        # Push workspace_updated to all members so other tabs/users react immediately
        await self._broadcast_workspace_update(db, workspace_id)
        return ws

    async def _broadcast_workspace_update(self, db: AsyncSession, workspace_id: UUID):
        """Publish workspace_updated to every member's personal notification channel."""
        try:
            from app.modules.websocket.manager import _redis_pool
            import json as _json

            if _redis_pool is None:
                return

            stmt = select(WorkspaceMember.user_id).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.is_deleted.is_(False),
            )
            result = await db.execute(stmt)
            user_ids = [str(row[0]) for row in result.all()]

            payload = _json.dumps(
                {
                    "action": "workspace_updated",
                    "workspace_id": str(workspace_id),
                }
            )
            for uid in user_ids:
                await _redis_pool.publish(f"notifications:{uid}", payload)
        except Exception as e:
            logger.warning("Failed to broadcast workspace update: %s", e)

    async def delete_workspace(
        self, db: AsyncSession, workspace_id: UUID, current_user: User
    ) -> None:
        ws = await self._check_workspace_owner(db, workspace_id, current_user.id)
        if ws.owner_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="workspace.owner_required"
            )
        # Deleting cascades to every project and task: refuse while projects remain
        live_projects = await db.scalar(
            select(func.count(Project.id)).where(
                Project.workspace_id == workspace_id, Project.is_deleted.is_(False)
            )
        )
        if live_projects:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="workspace.not_empty"
            )
        if ws.type == "personal":
            personal = await db.scalar(
                select(func.count(Workspace.id)).where(
                    Workspace.owner_id == current_user.id, Workspace.type == "personal"
                )
            )
            if (personal or 0) <= 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="workspace.last_personal",
                )

        try:
            await db.delete(ws)
            await db.commit()
        except IntegrityError as e:
            await db.rollback()
            logger.warning("Integrity violation: %s", e.orig)
            raise HTTPException(status_code=409, detail="domain.conflict_error")
        except OperationalError:
            await db.rollback()
            logger.exception("DB operational error")
            raise HTTPException(status_code=503, detail="server.db_unavailable")
        except Exception:
            await db.rollback()
            logger.exception("Unexpected error")
            raise

    async def get_workspace_members(
        self, db: AsyncSession, workspace_id: UUID, current_user: User
    ) -> List[WorkspaceMember]:
        # Validate access
        await self.get_workspace(db, workspace_id, current_user)

        stmt = (
            select(WorkspaceMember)
            .where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.is_deleted.is_(False),
            )
            .options(
                selectinload(WorkspaceMember.user),
                selectinload(WorkspaceMember.role).selectinload(Role.permissions),
            )
        )

        res = await db.execute(stmt)
        return list(res.scalars().all())

    async def get_workspace_invitations(
        self, db: AsyncSession, workspace_id: UUID, current_user: User
    ) -> List[WorkspaceInvitation]:
        await self._check_workspace_owner(db, workspace_id, current_user.id)

        stmt = (
            select(WorkspaceInvitation)
            .where(
                WorkspaceInvitation.workspace_id == workspace_id,
                WorkspaceInvitation.is_deleted.is_(False),
                WorkspaceInvitation.status == "pending",
            )
            .options(selectinload(WorkspaceInvitation.role))
        )

        res = await db.execute(stmt)
        return list(res.scalars().all())

    async def invite_workspace_member(
        self,
        db: AsyncSession,
        workspace_id: UUID,
        invite_in: WorkspaceMemberInvite,
        current_user: User,
    ) -> Dict[str, str]:
        ws = await self._check_workspace_owner(db, workspace_id, current_user.id)
        if ws.type == "personal":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="workspace.personal_cannot_invite",
            )
        await self._validate_role(db, invite_in.role_id, workspace_id)

        user_stmt = select(User).where(User.email == invite_in.email)
        user = await db.scalar(user_stmt)

        if user:
            mem_stmt = select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user.id,
            )
            mem = await db.scalar(mem_stmt)
            if mem:
                if mem.is_deleted:
                    mem.is_deleted = False
                    mem.deleted_at = None
                    mem.role_id = invite_in.role_id
                else:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="workspace.member_already_exists",
                    )
            else:
                new_mem = WorkspaceMember(
                    workspace_id=workspace_id,
                    user_id=user.id,
                    role_id=invite_in.role_id,
                )
                db.add(new_mem)
        else:
            inv = WorkspaceInvitation(
                workspace_id=workspace_id,
                email=invite_in.email,
                role_id=invite_in.role_id,
                token=secrets.token_urlsafe(32),
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            )
            db.add(inv)

        try:
            await db.commit()
            return {"status": "success", "message": "User invited successfully"}
        except IntegrityError as e:
            await db.rollback()
            logger.warning("Integrity violation: %s", e.orig)
            raise HTTPException(status_code=409, detail="domain.conflict_error")
        except OperationalError:
            await db.rollback()
            logger.exception("DB operational error")
            raise HTTPException(status_code=503, detail="server.db_unavailable")
        except Exception:
            await db.rollback()
            logger.exception("Unexpected error")
            raise

    async def update_workspace_member(
        self,
        db: AsyncSession,
        workspace_id: UUID,
        user_id: UUID,
        member_in: WorkspaceMemberUpdate,
        current_user: User,
    ) -> WorkspaceMember:
        ws = await self._check_workspace_owner(db, workspace_id, current_user.id)
        self._check_target_member(ws, user_id, current_user)

        mem = await db.scalar(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
                WorkspaceMember.is_deleted.is_(False),
            )
        )
        if not mem:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="workspace.member_not_found",
            )

        await self._validate_role(db, member_in.role_id, workspace_id)
        mem.role_id = member_in.role_id

        try:
            await db.commit()
            # Refresh to load relations
            mem = await db.scalar(
                select(WorkspaceMember)
                .where(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.user_id == user_id,
                )
                .options(
                    selectinload(WorkspaceMember.user),
                    selectinload(WorkspaceMember.role),
                )
            )
            return mem
        except IntegrityError as e:
            await db.rollback()
            logger.warning("Integrity violation: %s", e.orig)
            raise HTTPException(status_code=409, detail="domain.conflict_error")
        except OperationalError:
            await db.rollback()
            logger.exception("DB operational error")
            raise HTTPException(status_code=503, detail="server.db_unavailable")
        except Exception:
            await db.rollback()
            logger.exception("Unexpected error")
            raise

    async def remove_workspace_member(
        self, db: AsyncSession, workspace_id: UUID, user_id: UUID, current_user: User
    ) -> None:
        ws = await self._check_workspace_owner(db, workspace_id, current_user.id)
        self._check_target_member(ws, user_id, current_user)

        mem = await db.scalar(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
                WorkspaceMember.is_deleted.is_(False),
            )
        )
        if not mem:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="workspace.member_not_found",
            )

        now = datetime.now(timezone.utc)
        mem.is_deleted = True
        mem.deleted_at = now
        # Leaving the workspace also ends the memberships of its projects
        await db.execute(
            update(ProjectMember)
            .where(
                ProjectMember.user_id == user_id,
                ProjectMember.is_deleted.is_(False),
                ProjectMember.project_id.in_(
                    select(Project.id).where(Project.workspace_id == workspace_id)
                ),
            )
            .values(is_deleted=True, deleted_at=now)
        )
        try:
            await db.commit()
        except IntegrityError as e:
            await db.rollback()
            logger.warning("Integrity violation: %s", e.orig)
            raise HTTPException(status_code=409, detail="domain.conflict_error")
        except OperationalError:
            await db.rollback()
            logger.exception("DB operational error")
            raise HTTPException(status_code=503, detail="server.db_unavailable")
        except Exception:
            await db.rollback()
            logger.exception("Unexpected error")
            raise

    async def cancel_workspace_invitation(
        self, db: AsyncSession, workspace_id: UUID, invite_id: UUID, current_user: User
    ) -> None:
        await self._check_workspace_owner(db, workspace_id, current_user.id)

        inv = await db.scalar(
            select(WorkspaceInvitation).where(
                WorkspaceInvitation.id == invite_id,
                WorkspaceInvitation.workspace_id == workspace_id,
                WorkspaceInvitation.is_deleted.is_(False),
            )
        )
        if not inv:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="workspace.invitation_not_found",
            )

        inv.is_deleted = True
        inv.deleted_at = datetime.utcnow()
        inv.status = "cancelled"
        try:
            await db.commit()
        except IntegrityError as e:
            await db.rollback()
            logger.warning("Integrity violation: %s", e.orig)
            raise HTTPException(status_code=409, detail="domain.conflict_error")
        except OperationalError:
            await db.rollback()
            logger.exception("DB operational error")
            raise HTTPException(status_code=503, detail="server.db_unavailable")
        except Exception:
            await db.rollback()
            logger.exception("Unexpected error")
            raise


workspace_manager = WorkspaceManager()
