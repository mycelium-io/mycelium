# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The person's own widgets, run by the desktop app on this computer.

What runs is only ever what ``[statusline]`` in this computer's
``~/.mycelium/config.toml`` says (``config.StatuslineConfig``). Nothing from a
room, the hub or another member reaches it, and the app's pages read the
results without being able to name a command. Each widget's command runs every
``every`` on a thread of its own, never twice at once; the first line it prints
is its value. A run that exits non-zero has failed, and one still running after
``timeout`` is stopped, with whatever it started, and counts as hung.

The file is read again when it changes, so editing it takes effect without a
restart. A file that doesn't parse runs nothing and says why.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import toml

from mycelium.config import StatuslineConfig, StatusWidget

#: The event the supervisor sends the app with every change.
EVENT = "widgets"
#: How much of the first line a value or an error keeps.
LINE_CHARS = 200


@dataclass
class Run:
    """How a widget's last run went."""

    ok: bool
    #: The first line it printed.
    value: str | None = None
    exit: int | None = None
    timed_out: bool = False
    #: The first line of what it printed to stderr, when it failed.
    error: str | None = None
    #: When it finished, as an ISO time.
    ran_at: str | None = None


def default_path() -> Path:
    return Path.home() / ".mycelium" / "config.toml"


def _first_line(text: str) -> str | None:
    line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    return line[:LINE_CHARS] or None


def _env() -> dict[str, str]:
    """This process's environment, with the folders a terminal usually adds
    after its PATH, since the app starts without a terminal's PATH."""
    from mycelium.runner.frameworks import install_dirs

    env = dict(os.environ)
    extra = [str(d) for d in install_dirs() if d.is_dir()]
    env["PATH"] = os.pathsep.join([env.get("PATH", os.defpath), *extra])
    return env


def run_command(command: str, timeout: float) -> Run:
    """Run ``command`` in the shell, stopping it (and what it started) after ``timeout``."""
    try:
        proc = subprocess.Popen(  # noqa: S602 - the person's own command, from their own file
            command,
            shell=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_env(),
            # Its own process group, so a hung run is stopped with what it started.
            start_new_session=sys.platform != "win32",
        )
    except OSError as e:
        return Run(ok=False, error=str(e)[:LINE_CHARS])
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        if sys.platform != "win32":
            with contextlib.suppress(OSError):
                os.killpg(proc.pid, signal.SIGKILL)
        proc.kill()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.communicate(timeout=5)
        return Run(ok=False, timed_out=True)
    if proc.returncode != 0:
        return Run(ok=False, exit=proc.returncode, error=_first_line(err))
    return Run(ok=True, value=_first_line(out), exit=0)


class Widgets:
    """The widgets in ``path``, run on their intervals by :meth:`tick`."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        run: Any = run_command,
        clock: Any = time.monotonic,
    ) -> None:
        self.path = path or default_path()
        self._run = run
        self._clock = clock
        self._lock = threading.Lock()
        self._mtime: float | None = None
        self.widgets: list[StatusWidget] = []
        self.error: str | None = None
        #: By position, since a label can repeat.
        self._runs: dict[int, Run] = {}
        self._due: dict[int, float] = {}
        self._running: set[int] = set()
        self._changed = True

    def _load(self) -> None:
        """Read the file again when it has changed since the last read."""
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            mtime = None
        if mtime == self._mtime:
            return
        self._mtime = mtime
        widgets: list[StatusWidget] = []
        error = None
        if mtime is not None:
            try:
                raw = toml.loads(self.path.read_text(encoding="utf-8")).get("statusline") or {}
                widgets = StatuslineConfig.model_validate(raw).widget
            except Exception as e:  # noqa: BLE001 - a bad file runs nothing and says why
                error = f"[statusline] in {self.path} isn't valid: {e}".splitlines()[0]
        with self._lock:
            if [w.model_dump() for w in widgets] != [w.model_dump() for w in self.widgets]:
                self._runs.clear()
                self._due.clear()
            self.widgets, self.error = widgets, error
            self._changed = True

    def tick(self) -> bool:
        """Start every command that's due; ``True`` when there's news to send."""
        self._load()
        now = self._clock()
        with self._lock:
            for n, widget in enumerate(self.widgets):
                if widget.command is None or n in self._running:
                    continue
                if now < self._due.get(n, 0.0):
                    continue
                self._running.add(n)
                self._due[n] = now + widget.seconds()
                threading.Thread(
                    target=self._run_one, args=(n, widget), name=f"widget-{n}", daemon=True
                ).start()
            changed, self._changed = self._changed, False
        return changed

    def _run_one(self, n: int, widget: StatusWidget) -> None:
        run = self._run(widget.command, widget.timeout)
        run.ran_at = datetime.now(UTC).isoformat(timespec="seconds")
        with self._lock:
            self._running.discard(n)
            if n < len(self.widgets) and self.widgets[n] == widget:
                self._runs[n] = run
                self._changed = True

    def snapshot(self) -> dict[str, Any]:
        """The event the app is sent: the file, any error, and each widget with
        its last run (``None`` before its first, and for fixed text)."""
        with self._lock:
            return {
                "type": EVENT,
                "config": str(self.path),
                "error": self.error,
                "widgets": [
                    {**w.model_dump(), "run": asdict(self._runs[n]) if n in self._runs else None}
                    for n, w in enumerate(self.widgets)
                ],
            }
