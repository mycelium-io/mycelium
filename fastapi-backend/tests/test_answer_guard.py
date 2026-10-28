# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The guard every test runs under: a response model that drops a key its
handler returns fails the test that reached the route (``answer_guard``)."""

from __future__ import annotations

import sys
import types

import pytest
from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel

from tests import answer_guard


class _Said(BaseModel):
    handle: str


def _app() -> tuple[FastAPI, types.ModuleType]:
    """An app with one route whose model is missing a key its handler returns,
    defined in a module of its own and mounted through a router with a prefix,
    as the hub's routes are (FastAPI serves an included router's routes from
    copies, so a guard on the original alone would see nothing)."""
    module = types.ModuleType("tests._guarded_route")

    async def members() -> dict:
        return {"handle": "scout", "can_reply": False}

    members.__module__ = module.__name__
    module.members = members  # type: ignore[attr-defined]
    sys.modules[module.__name__] = module
    router = APIRouter()
    router.get("/members", response_model=_Said)(members)
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app, module


def test_the_guard_finds_a_dropped_key_nested_in_lists() -> None:
    raw = {"members": [{"handle": "a", "can_reply": True}]}
    sent = {"members": [{"handle": "a"}]}
    assert list(answer_guard.dropped(raw, sent)) == ["members[0].can_reply"]


async def test_a_route_called_over_http_fails_on_a_dropped_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _ = _app()
    answer_guard.install(app, monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with pytest.raises(AssertionError, match="can_reply"):
            await client.get("/api/members")


async def test_a_route_called_as_a_function_fails_on_a_dropped_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, module = _app()
    answer_guard.install(app, monkeypatch)
    with pytest.raises(AssertionError, match="can_reply"):
        await module.members()


def test_a_route_that_drops_on_purpose_is_declared(monkeypatch: pytest.MonkeyPatch) -> None:
    app, module = _app()
    monkeypatch.setitem(answer_guard.DROPS_ON_PURPOSE, "test_answer_guard.py:members", "a test")
    answer_guard.install(app, monkeypatch)
    import asyncio

    assert asyncio.run(module.members()) == {"handle": "scout", "can_reply": False}
