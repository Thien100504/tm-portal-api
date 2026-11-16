from __future__ import annotations
import uuid
from datetime import date
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, UUIDMixin, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from .workspace import Workspace
    from .project import Project
    from .task import Task


class Epic(UUIDMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "epics"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    color: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String, default="open", nullable=False)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace")
    project: Mapped[Optional["Project"]] = relationship("Project")
    tasks: Mapped[List["Task"]] = relationship("Task", back_populates="epic")
