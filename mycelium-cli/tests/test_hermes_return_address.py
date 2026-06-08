# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for Hermes cross-channel return-address resolution."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

_PLUGIN_ROOT = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "mycelium"
    / "integrations"
    / "hermes"
    / "assets"
    / "mycelium"
    / "plugin"
)
_PKG = "_hermes_plugin_return_address_under_test"


def _load_return_address_module():
    name = f"{_PKG}.return_address"
    if name in sys.modules:
        return sys.modules[name]
    if _PKG not in sys.modules:
        pkg_spec = importlib.util.spec_from_file_location(
            _PKG,
            _PLUGIN_ROOT / "__init__.py",
            submodule_search_locations=[str(_PLUGIN_ROOT)],
        )
        assert pkg_spec is not None
        pkg = importlib.util.module_from_spec(pkg_spec)
        sys.modules[_PKG] = pkg
        pkg.__path__ = [str(_PLUGIN_ROOT)]
    spec = importlib.util.spec_from_file_location(name, _PLUGIN_ROOT / "return_address.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_notify_home_module():
    _load_return_address_module()
    name = f"{_PKG}.notify_home"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _PLUGIN_ROOT / "notify_home.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def ra_module(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    return _load_return_address_module()


def test_read_home_address_from_sessions_picks_newest_non_mycelium(ra_module, tmp_path) -> None:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    now = datetime.now(tz=UTC)
    older = (now - timedelta(minutes=10)).isoformat()
    newer = now.isoformat()
    sessions_dir.joinpath("sessions.json").write_text(
        json.dumps(
            {
                "agent:main:mycelium-room:group:demo:alice": {
                    "session_key": "agent:main:mycelium-room:group:demo:alice",
                    "updated_at": newer,
                    "platform": "mycelium-room",
                    "origin": {
                        "platform": "mycelium-room",
                        "chat_id": "demo:alice",
                    },
                },
                "agent:main:matrix:dm:!room:example.com": {
                    "session_key": "agent:main:matrix:dm:!room:example.com",
                    "updated_at": older,
                    "platform": "matrix",
                    "origin": {
                        "platform": "matrix",
                        "chat_id": "!room:example.com",
                    },
                },
                "agent:main:telegram:dm:12345": {
                    "session_key": "agent:main:telegram:dm:12345",
                    "updated_at": newer,
                    "platform": "telegram",
                    "origin": {
                        "platform": "telegram",
                        "chat_id": "12345",
                        "thread_id": "99",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    addr = ra_module.read_home_address_from_sessions()
    assert addr is not None
    assert addr.platform == "telegram"
    assert addr.chat_id == "12345"
    assert addr.thread_id == "99"


def test_sidecar_preferred_over_sessions(ra_module, tmp_path) -> None:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    sessions_dir.joinpath("sessions.json").write_text(
        json.dumps(
            {
                "agent:main:telegram:dm:old": {
                    "updated_at": datetime.now(tz=UTC).isoformat(),
                    "platform": "telegram",
                    "origin": {"platform": "telegram", "chat_id": "old"},
                }
            }
        ),
        encoding="utf-8",
    )
    tmp_path.joinpath(".mycelium-return-origin.json").write_text(
        json.dumps(
            {
                "platform": "matrix",
                "chat_id": "!fresh:example.com",
                "recorded_at": datetime.now(tz=UTC).isoformat(),
                "origin": {"platform": "matrix", "chat_id": "!fresh:example.com"},
            }
        ),
        encoding="utf-8",
    )
    addr = ra_module.read_home_address()
    assert addr is not None
    assert addr.platform == "matrix"
    assert addr.chat_id == "!fresh:example.com"


def test_stash_return_address_is_idempotent(ra_module) -> None:
    book = ra_module.ReturnAddressBook()
    log = MagicMock()
    addr = ra_module.HomeAddress(platform="matrix", chat_id="!x:server")

    def fake_read(_log=None):
        return addr

    ra_module.read_home_address = fake_read
    ra_module.stash_return_address(book, session_room="demo:session:1", agent_id="alice", log=log)
    ra_module.stash_return_address(book, session_room="demo:session:1", agent_id="alice", log=log)
    assert len(book) == 1
    assert book.lookup(session_room="demo:session:1", agent_id="alice") == addr


def test_record_last_origin_skips_mycelium_platform(ra_module, tmp_path) -> None:
    source = SimpleNamespace(
        platform=SimpleNamespace(value="mycelium-room"),
        chat_id="demo:alice",
        chat_type="group",
        thread_id=None,
        user_id="bot",
        user_name="bot",
    )
    ra_module.record_last_origin(source)
    assert not (tmp_path / ".mycelium-return-origin.json").exists()


def test_record_last_origin_writes_matrix_sidecar(ra_module, tmp_path) -> None:
    source = SimpleNamespace(
        platform=SimpleNamespace(value="matrix"),
        chat_id="!abc:example.com",
        chat_type="dm",
        thread_id=None,
        user_id="u1",
        user_name="user",
        to_dict=lambda: {
            "platform": "matrix",
            "chat_id": "!abc:example.com",
            "chat_type": "dm",
        },
    )
    ra_module.record_last_origin(source)
    data = json.loads((tmp_path / ".mycelium-return-origin.json").read_text(encoding="utf-8"))
    assert data["platform"] == "matrix"
    assert data["chat_id"] == "!abc:example.com"


@pytest.mark.asyncio
async def test_deliver_notify_home_uses_gateway_runner_adapters(monkeypatch) -> None:
    import types

    notify_home = _load_notify_home_module()
    ra = _load_return_address_module()

    book = ra.ReturnAddressBook()
    book.stash(
        session_room="demo:session:9",
        agent_id="alice",
        address=ra.HomeAddress(platform="matrix", chat_id="!room:example.com"),
    )

    adapter = MagicMock()
    adapter.send = AsyncMock(return_value=SimpleNamespace(success=True))

    class FakePlatform:
        __slots__ = ("value",)

        def __init__(self, value: str) -> None:
            self.value = value

        def __hash__(self) -> int:
            return hash(self.value)

        def __eq__(self, other: object) -> bool:
            return isinstance(other, FakePlatform) and other.value == self.value

    matrix_key = FakePlatform("matrix")
    runner = SimpleNamespace(adapters={matrix_key: adapter})

    config_mod = types.ModuleType("gateway.config")
    config_mod.Platform = FakePlatform  # ty: ignore[unresolved-attribute]
    run_mod = types.ModuleType("gateway.run")
    run_mod._gateway_runner_ref = lambda: runner  # ty: ignore[unresolved-attribute]
    monkeypatch.setitem(sys.modules, "gateway.config", config_mod)
    monkeypatch.setitem(sys.modules, "gateway.run", run_mod)

    action = SimpleNamespace(
        session_room="demo:session:9",
        agent_ids=("alice",),
        consensus_summary="Consensus reached",
    )

    await notify_home.deliver_notify_home(action=action, addresses=book)

    adapter.send.assert_awaited_once()
    assert adapter.send.await_args is not None
    kwargs = adapter.send.await_args.kwargs
    assert kwargs["chat_id"] == "!room:example.com"
    assert kwargs["content"] == "Consensus reached"
    assert len(book) == 0
