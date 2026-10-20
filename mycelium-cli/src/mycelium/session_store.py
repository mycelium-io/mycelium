# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Where a person's sign-in (``mycelium login``) is kept, and who may use it.

Every agent on this machine runs as the same user as the person, so a sign-in
in a file the CLI reads is one every agent can read and act as. So:

- **The desktop app makes it and keeps it.** ``mycelium login`` asks the app to
  sign in (:func:`login_in_app`): the app runs the browser sign-in itself and
  keeps the result, refresh token included, so the CLI never holds or sends
  one. A command asks the app for an access token (``desktop.session_relay``),
  and the app asks the person first (Touch ID or their password on macOS, a
  dialog elsewhere), with a short grace so several commands in a row ask once.
  An agent can't answer that question.
- **The CLI checks who answers.** Any program can listen where the app's
  socket is, so a request goes only to a listener the system says is the
  signed app (``session_relay.listener_is_app``, on macOS).
- **Inside an agent's pane the person's sign-in is never used**
  (``caller.in_agent_pane``): an agent acts with its own credentials only.
- **Without the app** nothing is kept, and ``mycelium login`` says to open
  Mycelium. ``mycelium login --remember`` writes it to a file (``0600``) with a
  warning that any program running as this user can read it, for a server
  where the operator decides that's acceptable.

A file written before this, without ``--remember``, is still used, with a
warning, until ``mycelium login`` with the app running replaces it.
"""

from __future__ import annotations

import contextlib
import json
import socket
import sys
from typing import TYPE_CHECKING, Any

from mycelium import caller
from mycelium.tokens import StoredToken, clear_token, load_token, save_token, token_path

if TYPE_CHECKING:
    from pathlib import Path

    from mycelium.config import MyceliumConfig

#: Where the session came from: the app, a remembered file, or this process.
APP, FILE, HERE = "app", "file", "here"

#: The key a remembered file carries, so an older file reads as one to replace.
REMEMBER_KEY = "remember"

#: How long the CLI waits for the app, which may be waiting on the person.
ANSWER_S = 130.0
#: How long it waits for a sign-in, which the person finishes in the browser.
LOGIN_S = 340.0

_cache: dict[str, tuple[StoredToken | None, str | None]] = {}


class InAgentPane(Exception):
    """Refused: a person's sign-in can't be used or kept from an agent's pane."""


class LoginFailed(Exception):
    """The app couldn't sign in, or the person said no; the message says which."""


def _hub(config: MyceliumConfig) -> str:
    return config.server.api_url.rstrip("/")


def _connect(timeout: float) -> socket.socket | None:
    """A connection to the app, or ``None`` when it isn't here, or when what
    listens isn't the signed app."""
    from mycelium.desktop.session_relay import listener_is_app, socket_path

    path = socket_path()
    if not hasattr(socket, "AF_UNIX") or not path.exists():
        return None
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        conn.settimeout(timeout)
        conn.connect(str(path))
    except OSError:
        conn.close()
        return None
    if listener_is_app(conn) is False:
        conn.close()
        _warn_impostor(path)
        return None
    return conn


