"""add tasks.type (story, task, bug)

Existing tasks become "task".

Revision ID: c9e0632baefa
Revises: 402e7a61059c
Create Date: 2026-11-27 01:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c9e0632baefa"
down_revision: str | None = "402e7a61059c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("type", sa.String(20), server_default="task", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("tasks", "type")
