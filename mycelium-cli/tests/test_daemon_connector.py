# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Daemon SLIM connector — wake path, reply shape, gates, and control verbs.

The merge gate for Step 5 (no SLIM node, ``claude`` mocked at the integration
boundary). Pins that an inbound L9 message addressed to an owned handle wakes a
cold spawn and its reply is published as a valid ``exchange`` parented on the
message that woke it; that a message addressed elsewhere / the agent's own reply
does not; and that the budget / depth / allow_from gates, the per-handle serial
lock, and the ``abort`` / ``status`` control verbs survive the transport swap.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from mycelium.config import MyceliumConfig, ServerConfig
from mycelium.daemon import config as daemon_config
from mycelium.daemon import connector
from mycelium.daemon.config import DaemonConfig
from mycelium.daemon.state import DaemonState, RunningProc
from mycelium.integrations._spawn_common import SpawnResult
from mycelium.protocol import AgentManifest
from mycelium.slim import l9


@pytest.fixture(autouse=True)
def _tmp_daemon_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(daemon_config, "daemon_config_path", lambda: tmp_path / "daemon.toml")


def _config() -> MyceliumConfig:
    return MyceliumConfig(server=ServerConfig(api_url="http://localhost:8000"))


def _manifest(handle: str = "agent-a", **kw: Any) -> AgentManifest:
    return AgentManifest(
        handle=handle,
        adapter="claude_code",
        cwd=kw.get("cwd", "/tmp/x"),
        description="room participant",
        allow_from=kw.get("allow_from", []),
        budget_usd_per_month=kw.get("budget_usd_per_month", 0.0),
    )


def _inbound(
    *,
    sender: str = "human",
    recipients: list[str] | None = None,
    text: str = "@agent-a hello",
    message_id: str = "woke-1",
) -> dict:
    return l9.build_reply_content(
        sender=sender,
        recipients=["agent-a"] if recipients is None else recipients,
        episode="urn:ioc:mycelium:episode:r:live",
        parents=[],
        topic="urn:concept:mycelium:r",
        text=text,
        message_id=message_id,
    )


def _patch_spawn(
    monkeypatch: pytest.MonkeyPatch, *, result: SpawnResult | None = None
) -> MagicMock:
    """Patch the connector's integration boundary; return the mocked ``spawn``."""
    spawn = AsyncMock(
        return_value=result
        or SpawnResult(ok=True, final_message="done", transcript="", cost_usd=0.01, duration_s=0.1)
    )
    integration = MagicMock(lifecycle="cold_spawn", spawn=spawn)
    monkeypatch.setattr(connector, "get_integration", lambda _adapter: integration)
    monkeypatch.setattr(connector, "_fetch_agent_context", AsyncMock(return_value=(None, "")))
    monkeypatch.setattr(connector, "_post_log", AsyncMock(return_value=None))
    monkeypatch.setattr(connector, "load_notes", lambda _room, _handle: "")
    return spawn


async def _run(state: DaemonState, published: list[dict], content: dict, **overrides: Any) -> None:
    async def publish(c: dict) -> None:
        published.append(c)

    kwargs: dict[str, Any] = {
        "config": _config(),
        "daemon_cfg": DaemonConfig(),
        "state": state,
        "room": "r",
        "handle": "agent-a",
        "content": content,
        "publish": publish,
    }
    kwargs.update(overrides)
    await connector.handle_inbound(**kwargs)


# ── should_wake (pure) ────────────────────────────────────────────────────────


def test_wake_on_recipient_match() -> None:
    assert connector.should_wake(_inbound(recipients=["agent-a"], text="hi"), "agent-a")


def test_wake_on_at_mention_even_without_recipient() -> None:
    assert connector.should_wake(_inbound(recipients=["other"], text="@agent-a do it"), "agent-a")


def test_no_wake_on_own_reply() -> None:
    assert not connector.should_wake(_inbound(sender="agent-a", recipients=["human"]), "agent-a")


def test_no_wake_when_addressed_elsewhere() -> None:
    assert not connector.should_wake(_inbound(recipients=["agent-b"], text="hello all"), "agent-a")


def test_no_wake_on_non_exchange_envelope() -> None:
    content = _inbound(recipients=["agent-a"])
    content["l9"]["header"]["kind"] = "commit"
    assert not connector.should_wake(content, "agent-a")


# ── Wake path + reply shape ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wake_spawns_and_publishes_valid_l9_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    spawn = _patch_spawn(monkeypatch)
    monkeypatch.setattr(connector, "load_manifest", lambda _room, _handle: _manifest())
    state = DaemonState()
    published: list[dict] = []

    await _run(state, published, _inbound(message_id="woke-1"))

    spawn.assert_awaited_once()
    assert len(published) == 1
    reply = published[0]
    # Reply is a valid exchange authored by the handle, parented on the waker.
    assert l9.kind_of(reply) == "exchange"
    assert l9.sender_of(reply) == "agent-a"
    assert l9.recipients_of(reply) == ["human"]
    assert reply["l9"]["header"]["message"]["parents"] == ["woke-1"]
    assert l9.human_text_of(reply) == "done"


