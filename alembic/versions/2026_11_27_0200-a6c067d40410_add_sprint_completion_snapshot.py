"""add sprints.completion_snapshot

Sprints completed before this migration have no snapshot; their report is
still computed from the tasks currently in the sprint.

Revision ID: a6c067d40410
Revises: c9e0632baefa
Create Date: 2026-11-27 02:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a6c067d40410"
down_revision: str | None = "c9e0632baefa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sprints",
        sa.Column(
            "completion_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("sprints", "completion_snapshot")
