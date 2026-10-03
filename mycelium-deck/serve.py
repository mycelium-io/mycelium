#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors
# /// script
# requires-python = ">=3.10"
# ///
"""Serve the deck with live terminals.

    uv run mycelium-deck/serve.py [--cwd DIR] [--app URL] [--port 8765] [--login] [--no-open]

Serves the repository on 127.0.0.1 and gives each terminal in the deck a
real shell on a pseudo-terminal. The shells run as you, in --cwd (the
directory you started in, by default), with your environment, so `mycelium`
there is your own CLI talking to your own hub.

Only this machine can reach it, and every terminal request must carry the
token printed in the URL, so another page open in the browser cannot type
into a shell. Standard library only; macOS and Linux.
"""

from __future__ import annotations

import argparse
import base64
import fcntl
import json
import os
import pty
import re
import secrets
import shutil
import signal
import struct
import sys
import tempfile
import termios
import threading
import webbrowser
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
HISTORY = 256 * 1024  # bytes of output kept per shell, replayed on reconnect
SESSION_ID = re.compile(r"^[a-z0-9-]{1,40}$")

# A plain prompt for the stage: the folder, then a dollar sign.
CLEAN_RC = r"""
[ -f /etc/bashrc ] && . /etc/bashrc >/dev/null 2>&1
PS1='\[\e[2m\]\W\[\e[0m\] \[\e[35m\]$\[\e[0m\] '
PROMPT_COMMAND=
"""


class Shell:
    """One shell on its own pseudo-terminal, with its output kept for replay."""

    def __init__(
        self, argv: list[str], cwd: str, env: dict[str, str], cols: int, rows: int
    ) -> None:
        self.output = bytearray()
        self.offset = 0  # bytes dropped from the front of `output`
        self.alive = True
        self.changed = threading.Condition()
        pid, fd = pty.fork()
        if pid == 0:
            try:
                os.chdir(cwd)
                os.execvpe(argv[0], argv, env)
            finally:
                os._exit(127)
        self.pid, self.fd = pid, fd
        self.resize(cols, rows)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        while True:
            try:
                data = os.read(self.fd, 65536)
            except OSError:
                data = b""
            with self.changed:
                if not data:
                    self.alive = False
                    self.changed.notify_all()
                    break
                self.output += data
                if len(self.output) > HISTORY:
                    cut = len(self.output) - HISTORY
                    del self.output[:cut]
                    self.offset += cut
                self.changed.notify_all()
        try:
            os.waitpid(self.pid, 0)
        except ChildProcessError:
            pass

    def since(self, pos: int, timeout: float) -> tuple[bytes, int, bool]:
        """Output after absolute position `pos`, waiting up to `timeout` for some."""
        with self.changed:
            end = self.offset + len(self.output)
            if pos >= end and self.alive:
                self.changed.wait(timeout)
                end = self.offset + len(self.output)
            start = max(pos, self.offset) - self.offset
            return bytes(self.output[start:]), end, self.alive

    def write(self, data: bytes) -> None:
        if self.alive:
            os.write(self.fd, data)

    def resize(self, cols: int, rows: int) -> None:
        cols, rows = max(20, min(cols, 400)), max(5, min(rows, 200))
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def kill(self) -> None:
        if self.alive:
            try:
                os.kill(self.pid, signal.SIGHUP)
            except ProcessLookupError:
                pass


class Deck:
    def __init__(self, args: argparse.Namespace) -> None:
        self.token = secrets.token_urlsafe(18)
        self.port = args.port
        self.cwd = str(Path(args.cwd).resolve())
        self.shells: dict[str, Shell] = {}
        self.lock = threading.Lock()
        self.env = {**os.environ, "TERM": "xterm-256color", "COLORTERM": "truecolor"}
        self.env.pop("PROMPT_COMMAND", None)
        bash = shutil.which("bash")
        if args.login or not bash:
            self.argv = [os.environ.get("SHELL") or bash or "/bin/sh", "-l"]
        else:
            rc = Path(tempfile.mkdtemp(prefix="mycelium-deck-")) / "bashrc"
            rc.write_text(CLEAN_RC)
            self.argv = [bash, "--noprofile", "--rcfile", str(rc), "-i"]
            self.env["BASH_SILENCE_DEPRECATION_WARNING"] = "1"

    def shell(self, sid: str, cols: int, rows: int) -> Shell:
        with self.lock:
            sh = self.shells.get(sid)
            if sh is None or not sh.alive:
                sh = self.shells[sid] = Shell(self.argv, self.cwd, self.env, cols, rows)
            return sh

    def close(self) -> None:
        for sh in self.shells.values():
            sh.kill()


