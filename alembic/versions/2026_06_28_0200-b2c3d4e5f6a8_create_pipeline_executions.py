"""create pipeline_executions table

Revision ID: b2c3d4e5f6a8
Revises: a1b2c3d4e5f7
Create Date: 2026-06-28 02:00:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "b2c3d4e5f6a8"
down_revision = "a1b2c3d4e5f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pipeline_executions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("execution_id", sa.String(32), nullable=False, index=True),
        sa.Column("pipeline_name", sa.String(50), nullable=False, index=True),
        sa.Column("event_type", sa.String(50), nullable=False, index=True),
        sa.Column("correlation_id", sa.String(32), nullable=True),
        sa.Column("total_ms", sa.Float, nullable=False),
        sa.Column("handler_count", sa.Integer, nullable=False),
        sa.Column("success_count", sa.Integer, nullable=False),
        sa.Column("failed_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("handlers_detail", JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("pipeline_executions")
