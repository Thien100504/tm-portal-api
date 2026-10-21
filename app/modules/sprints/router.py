import uuid
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.events.sprint_events import sprint_events
from app.models.sprint import Sprint
from app.models.user import User
from app.modules.auth.dependencies import get_current_active_user
from app.modules.projects.dependencies import get_project_access, get_project_pm_access
from app.modules.sprints.manager import sprint_manager
from app.modules.sprints.schemas import (
    SprintCreate,
    SprintCompleteRequest,
    SprintResponse,
    SprintStats,
    SprintUpdate,
)

router = APIRouter(tags=["sprints"])


# ─── Project-scoped endpoints ────────────────────────────────────────


@router.get("/projects/{project_id}/sprints", response_model=List[SprintResponse])
async def get_sprints(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """List the sprints of the project (ordered by start_date)."""
    await get_project_access(project_id, db, current_user)
    return await sprint_manager.get_sprints_by_project(db, project_id)


@router.post(
    "/projects/{project_id}/sprints",
    response_model=SprintResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_sprint(
    project_id: uuid.UUID,
    sprint_in: SprintCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Create a sprint. PM/owner only."""
    await get_project_pm_access(project_id, db, current_user)
    sprint = await sprint_manager.create(db, obj_in=sprint_in, project_id=project_id)
    await sprint_events.emit(
        db, background_tasks, "sprint.created", sprint, actor=current_user
    )
    return sprint


# ─── Sprint detail endpoints ─────────────────────────────────────────


@router.get("/sprints/{sprint_id}", response_model=SprintResponse)
async def get_sprint(
    sprint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    sprint = await _get_sprint_or_404(db, sprint_id)
    await get_project_access(sprint.project_id, db, current_user)
    return sprint


@router.put("/sprints/{sprint_id}", response_model=SprintResponse)
async def update_sprint(
    sprint_id: uuid.UUID,
    sprint_in: SprintUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Update a sprint (name, goal, planned dates). PM/owner only."""
    sprint = await _get_sprint_or_404(db, sprint_id)
    await get_project_pm_access(sprint.project_id, db, current_user)
    return await sprint_manager.update(db, db_obj=sprint, obj_in=sprint_in)


@router.delete("/sprints/{sprint_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sprint(
    sprint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Delete a sprint (only while status = planning)."""
    sprint = await _get_sprint_or_404(db, sprint_id)
    await get_project_pm_access(sprint.project_id, db, current_user)
    if sprint.status != "planning":
        raise HTTPException(
            status_code=400,
            detail="sprint.error_cannot_delete_active",
        )
    await sprint_manager.remove(db, id=sprint_id)


# ─── Sprint lifecycle actions ─────────────────────────────────────────


@router.post("/sprints/{sprint_id}/start", response_model=SprintResponse)
async def start_sprint(
    sprint_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Start a sprint: planning → active.
    - Sets started_at = now()
    - Validates that only one sprint per project is active
    """
    sprint = await _get_sprint_or_404(db, sprint_id)
    await get_project_pm_access(sprint.project_id, db, current_user)
    sprint = await sprint_manager.start_sprint(db, sprint)
    await sprint_events.emit(
        db, background_tasks, "sprint.started", sprint, actor=current_user
    )
    return sprint


@router.post("/sprints/{sprint_id}/complete")
async def complete_sprint(
    sprint_id: uuid.UUID,
    body: SprintCompleteRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Complete a sprint: active → completed.
    - incomplete_action = 'backlog': unfinished tasks go back to the backlog
    - incomplete_action = 'next_sprint': unfinished tasks move to another sprint
    - Sets completed_at = now()
    Returns a summary: done_count, incomplete_count, total_count.
    """
    sprint = await _get_sprint_or_404(db, sprint_id)
    await get_project_pm_access(sprint.project_id, db, current_user)
    summary = await sprint_manager.complete_sprint(
        db,
        sprint,
        incomplete_action=body.incomplete_action,
        target_sprint_id=body.target_sprint_id,
    )
    await sprint_events.emit(
        db,
        background_tasks,
        "sprint.completed",
        sprint,
        actor=current_user,
        extra={"summary": summary},
    )
    return summary


@router.post("/sprints/{sprint_id}/reopen", response_model=SprintResponse)
async def reopen_sprint(
    sprint_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Reopen a completed sprint (e.g. completed by mistake).
    - completed → active, completed_at = None
    - Validates that no other sprint of the project is active
    - Tasks moved out when the sprint was completed do NOT come back
    """
    sprint = await _get_sprint_or_404(db, sprint_id)
    await get_project_pm_access(sprint.project_id, db, current_user)
    sprint = await sprint_manager.reopen_sprint(db, sprint)
    await sprint_events.emit(
        db, background_tasks, "sprint.reopened", sprint, actor=current_user
    )
    return sprint


@router.get("/sprints/{sprint_id}/stats", response_model=SprintStats)
async def get_sprint_stats(
    sprint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Sprint stats: total, done, incomplete, completion_rate, velocity, actual_days."""
    sprint = await _get_sprint_or_404(db, sprint_id)
    await get_project_access(sprint.project_id, db, current_user)
    return await sprint_manager.get_stats(db, sprint)


@router.get("/sprints/{sprint_id}/burndown")
async def get_sprint_burndown(
    sprint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Daily burndown chart data.
    Returns a list of {date, ideal_hours, remaining_hours}.
    """
    sprint = await _get_sprint_or_404(db, sprint_id)
    await get_project_access(sprint.project_id, db, current_user)
    return await sprint_manager.get_burndown(db, sprint)


# ─── Helper ──────────────────────────────────────────────────────────


async def _get_sprint_or_404(db: AsyncSession, sprint_id: uuid.UUID) -> Sprint:
    sprint = await sprint_manager.get(db, sprint_id)
    if not sprint or sprint.is_deleted:
        raise HTTPException(status_code=404, detail="sprint.not_found")
    return sprint
