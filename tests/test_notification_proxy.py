"""Tests for the notification-service proxy: auth header, no double push, error mapping."""

import uuid
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import HTTPException

from app.modules.notifications import service as notif_svc


def _client(status=200, payload=None, seen=None):
    """A fake httpx.AsyncClient class that records its constructor kwargs."""
    seen = seen if seen is not None else {}

    class FakeClient:
        def __init__(self, **kwargs):
            seen.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def _respond(self, method, url, **kwargs):
            return httpx.Response(
                status,
                json=payload if payload is not None else {},
                request=httpx.Request(method, url),
            )

        async def get(self, url, **kwargs):
            return await self._respond("GET", url, **kwargs)

        async def patch(self, url, **kwargs):
            return await self._respond("PATCH", url, **kwargs)

    return FakeClient


@pytest.mark.asyncio
async def test_requests_carry_the_internal_token():
    seen = {}
    with (
        patch.object(notif_svc, "_HEADERS", {"X-Internal-Token": "secret"}),
        patch.object(notif_svc.httpx, "AsyncClient", _client(200, {"count": 3}, seen)),
    ):
        assert await notif_svc.get_unread_count(None, uuid.uuid4()) == 3
    assert seen["headers"] == {"X-Internal-Token": "secret"}


@pytest.mark.asyncio
async def test_mark_read_missing_notification_is_false():
    with patch.object(notif_svc.httpx, "AsyncClient", _client(404)):
        assert await notif_svc.mark_read(None, uuid.uuid4(), uuid.uuid4()) is False


@pytest.mark.asyncio
async def test_mark_read_success():
    with patch.object(
        notif_svc.httpx, "AsyncClient", _client(200, {"id": str(uuid.uuid4())})
    ):
        assert await notif_svc.mark_read(None, uuid.uuid4(), uuid.uuid4()) is True


@pytest.mark.asyncio
async def test_mark_read_service_error_is_503():
    with patch.object(notif_svc.httpx, "AsyncClient", _client(500)):
        with pytest.raises(HTTPException) as exc:
            await notif_svc.mark_read(None, uuid.uuid4(), uuid.uuid4())
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_create_and_push_does_not_push_to_redis_itself():
    """The worker pushes after saving; pushing here as well delivered everything twice."""
    with (
        patch.object(notif_svc, "_publish_notification_sync") as publish,
        patch.object(notif_svc, "push_via_redis", new_callable=AsyncMock) as redis_push,
    ):
        payload = await notif_svc.create_and_push(
            None, user_id=uuid.uuid4(), title_key="k", event_type="project.member_added"
        )
    publish.assert_called_once()
    redis_push.assert_not_awaited()
    assert payload["event"] == "project.member_added"


def test_list_rejects_invalid_limit():
    from fastapi.testclient import TestClient

    from app.main import app
    from app.modules.auth.dependencies import get_current_active_user

    app.dependency_overrides[get_current_active_user] = lambda: type(
        "U", (), {"id": uuid.uuid4()}
    )()
    try:
        client = TestClient(app)
        assert client.get("/api/v1/notifications?limit=0").status_code == 422
        assert client.get("/api/v1/notifications?limit=101").status_code == 422
        assert client.get("/api/v1/notifications?offset=-1").status_code == 422
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
