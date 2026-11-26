from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.request_context import client_id_var, parse_client_id
from app.middleware.request_id import RequestIDMiddleware


@pytest.mark.parametrize(
    "value, expected",
    [
        (
            "3f2b9c1e-8d4a-4f6b-9a2e-1c7d5e8f0a3b",
            "3f2b9c1e-8d4a-4f6b-9a2e-1c7d5e8f0a3b",
        ),
        ("tab1", "tab1"),
        (None, None),
        ("", None),
        ("has space", None),
        ("<script>", None),
        ("a" * 65, None),
    ],
)
def test_parse_client_id(value, expected):
    assert parse_client_id(value) == expected


def _ctx():
    ctx = MagicMock()
    ctx.event_type = "task.updated"
    ctx.task.project_id = "project-1"
    ctx.task.id = "task-1"
    ctx.actor.id = "user-1"
    return ctx


@pytest.mark.asyncio
async def test_task_broadcast_carries_the_sending_tab():
    from app.events.task_events import WebSocketHandler

    token = client_id_var.set("tab-a")
    try:
        with patch("app.events.task_events.manager") as mgr:
            mgr.broadcast_to_project = AsyncMock()
            await WebSocketHandler().handle(_ctx())
    finally:
        client_id_var.reset(token)

    payload = mgr.broadcast_to_project.call_args[0][1]
    assert payload["client_id"] == "tab-a"
    assert payload["actor_id"] == "user-1"


@pytest.mark.asyncio
async def test_task_broadcast_without_client_id():
    from app.events.task_events import WebSocketHandler

    with patch("app.events.task_events.manager") as mgr:
        mgr.broadcast_to_project = AsyncMock()
        await WebSocketHandler().handle(_ctx())

    assert "client_id" not in mgr.broadcast_to_project.call_args[0][1]


@pytest.mark.asyncio
async def test_middleware_exposes_client_id_to_the_request():
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)

    @app.get("/whoami")
    async def whoami():
        return {"client_id": client_id_var.get()}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        ok = await client.get("/whoami", headers={"X-Client-Id": "tab-b"})
        bad = await client.get("/whoami", headers={"X-Client-Id": "not valid!"})
        none = await client.get("/whoami")

    assert ok.json() == {"client_id": "tab-b"}
    assert bad.json() == {"client_id": None}
    assert none.json() == {"client_id": None}
    assert client_id_var.get() is None
