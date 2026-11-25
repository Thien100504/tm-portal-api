from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from .ai import AISuggestion
    from .epic import Epic
    from .project import Project
    from .sprint import Sprint
    from .user import User
    from .workspace import Workspace


class TaskDependency(Base):
    __tablename__ = "task_dependencies"

    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
    )
    depends_on_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
    )


class Comment(UUIDMixin, SoftDeleteMixin, Base):
    __tablename__ = "comments"

    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    task: Mapped[Task] = relationship("Task", back_populates="comments")
    user: Mapped[User] = relationship(
        "User", back_populates="comments", foreign_keys=[user_id]
    )


class Task(UUIDMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "tasks"

    # ── Composite indexes for the most common query patterns ─────────
    __table_args__ = (
        # Kanban page load: WHERE project_id = ? AND is_deleted = false
        Index("ix_tasks_project_deleted", "project_id", "is_deleted"),
        # Status filter: WHERE project_id = ? AND is_deleted = false AND status = ?
        Index("ix_tasks_project_deleted_status", "project_id", "is_deleted", "status"),
        # Subtask lookup: WHERE parent_task_id = ? (AND is_deleted = false)
        Index("ix_tasks_parent_deleted", "parent_task_id", "is_deleted"),
        # Dashboard: WHERE assignee_id = ? AND is_deleted = false
        Index("ix_tasks_assignee_deleted", "assignee_id", "is_deleted"),
        # Overdue / upcoming: WHERE deadline IS NOT NULL AND status != 'done'
        Index("ix_tasks_deadline_status", "deadline", "status"),
        # Sprint board: WHERE sprint_id = ? AND is_deleted = false
        Index("ix_tasks_sprint_deleted", "sprint_id", "is_deleted"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True
    )
    sprint_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sprints.id", ondelete="SET NULL"), nullable=True
    )
    epic_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("epics.id", ondelete="SET NULL"), nullable=True
    )
    parent_task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, default="todo", nullable=False)
    priority: Mapped[str] = mapped_column(String, default="medium", nullable=False)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    estimated_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    story_points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    auto_start: Mapped[bool] = mapped_column(
        default=False, server_default="false", nullable=False
    )

    # Relationships
    project: Mapped[Project] = relationship("Project", back_populates="tasks")
    workspace: Mapped[Workspace | None] = relationship("Workspace")
    sprint: Mapped[Sprint] = relationship("Sprint", back_populates="tasks")
    epic: Mapped[Epic | None] = relationship("Epic", back_populates="tasks")

    parent_task: Mapped[Task | None] = relationship(
        "Task", remote_side="[Task.id]", back_populates="subtasks"
    )
    subtasks: Mapped[list[Task]] = relationship(
        "Task", back_populates="parent_task", cascade="all, delete-orphan"
    )

    assignee: Mapped[User] = relationship(
        "User", back_populates="assigned_tasks", foreign_keys=[assignee_id]
    )
    creator: Mapped[User] = relationship(
        "User", back_populates="created_tasks", foreign_keys=[created_by]
    )

    comments: Mapped[list[Comment]] = relationship(
        "Comment", back_populates="task", cascade="all, delete-orphan"
    )

    # Self-referential Many-to-Many for Dependencies
    dependencies: Mapped[list[Task]] = relationship(
        "Task",
        secondary="task_dependencies",
        primaryjoin="Task.id == TaskDependency.task_id",
        secondaryjoin="Task.id == TaskDependency.depends_on_id",
        back_populates="dependent_tasks",
    )
    dependent_tasks: Mapped[list[Task]] = relationship(
        "Task",
        secondary="task_dependencies",
        primaryjoin="Task.id == TaskDependency.depends_on_id",
        secondaryjoin="Task.id == TaskDependency.task_id",
        back_populates="dependencies",
        viewonly=True,
    )

    ai_suggestions: Mapped[list[AISuggestion]] = relationship(
        "AISuggestion", back_populates="task", cascade="all, delete-orphan"
    )
