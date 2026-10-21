import uuid
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.events.project_events import project_events
from app.models.user import User
from app.models.workspace import WorkspaceMember
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

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=List[ProjectResponse])
async def get_projects(
    workspace_id: Optional[uuid.UUID] = None,
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
    """Create a project."""
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
    """Delete a project. Owner only."""
    project = await project_manager.get(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="project.not_found")

    if project.owner_id != current_user.id:
        ws_mem = await db.scalar(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == project.workspace_id,
                WorkspaceMember.user_id == current_user.id,
            )
        )
        if not ws_mem:
            raise HTTPException(status_code=403, detail="project.owner_only")

    await project_manager.remove(db, id=project_id)


@router.get("/{project_id}/members", response_model=List[ProjectMemberResponse])
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
    await get_project_access(project_id, db, current_user)

    member = await project_manager.get_member(db, project_id, user_id)
    if not member:
        raise HTTPException(status_code=404, detail="project.member_not_found")

    update_data = member_in.model_dump(exclude_unset=True)

    # Check permissions
    if "project_role" in update_data:
        # Require PM access to update roles
        await get_project_pm_access(project_id, db, current_user)

    if "telegram_thread_id" in update_data:
        # Allow user to update their own, OR require PM access
        if current_user.id != user_id:
            await get_project_pm_access(project_id, db, current_user)

    return await project_manager.update_member(db, member, update_data)
