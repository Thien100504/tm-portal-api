from typing import List
import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.user import User
from app.models.rbac import Permission
from app.modules.auth.dependencies import get_current_active_user
from app.modules.rbac.manager import rbac_manager
from app.modules.rbac.schemas import (
    PermissionResponse,
    RoleResponse,
    RoleCreate,
    RoleUpdate,
    RoleUpdatePermissions,
)

router = APIRouter(prefix="/roles", tags=["roles"])


@router.get("/permissions", response_model=List[PermissionResponse])
async def get_permissions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """List all available permissions."""
    stmt = select(Permission).order_by(Permission.module, Permission.code)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("", response_model=List[RoleResponse])
async def get_roles(
    scope: str = "project",
    workspace_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """List the roles available for a project/workspace."""
    return await rbac_manager.get_roles(db, scope, workspace_id)


@router.post("", response_model=RoleResponse, status_code=status.HTTP_201_CREATED)
async def create_role(
    role_in: RoleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Create a new role (workspaces only)."""
    return await rbac_manager.create_role(db, role_in, current_user)


@router.put("/{role_id}", response_model=RoleResponse)
async def update_role(
    role_id: uuid.UUID,
    role_in: RoleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Update a role."""
    return await rbac_manager.update_role(db, role_id, role_in, current_user)


@router.put("/{role_id}/permissions", response_model=RoleResponse)
async def update_role_permissions(
    role_id: uuid.UUID,
    perms_in: RoleUpdatePermissions,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Update the permissions of a role."""
    return await rbac_manager.update_role_permissions(
        db, role_id, perms_in, current_user
    )


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    role_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Soft-delete a role."""
    return await rbac_manager.delete_role(db, role_id, current_user)


@router.get("/my-permissions", response_model=List[str])
async def get_my_permissions(
    project_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """List the permission codes of the current user in a project/workspace."""
    # With a project, the workspace is always the project's own (see resolve_workspace)
    workspace_id = await rbac_manager.resolve_workspace(db, workspace_id, project_id)
    if not workspace_id:
        return []

    perms = await rbac_manager.get_user_permissions(
        db, current_user.id, workspace_id, project_id
    )
    return list(perms)
