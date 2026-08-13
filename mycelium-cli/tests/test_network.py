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
    base = {
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


def _patch(monkeypatch: pytest.MonkeyPatch, tmp_path, health: dict) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("x")
    fake_config = SimpleNamespace(server=SimpleNamespace(api_url="http://localhost:8000"))
    monkeypatch.setattr(
        net_cmd.MyceliumConfig, "get_config_path", classmethod(lambda _cls: cfg_path)
    )
    monkeypatch.setattr(net_cmd.MyceliumConfig, "load", classmethod(lambda _cls: fake_config))

    client = Mock()
    client.get.return_value = SimpleNamespace(json=lambda: health)
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
