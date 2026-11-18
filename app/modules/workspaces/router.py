from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.modules.auth.dependencies import get_current_active_user
from app.modules.workspaces.schemas import (
    WorkspaceCreate,
    WorkspaceUpdate,
    WorkspaceResponse,
    WorkspaceMemberResponse,
    WorkspaceMemberInvite,
    WorkspaceMemberUpdate,
    WorkspaceInvitationResponse,
)
from app.modules.workspaces.manager import workspace_manager

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get("", response_model=List[WorkspaceResponse])
async def list_workspaces(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """List every workspace the user can access."""
    return await workspace_manager.list_workspaces(db, current_user)


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    ws_in: WorkspaceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Create a workspace."""
    return await workspace_manager.create_workspace(db, ws_in, current_user)


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(
    workspace_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Get a workspace."""
    return await workspace_manager.get_workspace(db, workspace_id, current_user)


@router.put("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(
    workspace_id: UUID,
    ws_in: WorkspaceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Update a workspace (owner or admin only)."""
    return await workspace_manager.update_workspace(
        db, workspace_id, ws_in, current_user
    )


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(
    workspace_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Delete a workspace (owner or admin only)."""
    return await workspace_manager.delete_workspace(db, workspace_id, current_user)


@router.get("/{workspace_id}/members", response_model=List[WorkspaceMemberResponse])
async def get_workspace_members(
    workspace_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """List the workspace members."""
    return await workspace_manager.get_workspace_members(db, workspace_id, current_user)


@router.get(
    "/{workspace_id}/invitations", response_model=List[WorkspaceInvitationResponse]
)
async def get_workspace_invitations(
    workspace_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """List the pending invitations."""
    return await workspace_manager.get_workspace_invitations(
        db, workspace_id, current_user
    )


@router.post("/{workspace_id}/members/invite")
async def invite_workspace_member(
    workspace_id: UUID,
    invite_in: WorkspaceMemberInvite,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Invite a user to the workspace."""
    return await workspace_manager.invite_workspace_member(
        db, workspace_id, invite_in, current_user
    )


@router.put("/{workspace_id}/members/{user_id}", response_model=WorkspaceMemberResponse)
async def update_workspace_member(
    workspace_id: UUID,
    user_id: UUID,
    member_in: WorkspaceMemberUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Change a member's role in the workspace."""
    return await workspace_manager.update_workspace_member(
        db, workspace_id, user_id, member_in, current_user
    )


@router.delete(
    "/{workspace_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_workspace_member(
    workspace_id: UUID,
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Remove a member from the workspace (soft delete)."""
    return await workspace_manager.remove_workspace_member(
        db, workspace_id, user_id, current_user
    )


@router.delete(
    "/{workspace_id}/invitations/{invite_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def cancel_workspace_invitation(
    workspace_id: UUID,
    invite_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Cancel a workspace invitation."""
    return await workspace_manager.cancel_workspace_invitation(
        db, workspace_id, invite_id, current_user
    )
