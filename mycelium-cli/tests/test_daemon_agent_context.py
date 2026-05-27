# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Tests for the daemon's room-plan briefing: render + per-room fetch cache."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest

from mycelium.daemon import dispatch


@pytest.fixture(autouse=True)
def _clear_cache() -> Iterator[None]:
    dispatch._agent_context_cache.clear()
    yield
    dispatch._agent_context_cache.clear()


# ── _render_plan_block ───────────────────────────────────────────────────────


def test_render_plan_block_empty_when_no_context() -> None:
    assert dispatch._render_plan_block(None, "") == ""
    assert dispatch._render_plan_block("", "2026-05-21T18:00:00+00:00") == ""


def test_render_plan_block_includes_context_and_staleness_hint() -> None:
    block = dispatch._render_plan_block("Open tasks (1):\n- [tasks] x", "2026-05-21T18:00:00+00:00")
    assert "## Room plan" in block
    assert "Open tasks (1)" in block
    assert "mycelium plan tasks" in block  # the live-state escape hatch


# ── _humanize_age ────────────────────────────────────────────────────────────


def test_humanize_age_empty_or_bad() -> None:
    assert dispatch._humanize_age("") == ""
    assert dispatch._humanize_age("not-a-timestamp") == ""


def test_humanize_age_just_now() -> None:
    now = datetime.now(UTC).isoformat()
    assert "just now" in dispatch._humanize_age(now)


def test_humanize_age_minutes() -> None:
    ten_min_ago = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    assert "~10 min ago" in dispatch._humanize_age(ten_min_ago)


# ── _fetch_agent_context cache ───────────────────────────────────────────────


class _FakeResp:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    """Stand-in for httpx.AsyncClient that counts GETs."""

    calls = 0

    def __init__(self, *_a, **_kw) -> None:
        pass

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *_exc) -> None:
        return None

    async def get(self, _url: str, *, params: dict) -> _FakeResp:  # noqa: ARG002
        type(self).calls += 1
        return _FakeResp({"context": "ctx", "generated_at": "2026-05-21T18:00:00+00:00"})


def test_fetch_agent_context_caches_within_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeClient.calls = 0
    monkeypatch.setattr(dispatch.httpx, "AsyncClient", _FakeClient)

    async def run() -> None:
        a = await dispatch._fetch_agent_context("http://hub", "room-a", "alpha")
        b = await dispatch._fetch_agent_context("http://hub", "room-a", "beta")
        assert a == ("ctx", "2026-05-21T18:00:00+00:00")
        assert b == a

    asyncio.run(run())
    assert _FakeClient.calls == 1  # second call served from cache


def test_fetch_agent_context_separate_per_room(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeClient.calls = 0
    monkeypatch.setattr(dispatch.httpx, "AsyncClient", _FakeClient)

    async def run() -> None:
        await dispatch._fetch_agent_context("http://hub", "room-a", "alpha")
        await dispatch._fetch_agent_context("http://hub", "room-b", "alpha")

    asyncio.run(run())
    assert _FakeClient.calls == 2


def test_fetch_agent_context_swallows_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BoomClient(_FakeClient):
        async def get(self, _url: str, *, params: dict) -> _FakeResp:  # noqa: ARG002
            raise RuntimeError("network down")

    monkeypatch.setattr(dispatch.httpx, "AsyncClient", _BoomClient)

    async def run() -> None:
        result = await dispatch._fetch_agent_context("http://hub", "room-x", "alpha")
        assert result == (None, "")  # never raises, block omitted

    asyncio.run(run())