def handler(deck: Deck) -> type[SimpleHTTPRequestHandler]:
    hosts = {f"127.0.0.1:{deck.port}", f"localhost:{deck.port}"}

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw) -> None:
            super().__init__(*a, directory=str(ROOT), **kw)

        def log_message(self, fmt: str, *args) -> None:
            if not self.path.startswith("/term/"):
                sys.stderr.write("  " + fmt % args + "\n")

        # Requests to /term/ must come to this host by name (no DNS rebinding),
        # from this origin when the browser says one, with the token.
        def _allowed(self) -> dict[str, list[str]] | None:
            query = parse_qs(urlsplit(self.path).query)
            origin = self.headers.get("Origin")
            ok = (
                self.headers.get("Host") in hosts
                and (origin is None or urlsplit(origin).netloc in hosts)
                and secrets.compare_digest(query.get("token", [""])[0], deck.token)
                and SESSION_ID.match(query.get("id", [""])[0])
            )
            if not ok:
                self.send_error(HTTPStatus.FORBIDDEN)
                return None
            return query

        def _body(self) -> bytes:
            n = int(self.headers.get("Content-Length") or 0)
            return self.rfile.read(min(n, 1 << 20))

        def _ok(self, payload: dict | None = None) -> None:
            body = json.dumps(payload or {}).encode()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if not self.path.startswith("/term/"):
                if self.headers.get("Host") not in hosts:
                    self.send_error(HTTPStatus.FORBIDDEN)
                    return
                super().do_GET()
                return
            query = self._allowed()
            if query is None:
                return
            if urlsplit(self.path).path != "/term/stream":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            sh = deck.shells.get(query["id"][0])
            if sh is None:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            pos = 0
            try:
                while True:
                    data, pos, alive = sh.since(pos, 15)
                    if data:
                        self.wfile.write(b"data: " + base64.b64encode(data) + b"\n\n")
                    elif alive:
                        self.wfile.write(b": keep-alive\n\n")
                    if not alive and not data:
                        self.wfile.write(b"event: exit\ndata: \n\n")
                        self.wfile.flush()
                        return
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return

        def do_POST(self) -> None:
            query = self._allowed()
            if query is None:
                return
            sid, path = query["id"][0], urlsplit(self.path).path
            if path == "/term/open":
                size = json.loads(self._body() or b"{}")
                deck.shell(sid, int(size.get("cols", 80)), int(size.get("rows", 24)))
                self._ok()
            elif path in ("/term/input", "/term/resize"):
                sh = deck.shells.get(sid)
                if sh is None:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                if path == "/term/input":
                    sh.write(self._body())
                else:
                    size = json.loads(self._body() or b"{}")
                    sh.resize(int(size.get("cols", 80)), int(size.get("rows", 24)))
                self._ok()
            else:
                self.send_error(HTTPStatus.NOT_FOUND)

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the deck with live terminals.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--cwd", default=os.getcwd(), help="where the shells start (default: here)")
    parser.add_argument(
        "--app", help="the Mycelium app to show in app panes (default: :8080, then :3717)"
    )
    parser.add_argument(
        "--login", action="store_true", help="your own login shell and prompt, not the plain one"
    )
    parser.add_argument(
        "--no-open", action="store_true", help="print the URL without opening a browser"
    )
    args = parser.parse_args()

    deck = Deck(args)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler(deck))
    server.daemon_threads = True
    url = f"http://127.0.0.1:{args.port}/mycelium-deck/index.html?token={deck.token}"
    if args.app:
        url += "&app=" + quote(args.app, safe="")
    print(
        f"\n  Deck with live terminals:\n  {url}\n\n  Shells start in {deck.cwd}. Ctrl-C to stop.\n"
    )
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        deck.close()
        server.server_close()


if __name__ == "__main__":
    main()