def _ask(op: str, hub: str, extra: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Ask the desktop app; ``None`` when it isn't running here."""
    wait = LOGIN_S if op == "login" else ANSWER_S
    conn = _connect(wait)
    if conn is None:
        return None
    request: dict[str, Any] = {"op": op, "hub": hub, **(extra or {})}
    try:
        with conn, conn.makefile("rw", encoding="utf-8") as stream:
            stream.write(json.dumps(request) + "\n")
            stream.flush()
            reply = json.loads(stream.readline() or "null")
    except (OSError, ValueError):
        return None
    return reply if isinstance(reply, dict) else None


def app_running() -> bool:
    """Whether the desktop app is here to keep a sign-in."""
    conn = _connect(2)
    if conn is None:
        return False
    with contextlib.suppress(OSError):
        conn.close()
    return True


def _remembered() -> bool:
    try:
        data = json.loads(token_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and bool(data.get(REMEMBER_KEY))


def unkept_file() -> Path | None:
    """A sign-in file written before the app kept sign-ins (not ``--remember``),
    which the app offers to replace with a sign-in of its own."""
    path = token_path()
    return path if path.exists() and not _remembered() else None


def load(config: MyceliumConfig, *, fresh: bool = False) -> tuple[StoredToken | None, str | None]:
    """The person's session for this hub and where it was kept; ``(None, None)``
    when there is none, or when this is an agent's pane.

    From the app it's an access token alone: the app keeps the refresh token
    and renews it, so a process that got one never holds anything lasting.
    ``fresh`` asks again rather than using what this process already got (an
    access token that ran out)."""
    if caller.in_agent_pane():
        return None, None
    hub = _hub(config)
    if hub in _cache and not fresh:
        return _cache[hub]
    found: tuple[StoredToken | None, str | None] = (None, None)
    reply = _ask("get", hub)
    if reply is not None and reply.get("ok") and isinstance(reply.get("session"), dict):
        found = (StoredToken.from_dict(reply["session"]), APP)
    elif (stored := load_token()) is not None:
        found = (stored, FILE)
        if not _remembered():
            _warn_file()
    _cache[hub] = found
    return found


def login_in_app(config: MyceliumConfig, **login: Any) -> tuple[StoredToken, bool] | None:
    """Have the desktop app sign in to this hub, with ``login``'s issuer,
    client id, scope, audience and redirect port. Returns the access token the
    app hands back and whether the app can renew it; ``None`` when the app
    isn't here. The app keeps the refresh token; nothing here ever sees it."""
    if caller.in_agent_pane():
        msg = "an agent's pane can't sign in as a person"
        raise InAgentPane(msg)
    hub = _hub(config)
    asked = {k: v for k, v in login.items() if v not in (None, "")}
    reply = _ask("login", hub, {"login": asked})
    if reply is None:
        return None
    session = reply.get("session")
    token = StoredToken.from_dict(session) if isinstance(session, dict) else None
    if not reply.get("ok") or token is None:
        raise LoginFailed(str(reply.get("error") or "Mycelium didn't sign in"))
    if not _remembered():
        # A file from before the app made sign-ins: this one replaces it.
        clear_token()
    _cache[hub] = (token, APP)
    return token, bool(reply.get("refreshable"))


def save(config: MyceliumConfig, token: StoredToken, *, remember: bool = False) -> str:
    """Keep a sign-in the CLI made itself (no app here): in a file with
    ``remember``, else for this process only. Returns :data:`FILE` or :data:`HERE`."""
    if caller.in_agent_pane():
        msg = "an agent's pane can't keep a person's sign-in"
        raise InAgentPane(msg)
    where = HERE
    if remember:
        _write_file(token, remember=True)
        where = FILE
    _cache[_hub(config)] = (token, where)
    return where


def _write_file(token: StoredToken, *, remember: bool) -> None:
    """The file, ``0600`` (``tokens.save_token``), saying whether it was kept on purpose."""
    path = save_token(token)
    if remember:
        data = json.loads(path.read_text(encoding="utf-8"))
        data[REMEMBER_KEY] = True
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def renewed(config: MyceliumConfig, token: StoredToken, where: str | None) -> None:
    """Keep a session the CLI renewed itself (a file's) where the old one was.
    The app's sign-ins are renewed by the app."""
    if where == FILE:
        _write_file(token, remember=_remembered())
    _cache[_hub(config)] = (token, where)


def clear(config: MyceliumConfig) -> bool:
    """Forget the session for this hub, wherever it was kept."""
    hub = _hub(config)
    _cache.pop(hub, None)
    reply = _ask("delete", hub)
    removed = clear_token()
    return removed or bool(reply and reply.get("ok"))


_warned = False
_warned_impostor = False


def _warn_file() -> None:
    global _warned  # noqa: PLW0603 - once per process
    if _warned:
        return
    _warned = True
    print(  # noqa: T201
        f"warning: your sign-in is in {token_path()}, which any program running as you can "
        "read, agents included. With Mycelium open, run 'mycelium login' to have Mycelium "
        "keep it instead, or 'mycelium login --remember' to keep the file on purpose.",
        file=sys.stderr,
    )


def _warn_impostor(path: object) -> None:
    global _warned_impostor  # noqa: PLW0603 - once per process
    if _warned_impostor:
        return
    _warned_impostor = True
    print(  # noqa: T201
        f"warning: the program listening at {path} isn't the Mycelium app, so this command "
        "doesn't use it for your sign-in. Quit and reopen Mycelium.",
        file=sys.stderr,
    )
