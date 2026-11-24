"""Unit tests for various Pydantic schema classes across modules."""

import uuid
from datetime import datetime

import pytest
from pydantic import ValidationError

from app.config import get_settings
from app.modules.dashboard.schemas import (
    AdminStats,
    BlockedTask,
    MyTaskStats,
    PersonalStats,
    ProjectProgress,
    RecentUser,
    TasksByStatus,
    TeamMemberWorkload,
    UpcomingTask,
)
from app.modules.projects.schemas import ProjectCreate, ProjectUpdate
from app.modules.sprints.schemas import SprintCreate, SprintUpdate
from app.modules.tasks.schemas import (
    CommentCreate,
    TaskCreate,
    TaskDependencyCreate,
    TaskUpdate,
)
from app.modules.workspaces.schemas import (
    WorkspaceCreate,
    WorkspaceMemberInvite,
    WorkspaceMemberUpdate,
    WorkspaceUpdate,
)

# ─── Config ──────────────────────────────────────────────────────────────────


def test_settings_defaults():
    settings = get_settings()
    assert settings.ALGORITHM == "HS256"
    assert settings.ACCESS_TOKEN_EXPIRE_MINUTES == 15
    assert settings.REFRESH_TOKEN_EXPIRE_DAYS == 7
    assert "postgresql" in settings.DATABASE_URL
    assert settings.DB_POOL_SIZE == 3
    assert settings.DB_MAX_OVERFLOW == 2


def test_settings_sync_database_url():
    settings = get_settings()
    sync_url = settings.SYNC_DATABASE_URL
    assert "+asyncpg" not in sync_url


# ─── TaskCreate ───────────────────────────────────────────────────────────────


def test_task_create_minimal():
    t = TaskCreate(title="My Task", project_id=uuid.uuid4())
    assert t.title == "My Task"
    assert t.priority == "medium"
    assert t.auto_start is False


def test_task_create_full():
    t = TaskCreate(
        title="Full Task",
        project_id=uuid.uuid4(),
        description="desc",
        priority="high",
        sprint_id=uuid.uuid4(),
        assignee_id=uuid.uuid4(),
    )
    assert t.priority == "high"
    assert t.description == "desc"


def test_task_create_title_too_short():
    with pytest.raises(ValidationError):
        TaskCreate(title="", project_id=uuid.uuid4())


def test_task_update_partial():
    t = TaskUpdate(title="Updated")
    assert t.title == "Updated"
    assert t.description is None


def test_task_dependency_create():
    dep = TaskDependencyCreate(depends_on_id=uuid.uuid4())
    assert dep.depends_on_id is not None


def test_comment_create():
    c = CommentCreate(content="A comment")
    assert c.content == "A comment"


def test_comment_create_empty():
    with pytest.raises(ValidationError):
        CommentCreate(content="")


# ─── SprintSchemas ───────────────────────────────────────────────────────────


def test_sprint_create():
    s = SprintCreate(name="Sprint 1")
    assert s.name == "Sprint 1"
    assert "status" not in s.model_dump()  # status only changes via the lifecycle


def test_sprint_update():
    s = SprintUpdate(name="Sprint Updated")
    assert s.name == "Sprint Updated"


# ─── WorkspaceSchemas ────────────────────────────────────────────────────────


def test_workspace_create():
    w = WorkspaceCreate(name="My Workspace")
    assert w.name == "My Workspace"


def test_workspace_update():
    w = WorkspaceUpdate(name="Updated Workspace")
    assert w.name == "Updated Workspace"


def test_workspace_member_invite():
    inv = WorkspaceMemberInvite(email="member@example.com")
    assert inv.email == "member@example.com"


def test_workspace_member_update():
    upd = WorkspaceMemberUpdate(role_id=uuid.uuid4())
    assert upd.role_id is not None


# ─── ProjectSchemas ──────────────────────────────────────────────────────────


def test_project_create():
    p = ProjectCreate(name="My Project", workspace_id=uuid.uuid4())
    assert p.name == "My Project"


def test_project_update():
    p = ProjectUpdate(name="Updated Project")
    assert p.name == "Updated Project"


# ─── DashboardSchemas ────────────────────────────────────────────────────────


def test_my_task_stats():
    s = MyTaskStats(todo=1, in_progress=2, review=0, done_this_week=5)
    assert s.todo == 1
    assert s.done_this_week == 5


def test_tasks_by_status():
    t = TasksByStatus(todo=3, in_progress=1, review=2, done=10)
    assert t.done == 10


def test_project_progress():
    p = ProjectProgress(
        id=uuid.uuid4(),
        name="Project A",
        my_tasks_done=3,
        my_tasks_total=10,
        my_role="Developer",
    )
    assert p.my_tasks_total == 10


def test_upcoming_task():
    t = UpcomingTask(
        id=uuid.uuid4(),
        title="Task Due",
        deadline=datetime.utcnow(),
        priority="high",
        status="todo",
        project_id=uuid.uuid4(),
        project_name="Project X",
    )
    assert t.title == "Task Due"


def test_team_member_workload():
    w = TeamMemberWorkload(
        user_id=uuid.uuid4(),
        full_name="Alice",
        email="alice@example.com",
        in_progress_count=3,
        todo_count=5,
        overdue_count=1,
    )
    assert w.full_name == "Alice"


def test_blocked_task():
    b = BlockedTask(
        id=uuid.uuid4(),
        title="Blocked Task",
        project_id=uuid.uuid4(),
        project_name="Proj",
        blocked_by_count=2,
    )
    assert b.blocked_by_count == 2


def test_recent_user():
    r = RecentUser(
        id=uuid.uuid4(),
        full_name="Bob",
        email="bob@example.com",
        system_role="user",
        created_at=datetime.utcnow(),
    )
    assert r.full_name == "Bob"


def test_personal_stats_build():
    stats = PersonalStats(
        my_tasks=MyTaskStats(todo=1, in_progress=0, review=0, done_this_week=0),
        overdue_count=0,
        my_projects_count=2,
        upcoming_tasks=[],
        my_projects=[],
        is_pm=False,
        team_workload=[],
        blocked_tasks=[],
    )
    assert stats.my_projects_count == 2


def test_admin_stats_build():
    stats = AdminStats(
        total_users=100,
        active_users=80,
        total_projects=20,
        active_projects=15,
        total_tasks=500,
        tasks_by_status=TasksByStatus(todo=100, in_progress=50, review=20, done=330),
        done_this_week=30,
        recent_users=[],
    )
    assert stats.total_users == 100
