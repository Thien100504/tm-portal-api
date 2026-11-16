# ruff: noqa: F821
from __future__ import annotations
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from .project import Project
    from .user import User

from .base import Base, UUIDMixin


class AutomationRule(UUIDMixin, Base):
    __tablename__ = "automation_rules"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    trigger_event: Mapped[str] = mapped_column(String, nullable=False)
    conditions: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    actions: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    project: Mapped["Project"] = relationship(
        "Project", back_populates="automation_rules"
    )
    creator: Mapped[Optional["User"]] = relationship(
        "User", back_populates="automation_rules", foreign_keys=[created_by]
    )
