# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Shared test fixtures.

No database (SLIM-native rebuild, Step 1): the store is markdown files + a local
JSONL index under a temp ``MYCELIUM_DATA_DIR``, and messages/presence live in the
in-process ``local_state`` shim which we reset per test.
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import local_state


@pytest.fixture(autouse=True)
def _set_data_dir(tmp_path, monkeypatch):
    """Use a temp directory for .mycelium/ data in all tests."""
    monkeypatch.setattr("app.config.settings.MYCELIUM_DATA_DIR", str(tmp_path / ".mycelium"))


@pytest.fixture(autouse=True)
def _reset_local_state():
    """Isolate the in-memory message/presence/subscription shim per test."""
    local_state.clear_all()
    yield
    local_state.clear_all()


@pytest_asyncio.fixture()
async def client():
    """AsyncClient wired to the FastAPI app (no database)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
