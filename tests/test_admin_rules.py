"""Admin safety rules."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.modules.admin.manager import admin_manager


def _db(user):
    db = MagicMock()
    db.get = AsyncMock(return_value=user)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_admin_cannot_demote_themselves():
    me = SimpleNamespace(id=uuid.uuid4(), system_role="admin", is_active=True)
    with pytest.raises(HTTPException) as exc:
        await admin_manager.update_user_role(_db(me), me.id, "user", actor_id=me.id)
    assert exc.value.detail == "admin.cannot_modify_self"
    assert me.system_role == "admin"


@pytest.mark.asyncio
async def test_admin_cannot_deactivate_themselves():
    me = SimpleNamespace(id=uuid.uuid4(), system_role="admin", is_active=True)
    with pytest.raises(HTTPException):
        await admin_manager.update_user_status(_db(me), me.id, False, actor_id=me.id)
    assert me.is_active is True


@pytest.mark.asyncio
async def test_admin_can_change_another_user():
    other = SimpleNamespace(id=uuid.uuid4(), system_role="user", is_active=True)
    await admin_manager.update_user_role(
        _db(other), other.id, "admin", actor_id=uuid.uuid4()
    )
    assert other.system_role == "admin"


@pytest.mark.asyncio
async def test_email_duplicates_ignore_case():
    user = SimpleNamespace(id=uuid.uuid4(), full_name="A", email="a@example.com")
    db = _db(user)
    db.scalar = AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))
    with pytest.raises(HTTPException) as exc:
        await admin_manager.update_user_profile(db, user.id, email="Bob@Example.com")
    assert exc.value.status_code == 409
    assert "lower(users.email)" in str(db.scalar.await_args.args[0])
