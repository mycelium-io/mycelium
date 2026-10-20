# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A person's sign-in is made and kept by the desktop app, and an agent's pane never gets it."""

from __future__ import annotations

import json
import socket
import threading
from pathlib import Path
from typing import Any

import pytest

from mycelium import caller, session_store
from mycelium.config import MyceliumConfig
from mycelium.desktop import session_relay
from mycelium.desktop.events import EventWriter
from mycelium.desktop.session_relay import SessionRelay
from mycelium.tokens import StoredToken, load_token, save_token, token_path

_TOKEN = StoredToken(access_token="at-person", issuer="https://idp.test", client_id="cli")
_LOGIN = {"issuer": "https://idp.test", "client_id": "cli", "scope": "openid", "redirect_port": 0}


@pytest.fixture
def config(isolated_home: Path) -> MyceliumConfig:
    cfg = MyceliumConfig()
    cfg.server.api_url = "https://hub.example.com"
    return cfg


class _App:
    """The desktop app's side: answers each request as the person would (yes),
    and signs in as the provider would."""

    def __init__(self, sock: Path) -> None:
        self.kept: dict[str, dict[str, Any]] = {}
        self.asked: list[str] = []
        self.events: list[dict[str, Any]] = []
        self.relay = SessionRelay(self._on_event, path=sock)
        assert self.relay.start()

    def _on_event(self, event: dict[str, Any]) -> None:
        def reply() -> None:
            self.asked.append(event["op"])
            self.events.append(event)
            hub, op = event["hub"], event["op"]
            if op == "login":
                self.kept[hub] = {**_TOKEN.to_dict(), "refresh_token": "rt-kept-by-the-app"}
                handed = {k: v for k, v in self.kept[hub].items() if k != "refresh_token"}
                body = {"ok": True, "session": handed, "refreshable": True}
            elif op == "get":
                kept = self.kept.get(hub)
                body = {"ok": True, "session": kept and {**kept, "refresh_token": None}}
            else:
                body = {"ok": self.kept.pop(hub, None) is not None}
            self.relay.answer(json.dumps({"session_reply": event["id"], **body}))

        threading.Thread(target=reply, daemon=True).start()


