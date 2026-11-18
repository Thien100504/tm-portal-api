"""
Dashboard Schemas

Pydantic models of the dashboard API responses.
Three layers:
  - PersonalStats: personal data (everyone)
  - AdminStats: system numbers (admin only)
  - DashboardResponse: both combined; the frontend renders by role
"""

from datetime import datetime
from typing import List
from uuid import UUID

from pydantic import BaseModel


# ── Shared building blocks ────────────────────────────────────────────


class UpcomingTask(BaseModel):
    id: UUID
    title: str
    deadline: datetime
    priority: str
    status: str
    project_id: UUID
    project_name: str

    class Config:
        from_attributes = True


class ProjectProgress(BaseModel):
    id: UUID
    name: str
    my_tasks_done: int  # task assigned to me, status = done
    my_tasks_total: int  # task assigned to me, total
    my_role: str  # viewer / project_manager

    class Config:
        from_attributes = True


class TeamMemberWorkload(BaseModel):
    user_id: UUID
    full_name: str
    email: str
    in_progress_count: int
    todo_count: int
    overdue_count: int


class BlockedTask(BaseModel):
    id: UUID
    title: str
    project_id: UUID
    project_name: str
    blocked_by_count: int  # number of unfinished dependencies


# ── Personal stats (every user) ──────────────────────────────────────


class MyTaskStats(BaseModel):
    todo: int = 0
    in_progress: int = 0
    review: int = 0
    done_this_week: int = 0


class PersonalStats(BaseModel):
    my_tasks: MyTaskStats
    overdue_count: int
    my_projects_count: int
    upcoming_tasks: List[UpcomingTask]
    my_projects: List[ProjectProgress]
    # PM extras (only filled when the user is a PM of at least one project)
    is_pm: bool = False
    team_workload: List[TeamMemberWorkload] = []
    blocked_tasks: List[BlockedTask] = []


# ── Admin stats (system_role = admin only) ───────────────────────────


class TasksByStatus(BaseModel):
    todo: int = 0
    in_progress: int = 0
    review: int = 0
    done: int = 0


class RecentUser(BaseModel):
    id: UUID
    full_name: str
    email: str
    system_role: str
    created_at: datetime

    class Config:
        from_attributes = True


class AdminStats(BaseModel):
    total_users: int
    active_users: int
    total_projects: int
    active_projects: int
    total_tasks: int
    tasks_by_status: TasksByStatus
    done_this_week: int
    recent_users: List[RecentUser]
