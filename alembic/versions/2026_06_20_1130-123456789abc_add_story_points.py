"""add story points

Revision ID: 123456789abc
Revises: 51d29509ab0a
Create Date: 2026-06-20 11:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "123456789abc"
down_revision: str | None = "51d29509ab0a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("story_points", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "story_points")
