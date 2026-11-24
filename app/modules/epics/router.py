import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.epic import Epic
from app.models.user import User
from app.modules.auth.dependencies import get_current_active_user
from app.modules.epics.manager import epic_manager
from app.modules.epics.schemas import EpicCreate, EpicResponse, EpicUpdate
from app.modules.projects.dependencies import get_project_access, get_project_pm_access
from app.modules.projects.manager import project_manager
from app.modules.rbac.manager import rbac_manager
from app.modules.workspaces.features import require_feature

router = APIRouter(
    prefix="/epics",
    tags=["epics"],
    dependencies=[Depends(require_feature("enable_epics"))],
)


async def check_workspace_access(
    workspace_id: uuid.UUID, db: AsyncSession, current_user: User
) -> None:
    """The workspace owner or an active (not removed) member."""
    if not await project_manager.is_workspace_member(db, workspace_id, current_user.id):
        raise HTTPException(status_code=403, detail="workspace.access_denied")


async def check_epic_manage(epic_project_id, workspace_id, db, current_user) -> None:
    """Project epics: the project's PM/owner. Workspace epics: a workspace admin."""
    if epic_project_id:
        await get_project_pm_access(epic_project_id, db, current_user)
    elif not await rbac_manager._check_workspace_admin_access(
        db, current_user.id, workspace_id
    ):
        raise HTTPException(status_code=403, detail="epic.edit_forbidden")


async def _get_live_epic(db: AsyncSession, epic_id: uuid.UUID) -> Epic:
    epic = await epic_manager.get(db, epic_id)
    if not epic or epic.is_deleted:
        raise HTTPException(status_code=404, detail="epic.not_found")
    return epic


@router.post("", response_model=EpicResponse, status_code=status.HTTP_201_CREATED)
async def create_epic(
    epic_in: EpicCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Create an epic in a project (PM/owner) or at workspace level (workspace admin)."""
    if epic_in.project_id:
        project = await get_project_pm_access(epic_in.project_id, db, current_user)
        # a project epic always lives in the project's workspace
        epic_in.workspace_id = project.workspace_id
    else:
        if not epic_in.workspace_id:
            raise HTTPException(status_code=400, detail="epic.missing_scope")
        await check_workspace_access(epic_in.workspace_id, db, current_user)
        await check_epic_manage(None, epic_in.workspace_id, db, current_user)

    return await epic_manager.create(db, obj_in=epic_in)


@router.get("", response_model=list[EpicResponse])
async def list_epics(
    workspace_id: uuid.UUID | None = Query(None),
    project_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """List epics by project_id or workspace_id."""
    if not workspace_id and not project_id:
        raise HTTPException(status_code=400, detail="epic.missing_scope")

    if project_id:
        await get_project_access(project_id, db, current_user)
        return await epic_manager.get_epics_by_project(db, project_id)

    await check_workspace_access(workspace_id, db, current_user)
    return await epic_manager.get_epics_by_workspace(db, workspace_id)


@router.get("/{epic_id}", response_model=EpicResponse)
async def get_epic(
    epic_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Get an epic."""
    epic = await _get_live_epic(db, epic_id)
    if epic.project_id:
        await get_project_access(epic.project_id, db, current_user)
    else:
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
    epic = await _get_live_epic(db, epic_id)
    await check_epic_manage(epic.project_id, epic.workspace_id, db, current_user)
    return await epic_manager.update(db, db_obj=epic, obj_in=epic_in)


@router.delete("/{epic_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_epic(
    epic_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Delete an epic (soft delete: tasks keep their link for history)."""
    epic = await _get_live_epic(db, epic_id)
    await check_epic_manage(epic.project_id, epic.workspace_id, db, current_user)
    await epic_manager.soft_delete(db, epic, current_user.id)
    return None
