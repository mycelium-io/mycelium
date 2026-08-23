# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The hub-facing commands must work with no config file at all.

A ``--client-only`` install is the CLI on PATH plus environment variables and
nothing else: no ``~/.mycelium/config.toml``, no data dir. ``MyceliumConfig.load()``
already produces a usable config from env alone, so any command whose work is a
plain HTTP call to the hub has to run on that config. These tests point ``HOME``
at an empty temp dir, put the hub settings in the environment, and drive each
command with only its transport stubbed — the real loader runs.
"""

from __future__ import annotations

import datetime
import json
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, Mock

import pytest
import typer
from typer.testing import CliRunner

from mycelium.commands import instance as instance_cmd
from mycelium.commands import network as net_cmd
from mycelium.commands import room as room_cmd
from mycelium.config import MyceliumConfig

if TYPE_CHECKING:
    from pathlib import Path

HUB_URL = "http://hub.test:8000"

runner = CliRunner()


@pytest.fixture(autouse=True)
def env_only(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty ``HOME`` plus the hub settings in the environment."""
    monkeypatch.setenv("MYCELIUM_API_URL", HUB_URL)
    monkeypatch.setenv("MYCELIUM_ACTIVE_ROOM", "a2a-test")
    assert not MyceliumConfig.get_config_path().exists()
    return isolated_home


def _no_op_typed_client(monkeypatch: pytest.MonkeyPatch) -> None:
    cm = MagicMock()
    cm.__enter__.return_value = Mock(name="client")
    cm.__exit__.return_value = None
    monkeypatch.setattr(room_cmd, "_typed_client", lambda _c: cm)


def _fake_http(monkeypatch: pytest.MonkeyPatch, module: object, health: dict) -> Mock:
    """Stand in for ``MyceliumHTTPClient`` on ``module``, answering ``/health``."""
    client = Mock()
    client.get.side_effect = lambda path, **_kw: SimpleNamespace(
        json=lambda: health if path == "/health" else {}
    )
    cm = MagicMock()
    cm.__enter__.return_value = client
    cm.__exit__.return_value = None
    monkeypatch.setattr(module, "MyceliumHTTPClient", lambda **_kw: cm)
    return client


def test_config_loads_from_env_with_no_file() -> None:
    assert MyceliumConfig.load().server.api_url == HUB_URL


def test_room_ls_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    from mycelium_backend_client.models import RoomRead

    _no_op_typed_client(monkeypatch)
    monkeypatch.setattr(
        "mycelium_backend_client.api.rooms.list_rooms_api_rooms_get.sync",
        lambda **_kw: [
            RoomRead(
                id=1,
                name="a2a-test",
                is_public=True,
                created_at=datetime.datetime(2026, 6, 1),  # noqa: DTZ001
            )
        ],
    )
    result = runner.invoke(room_cmd.app, ["ls"])
    assert result.exit_code == 0, result.output
    assert "a2a-test" in result.output
    assert "config.toml" not in result.output


def test_room_create_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    from mycelium_backend_client.models import RoomRead

    _no_op_typed_client(monkeypatch)
    monkeypatch.setattr(
        "mycelium_backend_client.api.rooms.create_room_api_rooms_post.sync",
        lambda **_kw: RoomRead(
            id=2,
            name="fresh",
            is_public=True,
            created_at=datetime.datetime(2026, 6, 1),  # noqa: DTZ001
        ),
    )
    result = runner.invoke(room_cmd.app, ["create", "fresh"])
    assert result.exit_code == 0, result.output
    assert "config.toml" not in result.output


def test_room_delete_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_op_typed_client(monkeypatch)
    monkeypatch.setattr(
        "mycelium_backend_client.api.rooms.delete_room_api_rooms_room_name_delete.sync_detailed",
        lambda **_kw: SimpleNamespace(status_code=204),
    )
    result = runner.invoke(room_cmd.app, ["delete", "doomed", "--force"])
    assert result.exit_code == 0, result.output
    assert "deleted" in result.output
    assert "config.toml" not in result.output


def _network_app() -> typer.Typer:
    app = typer.Typer()

    @app.callback()
    def _root(ctx: typer.Context) -> None:
        ctx.obj = {"json": False}

    app.command(name="network")(net_cmd.network)
    return app


def test_network_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_http(
        monkeypatch,
        net_cmd,
        {
            "status": "ok",
            "coordination": {
                "endpoint": "http://slim:46357",
                "slim_enabled": True,
                "channels_live": 0,
                "provisions_ok": 0,
                "provisions_failed": 0,
                "invite_failures": 0,
                "rooms": [],
            },
        },
    )
    result = runner.invoke(_network_app(), ["network"])
    assert result.exit_code == 0, result.output
    assert "Mycelium Network" in result.output
    assert "config.toml" not in result.output


def _status_app(json_flag: bool = False) -> typer.Typer:
    app = typer.Typer()

    @app.callback()
    def _root(ctx: typer.Context) -> None:
        ctx.obj = {"json": json_flag}

    app.command(name="status")(instance_cmd.status)
    return app


@pytest.fixture
def _no_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        instance_cmd,
        "_check_docker_containers",
        lambda: {"available": False, "message": "Docker not available"},
    )


@pytest.mark.usefixtures("_no_docker")
def test_status_runs_and_reports_the_absent_file(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_http(monkeypatch, instance_cmd, {"status": "ok", "version": "3.0.1"})
    result = runner.invoke(_status_app(), ["status"])
    assert result.exit_code == 0, result.output
    assert "All systems operational" in result.output
    # The missing file is reported as context, never as a failure.
    assert "absent" in result.output


@pytest.mark.usefixtures("_no_docker")
def test_status_json_marks_the_file_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_http(monkeypatch, instance_cmd, {"status": "ok", "version": "3.0.1"})
    result = runner.invoke(_status_app(json_flag=True), ["status"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["config"]["file_present"] is False
    assert payload["config"]["api_url"] == HUB_URL
