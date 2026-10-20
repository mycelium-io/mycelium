# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Where a person's sign-in (``mycelium login``) is kept, and who may use it.

Every agent on this machine runs as the same user as the person, so a sign-in
in a file the CLI reads is one every agent can read and act as. So:

- **The desktop app keeps it.** The CLI asks the app for it
  (``desktop.session_relay``), and the app asks the person first (Touch ID or
  their password on macOS, a dialog elsewhere), with a short grace so several
  commands in a row ask once. An agent can't answer that question.
- **Inside an agent's pane the person's sign-in is never used**
  (``caller.in_agent_pane``): an agent acts with its own credentials only.
- **Without the app** nothing is kept, and ``mycelium login`` says to open
  Mycelium. ``mycelium login --remember`` writes it to a file (``0600``) with a
  warning that any program running as this user can read it, for a server
  where the operator decides that's acceptable.

A file written before this, without ``--remember``, is moved into the app's
keeping the first time the app is there to take it, and deleted.
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
    from mycelium.config import MyceliumConfig

#: Where the session came from: the app, a remembered file, or this process.
APP, FILE, HERE = "app", "file", "here"

#: The key a remembered file carries, so an older file reads as one to move.
REMEMBER_KEY = "remember"

#: How long the CLI waits for the app, which may be waiting on the person.
ANSWER_S = 130.0

_cache: dict[str, tuple[StoredToken | None, str | None]] = {}


class InAgentPane(Exception):
    """Refused: a person's sign-in can't be used or kept from an agent's pane."""


def _hub(config: MyceliumConfig) -> str:
    return config.server.api_url.rstrip("/")


def _ask(op: str, hub: str, session: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Ask the desktop app; ``None`` when it isn't running here."""
    from mycelium.desktop.session_relay import socket_path

    path = socket_path()
    if not hasattr(socket, "AF_UNIX") or not path.exists():
        return None
    request: dict[str, Any] = {"op": op, "hub": hub}
    if session is not None:
        request["session"] = session
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(ANSWER_S)
            conn.connect(str(path))
            with conn.makefile("rw", encoding="utf-8") as stream:
                stream.write(json.dumps(request) + "\n")
                stream.flush()
                reply = json.loads(stream.readline() or "null")
    except (OSError, ValueError):
        return None
    return reply if isinstance(reply, dict) else None


def app_running() -> bool:
    """Whether the desktop app is here to keep a sign-in."""
    from mycelium.desktop.session_relay import socket_path

    path = socket_path()
    if not hasattr(socket, "AF_UNIX") or not path.exists():
        return False
    with contextlib.suppress(OSError), socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(2)
        s.connect(str(path))
        return True
    return False


def _remembered() -> bool:
    try:
        data = json.loads(token_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and bool(data.get(REMEMBER_KEY))


def load(config: MyceliumConfig) -> tuple[StoredToken | None, str | None]:
    """The person's session for this hub and where it was kept; ``(None, None)``
    when there is none, or when this is an agent's pane."""
    if caller.in_agent_pane():
        return None, None
    hub = _hub(config)
    if hub in _cache:
        return _cache[hub]
    found: tuple[StoredToken | None, str | None] = (None, None)
    reply = _ask("get", hub)
    if reply is not None and reply.get("ok") and isinstance(reply.get("session"), dict):
        found = (StoredToken.from_dict(reply["session"]), APP)
    else:
        stored = load_token()
        if stored is not None:
            if not _remembered() and reply is not None:
                # From before the app kept sign-ins: hand it over, then remove
                # the file any program could read.
                moved = _ask("put", hub, stored.to_dict())
                if moved is not None and moved.get("ok"):
                    clear_token()
                    found = (stored, APP)
                else:
                    found = (stored, FILE)
            else:
                found = (stored, FILE)
                if not _remembered():
                    _warn_file()
    _cache[hub] = found
    return found


def save(config: MyceliumConfig, token: StoredToken, *, remember: bool = False) -> str:
    """Keep ``token`` for this hub; returns where (:data:`APP`, :data:`FILE` or :data:`HERE`)."""
    if caller.in_agent_pane():
        msg = "an agent's pane can't keep a person's sign-in"
        raise InAgentPane(msg)
    hub = _hub(config)
    reply = _ask("put", hub, token.to_dict())
    if reply is not None and reply.get("ok"):
        clear_token()
        where = APP
    elif remember:
        _write_file(token, remember=True)
        where = FILE
    else:
        where = HERE
    _cache[hub] = (token, where)
    return where


def _write_file(token: StoredToken, *, remember: bool) -> None:
    """The file, ``0600`` (``tokens.save_token``), saying whether it was kept on purpose."""
    path = save_token(token)
    if remember:
        data = json.loads(path.read_text(encoding="utf-8"))
        data[REMEMBER_KEY] = True
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def renewed(config: MyceliumConfig, token: StoredToken, where: str | None) -> None:
    """Keep a renewed session where the old one was."""
    hub = _hub(config)
    if where == APP:
        _ask("put", hub, token.to_dict())
    elif where == FILE:
        _write_file(token, remember=_remembered())
    _cache[hub] = (token, where)


def clear(config: MyceliumConfig) -> bool:
    """Forget the session for this hub, wherever it was kept."""
    hub = _hub(config)
    _cache.pop(hub, None)
    reply = _ask("delete", hub)
    removed = clear_token()
    return removed or bool(reply and reply.get("ok"))


_warned = False


def _warn_file() -> None:
    global _warned  # noqa: PLW0603 - once per process
    if _warned:
        return
    _warned = True
    print(  # noqa: T201
        f"warning: your sign-in is in {token_path()}, which any program running as you can "
        "read, agents included. Open Mycelium to keep it there instead, or run "
        "'mycelium login --remember' to keep the file on purpose.",
        file=sys.stderr,
    )
