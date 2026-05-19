# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Regression: a stalled SSE stream must reconnect, not hang forever.

Before the fix, `subscribe_room` used `httpx.AsyncClient(timeout=None)`, so a
half-open connection (peer/NAT/LB dropped it without a FIN) left
`aiter_text()` blocked forever while the daemon still reported the room
"connected" — silently deaf, no reconnect. The read timeout (~3× the
backend's 15s keep-alive) turns that into an `httpx.ReadTimeout` that drives
a reconnect.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from mycelium.daemon import dispatch
from mycelium.daemon.state import DaemonState


def test_read_timeout_is_bounded_and_above_keepalive() -> None:
    """The invariant the fix rests on. Guards against a revert to
    `timeout=None` or a read timeout below the keep-alive cadence (which
    would make a healthy idle stream flap)."""
    assert dispatch._SSE_READ_TIMEOUT_S is not None
    assert dispatch._SSE_READ_TIMEOUT_S > dispatch._SSE_KEEPALIVE_S
    assert dispatch._SSE_CONNECT_TIMEOUT_S > 0


def test_stalled_stream_reconnects(monkeypatch: pytest.MonkeyPatch) -> None:
    state = DaemonState()
    room = "r1"

    class FakeResp:
        status_code = 200

        async def aiter_text(self):
            # Half-open connection: no bytes ever arrive. httpx would raise
            # ReadTimeout here once the bounded read timeout elapses.
            raise httpx.ReadTimeout("simulated stalled connection")
            yield  # noqa: unreachable — makes this an async generator

    class FakeStreamCM:
        async def __aenter__(self):
            return FakeResp()

        async def __aexit__(self, *_a):
            return False

    class FakeClient:
        def __init__(self, *_a, **kw):
            # Assert the bug can't come back: the client must be bounded.
            t = kw.get("timeout")
            assert t is not None, "AsyncClient must not use timeout=None"
            assert t.read == dispatch._SSE_READ_TIMEOUT_S

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        def stream(self, *_a, **_kw):
            return FakeStreamCM()

    monkeypatch.setattr(dispatch.httpx, "AsyncClient", FakeClient)

    # Break the reconnect loop after the first retry backoff so the test is
    # bounded — and prove the loop actually reaches the retry (i.e. it
    # recovered from the stall rather than propagating / hanging).
    async def fake_sleep(_seconds: float) -> None:
        state.stopping.set()

    monkeypatch.setattr(dispatch.asyncio, "sleep", fake_sleep)

    config = SimpleNamespace(server=SimpleNamespace(api_url="http://hub:8000"))
    daemon_cfg = SimpleNamespace(depth_cap=5, claude_binary="claude")

    async def run() -> None:
        await asyncio.wait_for(
            dispatch.subscribe_room(
                config=config,  # type: ignore[arg-type]
                daemon_cfg=daemon_cfg,  # type: ignore[arg-type]
                state=state,
                room_name=room,
            ),
            timeout=5.0,  # if it hangs, fail loudly instead of blocking CI
        )

    asyncio.run(run())

    # Recovered: classified as a stall, room not left "connected", returned.
    assert state.last_error is not None
    assert state.last_error["where"] == f"sse_stalled[{room}]"
    assert room not in state.rooms_connected