@pytest.mark.asyncio
async def test_addressed_elsewhere_does_not_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
    spawn = _patch_spawn(monkeypatch)
    monkeypatch.setattr(connector, "load_manifest", lambda _room, _handle: _manifest())
    state = DaemonState()
    published: list[dict] = []

    await _run(state, published, _inbound(recipients=["agent-b"], text="hello all"))

    spawn.assert_not_awaited()
    assert published == []


@pytest.mark.asyncio
async def test_own_reply_does_not_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
    spawn = _patch_spawn(monkeypatch)
    monkeypatch.setattr(connector, "load_manifest", lambda _room, _handle: _manifest())
    state = DaemonState()
    published: list[dict] = []

    await _run(state, published, _inbound(sender="agent-a", recipients=["human"]))

    spawn.assert_not_awaited()
    assert published == []


# ── Gates ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_budget_gate_blocks_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
    spawn = _patch_spawn(monkeypatch)
    monkeypatch.setattr(
        connector, "load_manifest", lambda _room, _handle: _manifest(budget_usd_per_month=5.0)
    )
    state = DaemonState()
    ym = datetime.now(UTC).strftime("%Y-%m")
    state.budget_used_usd[("agent-a", ym)] = 10.0
    published: list[dict] = []

    await _run(state, published, _inbound())

    spawn.assert_not_awaited()
    assert published == []


@pytest.mark.asyncio
async def test_depth_gate_blocks_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
    spawn = _patch_spawn(monkeypatch)
    monkeypatch.setattr(connector, "load_manifest", lambda _room, _handle: _manifest())
    state = DaemonState()
    # Fill the sender's dispatch bucket to the cap so the next is refused.
    daemon_cfg = DaemonConfig(depth_cap=1)
    state.recent_dispatches["human"].append(time.monotonic())
    published: list[dict] = []

    await _run(state, published, _inbound(), daemon_cfg=daemon_cfg)

    spawn.assert_not_awaited()
    assert published == []


@pytest.mark.asyncio
async def test_allow_from_gate_blocks_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
    spawn = _patch_spawn(monkeypatch)
    monkeypatch.setattr(
        connector, "load_manifest", lambda _room, _handle: _manifest(allow_from=["someone-else"])
    )
    state = DaemonState()
    published: list[dict] = []

    await _run(state, published, _inbound())

    spawn.assert_not_awaited()
    assert published == []


# ── Control verbs ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_abort_terminates_running_and_replies(monkeypatch: pytest.MonkeyPatch) -> None:
    spawn = _patch_spawn(monkeypatch)
    monkeypatch.setattr(connector, "load_manifest", lambda _room, _handle: _manifest())
    state = DaemonState()
    proc = MagicMock()
    state.running["agent-a"] = RunningProc(
        process=proc, started_at=time.monotonic(), prompt="p", sender="human", room="r"
    )
    published: list[dict] = []

    await _run(state, published, _inbound(text="@agent-a abort"))

    proc.terminate.assert_called_once()
    spawn.assert_not_awaited()  # a control verb never cold-spawns
    assert len(published) == 1
    assert "aborted" in l9.human_text_of(published[0])


@pytest.mark.asyncio
async def test_status_replies_without_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
    spawn = _patch_spawn(monkeypatch)
    monkeypatch.setattr(connector, "load_manifest", lambda _room, _handle: _manifest())
    state = DaemonState()
    published: list[dict] = []

    await _run(state, published, _inbound(text="@agent-a status"))

    spawn.assert_not_awaited()
    assert len(published) == 1
    assert "idle" in l9.human_text_of(published[0])


# ── Per-handle serial lock ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_per_handle_lock_serializes_spawns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(connector, "load_manifest", lambda _room, _handle: _manifest())
    monkeypatch.setattr(connector, "_fetch_agent_context", AsyncMock(return_value=(None, "")))
    monkeypatch.setattr(connector, "_post_log", AsyncMock(return_value=None))
    monkeypatch.setattr(connector, "load_notes", lambda _room, _handle: "")

    in_flight = 0
    max_in_flight = 0

    async def _slow_spawn(*, request: Any) -> SpawnResult:  # noqa: ARG001
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.02)
        in_flight -= 1
        return SpawnResult(
            ok=True, final_message="done", transcript="", cost_usd=0.0, duration_s=0.0
        )

    integration = MagicMock(lifecycle="cold_spawn", spawn=_slow_spawn)
    monkeypatch.setattr(connector, "get_integration", lambda _adapter: integration)

    state = DaemonState()
    published: list[dict] = []
    await asyncio.gather(
        _run(state, published, _inbound(message_id="a")),
        _run(state, published, _inbound(message_id="b")),
    )

    assert max_in_flight == 1  # the per-handle lock never lets two turns overlap
    assert len(published) == 2
