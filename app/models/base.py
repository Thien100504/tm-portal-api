from __future__ import annotations

"""
Shared base models and mixins.

Includes:
- DeclarativeBase for SQLAlchemy 2.0
- UUIDMixin: UUID id column, auto-generated uuid4
- TimestampMixin: created_at, updated_at columns updated automatically
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


class UUIDMixin:
    """
    Mixin providing a UUID id column.

    Automatically generates a uuid4 value for each new record.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )


class TimestampMixin:
    """
    Mixin providing timestamp tracking columns.

    - created_at: record creation time (server_default)
    - updated_at: last update time (automatic onupdate)
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    """
    Mixin with the columns used for soft deletion.

    - is_deleted: Whether the record has been deleted.
    - deleted_at: Time of deletion.
    - deleted_by: ID of the user who performed the deletion.
    """

    is_deleted: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False, index=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
