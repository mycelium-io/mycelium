# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Connector wiring for host-run engines.

Pins that (1) ``connector_targets`` gives a first-party engine a connector only
when ``engine_runtime == "host"``, and (2) an ``@``-summon of an engine handle
routes to the host drive (``dispatch_engine``) instead of a cold spawn.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from mycelium.config import MyceliumConfig, ServerConfig
from mycelium.daemon import connector
from mycelium.daemon.config import DaemonConfig
from mycelium.daemon.state import DaemonState
from mycelium.integrations.engine import host as engine_host
from mycelium.protocol import AgentManifest
from mycelium.slim import l9


def _wire(monkeypatch: pytest.MonkeyPatch, roster: dict[str, AgentManifest]) -> None:
    monkeypatch.setattr(connector, "list_agent_handles", lambda _room: list(roster))
    monkeypatch.setattr(connector, "load_manifest", lambda _room, h: roster.get(h))
    lifecycles = {"claude_code": "cold_spawn", "engine": "backend_engine"}
    monkeypatch.setattr(
        connector,
        "get_integration",
        lambda adapter: MagicMock(lifecycle=lifecycles[adapter]),
    )


def _engine(handle: str = "mediator-1") -> AgentManifest:
    return AgentManifest(handle=handle, adapter="engine", kind="aligner")


def _claude(handle: str = "growth") -> AgentManifest:
    return AgentManifest(handle=handle, adapter="claude_code", cwd="/tmp/x")


# ── connector_targets ────────────────────────────────────────────────────────


def test_targets_include_engine_only_when_host(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire(monkeypatch, {"mediator-1": _engine(), "growth": _claude()})
    daemon_cfg = DaemonConfig(rooms=["r"], handles=["mediator-1", "growth"])

    backend = connector.connector_targets(daemon_cfg, engine_runtime="backend")
    assert ("r", "mediator-1") not in backend  # backend runtime → engine skipped
    assert ("r", "growth") in backend  # cold_spawn agent always gets a connector

    hosted = connector.connector_targets(daemon_cfg, engine_runtime="host")
    assert ("r", "mediator-1") in hosted  # host runtime → engine gets a connector
    assert ("r", "growth") in hosted


def test_targets_skip_unowned_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire(monkeypatch, {"mediator-1": _engine()})
    # handle not owned in daemon.toml → not this daemon's engine to drive.
    daemon_cfg = DaemonConfig(rooms=["r"], handles=[])
    assert connector.connector_targets(daemon_cfg, engine_runtime="host") == []


# ── handle_inbound routes an engine summon to the host drive ─────────────────


def _summon(engine_handle: str = "mediator-1") -> dict:
    return l9.build_reply_content(
        sender="human",
        recipients=[engine_handle],
        episode="urn:ioc:mycelium:episode:r:live",
        parents=[],
        topic="urn:concept:mycelium:r",
        text=f"@{engine_handle} converge us",
        message_id="summon-1",
    )


@pytest.mark.asyncio
async def test_engine_summon_launches_host_drive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(connector, "load_manifest", lambda _room, _h: _engine())
    dispatched = AsyncMock()
    monkeypatch.setattr(engine_host, "dispatch_engine", dispatched)
    # A cold-spawn must NOT happen for an engine.
    monkeypatch.setattr(
        connector,
        "get_integration",
        lambda _a: MagicMock(spawn=AsyncMock(side_effect=AssertionError)),
    )

    state = DaemonState()

    async def publish(_c: dict) -> None:
        return None

    await connector.handle_inbound(
        config=MyceliumConfig(server=ServerConfig(api_url="http://x")),
        daemon_cfg=DaemonConfig(),
        state=state,
        room="r",
        handle="mediator-1",
        content=_summon(),
        publish=publish,
    )

    dispatched.assert_awaited_once()
    assert dispatched.await_args is not None
    kwargs = dispatched.await_args.kwargs
    assert kwargs["handle"] == "mediator-1"
    assert kwargs["kind"] == "aligner"
    assert kwargs["room"] == "r"


@pytest.mark.asyncio
async def test_engine_ignores_message_not_addressed_to_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(connector, "load_manifest", lambda _room, _h: _engine())
    dispatched = AsyncMock()
    monkeypatch.setattr(engine_host, "dispatch_engine", dispatched)

    # Addressed to someone else, no @mention of the engine → no drive.
    other: dict[str, Any] = l9.build_reply_content(
        sender="human",
        recipients=["growth"],
        episode="urn:ioc:mycelium:episode:r:live",
        parents=[],
        topic="urn:concept:mycelium:r",
        text="hey growth",
        message_id="m-2",
    )

    async def publish(_c: dict) -> None:
        return None

    await connector.handle_inbound(
        config=MyceliumConfig(),
        daemon_cfg=DaemonConfig(),
        state=DaemonState(),
        room="r",
        handle="mediator-1",
        content=other,
        publish=publish,
    )
    dispatched.assert_not_awaited()
