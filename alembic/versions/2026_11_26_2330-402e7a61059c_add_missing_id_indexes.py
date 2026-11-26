"""add the id indexes missing on ai_metrics and pipeline_executions

Every UUIDMixin table declares index=True on id, but the hand-written
migrations for these two tables never created the index, so the models and
the schema disagreed (reported by `alembic check`).

Revision ID: 402e7a61059c
Revises: c7d1e2f3a4b5
Create Date: 2026-11-26 23:30:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "402e7a61059c"
down_revision: str | None = "c7d1e2f3a4b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_ai_metrics_id", "ai_metrics", ["id"], if_not_exists=True)
    op.create_index(
        "ix_pipeline_executions_id", "pipeline_executions", ["id"], if_not_exists=True
    )


def downgrade() -> None:
    op.drop_index(
        "ix_pipeline_executions_id", table_name="pipeline_executions", if_exists=True
    )
    op.drop_index("ix_ai_metrics_id", table_name="ai_metrics", if_exists=True)
