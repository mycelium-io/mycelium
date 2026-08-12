# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Connector reliability: idle keepalive + self-rejoin announce.

SLIM reaps a group member after ~30s of silence (3 missed heartbeats), which
would drop an idle-but-connected agent mid-coordination. The connector publishes
a keepalive well inside that window, and announces itself on each (re)connect so a
slept/dropped member rejoins without a fresh @mention. These pin the message
shape + skip semantics node-free.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import pytest

from mycelium.daemon import connector
from mycelium.engine.runtime import EngineDrive
from mycelium.slim import l9, member


def _keepalive(sender: str = "growth") -> dict:
    return l9.build_reply_content(
        sender=sender,
        recipients=[],
        episode="urn:ioc:mycelium:episode:r:live",
        parents=[],
        topic="urn:concept:mycelium:r",
        text="",
        payload_type="keepalive",
    )


# ── keepalive loop ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_keepalive_loop_publishes_ping(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(member, "KEEPALIVE_INTERVAL_S", 0.01)
    published: list[dict] = []

    async def publish(c: dict) -> None:
        published.append(c)

    stopping = asyncio.Event()
    task = asyncio.create_task(member.keepalive_loop(publish, "r", "agent-a", stopping))
    await asyncio.sleep(0.05)
    stopping.set()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    assert published, "keepalive loop should have published at least one ping"
    ping = published[0]
    assert l9.payload_type_of(ping) == member.KEEPALIVE_TYPE
    assert l9.sender_of(ping) == "agent-a"


@pytest.mark.asyncio
async def test_keepalive_loop_stops_on_publish_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(member, "KEEPALIVE_INTERVAL_S", 0.01)

    async def publish(_c: dict) -> None:
        raise RuntimeError("session dropping")

    # A failed keepalive ends the loop cleanly (the message stream owns reconnect)
    # — it must return, not raise or hang.
    await asyncio.wait_for(member.keepalive_loop(publish, "r", "a", asyncio.Event()), timeout=1.0)


# ── keepalive never wakes or drives ──────────────────────────────────────────


def test_keepalive_does_not_wake() -> None:
    assert connector.should_wake(_keepalive(), "agent-a") is False


@pytest.mark.asyncio
async def test_drive_ignores_keepalive_then_reads_reply() -> None:
    """A keepalive from the addressed agent must NOT be misread as its reply — the
    drive skips it and waits for the real prose."""

    class _Channel:
        def __init__(self) -> None:
            self.published: list[dict] = []
            self._inbox: list[dict] = []

        async def publish(self, content: dict[str, Any]) -> None:
            self.published.append(content)
            if (l9.payload_data_of(content) or {}).get("action") == "position":
                for handle in l9.recipients_of(content):
                    # A keepalive lands first (must be skipped), then the real reply.
                    self._inbox.append(_keepalive(handle))
                    self._inbox.append(
                        l9.build_reply_content(
                            sender=handle,
                            recipients=["mediator-1"],
                            episode="ep",
                            parents=[],
                            text="I accept 30.",
                            payload_type="reply",
                            payload_data={"action": "reply"},
                        )
                    )

        async def receive(self, *, timeout_s: float) -> dict[str, Any] | None:
            return self._inbox.pop(0) if self._inbox else None

    def brain(prompt: str, *, system: str = "", temperature: float = 0.3) -> str:
        import json

        if "identify the negotiable ISSUES" in prompt:
            return json.dumps({"issues": [{"name": "cap", "options": ["25", "30", "35"]}]})
        if "Interpret @" in prompt:
            if '"action":"counter"' in prompt:
                return json.dumps({"action": "counter", "offer": {"cap": "30"}})
            return json.dumps({"action": "accept"})
        return "lock 30."

    drive = EngineDrive(
        engine_handle="mediator-1",
        room="r",
        episode="ep",
        topic="t",
        channel=_Channel(),
        brain=brain,
        max_steps=12,
        round_timeout_s=2.0,
    )
    assignments = await drive.run(["growth", "risk"], {"growth": "35", "risk": "25"})
    # Converged on the real reply, not the empty keepalive (which would read as reject).
    assert assignments == {"cap": "30"}


# ── self-rejoin announce ─────────────────────────────────────────────────────


class _FakeResp:
    def __init__(self, boom: bool = False) -> None:
        self._boom = boom

    def raise_for_status(self) -> None:
        if self._boom:
            raise RuntimeError("500")


class _FakeClient:
    def __init__(self, calls: list[tuple[str, dict]], boom: bool = False) -> None:
        self._calls = calls
        self._boom = boom

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *_a: object) -> bool:
        return False

    async def post(self, url: str, json: dict | None = None) -> _FakeResp:
        self._calls.append((url, json or {}))
        return _FakeResp(self._boom)


@pytest.mark.asyncio
async def test_announce_presence_posts_join(monkeypatch: pytest.MonkeyPatch) -> None:
    from mycelium.config import MyceliumConfig, ServerConfig

    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(connector.httpx, "AsyncClient", lambda **_k: _FakeClient(calls))
    cfg = MyceliumConfig(server=ServerConfig(api_url="http://localhost:8000"))

    await connector.announce_presence(cfg, "myroom", "agent-a")

    assert calls == [
        ("http://localhost:8000/api/rooms/myroom/sessions", {"agent_handle": "agent-a"})
    ]


@pytest.mark.asyncio
async def test_announce_presence_is_best_effort(monkeypatch: pytest.MonkeyPatch) -> None:
    from mycelium.config import MyceliumConfig

    monkeypatch.setattr(connector.httpx, "AsyncClient", lambda **_k: _FakeClient([], boom=True))
    # A backend error must not raise — the connector still falls back to waiting.
    await connector.announce_presence(MyceliumConfig(), "r", "a")
