"""
Destructive assistant actions wait for the user's own click.

A delete asked through the chat is stored here (Redis, 10 minutes) and the UI
shows a confirmation card. Only POST /chat/sessions/{id}/actions/{token} from
the same user and session carries it out, so neither the model nor text planted
in project data can delete anything by itself.
"""

import json
import secrets

import redis.asyncio as aioredis

from app.config import get_settings

TTL_SECONDS = 600


def _key(token: str) -> str:
    return f"ai:pending:{token}"


async def save(action: dict) -> str:
    """Store the action; returns the one-time token for the confirmation card."""
    token = secrets.token_urlsafe(18)
    client = aioredis.from_url(get_settings().REDIS_URL)
    try:
        await client.set(_key(token), json.dumps(action), ex=TTL_SECONDS)
    finally:
        await client.aclose()
    return token


async def take(token: str) -> dict | None:
    """Read and remove the action in one step, so a token works only once."""
    client = aioredis.from_url(get_settings().REDIS_URL)
    try:
        raw = await client.getdel(_key(token))
    finally:
        await client.aclose()
    return json.loads(raw) if raw else None
