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
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, Mock

import pytest
import typer
from typer.testing import CliRunner

from mycelium.commands import instance as instance_cmd
from mycelium.commands import network as net_cmd
from mycelium.commands import room as room_cmd
from mycelium.config import MyceliumConfig
from mycelium_backend_client.models import WhoamiRead
from tests.conftest import install_stand_in_hub
from tests.hub_answers import ok

if TYPE_CHECKING:
    from pathlib import Path

HUB_URL = "http://hub.test:8000"

runner = CliRunner()


@pytest.fixture(autouse=True)
def env_only(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty ``HOME`` plus the hub settings in the environment."""
    monkeypatch.setenv("MYCELIUM_API_URL", HUB_URL)
    monkeypatch.setenv("MYCELIUM_ACTIVE_ROOM", "a2a-test")
    # A hub with sign-in off: whoami names nobody, so status says nothing of a credential.
    monkeypatch.setattr("mycelium.identity._hub_whoami", lambda _config: None)
    assert not MyceliumConfig.get_config_path().exists()
    return isolated_home


def _no_op_typed_client(monkeypatch: pytest.MonkeyPatch) -> None:
    cm = MagicMock()
    cm.__enter__.return_value = Mock(name="client")
    cm.__exit__.return_value = None
    monkeypatch.setattr(room_cmd, "_typed_client", lambda _c: cm)


def _health(**sections: object) -> dict:
    """A hub's ``/health`` answer at 3.0.1, with ``sections``."""
    return {"status": "ok", "service": "mycelium-backend", "version": "3.0.1", **sections}


def _stand_in_hub(monkeypatch: pytest.MonkeyPatch, health: dict, *, at: str = "/health") -> None:
    """A hub answering ``health`` at ``at`` and 404 everywhere else."""
    install_stand_in_hub(monkeypatch).answer = lambda request: (
        health if request.url.path == at else (404, {"detail": "Not Found"})
    )


def test_config_loads_from_env_with_no_file() -> None:
    assert MyceliumConfig.load().server.api_url == HUB_URL


def test_room_ls_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    from mycelium_backend_client.models import RoomRead

    _no_op_typed_client(monkeypatch)
    monkeypatch.setattr(
        "mycelium_backend_client.api.rooms.list_rooms_api_rooms_get.sync_detailed",
        lambda **_kw: ok(
            [
                RoomRead(
                    id=1,
                    name="a2a-test",
                    is_public=True,
                    created_at=datetime.datetime(2026, 6, 1),  # noqa: DTZ001
                )
            ]
        ),
    )
    result = runner.invoke(room_cmd.app, ["ls"])
    assert result.exit_code == 0, result.output
    assert "a2a-test" in result.output
    assert "config.toml" not in result.output


def test_room_create_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    from mycelium_backend_client.models import RoomRead

    _no_op_typed_client(monkeypatch)
    monkeypatch.setattr(
        "mycelium_backend_client.api.rooms.create_room_api_rooms_post.sync_detailed",
        lambda **_kw: ok(
            RoomRead(
                id=2,
                name="fresh",
                is_public=True,
                created_at=datetime.datetime(2026, 6, 1),  # noqa: DTZ001
            ),
            201,
        ),
    )
    result = runner.invoke(room_cmd.app, ["create", "fresh"])
    assert result.exit_code == 0, result.output
    assert "config.toml" not in result.output


def test_room_delete_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_op_typed_client(monkeypatch)
    monkeypatch.setattr(
        "mycelium_backend_client.api.rooms.delete_room_api_rooms_room_name_delete.sync_detailed",
        lambda **_kw: ok(None, 204),
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
    _stand_in_hub(
        monkeypatch,
        _health(
            coordination={
                "endpoint": "http://slim:46357",
                "slim_enabled": True,
                "channels_live": 0,
                "provisions_ok": 0,
                "provisions_failed": 0,
                "invite_failures": 0,
                "rooms": [],
            },
        ),
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
    _stand_in_hub(monkeypatch, _health())
    result = runner.invoke(_status_app(), ["status"])
    assert result.exit_code == 0, result.output
    assert "All systems operational" in result.output
    # The missing file is reported as context, never as a failure.
    assert "absent" in result.output


@pytest.mark.usefixtures("_no_docker")
def test_status_asks_a_hub_at_its_apps_address_under_api_and_says_a_refused_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """At the app's address /health is the app's 404; a missing credential is said as that."""
    _stand_in_hub(monkeypatch, _health(), at="/api/health")
    monkeypatch.setattr(
        "mycelium.identity._hub_whoami", lambda _config: WhoamiRead(gated=True, handle=None)
    )
    result = runner.invoke(_status_app(), ["status"])
    out = " ".join(result.output.split())
    assert "Running at" in out
    assert "HTTP 404" not in out
    assert "no credential: this terminal sends none" in out
    assert "mycelium login" in out


@pytest.mark.usefixtures("_no_docker")
def test_status_json_marks_the_file_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    _stand_in_hub(monkeypatch, _health())
    result = runner.invoke(_status_app(json_flag=True), ["status"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["config"]["file_present"] is False
    assert payload["config"]["api_url"] == HUB_URL
