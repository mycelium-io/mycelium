# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A person's sign-in is kept by the desktop app, and an agent's pane never gets it."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest

from mycelium import caller, session_store
from mycelium.config import MyceliumConfig
from mycelium.desktop.events import EventWriter
from mycelium.desktop.session_relay import SessionRelay
from mycelium.tokens import StoredToken, load_token, save_token, token_path

_TOKEN = StoredToken(access_token="at-person", issuer="https://idp.test", client_id="cli")


@pytest.fixture
def config(isolated_home: Path) -> MyceliumConfig:
    cfg = MyceliumConfig()
    cfg.server.api_url = "https://hub.example.com"
    return cfg


class _App:
    """The desktop app's side: answers each request as the person would (yes)."""

    def __init__(self, sock: Path) -> None:
        self.kept: dict[str, dict[str, Any]] = {}
        self.asked: list[str] = []
        self.relay = SessionRelay(self._on_event, path=sock)
        assert self.relay.start()

    def _on_event(self, event: dict[str, Any]) -> None:
        def reply() -> None:
            self.asked.append(event["op"])
            hub, op = event["hub"], event["op"]
            if op == "put":
                self.kept[hub] = event["session"]
                body = {"ok": True}
            elif op == "get":
                body = {"ok": True, "session": self.kept.get(hub)}
            else:
                body = {"ok": self.kept.pop(hub, None) is not None}
            self.relay.answer(json.dumps({"session_reply": event["id"], **body}))

        threading.Thread(target=reply, daemon=True).start()


@pytest.fixture
def app(isolated_home: Path, monkeypatch: pytest.MonkeyPatch):
    # A short path: a Unix socket's name can't be long, and a temp HOME can be.
    import tempfile

    sock = Path(tempfile.mkdtemp(prefix="myc-")) / "s.sock"
    monkeypatch.setattr("mycelium.desktop.session_relay.socket_path", lambda: sock)
    running = _App(sock)
    yield running
    running.relay.stop()


def test_the_app_keeps_the_sign_in_and_the_file_never_exists(config, app) -> None:
    assert session_store.save(config, _TOKEN) == session_store.APP
    assert not token_path().exists()
    session_store._cache.clear()
    found, where = session_store.load(config)
    assert (found.access_token if found else None, where) == ("at-person", session_store.APP)


def test_a_file_from_before_moves_into_the_app_and_is_deleted(config, app) -> None:
    save_token(_TOKEN)  # written before the app kept sign-ins
    found, where = session_store.load(config)
    assert found is not None
    assert where == session_store.APP
    assert app.kept["https://hub.example.com"]["access_token"] == "at-person"
    assert not token_path().exists()


def test_without_the_app_nothing_is_kept_unless_remembered(config) -> None:
    assert session_store.save(config, _TOKEN) == session_store.HERE
    assert load_token() is None
    assert session_store.save(config, _TOKEN, remember=True) == session_store.FILE
    assert json.loads(token_path().read_text())["remember"] is True
    assert token_path().stat().st_mode & 0o777 == 0o600


def test_an_agents_pane_never_gets_the_persons_sign_in(config, app, monkeypatch) -> None:
    session_store.save(config, _TOKEN)
    session_store._cache.clear()
    monkeypatch.setenv("MYCELIUM_AGENT_PANE", "builder")
    monkeypatch.setenv("MYCELIUM_AGENT_HANDLE", "builder")
    assert session_store.load(config) == (None, None)
    assert "get" not in app.asked
    with pytest.raises(session_store.InAgentPane):
        session_store.save(config, _TOKEN)


def test_an_agents_pane_cant_act_as_anyone_else(config, monkeypatch) -> None:
    monkeypatch.setenv("MYCELIUM_AGENT_PANE", "builder")
    monkeypatch.setenv("MYCELIUM_AGENT_HANDLE", "builder")
    with pytest.raises(caller.ActingAsOtherError, match="act as @builder only"):
        caller.credential(config, "julia")
    # As itself is fine: it simply has no person's session to fall back on.
    assert caller.credential(config, "builder").value is None


def test_a_pane_herdrs_registry_maps_is_an_agents_even_unmarked(monkeypatch) -> None:
    monkeypatch.setattr(
        caller, "pane_agent", lambda: caller.PaneAgent(pane="w1:p2", handle="scout", room="r")
    )
    assert caller.in_agent_pane() == "scout"


def test_the_log_never_holds_the_sign_in(tmp_path: Path) -> None:
    import io

    out = io.StringIO()
    writer = EventWriter(tmp_path / "desktop.log", line=json.dumps, stdout=out)
    writer.emit({"type": "session", "id": 1, "op": "put", "session": {"access_token": "at-x"}})
    writer.close()
    assert "at-x" not in (tmp_path / "desktop.log").read_text()
    assert "at-x" in out.getvalue()  # the app still gets it
