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

A sign-in is made by the app too (``login``): it runs the browser sign-in
itself and keeps what it gets, so the CLI never holds or sends a refresh
token. A command gets an access token alone.

Any program can also listen where the socket is, so before the CLI believes
an answer it checks who is listening (:func:`listener_is_app`): on macOS, a
program signed by Mycelium whose parent is the signed app.

    request: {"op": "get" | "login" | "delete", "hub": "<origin>", "login": {...}}
    reply:   {"ok": true, "session": {...} | null} or {"ok": false, "error": "..."}
"""

from __future__ import annotations

import contextlib
import itertools
import json
import os
import socket
import struct
import subprocess
import sys
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
#: How long a sign-in may take, in the browser, after the question.
LOGIN_S = 330.0
#: Who signs the desktop app (its Developer ID team) and the app's own id.
APP_TEAM = "4U24U28B5M"
APP_ID = "io.mycelium.desktop"
#: Set by someone running an unsigned build of the app (development), so the
#: CLI talks to it without the signature check.
UNSIGNED_APP_ENV = "MYCELIUM_DESKTOP_UNSIGNED"
#: macOS's level and option for the peer's pid on a Unix socket.
_SOL_LOCAL, _LOCAL_PEERPID = 0, 0x002
#: How much of a command line the app's question shows.
COMMAND_CHARS = 80


def peer_pid(conn: socket.socket) -> int | None:
    """The pid of the process on the other end of ``conn``, as the kernel says."""
    try:
        if sys.platform == "darwin":
            return struct.unpack("i", conn.getsockopt(_SOL_LOCAL, _LOCAL_PEERPID, 4))[0]
        so_peercred = getattr(socket, "SO_PEERCRED", None)
        if so_peercred is not None:
            raw = conn.getsockopt(socket.SOL_SOCKET, so_peercred, struct.calcsize("3i"))
            return struct.unpack("3i", raw)[0]
    except OSError:
        return None
    return None


def _signed(pid: int, requirement: str) -> bool:
    """Whether the running process ``pid`` satisfies a code requirement. The
    system checks the code it is running, not a file that could be swapped;
    its resources aren't checked, since the UI server's cache writes there."""
    try:
        done = subprocess.run(  # noqa: S603 - codesign by absolute path, a pid from the kernel
            ["/usr/bin/codesign", "--verify", "--ignore-resources", f"-R={requirement}", str(pid)],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return done.returncode == 0


def _parent(pid: int) -> int | None:
    try:
        out = subprocess.run(  # noqa: S603 - ps by absolute path, a pid from the kernel
            ["/bin/ps", "-o", "ppid=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None
    return int(out) if out.isdigit() else None


def listener_is_app(conn: socket.socket) -> bool | None:
    """Whether what listens on the other end of ``conn`` is the desktop app's
    supervisor: a program Mycelium signed, started by the signed app.

    ``True`` or ``False`` on macOS, where the system can tell; ``None`` where it
    can't (the check is skipped there, and for an unsigned development build
    when :data:`UNSIGNED_APP_ENV` is set)."""
    if sys.platform != "darwin" or os.environ.get(UNSIGNED_APP_ENV) == "1":
        return None
    pid = peer_pid(conn)
    if pid is None:
        return False
    team = f'anchor apple generic and certificate leaf[subject.OU] = "{APP_TEAM}"'
    if not _signed(pid, team):
        return False
    parent = _parent(pid)
    return parent is not None and _signed(parent, f'{team} and identifier "{APP_ID}"')


def describe_peer(conn: socket.socket) -> dict[str, str | None]:
    """What's asking: its command (from ``mycelium`` on), its folder and its
    terminal. A process that has no terminal (an agent's background job, a
    script) gets ``tty: None``, which the app never gives grace to."""
    pid = peer_pid(conn)
    if pid is None:
        return {"command": None, "cwd": None, "tty": None}
    command = tty = cwd = None
    try:
        out = subprocess.run(  # noqa: S603 - ps by absolute path, a pid from the kernel
            ["/bin/ps", "-o", "tty=", "-o", "command=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout.strip()
        if out:
            first, _, rest = out.partition(" ")
            tty = None if first.strip("?-") == "" else first
            command = shown_command(rest.strip())
    except (OSError, subprocess.TimeoutExpired):
        pass
    cwd = _cwd_of(pid)
    return {"command": command, "cwd": cwd, "tty": tty}


def shown_command(command_line: str) -> str:
    """A command line as a person reads it: from ``mycelium`` on, without the
    interpreter and path in front, cut to :data:`COMMAND_CHARS`."""
    words = command_line.split()
    for i, word in enumerate(words):
        if Path(word).name == "mycelium":
            words = ["mycelium", *words[i + 1 :]]
            break
    shown = " ".join(words)
    return shown if len(shown) <= COMMAND_CHARS else shown[: COMMAND_CHARS - 1] + "…"


def _cwd_of(pid: int) -> str | None:
    proc = Path(f"/proc/{pid}/cwd")
    try:
        if proc.exists():
            return _homed(str(proc.resolve()))
        out = subprocess.run(  # noqa: S603 - lsof by absolute path, a pid from the kernel
            ["/usr/sbin/lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    folder = next((line[1:] for line in out.splitlines() if line.startswith("n")), None)
    return _homed(folder) if folder else None


def _homed(path: str) -> str:
    home = str(Path.home())
    return "~" + path[len(home) :] if path == home or path.startswith(home + "/") else path


#: The operations a request may name.
OPS = frozenset({"get", "login", "delete"})
#: What a ``login`` request may say, and the type each must be.
LOGIN_FIELDS = {
    "issuer": str,
    "client_id": str,
    "scope": str,
    "audience": str,
    "redirect_port": int,
}


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
        caller = describe_peer(conn)
        # A caller that hung up (one only checking the app is here) gets nothing.
        with contextlib.suppress(OSError), conn, conn.makefile("rw", encoding="utf-8") as stream:
            reply = self._handle(stream.readline(), caller)
            stream.write(json.dumps(reply) + "\n")
            stream.flush()

    def _handle(self, line: str, caller: dict[str, str | None] | None = None) -> dict[str, Any]:
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
        # Who's asking, as the system says (never as the request says): the app
        # names it in its question and keeps a yes to that one terminal.
        event["caller"] = caller or {"command": None, "cwd": None, "tty": None}
        if op == "login":
            asked = request.get("login") if isinstance(request.get("login"), dict) else {}
            event["login"] = {
                k: asked[k] for k, kind in LOGIN_FIELDS.items() if isinstance(asked.get(k), kind)
            }
        self.emit(event)
        try:
            if not done.wait(LOGIN_S if op == "login" else ANSWER_S):
                return {"ok": False, "error": "Mycelium didn't answer in time"}
            reply = slot[0]
        finally:
            with self._lock:
                self._waiting.pop(rid, None)
        return {"ok": bool(reply.get("ok")), "session": reply.get("session"),
                "refreshable": bool(reply.get("refreshable")),
                "error": reply.get("error")}  # fmt: skip
