# ruff: noqa: F821
from __future__ import annotations
import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Date, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, UUIDMixin, SoftDeleteMixin

if TYPE_CHECKING:
    from .project import Project
    from .task import Task


class Sprint(UUIDMixin, SoftDeleteMixin, Base):
    __tablename__ = "sprints"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    goal: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String, default="planning", nullable=False)
    # Actual times — set by the server when the PM clicks Start/Complete
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    project: Mapped["Project"] = relationship("Project", back_populates="sprints")
    tasks: Mapped[List["Task"]] = relationship("Task", back_populates="sprint")
