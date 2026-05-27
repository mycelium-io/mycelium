# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

from collections.abc import AsyncGenerator
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import settings
from .models import Base

parsed_db_url = urlparse(settings.DATABASE_URL)

if parsed_db_url.scheme.startswith("postgresql") and "+" not in parsed_db_url.scheme:
    async_db_connection_url = (
        f"postgresql+asyncpg://{parsed_db_url.username}:{parsed_db_url.password}@"
        f"{parsed_db_url.hostname}{':' + str(parsed_db_url.port) if parsed_db_url.port else ''}"
        f"{parsed_db_url.path}"
    )
else:
    async_db_connection_url = settings.DATABASE_URL

_engine_kwargs: dict[str, object] = {"pool_recycle": 1800}
if not async_db_connection_url.startswith("sqlite"):
    _engine_kwargs.update(pool_size=5, max_overflow=10, pool_timeout=30)

engine = create_async_engine(async_db_connection_url, **_engine_kwargs)


async_session_maker = async_sessionmaker(engine, expire_on_commit=settings.EXPIRE_ON_COMMIT)


async def create_db_and_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session
