import logging
from sqlalchemy.exc import IntegrityError, OperationalError

logger = logging.getLogger(__name__)
from typing import Optional, Set, List
import uuid
from datetime import datetime
from fastapi import HTTPException, status
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.project import Project, ProjectMember
from app.models.workspace import Workspace, WorkspaceMember
from app.models.rbac import Role, Permission
from app.models.user import User
from app.modules.rbac.schemas import RoleCreate, RoleUpdate, RoleUpdatePermissions


class RBACManager:
    async def get_user_permissions(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        project_id: Optional[uuid.UUID] = None,
    ) -> Set[str]:
        permissions = set()

        # Workspace Level
        ws_stmt = (
            select(WorkspaceMember)
            .where(
                WorkspaceMember.user_id == user_id,
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.is_deleted.is_(False),
            )
            .options(selectinload(WorkspaceMember.role).selectinload(Role.permissions))
        )
        ws_res = await db.execute(ws_stmt)
        ws_member = ws_res.scalars().first()

        if ws_member and ws_member.role and not ws_member.role.is_deleted:
            for p in ws_member.role.permissions:
                permissions.add(p.code)

        # Project Level
        if project_id:
            prj_stmt = (
                select(ProjectMember)
                .where(
                    ProjectMember.user_id == user_id,
                    ProjectMember.project_id == project_id,
                )
                .options(
                    selectinload(ProjectMember.role).selectinload(Role.permissions)
                )
            )
            prj_res = await db.execute(prj_stmt)
            prj_member = prj_res.scalars().first()

            if prj_member and prj_member.role and not prj_member.role.is_deleted:
                for p in prj_member.role.permissions:
                    permissions.add(p.code)

        return permissions

    async def check_permission(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        permission_code: str,
        workspace_id: Optional[uuid.UUID] = None,
        project_id: Optional[uuid.UUID] = None,
    ) -> bool:
        if not workspace_id and project_id:
            prj_stmt = select(Project.workspace_id).where(Project.id == project_id)
            ws_id = await db.scalar(prj_stmt)
            if not ws_id:
                return False
            workspace_id = ws_id

        if not workspace_id:
            return False

        perms = await self.get_user_permissions(db, user_id, workspace_id, project_id)
        return permission_code in perms

    async def _check_workspace_admin_access(
        self, db: AsyncSession, user_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> bool:
        """Check if user is owner of the workspace or has workspace.admin permission"""
        ws = await db.scalar(select(Workspace).where(Workspace.id == workspace_id))
        if ws and ws.owner_id == user_id:
            return True
        return await self.check_permission(
            db, user_id, "workspace.admin", workspace_id=workspace_id
        )

    async def get_roles(
        self, db: AsyncSession, scope: str, workspace_id: Optional[uuid.UUID] = None
    ) -> List[Role]:
        conditions = [Role.scope == scope, Role.is_deleted.is_(False)]
        if workspace_id:
            conditions.append(
                (Role.is_system_default.is_(True)) | (Role.workspace_id == workspace_id)
            )
        else:
            conditions.append(Role.is_system_default.is_(True))

        stmt = (
            select(Role)
            .where(and_(*conditions))
            .options(selectinload(Role.permissions))
            .order_by(Role.name)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def create_role(
        self, db: AsyncSession, role_in: RoleCreate, current_user: User
    ) -> Role | None:
        if role_in.workspace_id:
            has_access = await self._check_workspace_admin_access(
                db, current_user.id, role_in.workspace_id
            )
            if not has_access:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, detail="rbac.admin_required"
                )

        db_role = Role(
            name=role_in.name,
            description=role_in.description,
            scope=role_in.scope,
            workspace_id=role_in.workspace_id,
            is_system_default=False,
        )
        try:
            db.add(db_role)
            await db.commit()
            result = await db.execute(
                select(Role)
                .where(Role.id == db_role.id)
                .options(selectinload(Role.permissions))
            )
            return result.scalars().first()
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

    async def update_role(
        self,
        db: AsyncSession,
        role_id: uuid.UUID,
        role_in: RoleUpdate,
        current_user: User,
    ) -> Role | None:
        role = await db.scalar(
            select(Role)
            .where(Role.id == role_id, Role.is_deleted.is_(False))
            .options(selectinload(Role.permissions))
        )
        if not role:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="rbac.role_not_found"
            )

        if role.is_system_default:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="rbac.cannot_modify_system_role",
            )

        if role.workspace_id:
            has_access = await self._check_workspace_admin_access(
                db, current_user.id, role.workspace_id
            )
            if not has_access:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, detail="rbac.admin_required"
                )

        if role_in.name is not None:
            role.name = role_in.name
        if role_in.description is not None:
            role.description = role_in.description

        try:
            await db.commit()
            result = await db.execute(
                select(Role)
                .where(Role.id == role.id)
                .options(selectinload(Role.permissions))
            )
            return result.scalars().first()
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

    async def update_role_permissions(
        self,
        db: AsyncSession,
        role_id: uuid.UUID,
        perms_in: RoleUpdatePermissions,
        current_user: User,
    ) -> Role | None:
        role = await db.scalar(
            select(Role)
            .where(Role.id == role_id, Role.is_deleted.is_(False))
            .options(selectinload(Role.permissions))
        )
        if not role:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="rbac.role_not_found"
            )

        if role.is_system_default:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="rbac.cannot_modify_system_role",
            )

        if role.workspace_id:
            has_access = await self._check_workspace_admin_access(
                db, current_user.id, role.workspace_id
            )
            if not has_access:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, detail="rbac.admin_required"
                )

        # Validate permissions
        stmt = select(Permission).where(Permission.id.in_(perms_in.permission_ids))
        result = await db.execute(stmt)
        permissions = result.scalars().all()

        if len(permissions) != len(set(perms_in.permission_ids)):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="rbac.some_permissions_invalid",
            )

        role.permissions = list(permissions)
        try:
            await db.commit()
            return await db.scalar(
                select(Role)
                .where(Role.id == role.id)
                .options(selectinload(Role.permissions))
            )
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

    async def delete_role(
        self, db: AsyncSession, role_id: uuid.UUID, current_user: User
    ) -> None:
        role = await db.scalar(
            select(Role).where(Role.id == role_id, Role.is_deleted.is_(False))
        )
        if not role:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="rbac.role_not_found"
            )

        if role.is_system_default:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="rbac.cannot_delete_system_role",
            )

        if role.workspace_id:
            has_access = await self._check_workspace_admin_access(
                db, current_user.id, role.workspace_id
            )
            if not has_access:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, detail="rbac.admin_required"
                )

        role.is_deleted = True
        role.deleted_at = datetime.utcnow()
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


rbac_manager = RBACManager()
