import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.modules.auth.dependencies import get_current_active_user
from app.modules.projects.dependencies import get_project_access, get_project_pm_access
from app.modules.epics.manager import epic_manager
from app.modules.epics.schemas import EpicCreate, EpicUpdate, EpicResponse

router = APIRouter(prefix="/epics", tags=["epics"])


async def check_workspace_access(
    workspace_id: uuid.UUID, db: AsyncSession, current_user: User
):
    ws = await db.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="workspace.not_found")

    if ws.owner_id != current_user.id:
        ws_mem = await db.scalar(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == current_user.id,
            )
        )
        if not ws_mem:
            raise HTTPException(status_code=403, detail="workspace.access_denied")


@router.post("", response_model=EpicResponse, status_code=status.HTTP_201_CREATED)
async def create_epic(
    epic_in: EpicCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Create an epic in a project or a workspace."""
    # Check workspace permissions
    await check_workspace_access(epic_in.workspace_id, db, current_user)

    # With a project_id, check project permissions (only a PM or the owner can create project epics)
    if epic_in.project_id:
        await get_project_pm_access(epic_in.project_id, db, current_user)

    return await epic_manager.create(db, obj_in=epic_in)


@router.get("", response_model=List[EpicResponse])
async def list_epics(
    workspace_id: Optional[uuid.UUID] = Query(None),
    project_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """List epics by project_id or workspace_id."""
    if not workspace_id and not project_id:
        raise HTTPException(status_code=400, detail="epic.missing_scope")

    if project_id:
        await get_project_access(project_id, db, current_user)
        return await epic_manager.get_epics_by_project(db, project_id)

    if workspace_id:
        await check_workspace_access(workspace_id, db, current_user)
        return await epic_manager.get_epics_by_workspace(db, workspace_id)


@router.get("/{epic_id}", response_model=EpicResponse)
async def get_epic(
    epic_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Get an epic."""
    epic = await epic_manager.get(db, epic_id)
    if not epic or epic.is_deleted:
        raise HTTPException(status_code=404, detail="epic.not_found")

    await check_workspace_access(epic.workspace_id, db, current_user)
    return epic


@router.put("/{epic_id}", response_model=EpicResponse)
async def update_epic(
    epic_id: uuid.UUID,
    epic_in: EpicUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Update an epic."""
    epic = await epic_manager.get(db, epic_id)
    if not epic or epic.is_deleted:
        raise HTTPException(status_code=404, detail="epic.not_found")

    # Check project PM/owner access if project-scoped, else owner of workspace
    if epic.project_id:
        await get_project_pm_access(epic.project_id, db, current_user)
    else:
        ws = await db.get(Workspace, epic.workspace_id)
        if not ws:
            raise HTTPException(status_code=404, detail="workspace.not_found")
        if ws.owner_id != current_user.id:
            ws_mem = await db.scalar(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == epic.workspace_id,
                    WorkspaceMember.user_id == current_user.id,
                )
            )
            if not ws_mem:
                raise HTTPException(status_code=403, detail="epic.edit_forbidden")

    return await epic_manager.update(db, db_obj=epic, obj_in=epic_in)


@router.delete("/{epic_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_epic(
    epic_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Delete an epic (soft delete)."""
    epic = await epic_manager.get(db, epic_id)
    if not epic or epic.is_deleted:
        raise HTTPException(status_code=404, detail="epic.not_found")

    if epic.project_id:
        await get_project_pm_access(epic.project_id, db, current_user)
    else:
        ws = await db.get(Workspace, epic.workspace_id)
        if not ws:
            raise HTTPException(status_code=404, detail="workspace.not_found")
        if ws.owner_id != current_user.id:
            ws_mem = await db.scalar(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == epic.workspace_id,
                    WorkspaceMember.user_id == current_user.id,
                )
            )
            if not ws_mem:
                raise HTTPException(status_code=403, detail="epic.delete_forbidden")

    await epic_manager.remove(db, id=epic_id)
    return None
