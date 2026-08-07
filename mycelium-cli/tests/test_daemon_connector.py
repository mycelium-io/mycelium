# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Daemon SLIM connector — wake path, reply shape, gates, and control verbs.

The merge gate (no SLIM node, ``claude`` mocked at the integration
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


# ── position marker parsing (pure) ────────────────────────────────────────────


def test_parse_marker_lifts_confidence_and_stance_and_strips() -> None:
    payload, clean = connector.parse_position_marker(
        "I can accept 30% tech.\n\n[[mycelium: confidence=0.85 stance=accept]]"
    )
    assert payload == {"confidence": 0.85, "action": "accept"}
    assert clean == "I can accept 30% tech."
    assert "mycelium" not in clean


def test_parse_marker_absent_is_plain_reply() -> None:
    payload, clean = connector.parse_position_marker("just a normal reply, no marker")
    assert payload == {}
    assert clean == "just a normal reply, no marker"


def test_parse_marker_drops_out_of_range_confidence() -> None:
    payload, _clean = connector.parse_position_marker("x [[mycelium: confidence=1.5 stance=block]]")
    # 1.5 is out of [0,1] and dropped; `block` maps to reject
    assert payload == {"action": "reject"}


def test_parse_marker_malformed_confidence_ignored() -> None:
    payload, _clean = connector.parse_position_marker("x [[mycelium: confidence=high]]")
    assert payload == {}


def test_parse_marker_empty_body_after_strip_falls_back_to_original() -> None:
    payload, clean = connector.parse_position_marker("[[mycelium: confidence=0.7]]")
    assert payload == {"confidence": 0.7}
    assert clean  # never post an empty reply


def test_build_reply_carries_epistemic_payload() -> None:
    woke = _inbound(sender="human", recipients=["agent-a"], text="@agent-a your call")
    reply = connector.build_reply(
        handle="agent-a",
        room="r",
        woke=woke,
        text="I accept the guardrail.\n[[mycelium: confidence=0.9 stance=accept]]",
    )
    data = l9.payload_data_of(reply)
    assert data.get("confidence") == 0.9
    assert data.get("action") == "accept"
    assert "mycelium" not in l9.human_text_of(reply)


def test_build_reply_plain_text_has_empty_payload() -> None:
    woke = _inbound(sender="human", recipients=["agent-a"], text="@agent-a hi")
    reply = connector.build_reply(handle="agent-a", room="r", woke=woke, text="hello there")
    assert l9.payload_data_of(reply) == {}


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


# ── remote endpoint plumbing ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_connector_uses_configured_remote_node_endpoint(monkeypatch):
    """The connector dials ``config.slim.node_endpoint`` — a remote LAN node, not
    the localhost default — so ``mycelium connect <A-LAN-IP>`` actually points a
    member host at host A's shared node."""
    from mycelium.config import SlimConfig
    from mycelium.slim.client import SlimUnavailableError

    dialed: list[str] = []

    class _FakeClient:
        def __init__(self, _identity: Any) -> None:
            pass

        async def connect(self, node: str) -> Any:
            dialed.append(node)
            # Break out of run_connector's reconnect loop cleanly.
            raise SlimUnavailableError("no wheel in test")

    monkeypatch.setattr(connector, "SlimClient", _FakeClient)

    config = MyceliumConfig(
        server=ServerConfig(api_url="http://localhost:8000"),
        slim=SlimConfig(node_endpoint="http://host-a.lan:46357"),
    )
    await connector.run_connector(
        config=config,
        daemon_cfg=DaemonConfig(),
        state=DaemonState(),
        room="demo",
        handle="agent-a",
    )
    assert dialed == ["http://host-a.lan:46357"]
