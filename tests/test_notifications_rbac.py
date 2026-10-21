"""Tests for notifications/service.py and rbac/manager.py."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─── Notification service (mock httpx) ───────────────────────────────────────


@pytest.mark.asyncio
async def test_get_for_user_success():
    from app.modules.notifications import service as svc

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = [{"id": "1", "title": "Hello"}]

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await svc.get_for_user(None, uuid.uuid4())

    assert len(result) == 1
    assert result[0]["title"] == "Hello"


@pytest.mark.asyncio
async def test_get_for_user_service_down():
    from fastapi import HTTPException
    from app.modules.notifications import service as svc

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=Exception("connection error"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(HTTPException) as exc:
            await svc.get_for_user(None, uuid.uuid4())
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_get_unread_count_success():
    from app.modules.notifications import service as svc

    mock_response = MagicMock()
    mock_response.json.return_value = {"count": 5}

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await svc.get_unread_count(None, uuid.uuid4())

    assert result == 5


@pytest.mark.asyncio
async def test_get_unread_count_service_down():
    from fastapi import HTTPException
    from app.modules.notifications import service as svc

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=Exception("timeout"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(HTTPException) as exc:
            await svc.get_unread_count(None, uuid.uuid4())
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_mark_read_success():
    from app.modules.notifications import service as svc

    mock_response = MagicMock()
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.patch = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await svc.mark_read(None, uuid.uuid4(), uuid.uuid4())

    assert result is True


@pytest.mark.asyncio
async def test_mark_read_service_down():
    from fastapi import HTTPException
    from app.modules.notifications import service as svc

    mock_client = AsyncMock()
    mock_client.patch = AsyncMock(side_effect=Exception("error"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(HTTPException) as exc:
            await svc.mark_read(None, uuid.uuid4(), uuid.uuid4())
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_mark_all_read_success():
    from app.modules.notifications import service as svc

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"marked_read": 3}

    mock_client = AsyncMock()
    mock_client.patch = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await svc.mark_all_read(None, uuid.uuid4())

    assert result == 3


@pytest.mark.asyncio
async def test_mark_all_read_service_down():
    from fastapi import HTTPException
    from app.modules.notifications import service as svc

    mock_client = AsyncMock()
    mock_client.patch = AsyncMock(side_effect=Exception("error"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(HTTPException) as exc:
            await svc.mark_all_read(None, uuid.uuid4())
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_create_and_push():
    from app.modules.notifications import service as svc

    with (
        patch("app.modules.notifications.service._publish_notification_sync"),
        patch(
            "fastapi.concurrency.run_in_threadpool", new_callable=AsyncMock
        ) as mock_threadpool,
        patch(
            "app.modules.notifications.service.push_via_redis", new_callable=AsyncMock
        ),
    ):
        mock_threadpool.return_value = None

        result = await svc.create_and_push(
            None,
            user_id=uuid.uuid4(),
            title="Test notification",
            event_type="task.created",
            message="A task was created",
            type="info",
        )

    assert result["title"] == "Test notification"
    assert "user_id" in result


@pytest.mark.asyncio
async def test_create_and_push_with_event_data():
    from app.modules.notifications import service as svc

    with (
        patch(
            "fastapi.concurrency.run_in_threadpool", new_callable=AsyncMock
        ) as mock_tp,
        patch(
            "app.modules.notifications.service.push_via_redis", new_callable=AsyncMock
        ),
    ):
        mock_tp.return_value = None

        result = await svc.create_and_push(
            None,
            user_id=uuid.uuid4(),
            title="Task done",
            event_data={"task_id": str(uuid.uuid4())},
            entity_type="task",
            entity_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
        )

    assert "data" in result
    assert result["entity_type"] == "task"


# ─── RBACManager.create_role ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rbac_create_role_no_workspace():
    from app.modules.rbac.manager import rbac_manager
    from app.modules.rbac.schemas import RoleCreate

    db = AsyncMock()
    user = MagicMock()
    user.id = uuid.uuid4()

    db.add = MagicMock()
    db.commit = AsyncMock()

    mock_role = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.first.return_value = mock_role
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    db.execute.return_value = mock_result

    role_in = RoleCreate(name="Developer", scope="project")
    await rbac_manager.create_role(db, role_in, user)

    db.add.assert_called_once()
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_rbac_create_role_integrity_error():
    from fastapi import HTTPException
    from app.modules.rbac.manager import rbac_manager
    from app.modules.rbac.schemas import RoleCreate
    from sqlalchemy.exc import IntegrityError

    db = AsyncMock()
    user = MagicMock()
    user.id = uuid.uuid4()
    db.add = MagicMock()
    db.commit = AsyncMock(side_effect=IntegrityError("dup", None, None))
    db.rollback = AsyncMock()

    role_in = RoleCreate(name="Duplicate", scope="project")
    with pytest.raises(HTTPException) as exc:
        await rbac_manager.create_role(db, role_in, user)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_rbac_create_role_operational_error():
    from fastapi import HTTPException
    from app.modules.rbac.manager import rbac_manager
    from app.modules.rbac.schemas import RoleCreate
    from sqlalchemy.exc import OperationalError

    db = AsyncMock()
    user = MagicMock()
    user.id = uuid.uuid4()
    db.add = MagicMock()
    db.commit = AsyncMock(side_effect=OperationalError("db down", None, None))
    db.rollback = AsyncMock()

    role_in = RoleCreate(name="Fail Role", scope="project")
    with pytest.raises(HTTPException) as exc:
        await rbac_manager.create_role(db, role_in, user)
    assert exc.value.status_code == 503


# ─── RBACManager.update_role ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rbac_update_role_not_found():
    from fastapi import HTTPException
    from app.modules.rbac.manager import rbac_manager
    from app.modules.rbac.schemas import RoleUpdate

    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)
    user = MagicMock()
    user.id = uuid.uuid4()

    with pytest.raises(HTTPException) as exc:
        await rbac_manager.update_role(db, uuid.uuid4(), RoleUpdate(name="X"), user)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_rbac_update_role_system_role():
    from fastapi import HTTPException
    from app.modules.rbac.manager import rbac_manager
    from app.modules.rbac.schemas import RoleUpdate

    db = AsyncMock()
    mock_role = MagicMock()
    mock_role.is_system_default = True
    db.scalar = AsyncMock(return_value=mock_role)
    user = MagicMock()

    with pytest.raises(HTTPException) as exc:
        await rbac_manager.update_role(db, uuid.uuid4(), RoleUpdate(name="X"), user)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_rbac_update_role_success():
    from app.modules.rbac.manager import rbac_manager
    from app.modules.rbac.schemas import RoleUpdate

    db = AsyncMock()
    mock_role = MagicMock()
    mock_role.is_system_default = False
    mock_role.workspace_id = None
    mock_role.name = "Old Name"
    mock_role.id = uuid.uuid4()
    db.scalar = AsyncMock(return_value=mock_role)
    db.commit = AsyncMock()

    updated_role = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.first.return_value = updated_role
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    db.execute.return_value = mock_result

    user = MagicMock()
    user.id = uuid.uuid4()

    await rbac_manager.update_role(db, uuid.uuid4(), RoleUpdate(name="New Name"), user)
    assert mock_role.name == "New Name"


# ─── RBACManager.delete_role ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rbac_delete_role_not_found():
    from fastapi import HTTPException
    from app.modules.rbac.manager import rbac_manager

    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)
    user = MagicMock()

    with pytest.raises(HTTPException) as exc:
        await rbac_manager.delete_role(db, uuid.uuid4(), user)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_rbac_delete_role_system_default():
    from fastapi import HTTPException
    from app.modules.rbac.manager import rbac_manager

    db = AsyncMock()
    mock_role = MagicMock()
    mock_role.is_system_default = True
    db.scalar = AsyncMock(return_value=mock_role)
    user = MagicMock()

    with pytest.raises(HTTPException) as exc:
        await rbac_manager.delete_role(db, uuid.uuid4(), user)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_rbac_delete_role_success():
    from app.modules.rbac.manager import rbac_manager

    db = AsyncMock()
    mock_role = MagicMock()
    mock_role.is_system_default = False
    mock_role.workspace_id = None
    mock_role.is_deleted = False
    db.scalar = AsyncMock(return_value=mock_role)
    db.commit = AsyncMock()
    user = MagicMock()
    user.id = uuid.uuid4()

    await rbac_manager.delete_role(db, uuid.uuid4(), user)
    assert mock_role.is_deleted is True
    db.commit.assert_called_once()
