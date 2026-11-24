from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from .project import Project
    from .task import Task
    from .workspace import Workspace


class Epic(UUIDMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "epics"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    color: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String, default="open", nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Relationships
    workspace: Mapped[Workspace] = relationship("Workspace")
    project: Mapped[Project | None] = relationship("Project")
    tasks: Mapped[list[Task]] = relationship("Task", back_populates="epic")
