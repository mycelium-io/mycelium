# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for ``mycelium room`` (list / create / use) on a fake backend.

Node-free: the generated ``rooms`` API ``.sync`` calls are stubbed and the typed
client is a no-op context manager, so these exercise the command plumbing —
rendering, the active-room switch, and the empty case — without a backend server.
"""

from __future__ import annotations

import datetime

import pytest
from typer.testing import CliRunner

from mycelium.commands import room as room_cmd

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolate(isolated_home, monkeypatch: pytest.MonkeyPatch) -> None:
    """A real (empty) config on a temp home, plus a no-op typed client.

    ``room`` reads ``config.get_active_room()`` and requires a config file to
    exist, so it needs the real ``MyceliumConfig`` (not the SimpleNamespace the
    shared ``backend`` fixture installs) — only the typed client is stubbed.
    """
    from unittest.mock import MagicMock, Mock

    from mycelium.config import MyceliumConfig

    cfg_path = isolated_home / ".mycelium" / "config.toml"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text("")
    monkeypatch.setattr(
        room_cmd.MyceliumConfig, "get_config_path", classmethod(lambda _cls: cfg_path)
    )
    monkeypatch.setattr(
        room_cmd.MyceliumConfig, "load", classmethod(lambda _cls, *a, **k: MyceliumConfig())
    )
    fake_cm = MagicMock()
    fake_cm.__enter__.return_value = Mock(name="client")
    fake_cm.__exit__.return_value = None
    monkeypatch.setattr(room_cmd, "_typed_client", lambda _c: fake_cm)


_ids = iter(range(1, 1000))


def _room(name: str) -> object:
    from mycelium_backend_client.models import RoomRead

    return RoomRead(
        id=next(_ids),
        name=name,
        is_public=True,
        created_at=datetime.datetime(2026, 6, 1),  # noqa: DTZ001
    )


def test_room_list_renders_rooms(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "mycelium_backend_client.api.rooms.list_rooms_api_rooms_get.sync",
        lambda **_kw: [_room("alpha"), _room("beta")],
    )
    result = runner.invoke(room_cmd.app, ["ls"])
    assert result.exit_code == 0, result.output
    assert "Rooms (2)" in result.output
    assert "alpha" in result.output and "beta" in result.output


def test_room_list_empty_prints_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "mycelium_backend_client.api.rooms.list_rooms_api_rooms_get.sync",
        lambda **_kw: [],
    )
    result = runner.invoke(room_cmd.app, ["ls"])
    assert result.exit_code == 0, result.output
    assert "No rooms found." in result.output


def test_room_list_passes_limit_and_name(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_sync(**kwargs):
        captured.update(kwargs)
        return [_room("alpha")]

    monkeypatch.setattr(
        "mycelium_backend_client.api.rooms.list_rooms_api_rooms_get.sync", fake_sync
    )
    result = runner.invoke(room_cmd.app, ["ls", "--limit", "7", "--name", "alpha"])
    assert result.exit_code == 0, result.output
    assert captured["limit"] == 7
    assert captured["name"] == "alpha"


def test_room_create_writes_local_dir_and_reports(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "mycelium_backend_client.api.rooms.create_room_api_rooms_post.sync",
        lambda **_kw: _room("gamma"),
    )
    result = runner.invoke(room_cmd.app, ["create", "gamma"])
    assert result.exit_code == 0, result.output
    assert "Created room: gamma" in result.output
    # The command also materializes the room dir locally (cross-machine safety).
    from mycelium.filesystem import get_room_dir

    assert get_room_dir("gamma").exists()
