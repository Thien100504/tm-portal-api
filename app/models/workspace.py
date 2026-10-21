from __future__ import annotations
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import String, ForeignKey, Boolean, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from .user import User
    from .project import Project
    from .rbac import Role


class Workspace(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, default="personal", nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    settings: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=lambda: {
            "enable_members": False,
            "enable_sprint": False,
            "enable_epics": False,
            "enable_story_points": False,
            "enable_workload": False,
            "enable_automation": False,
            "enable_ai": True,
            "enable_time_tracking": False,
            "enable_calendar": True,
            "enable_list_view": False,
            "enable_reports": False,
            "theme": "minimal",
        },
    )

    # Relationships
    owner: Mapped["User"] = relationship("User", foreign_keys=[owner_id])
    projects: Mapped[List["Project"]] = relationship(
        "Project", back_populates="workspace", cascade="all, delete-orphan"
    )
    memberships: Mapped[List["WorkspaceMember"]] = relationship(
        "WorkspaceMember", back_populates="workspace", cascade="all, delete-orphan"
    )


class WorkspaceMember(TimestampMixin, Base):
    __tablename__ = "workspace_members"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("roles.id", ondelete="SET NULL"), nullable=True
    )

    # Relationships
    workspace: Mapped["Workspace"] = relationship(
        "Workspace", back_populates="memberships"
    )
    user: Mapped["User"] = relationship("User")
    role: Mapped[Optional["Role"]] = relationship("Role")

    # Soft Delete
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, server_default="false", default=False, nullable=False
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class WorkspaceInvitation(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "workspace_invitations"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String, nullable=False, index=True)
    role_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("roles.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String, default="pending", nullable=False
    )  # pending, accepted, rejected, expired
    token: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # Soft Delete
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, server_default="false", default=False, nullable=False
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace")
    role: Mapped[Optional["Role"]] = relationship("Role")
