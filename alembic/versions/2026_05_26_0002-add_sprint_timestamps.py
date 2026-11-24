"""Add started_at and completed_at timestamps to sprints

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-26 00:02:00.000000

Why:
- Separate the planned dates (start_date/end_date, set by the PM in advance)
  from the actual times (started_at/completed_at, set automatically by the action)
- started_at is needed by the Burndown Chart (the actual starting point)
- completed_at is used for sprint velocity and reports
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sprints", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "sprints", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("sprints", "completed_at")
    op.drop_column("sprints", "started_at")
