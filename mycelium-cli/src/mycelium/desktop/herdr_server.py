# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""herdr's server when the program it runs from has been replaced under it.

macOS decides whether a process may read protected folders (``~/Documents``,
``~/Desktop``, ``~/Downloads``) from the code identity of the app responsible
for it. herdr's server keeps running when the app quits, because agents live
in it. So after the app is updated or reinstalled in place, the running server's
program file is a new one, and macOS can refuse that server, and every shell it
started, access to those folders until it restarts. Shells there print
``getcwd: Operation not permitted``.

This finds that case: a server running the app's own herdr, whose program file
was written after the server started. A herdr installed some other way (by
Homebrew, say) is the person's own and is left alone. The file's change time
(``st_ctime``) is used, because an update unpacks files with the times they
were built at, so their modification times can be older than the server.
Restarting stops the server, which ends the agents in it, and starts the same
program again.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

#: How long after the server started its program file may still change
#: without counting as replaced. The change time also moves when only a file's
#: attributes do, which macOS can do around an app's first launch.
SLACK_S = 120.0
#: How long a stopped or started server is waited for.
WAIT_S = 20.0
#: Where a restarted server's output goes.
LOG_PATH = Path.home() / ".mycelium" / "logs" / "herdr.log"
#: The command line a herdr server runs with: ``<program> server``.
SERVER_ARG = " server"


class RestartError(Exception):
    """herdr's server could not be restarted, said as a sentence."""


@dataclass
class Server:
    """A running herdr server: its process, its program and when it started."""

    pid: int
    program: Path
    #: When the process started, in seconds since the epoch.
    started: float

    def replaced_at(self) -> float | None:
        """When its program file was written after the server started, or ``None``.

        A program file that's gone counts as replaced now.
        """
        try:
            st = self.program.stat()
        except FileNotFoundError:
            return time.time()
        except OSError:
            return None
        written = max(st.st_mtime, st.st_ctime)
        return written if written > self.started + SLACK_S else None

    def wire(self) -> dict[str, Any]:
        replaced = self.replaced_at()
        return {
            "pid": self.pid,
            "program": str(self.program),
            "started": _iso(self.started),
            "replaced": _iso(replaced) if replaced is not None else None,
        }


def _iso(stamp: float) -> str:
    return datetime.fromtimestamp(stamp, UTC).isoformat(timespec="seconds")


def parse_ps(output: str) -> list[Server]:
    """The herdr servers in ``ps -axo pid=,lstart=,command=`` output (``LC_ALL=C``)."""
    found: list[Server] = []
    for line in output.splitlines():
        parts = line.split(None, 6)
        if len(parts) < 7 or not parts[0].isdigit():
            continue
        command = parts[6].rstrip()
        if not command.endswith(SERVER_ARG):
            continue
        program = command[: -len(SERVER_ARG)]
        if Path(program).name not in ("herdr", "herdr.exe"):
            continue
        try:
            started = time.mktime(time.strptime(" ".join(parts[1:6]), "%a %b %d %H:%M:%S %Y"))
        except ValueError:
            continue
        if not Path(program).is_absolute():
            program = shutil.which(program) or program
        found.append(Server(pid=int(parts[0]), program=Path(program), started=started))
    return found


def running() -> list[Server]:
    """The herdr servers running on this machine (none on Windows)."""
    if sys.platform == "win32":
        return []
    try:
        out = subprocess.run(
            ["ps", "-axo", "pid=,lstart=,command="],  # noqa: S607 - ps is the system's
            capture_output=True,
            text=True,
            env={**os.environ, "LC_ALL": "C"},
            timeout=5,
            check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return parse_ps(out)


def _same(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


def stale(app_herdr: Path | None) -> Server | None:
    """The herdr server running ``app_herdr`` (the app's own copy), when that
    program was replaced after it started. Other herdr servers, such as one
    from Homebrew, are skipped. ``None`` when there's no app copy to compare
    with, as in a checkout."""
    if app_herdr is None:
        return None
    for server in running():
        if _same(server.program, app_herdr) and server.replaced_at() is not None:
            return server
    return None


def agents_after_restart() -> str:
    """What happens to the agents in herdr when its server restarts, as a sentence."""
    try:
        from mycelium.machine import integrations

        state = integrations()
    except Exception:  # noqa: BLE001 - unknown reads as "they stop"
        state = None
    if state is not None and state.current and not state.missing:
        return (
            "Restarting stops the agents running in it. herdr brings each one back "
            "in its own conversation."
        )
    lost = f" ({', '.join(state.missing)})" if state is not None and state.missing else ""
    return (
        f"Restarting stops the agents running in it{lost}, and herdr can't bring them "
        "back on its own. Start them again from Your agents, or with "
        "`mycelium machine restart`. `mycelium machine integrations --install` makes "
        "herdr bring them back next time."
    )


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait(until: Any, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if until():
            return True
        time.sleep(0.2)
    return bool(until())


def restart(server: Server, start: list[str] | None = None, *, timeout: float = WAIT_S) -> None:
    """Stop ``server`` and start herdr's server again: ``start``, or by default
    the same program it was running.

    Asks the server to stop through its own command first, then signals it if
    it hasn't gone. The new server runs on its own, past whatever started it,
    and writes to :data:`LOG_PATH`.
    """
    start = start or [str(server.program), "server"]
    from mycelium.integrations.herdr import HerdrBridge

    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run(  # noqa: S603 - the server's own program, never a shell string
            [str(server.program), "server", "stop"],
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    if not _wait(lambda: not _alive(server.pid), timeout):
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(server.pid, 15)
        if not _wait(lambda: not _alive(server.pid), timeout):
            raise RestartError(f"herdr's server (pid {server.pid}) didn't stop.")
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with LOG_PATH.open("a") as log:
            subprocess.Popen(  # noqa: S603 - the server's own program, never a shell string
                start,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    except OSError as e:
        raise RestartError(f"herdr's server stopped but didn't start again: {e}") from e
    if not _wait(HerdrBridge().available, timeout):
        raise RestartError(
            f"herdr's server was started again but isn't answering yet. See {LOG_PATH}."
        )
