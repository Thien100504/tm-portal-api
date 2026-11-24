from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from .automation import AutomationRule
    from .rbac import Role
    from .sprint import Sprint
    from .task import Task
    from .user import User
    from .workspace import Workspace


class ProjectMember(SoftDeleteMixin, Base):
    __tablename__ = "project_members"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    project_role: Mapped[str] = mapped_column(
        String, default="viewer", nullable=False
    )  # Will be deprecated
    role_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("roles.id", ondelete="RESTRICT"), nullable=True
    )
    # Joined at defined as DateTime matching spec

    # Redefine joined_at as DateTime to match spec
    from datetime import datetime

    from sqlalchemy import DateTime, func

    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    telegram_thread_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # Relationships
    project: Mapped[Project] = relationship("Project", back_populates="memberships")
    user: Mapped[User] = relationship(
        "User", back_populates="project_memberships", foreign_keys=[user_id]
    )
    role: Mapped[Role | None] = relationship("Role")


class Project(UUIDMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True
    )
    type: Mapped[str] = mapped_column(String, default="standard", nullable=False)
    status: Mapped[str] = mapped_column(String, default="active", nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    telegram_chat_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # Relationships
    workspace: Mapped[Workspace] = relationship("Workspace", back_populates="projects")
    owner: Mapped[User] = relationship(
        "User", back_populates="owned_projects", foreign_keys=[owner_id]
    )
    memberships: Mapped[list[ProjectMember]] = relationship(
        "ProjectMember", back_populates="project", cascade="all, delete-orphan"
    )
    sprints: Mapped[list[Sprint]] = relationship(
        "Sprint", back_populates="project", cascade="all, delete-orphan"
    )
    tasks: Mapped[list[Task]] = relationship(
        "Task", back_populates="project", cascade="all, delete-orphan"
    )
    automation_rules: Mapped[list[AutomationRule]] = relationship(
        "AutomationRule", back_populates="project", cascade="all, delete-orphan"
    )
