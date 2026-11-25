import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.events.project_events import project_events
from app.models.user import User
from app.models.workspace import Workspace
from app.modules.auth.dependencies import get_current_active_user
from app.modules.auth.manager import user_manager
from app.modules.projects.dependencies import get_project_access, get_project_pm_access
from app.modules.projects.manager import project_manager
from app.modules.projects.schemas import (
    ProjectCreate,
    ProjectMemberCreate,
    ProjectMemberResponse,
    ProjectMemberUpdate,
    ProjectResponse,
    ProjectUpdate,
)
from app.modules.rbac.manager import rbac_manager

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectResponse])
async def get_projects(
    workspace_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """List the projects the user owns or is a member of."""
    return await project_manager.get_projects_for_user(
        db, current_user.id, workspace_id
    )


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    project_in: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Create a project (in a workspace the user belongs to, or their personal one)."""
    if project_in.workspace_id and not await project_manager.is_workspace_member(
        db, project_in.workspace_id, current_user.id
    ):
        raise HTTPException(status_code=403, detail="project.workspace_forbidden")
    return await project_manager.create_project_with_owner(
        db, project_in, current_user.id
    )


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Get a project."""
    project = await get_project_access(project_id, db, current_user)
    return await project_manager.attach_member_count(db, project)


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: uuid.UUID,
    project_in: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Update a project. Requires the owner or a Project Manager."""
    project = await get_project_pm_access(project_id, db, current_user)
    return await project_manager.update(db, db_obj=project, obj_in=project_in)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Delete (soft) a project. The owner or a workspace admin only."""
    project = await get_project_access(project_id, db, current_user)

    if project.owner_id != current_user.id:
        is_admin = (
            project.workspace_id
            and await rbac_manager._check_workspace_admin_access(
                db, current_user.id, project.workspace_id
            )
        )
        if not is_admin:
            raise HTTPException(status_code=403, detail="project.owner_only")

    await project_manager.soft_delete(db, project, current_user.id)


@router.get("/{project_id}/members", response_model=list[ProjectMemberResponse])
async def get_members(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """List the project members."""
    await get_project_access(project_id, db, current_user)
    return await project_manager.get_all_members(db, project_id)


@router.post("/{project_id}/members", response_model=ProjectMemberResponse)
async def add_member(
    project_id: uuid.UUID,
    member_in: ProjectMemberCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Add a member to the project. Owner or PM only."""
    project = await get_project_pm_access(project_id, db, current_user)

    existing = await project_manager.get_member(db, project_id, member_in.user_id)
    if existing:
        raise HTTPException(status_code=400, detail="project.member_exists")

    user = await user_manager.get(db, member_in.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="user.not_found")

    await project_manager.validate_role(db, member_in.role_id, project.workspace_id)
    if project.workspace_id:
        workspace = await db.get(Workspace, project.workspace_id)
        if (
            workspace
            and workspace.type != "personal"
            and not await project_manager.is_workspace_member(
                db, project.workspace_id, member_in.user_id
            )
        ):
            raise HTTPException(status_code=400, detail="project.user_not_in_workspace")

    result = await project_manager.add_member(
        db, project_id, member_in.user_id, member_in.project_role, member_in.role_id
    )
    await project_events.emit(
        db,
        background_tasks,
        "project.member_added",
        project,
        actor=current_user,
        extra={"target_user_id": member_in.user_id, "target_user_name": user.full_name},
    )
    return result


@router.delete(
    "/{project_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_member(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Remove a member from the project. Owner or PM only."""
    project = await get_project_pm_access(project_id, db, current_user)

    if user_id == project.owner_id:
        raise HTTPException(status_code=400, detail="project.cannot_remove_owner")

    user = await db.get(User, user_id)
    removed = await project_manager.remove_member(db, project_id, user_id)
    if not removed:
        raise HTTPException(status_code=404, detail="project.member_not_found")

    await project_events.emit(
        db,
        background_tasks,
        "project.member_removed",
        project,
        actor=current_user,
        extra={
            "target_user_id": user_id,
            "target_user_name": user.full_name if user else "Unknown",
        },
    )


@router.put("/{project_id}/members/{user_id}", response_model=ProjectMemberResponse)
async def update_member(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    member_in: ProjectMemberUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Update a project member.
    - Any user may update their own telegram_thread_id.
    - Only the PM/owner may change roles.
    """
    project = await get_project_access(project_id, db, current_user)

    member = await project_manager.get_member(db, project_id, user_id)
    if not member:
        raise HTTPException(status_code=404, detail="project.member_not_found")

    update_data = member_in.model_dump(exclude_unset=True)

    # Without PM rights a user may only change their own telegram_thread_id;
    # everything else (project_role, role_id, ...) needs the owner or a PM
    self_service = current_user.id == user_id and set(update_data) <= {
        "telegram_thread_id"
    }
    if not self_service:
        await get_project_pm_access(project_id, db, current_user)

    if "role_id" in update_data:
        await project_manager.validate_role(
            db, update_data["role_id"], project.workspace_id
        )

    return await project_manager.update_member(db, member, update_data)
