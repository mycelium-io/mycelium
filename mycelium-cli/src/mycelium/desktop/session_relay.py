# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Where the CLI asks for a person's sign-in: the desktop app, through here.

A person's session is kept by the desktop app (in the system keychain), never
in a file the CLI or an agent can read. The CLI asks for it over a socket the
supervisor listens on (:func:`socket_path`, this user's alone), and the
supervisor passes the request to the app as a ``session`` event on stdout. The
app asks the person (Touch ID or their password on macOS, a dialog elsewhere),
then answers on the supervisor's stdin with a line carrying ``session_reply``.

Any program running as this user can reach the socket, agents included. What
it can't do is answer the app's question, which is why the question is asked
on every read after a short grace (the app's to set).

    request: {"op": "get" | "put" | "delete", "hub": "<origin>", "session": {...}}
    reply:   {"ok": true, "session": {...} | null} or {"ok": false, "error": "..."}
"""

from __future__ import annotations

import contextlib
import itertools
import json
import os
import socket
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mycelium.config import MyceliumConfig

def socket_path() -> Path:
    """The socket the CLI connects to, under this user's ``~/.mycelium``."""
    return MyceliumConfig.get_global_config_dir() / "desktop" / "session.sock"

#: How long a request waits for the person to answer the app.
ANSWER_S = 120.0
#: The operations a request may name.
OPS = frozenset({"get", "put", "delete"})


class SessionRelay:
    """Accept the CLI's requests and pass them to the app, one at a time each."""

    def __init__(self, emit: Callable[[dict[str, Any]], None], path: Path | None = None) -> None:
        self.emit = emit
        self.path = path or socket_path()
        self._ids = itertools.count(1)
        self._waiting: dict[int, tuple[threading.Event, list[dict[str, Any]]]] = {}
        self._lock = threading.Lock()
        self._server: socket.socket | None = None

    def start(self) -> bool:
        """Listen on :attr:`path`. ``False`` where this platform has no Unix sockets."""
        if not hasattr(socket, "AF_UNIX"):
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        with contextlib.suppress(FileNotFoundError):
            self.path.unlink()
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        old = os.umask(0o177)
        try:
            server.bind(str(self.path))
        finally:
            os.umask(old)
        server.listen(8)
        self._server = server
        threading.Thread(target=self._accept, name="session-relay", daemon=True).start()
        return True

    def stop(self) -> None:
        if self._server is not None:
            with contextlib.suppress(OSError):
                self._server.close()
            with contextlib.suppress(FileNotFoundError):
                self.path.unlink()

    def answer(self, line: str) -> bool:
        """Take a line from the app's side of stdin; ``True`` if it was a reply."""
        try:
            data = json.loads(line)
        except ValueError:
            return False
        if not isinstance(data, dict) or "session_reply" not in data:
            return False
        with self._lock:
            waiting = self._waiting.get(int(data["session_reply"]))
        if waiting is not None:
            done, slot = waiting
            slot.append(data)
            done.set()
        return True

    def _accept(self) -> None:
        assert self._server is not None  # noqa: S101 - set by start()
        while True:
            try:
                conn, _ = self._server.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn: socket.socket) -> None:
        with conn, conn.makefile("rw", encoding="utf-8") as stream:
            reply = self._handle(stream.readline())
            stream.write(json.dumps(reply) + "\n")
            stream.flush()

    def _handle(self, line: str) -> dict[str, Any]:
        try:
            request = json.loads(line)
        except ValueError:
            return {"ok": False, "error": "not a request"}
        op = request.get("op") if isinstance(request, dict) else None
        hub = request.get("hub") if isinstance(request, dict) else None
        if op not in OPS or not isinstance(hub, str) or not hub:
            return {"ok": False, "error": "not a request"}
        rid = next(self._ids)
        done, slot = threading.Event(), []
        with self._lock:
            self._waiting[rid] = (done, slot)
        event: dict[str, Any] = {"type": "session", "id": rid, "op": op, "hub": hub}
        if op == "put":
            event["session"] = request.get("session")
        self.emit(event)
        try:
            if not done.wait(ANSWER_S):
                return {"ok": False, "error": "Mycelium didn't answer in time"}
            reply = slot[0]
        finally:
            with self._lock:
                self._waiting.pop(rid, None)
        return {"ok": bool(reply.get("ok")), "session": reply.get("session"),
                "error": reply.get("error")}  # fmt: skip
