import os

os.environ["APP_DATABASE_URL"] = "sqlite+aiosqlite:///./test.db"
os.environ["APP_SECRET_KEY"] = "test-secret-key-that-is-long-enough"

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from services.core.app.db import engine
from services.core.app.main import app
from services.core.app.models import Base


@pytest_asyncio.fixture(autouse=True)
async def database():
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as value:
        yield value


@pytest_asyncio.fixture
async def auth(client):
    response = await client.post("/api/v1/auth/register", json={"email": "moss@example.com", "password": "correct-horse-battery"})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}

