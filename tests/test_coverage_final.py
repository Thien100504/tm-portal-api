"""
Last push — need just 1+ statement to cross 80%.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError


# rbac_manager.create_role — OperationalError path (lines 156-159)
@pytest.mark.asyncio
async def test_rbac_create_role_operational_error():
    from app.modules.rbac.manager import rbac_manager
    from app.modules.rbac.schemas import RoleCreate

    db = AsyncMock()
    db.add = MagicMock()
    db.rollback = AsyncMock()

    async def raise_operational(*args, **kwargs):
        raise OperationalError("stmt", {}, Exception("db down"))

    db.commit = raise_operational

    current_user = MagicMock()
    current_user.id = uuid.uuid4()

    role_in = RoleCreate(name="test_role", scope="project", workspace_id=uuid.uuid4())

    with patch.object(
        rbac_manager, "_check_workspace_admin_access", new=AsyncMock(return_value=True)
    ):
        with pytest.raises(HTTPException) as exc:
            await rbac_manager.create_role(db, role_in, current_user)
    assert exc.value.status_code == 503


# rbac_manager.create_role — generic Exception path (lines 160-162)
@pytest.mark.asyncio
async def test_rbac_create_role_generic_exception():
    from app.modules.rbac.manager import rbac_manager
    from app.modules.rbac.schemas import RoleCreate

    db = AsyncMock()
    db.add = MagicMock()
    db.rollback = AsyncMock()

    async def raise_generic(*args, **kwargs):
        raise RuntimeError("unexpected")

    db.commit = raise_generic

    current_user = MagicMock()
    current_user.id = uuid.uuid4()

    role_in = RoleCreate(name="other_role", scope="project", workspace_id=uuid.uuid4())

    with patch.object(
        rbac_manager, "_check_workspace_admin_access", new=AsyncMock(return_value=True)
    ):
        with pytest.raises(RuntimeError):
            await rbac_manager.create_role(db, role_in, current_user)
