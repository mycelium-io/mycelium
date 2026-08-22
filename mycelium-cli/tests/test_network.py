"""Tests for `mycelium network` — the SLIM coordination fabric status view.

The command reads the backend's ``/health`` coordination block and renders the
node, channel counters, and per-room membership/telemetry. These tests patch the
config plumbing and the HTTP client, and assert on rendering, the room filter,
and the JSON path.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import httpx
import pytest
import typer
from typer.testing import CliRunner

from mycelium.commands import network as net_cmd


def _health(rooms: list[dict]) -> dict:
    return {
        "status": "ok",
        "coordination": {
            "endpoint": "http://slim:46357",
            "slim_enabled": True,
            "channels_live": len(rooms),
            "provisions_ok": len(rooms),
            "provisions_failed": 0,
            "invite_failures": 0,
            "rooms": rooms,
        },
    }


def _room(name: str, members: list[str] | None = None, **over: object) -> dict:
    base: dict[str, object] = {
        "room": name,
        "provisioned": True,
        "members": members or [],
        "pending_invites": 0,
        "episode_active": False,
        "reserves": 0,
        "receive_errors": 0,
    }
    base.update(over)
    return base


def _a2a_state(
    room: str,
    agents: list[dict] | None = None,
    exchanges: list[dict] | None = None,
    **exposure: object,
) -> dict:
    return {
        "room": room,
        "agents": agents or [],
        "exchanges": exchanges or [],
        "outbound_ok": 0,
        "outbound_failed": 0,
        "exposure": {
            "card_url": f"http://localhost:8000/api/rooms/{room}/.well-known/agent-card.json",
            "rpc_url": f"http://localhost:8000/api/rooms/{room}/a2a",
            "skills": [],
            "card_fetches": 0,
            "messages": 0,
            **exposure,
        },
    }


def _patch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    health: dict,
    a2a: dict[str, dict] | None = None,
    *,
    a2a_fails: bool = False,
) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("x")
    fake_config = SimpleNamespace(server=SimpleNamespace(api_url="http://localhost:8000"))
    monkeypatch.setattr(
        net_cmd.MyceliumConfig, "get_config_path", classmethod(lambda _cls: cfg_path)
    )
    monkeypatch.setattr(net_cmd.MyceliumConfig, "load", classmethod(lambda _cls: fake_config))

    states = a2a or {}

    def _get(path: str) -> SimpleNamespace:
        if path == "/health":
            return SimpleNamespace(json=lambda: health)
        if a2a_fails:
            raise httpx.HTTPStatusError("404", request=Mock(), response=Mock())
        room = path.removeprefix("/rooms/").removesuffix("/a2a/state")
        state = states.get(room, _a2a_state(room))
        return SimpleNamespace(json=lambda: state)

    client = Mock()
    client.get.side_effect = _get
    cm = MagicMock()
    cm.__enter__.return_value = client
    cm.__exit__.return_value = None
    monkeypatch.setattr(net_cmd, "MyceliumHTTPClient", lambda **_kw: cm)


def _app(json_flag: bool = False) -> typer.Typer:
    app = typer.Typer()

    @app.callback()
    def _root(ctx: typer.Context) -> None:
        ctx.obj = {"json": json_flag}

    app.command(name="network")(net_cmd.network)
    return app


def test_network_renders_fabric_and_rooms(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _patch(monkeypatch, tmp_path, _health([_room("handshake", ["mac", "workpc"])]))

    result = CliRunner().invoke(_app(), ["network"])

    assert result.exit_code == 0, result.output
    assert "Mycelium Network" in result.output
    assert "http://slim:46357" in result.output
    assert "fabric enabled" in result.output
    assert "handshake" in result.output
    assert "mac, workpc" in result.output  # server-held members shown in full


def test_network_filters_to_one_room(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _patch(monkeypatch, tmp_path, _health([_room("alpha"), _room("beta")]))

    result = CliRunner().invoke(_app(), ["network", "beta"])

    assert result.exit_code == 0, result.output
    assert "beta" in result.output
    assert "alpha" not in result.output


def test_network_empty_rooms(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _patch(monkeypatch, tmp_path, _health([]))

    result = CliRunner().invoke(_app(), ["network"])

    assert result.exit_code == 0, result.output
    assert "no provisioned rooms" in result.output


def test_network_json_output(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _patch(monkeypatch, tmp_path, _health([_room("handshake", ["mac"])]))

    result = CliRunner().invoke(_app(json_flag=True), ["network"])

    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    assert parsed["endpoint"] == "http://slim:46357"
    assert parsed["rooms"][0]["room"] == "handshake"


# ── the A2A bridge block ─────────────────────────────────────────────────────


def _bridged(**over: object) -> dict:
    agent: dict[str, object] = {
        "handle": "weather",
        "description": "forecasts",
        "card": "https://weather.example",
        "endpoint": "https://weather.example/a2a",
        "skills": ["forecast", "alerts"],
        "calls_ok": 3,
        "calls_failed": 1,
        "proxied": True,
    }
    agent.update(over)
    return agent


def test_bridged_agents_are_listed_with_endpoint_and_skills(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _patch(
        monkeypatch,
        tmp_path,
        _health([_room("handshake", ["mac"])]),
        {"handshake": _a2a_state("handshake", agents=[_bridged()])},
    )

    result = CliRunner().invoke(_app(), ["network"])

    assert result.exit_code == 0, result.output
    assert "A2A bridge · handshake" in result.output
    assert "@weather" in result.output
    assert "https://weather.example/a2a" in result.output
    assert "forecast, alerts" in result.output
    assert "3✓/1✗" in result.output
    # The honest boundary is stated, not implied.
    assert "not members of the" in result.output


def test_recent_exchanges_are_shown_with_their_outcome(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    exchanges = [
        {
            "id": "a2a-1",
            "handle": "weather",
            "direction": "outbound",
            "status": "ok",
            "at": "2026-08-22T10:00:00Z",
            "reply": "sunny all week",
            "duration_ms": 812,
        },
        {
            "id": "a2a-2",
            "handle": "weather",
            "direction": "outbound",
            "status": "error",
            "at": "2026-08-22T10:01:00Z",
            "detail": "card unresolvable: 404",
        },
    ]
    _patch(
        monkeypatch,
        tmp_path,
        _health([_room("handshake")]),
        {"handshake": _a2a_state("handshake", agents=[_bridged()], exchanges=exchanges)},
    )

    result = CliRunner().invoke(_app(), ["network"])

    assert "sunny all week" in result.output
    assert "812ms" in result.output
    assert "card unresolvable: 404" in result.output


def test_inbound_exposure_is_reported_once_the_card_is_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _patch(
        monkeypatch,
        tmp_path,
        _health([_room("handshake")]),
        {"handshake": _a2a_state("handshake", card_fetches=2, messages=1)},
    )

    result = CliRunner().invoke(_app(), ["network"])

    assert "inbound: card at" in result.output
    assert "2 fetches, 1 message)" in result.output


def test_quiet_room_prints_no_bridge_block(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _patch(monkeypatch, tmp_path, _health([_room("handshake")]))

    result = CliRunner().invoke(_app(), ["network"])

    assert "A2A bridge" not in result.output


def test_bridge_read_failure_does_not_break_the_view(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    # An older backend has no a2a state route; the fabric view still renders.
    _patch(monkeypatch, tmp_path, _health([_room("handshake", ["mac"])]), a2a_fails=True)

    result = CliRunner().invoke(_app(), ["network"])

    assert result.exit_code == 0, result.output
    assert "handshake" in result.output
    assert "A2A bridge" not in result.output


def test_json_output_carries_the_bridge_state(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _patch(
        monkeypatch,
        tmp_path,
        _health([_room("handshake")]),
        {"handshake": _a2a_state("handshake", agents=[_bridged()])},
    )

    result = CliRunner().invoke(_app(json_flag=True), ["network"])

    parsed = json.loads(result.output)
    assert parsed["rooms"][0]["a2a"]["agents"][0]["handle"] == "weather"
