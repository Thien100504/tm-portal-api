"""Add composite indexes for tasks table performance

Revision ID: a1b2c3d4e5f6
Revises: 9bc24802d82e
Create Date: 2026-05-26 00:01:00.000000

Why:
- project_id is the most queried column but had no index of its own
- Composite indexes speed up loading the Kanban board, Dashboard and Sprint board
- Without an index PostgreSQL does a full table scan on every Kanban load
"""

from typing import Sequence, Union
from alembic import op


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "9bc24802d82e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Kanban page load: WHERE project_id = ? AND is_deleted = false
    op.create_index(
        "ix_tasks_project_deleted", "tasks", ["project_id", "is_deleted"], unique=False
    )
    # Status filter: WHERE project_id = ? AND is_deleted = false AND status = ?
    op.create_index(
        "ix_tasks_project_deleted_status",
        "tasks",
        ["project_id", "is_deleted", "status"],
        unique=False,
    )
    # Subtask lookup: WHERE parent_task_id = ? AND is_deleted = false
    op.create_index(
        "ix_tasks_parent_deleted",
        "tasks",
        ["parent_task_id", "is_deleted"],
        unique=False,
    )
    # Dashboard personal stats: WHERE assignee_id = ? AND is_deleted = false
    op.create_index(
        "ix_tasks_assignee_deleted",
        "tasks",
        ["assignee_id", "is_deleted"],
        unique=False,
    )
    # Overdue/upcoming queries: WHERE deadline IS NOT NULL AND status != 'done'
    op.create_index(
        "ix_tasks_deadline_status", "tasks", ["deadline", "status"], unique=False
    )
    # Sprint board: WHERE sprint_id = ? AND is_deleted = false
    op.create_index(
        "ix_tasks_sprint_deleted", "tasks", ["sprint_id", "is_deleted"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_tasks_project_deleted", table_name="tasks")
    op.drop_index("ix_tasks_project_deleted_status", table_name="tasks")
    op.drop_index("ix_tasks_parent_deleted", table_name="tasks")
    op.drop_index("ix_tasks_assignee_deleted", table_name="tasks")
    op.drop_index("ix_tasks_deadline_status", table_name="tasks")
    op.drop_index("ix_tasks_sprint_deleted", table_name="tasks")
