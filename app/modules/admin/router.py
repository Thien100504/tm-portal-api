from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.modules.auth.dependencies import require_admin
from app.modules.admin.schemas import (
    AdminUserResponse,
    AdminUserUpdate,
    WorkspaceAdminResponse,
)
from app.modules.admin.manager import admin_manager

router = APIRouter(
    prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)]
)


@router.get("/users", response_model=List[AdminUserResponse])
async def list_users(db: AsyncSession = Depends(get_db)):
    """List every user of the system (admin only)."""
    return await admin_manager.list_users(db)


@router.put("/users/{user_id}/role", response_model=AdminUserResponse)
async def update_user_role(
    user_id: UUID,
    role: str = Body(..., embed=True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Change a user's system role (admin only)."""
    if role not in ["admin", "user"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="admin.invalid_role"
        )
    return await admin_manager.update_user_role(
        db, user_id, role, actor_id=current_user.id
    )


@router.put("/users/{user_id}/status", response_model=AdminUserResponse)
async def update_user_status(
    user_id: UUID,
    is_active: bool = Body(..., embed=True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Activate/deactivate a user (admin only)."""
    return await admin_manager.update_user_status(
        db, user_id, is_active, actor_id=current_user.id
    )


@router.get("/workspaces", response_model=List[WorkspaceAdminResponse])
async def list_workspaces(db: AsyncSession = Depends(get_db)):
    """List every workspace (admin only)."""
    return await admin_manager.list_workspaces(db)


@router.put("/users/{user_id}/profile", response_model=AdminUserResponse)
async def update_user_profile(
    user_id: UUID, profile_in: AdminUserUpdate, db: AsyncSession = Depends(get_db)
):
    """Update a user's name and email (admin only)."""
    return await admin_manager.update_user_profile(
        db,
        user_id,
        full_name=profile_in.full_name,
        email=profile_in.email,
    )


@router.put("/users/{user_id}/reset-password", response_model=AdminUserResponse)
async def reset_user_password(
    user_id: UUID,
    new_password: str = Body(..., embed=True),
    db: AsyncSession = Depends(get_db),
):
    """Reset a user's password (admin only)."""
    if len(new_password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="admin.password_too_short"
        )
    return await admin_manager.reset_user_password(db, user_id, new_password)
