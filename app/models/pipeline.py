from __future__ import annotations

"""Pipeline execution audit trail model."""

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, UUIDMixin


class PipelineExecution(UUIDMixin, Base):
    __tablename__ = "pipeline_executions"

    execution_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    pipeline_name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    correlation_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    total_ms: Mapped[float] = mapped_column(Float, nullable=False)
    handler_count: Mapped[int] = mapped_column(Integer, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    handlers_detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