@pytest.fixture
def sock(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # A short path: a Unix socket's name can't be long, and a temp HOME can be.
    import tempfile

    path = Path(tempfile.mkdtemp(prefix="myc-")) / "s.sock"
    monkeypatch.setattr("mycelium.desktop.session_relay.socket_path", lambda: path)
    return path


@pytest.fixture
def app(sock: Path, monkeypatch: pytest.MonkeyPatch):
    # The test process is the listener here, which no system would call the
    # signed app; the check itself has its own tests below.
    monkeypatch.setattr(session_relay, "listener_is_app", lambda conn: None)
    running = _App(sock)
    yield running
    running.relay.stop()


def test_the_app_signs_in_and_the_cli_never_gets_the_refresh_token(config, app) -> None:
    made = session_store.login_in_app(config, **_LOGIN)
    assert made is not None
    token, refreshable = made
    assert (token.access_token, token.refresh_token, refreshable) == ("at-person", None, True)
    assert app.kept["https://hub.example.com"]["refresh_token"] == "rt-kept-by-the-app"
    assert not token_path().exists()
    session_store._cache.clear()
    found, where = session_store.load(config)
    assert (found.access_token if found else None, where) == ("at-person", session_store.APP)
    assert found is not None
    assert found.refresh_token is None


def test_a_login_request_says_only_what_to_sign_in_with(config, app) -> None:
    session_store.login_in_app(config, **_LOGIN, session={"refresh_token": "x"})
    assert set(app.events[0]["login"]) == set(_LOGIN)
    assert "session" not in app.events[0]


def test_a_file_from_before_is_used_with_a_warning_until_a_login_replaces_it(
    config, app, capsys
) -> None:
    save_token(_TOKEN)  # written before the app kept sign-ins
    found, where = session_store.load(config)
    assert (found is not None, where) == (True, session_store.FILE)
    assert "any program running as you" in capsys.readouterr().err
    assert "get" in app.asked
    assert "login" not in app.asked  # the CLI never hands it over
    session_store.login_in_app(config, **_LOGIN)
    assert not token_path().exists()


def test_without_the_app_nothing_is_kept_unless_remembered(config) -> None:
    assert session_store.login_in_app(config, **_LOGIN) is None
    assert session_store.save(config, _TOKEN) == session_store.HERE
    assert load_token() is None
    assert session_store.save(config, _TOKEN, remember=True) == session_store.FILE
    assert json.loads(token_path().read_text())["remember"] is True
    assert token_path().stat().st_mode & 0o777 == 0o600


def test_an_agents_pane_never_gets_the_persons_sign_in(config, app, monkeypatch) -> None:
    session_store.login_in_app(config, **_LOGIN)
    session_store._cache.clear()
    monkeypatch.setenv("MYCELIUM_AGENT_PANE", "builder")
    monkeypatch.setenv("MYCELIUM_AGENT_HANDLE", "builder")
    assert session_store.load(config) == (None, None)
    assert "get" not in app.asked
    with pytest.raises(session_store.InAgentPane):
        session_store.login_in_app(config, **_LOGIN)
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


def test_the_app_is_told_who_asked_as_the_system_says(config, app) -> None:
    """The question names the command and its folder, read from the socket's
    peer rather than from anything the request claims."""
    session_store.login_in_app(config, **_LOGIN)
    asker = app.events[0]["caller"]
    assert set(asker) == {"command", "cwd", "tty"}
    assert asker["cwd"]  # the test process's own folder


def test_a_command_asks_the_app_again_when_its_access_token_runs_out(config, app) -> None:
    """The app keeps the refresh token and renews; a command holds an access
    token alone, and asks the app for another when it runs out."""
    import time

    from mycelium import client

    hub = "https://hub.example.com"
    app.kept[hub] = {"access_token": "at-old", "issuer": "i", "client_id": "c",
                     "expires_at": time.time() - 10}  # fmt: skip
    session_store.load(config)  # this process now holds the expired one
    app.kept[hub] = {"access_token": "at-new", "issuer": "i", "client_id": "c",
                     "expires_at": time.time() + 600}  # fmt: skip
    fresh = client.current_token(config)
    assert fresh is not None
    assert fresh.access_token == "at-new"
    assert fresh.refresh_token is None
    assert app.asked.count("get") == 2


def test_a_listener_that_isnt_the_app_is_never_asked(config, sock, monkeypatch, capsys) -> None:
    """A program listening where the app's socket is gets nothing: no request
    is sent to it and nothing it says is used."""
    monkeypatch.setattr(session_relay, "listener_is_app", lambda conn: False)
    impostor = _App(sock)
    impostor.kept["https://hub.example.com"] = _TOKEN.to_dict()
    try:
        assert session_store.load(config) == (None, None)
        assert session_store.login_in_app(config, **_LOGIN) is None
        assert impostor.asked == []
        assert "isn't the Mycelium app" in capsys.readouterr().err
    finally:
        impostor.relay.stop()


def test_on_macos_the_listener_must_be_signed_and_started_by_the_signed_app(monkeypatch) -> None:
    monkeypatch.setattr(session_relay.sys, "platform", "darwin")
    monkeypatch.delenv(session_relay.UNSIGNED_APP_ENV, raising=False)
    monkeypatch.setattr(session_relay, "peer_pid", lambda conn: 200)
    monkeypatch.setattr(session_relay, "_parent", lambda pid: 100)
    signed: dict[int, str] = {}

    def check(pid: int, requirement: str) -> bool:
        return pid in signed and all(part in requirement for part in signed[pid].split("|"))

    monkeypatch.setattr(session_relay, "_signed", check)
    conn = socket.socket()
    try:
        assert session_relay.listener_is_app(conn) is False  # nothing signed
        signed[200] = session_relay.APP_TEAM
        assert session_relay.listener_is_app(conn) is False  # signed, parent isn't the app
        signed[100] = f"{session_relay.APP_TEAM}|{session_relay.APP_ID}"
        assert session_relay.listener_is_app(conn) is True
        monkeypatch.setattr(session_relay, "_parent", lambda pid: None)
        assert session_relay.listener_is_app(conn) is False
        monkeypatch.setattr(session_relay.sys, "platform", "linux")
        assert session_relay.listener_is_app(conn) is None  # can't tell there
    finally:
        conn.close()


@pytest.mark.skipif(session_relay.sys.platform != "darwin", reason="the system can tell on macOS")
def test_a_program_listening_here_isnt_taken_for_the_app(sock, monkeypatch) -> None:
    """The real check, against this test process listening: unsigned, so not the app."""
    monkeypatch.delenv(session_relay.UNSIGNED_APP_ENV, raising=False)
    impostor = _App(sock)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.connect(str(sock))
            assert session_relay.listener_is_app(conn) is False
    finally:
        impostor.relay.stop()


def test_a_command_reads_from_mycelium_on() -> None:
    from mycelium.desktop.session_relay import shown_command

    line = "/usr/bin/python3 /Users/x/.local/bin/mycelium room messages checkout --limit 5"
    assert shown_command(line) == "mycelium room messages checkout --limit 5"
    assert len(shown_command("mycelium " + "x" * 200)) == 80
