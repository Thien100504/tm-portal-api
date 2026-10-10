"""
Pytest Configuration & Fixtures for the Task Manager Backend.

Provides shared fixtures:
- async client for FastAPI testing
- test database session
- sample data factories
"""

import asyncio
from collections.abc import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings
from app.database import get_db
from app.main import app
from app.models.base import Base

# ── pytest-asyncio configuration ─────────────────────────────────────


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create a shared event loop for the whole test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ── Test Database ─────────────────────────────────────────────────────

TEST_DATABASE_URL = get_settings().DATABASE_URL + "_test"

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
)

TestSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Fixture providing a database session for each test.

    Creates tables before the test and drops them afterwards.
    """
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestSessionLocal() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function")
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """
    Fixture providing an async HTTP client for testing API endpoints.

    Overrides the get_db dependency to use the test database session.
    """

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ── Sample Data Fixtures ──────────────────────────────────────────────
# TODO: Add sample data fixtures once concrete models are implemented
# Example:
#
# @pytest_asyncio.fixture
# async def sample_user(db_session: AsyncSession) -> User:
#     user = User(email="test@example.com", hashed_password="...")
#     db_session.add(user)
#     await db_session.commit()
#     return user
