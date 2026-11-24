"""
Dashboard Router

Two endpoints:
  GET /api/v1/dashboard/stats        → personal stats (every user)
  GET /api/v1/dashboard/admin-stats  → system-wide stats (admin only)

Design:
  - The dashboard is a "personal command center": a personal overview
    across ALL projects the user is in (not project-scoped).
  - Users see their own tasks (assignee_id = me).
  - Admins also see system-wide numbers.
  - PMs also see the team workload and blocked tasks.
"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.modules.auth.dependencies import get_current_active_user
from app.modules.dashboard.manager import dashboard_manager
from app.modules.dashboard.schemas import AdminStats, PersonalStats

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


# ─────────────────────────────────────────────────────────────────────
# GET /api/v1/dashboard/stats — personal stats (every user)
# ─────────────────────────────────────────────────────────────────────


@router.get("/stats", response_model=PersonalStats)
async def get_personal_stats(
    workspace_id: uuid.UUID | None = Query(None, description="Filter by workspace"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Returns the personal overview of the signed-in user.

    Scope: the projects of the workspace (if given) or ALL of the user's projects.
    Data: only tasks with assignee_id = current_user.id

    If the user is a PM of at least one project:
      - is_pm = True
      - team_workload: workload of each member of the projects they manage
      - blocked_tasks: tasks blocked by an unfinished dependency
    """
    return await dashboard_manager.get_personal_stats(db, current_user, workspace_id)


# ─────────────────────────────────────────────────────────────────────
# GET /api/v1/dashboard/admin-stats — system-wide stats (admin only)
# ─────────────────────────────────────────────────────────────────────


@router.get("/admin-stats", response_model=AdminStats)
async def get_admin_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Returns system-wide numbers.
    Only for system_role = 'admin'.
    """
    return await dashboard_manager.get_admin_stats(db, current_user)
