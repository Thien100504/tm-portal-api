# ruff: noqa: F821
from __future__ import annotations
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from .project import Project, ProjectMember
    from .task import Task, Comment
    from .automation import AutomationRule
    from .notification import Notification


class User(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    system_role: Mapped[str] = mapped_column(String, default="user", nullable=False)
    avatar_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    telegram_chat_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    owned_projects: Mapped[List["Project"]] = relationship(
        "Project", back_populates="owner", foreign_keys="[Project.owner_id]"
    )
    project_memberships: Mapped[List["ProjectMember"]] = relationship(
        "ProjectMember", back_populates="user", foreign_keys="[ProjectMember.user_id]"
    )
    assigned_tasks: Mapped[List["Task"]] = relationship(
        "Task", back_populates="assignee", foreign_keys="[Task.assignee_id]"
    )
    created_tasks: Mapped[List["Task"]] = relationship(
        "Task", back_populates="creator", foreign_keys="[Task.created_by]"
    )
    comments: Mapped[List["Comment"]] = relationship(
        "Comment", back_populates="user", foreign_keys="[Comment.user_id]"
    )
    automation_rules: Mapped[List["AutomationRule"]] = relationship(
        "AutomationRule", back_populates="creator"
    )
    notifications: Mapped[List["Notification"]] = relationship(
        "Notification", back_populates="user", cascade="all, delete-orphan"
    )
