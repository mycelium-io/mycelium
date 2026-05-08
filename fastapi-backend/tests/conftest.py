# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
Shared test fixtures.

Uses an in-memory SQLite DB so no Postgres is required.
Sets MYCELIUM_DATA_DIR to a temp directory for filesystem tests.
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import get_async_session
from app.main import app
from app.models import Base

TEST_DATABASE_URL = "sqlite+aiosqlite://"


@pytest.fixture(autouse=True)
def _set_data_dir(tmp_path, monkeypatch):
    """Use a temp directory for .mycelium/ data in all tests."""
    monkeypatch.setattr("app.config.settings.MYCELIUM_DATA_DIR", str(tmp_path / ".mycelium"))


@pytest_asyncio.fixture()
async def db_session():
    """Ephemeral in-memory SQLite session, schema created fresh per test."""
    engine = create_async_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})

    # SQLite enforces FK constraints only when PRAGMA foreign_keys=ON. Without
    # this the cascade-on-delete chain (room → coord_sessions → participants &
    # messages) wouldn't fire in tests, hiding regressions.
    @event.listens_for(engine.sync_engine, "connect")
    def _enable_sqlite_fk(dbapi_conn, _conn_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture()
async def client(db_session: AsyncSession):
    """AsyncClient wired to the FastAPI app, DB overridden to in-memory SQLite."""

    async def _override_db():
        yield db_session

    app.dependency_overrides[get_async_session] = _override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
