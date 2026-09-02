# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Shared test fixtures.

No database: the store is markdown files + a local
JSONL index under a temp ``MYCELIUM_DATA_DIR``, and messages/presence live in the
in-process ``in_memory_store`` which we reset per test.
"""

import pytest
import pytest_asyncio
from fastapi import Request
from httpx import ASGITransport, AsyncClient

from app.config import PrincipalRole
from app.main import app
from app.services import a2a_activity, in_memory_store
from app.services.auth import Principal, auth_gate


@pytest.fixture(autouse=True)
def _set_data_dir(tmp_path, monkeypatch):
    """Use a temp directory for .mycelium/ data in all tests."""
    monkeypatch.setattr("app.config.settings.MYCELIUM_DATA_DIR", str(tmp_path / ".mycelium"))


@pytest.fixture(autouse=True)
def _reset_in_memory_store():
    """Isolate the in-memory message/presence/subscription store per test."""
    in_memory_store.clear_all()
    yield
    in_memory_store.clear_all()


@pytest.fixture(autouse=True)
def _reset_a2a_activity():
    """Isolate the in-process A2A bridge telemetry per test."""
    a2a_activity.clear()
    yield
    a2a_activity.clear()


@pytest_asyncio.fixture()
async def client():
    """AsyncClient wired to the FastAPI app (no database)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture
def as_principal():
    """Act as a verified principal for the rest of the test.

    Overrides the gate itself, so the routes see exactly what a validated token
    leaves behind: a ``Principal`` on ``request.state``. Call with ``None`` to
    assert the anonymous branch through the same wiring. Signing a real token is
    ``test_auth_gate``'s subject, not every caller's.
    """

    def _act_as(handle: str | None, *, role: PrincipalRole = "agent") -> None:
        principal = (
            None
            if handle is None
            else Principal(
                subject=handle,
                handle=handle,
                role=role,
                issuer="https://idp.test/realms/mycelium",
            )
        )

        async def _fake_gate(request: Request) -> Principal | None:
            request.state.principal = principal
            return principal

        app.dependency_overrides[auth_gate] = _fake_gate

    yield _act_as
    app.dependency_overrides.pop(auth_gate, None)
