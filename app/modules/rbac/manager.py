import logging

from sqlalchemy.exc import IntegrityError, OperationalError

logger = logging.getLogger(__name__)
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.project import Project, ProjectMember
from app.models.rbac import Permission, Role
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.modules.rbac.schemas import RoleCreate, RoleUpdate, RoleUpdatePermissions

# System role used for project members that have a project_role but no role_id
PROJECT_ROLE_DEFAULTS = {
    "project_manager": "Project Manager",
    "member": "Member",
    "viewer": "Viewer",
}


class RBACManager:
    async def get_user_permissions(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        project_id: uuid.UUID | None = None,
    ) -> set[str]:
        # System admins bypass RBAC — return all permission codes
        user = await db.get(User, user_id)
        if user and user.system_role == "admin":
            all_perm_rows = await db.execute(select(Permission.code))
            return set(all_perm_rows.scalars().all())

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
                    ProjectMember.is_deleted.is_(False),
                )
                .options(
                    selectinload(ProjectMember.role).selectinload(Role.permissions)
                )
            )
            prj_res = await db.execute(prj_stmt)
            prj_member = prj_res.scalars().first()

            default_role = None
            if prj_member and prj_member.role and not prj_member.role.is_deleted:
                for p in prj_member.role.permissions:
                    permissions.add(p.code)
            elif prj_member:
                # Members without a role_id (e.g. a project's creator) use project_role
                default_role = PROJECT_ROLE_DEFAULTS.get(prj_member.project_role)

            # The project owner and the workspace owner always have full project rights
            if await self._owns_project(db, user_id, project_id, workspace_id):
                default_role = "Project Manager"

            if default_role:
                permissions |= await self._system_role_permissions(db, default_role)

        return permissions

    async def _owns_project(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        project_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> bool:
        project_owner = await db.scalar(
            select(Project.owner_id).where(Project.id == project_id)
        )
        if project_owner == user_id:
            return True
        workspace_owner = await db.scalar(
            select(Workspace.owner_id).where(Workspace.id == workspace_id)
        )
        return workspace_owner == user_id

    async def _system_role_permissions(self, db: AsyncSession, name: str) -> Set[str]:
        role = await db.scalar(
            select(Role)
            .where(
                Role.name == name,
                Role.scope == "project",
                Role.is_system_default.is_(True),
                Role.is_deleted.is_(False),
            )
            .options(selectinload(Role.permissions))
        )
        return {p.code for p in role.permissions} if role else set()

    async def resolve_workspace(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
    ) -> uuid.UUID | None:
        """
        Workspace that a permission check applies to.

        With a project, the workspace is always the project's own; a different
        workspace_id sent by the client is rejected (returns None), so admin
        rights in one workspace cannot be used on a project of another.
        """
        if project_id:
            ws_id = await db.scalar(
                select(Project.workspace_id).where(
                    Project.id == project_id, Project.is_deleted.is_(False)
                )
            )
            if not ws_id or (workspace_id and workspace_id != ws_id):
                return None
            return ws_id
        return workspace_id

    async def check_permission(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        permission_code: str,
        workspace_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
    ) -> bool:
        workspace_id = await self.resolve_workspace(db, workspace_id, project_id)
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

    async def _require_role_admin(
        self, db: AsyncSession, user: User, workspace_id: uuid.UUID | None
    ) -> None:
        """Workspace roles need workspace admin rights; global roles need a system admin."""
        if workspace_id:
            allowed = await self._check_workspace_admin_access(
                db, user.id, workspace_id
            )
        else:
            allowed = getattr(user, "system_role", None) == "admin"
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="rbac.admin_required"
            )

    async def get_roles(
        self, db: AsyncSession, scope: str, workspace_id: uuid.UUID | None = None
    ) -> list[Role]:
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
        await self._require_role_admin(db, current_user, role_in.workspace_id)

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

        await self._require_role_admin(db, current_user, role.workspace_id)

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

        await self._require_role_admin(db, current_user, role.workspace_id)

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

        await self._require_role_admin(db, current_user, role.workspace_id)

        role.is_deleted = True
        role.deleted_at = datetime.now(UTC)
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
