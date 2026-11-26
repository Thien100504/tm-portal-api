import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.main import app


@pytest.mark.asyncio
async def test_version_is_public_and_matches_the_setting(monkeypatch):
    monkeypatch.setattr(get_settings(), "APP_VERSION", "v9.9.9")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/v1/version")
    assert resp.status_code == 200
    assert resp.json() == {"version": "v9.9.9"}
