# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The person's own widgets, run by the desktop app on this computer.

What runs is only ever what ``[statusline]`` in this computer's
``~/.mycelium/config.toml`` says (``config.StatuslineConfig``). Nothing from a
room, the hub or another member reaches it, and the app's pages read the
results without being able to name a command. Each widget's command runs every
``every`` on a thread of its own, never twice at once; the first line it prints
is its value, unless it prints one JSON object, whose fields set its text and
look for that run (``read_output``). A run that exits non-zero has failed, and
one still running after ``timeout`` is stopped, with whatever it started, and
counts as hung.

A widget with ``every = "always"`` is kept running instead (:class:`Kept`):
started with the app and stopped with it, with whatever it started, and
started again when it exits, waiting longer each time it exits quickly. Its
value is the last line it printed, on either output; once it has stopped, the
last line it printed to stderr says why. It is also started again when the hub moves to
another port, since every command is given that port as ``$MYCELIUM_HUB_PORT``.
What it started is written down (``desktop-widgets.json``), so a later run of
the app stops what one that ended without stopping left running.

The file is read again when it changes, so editing it takes effect without a
restart. A file that doesn't parse runs nothing and says why.
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

import toml
from pydantic import ValidationError

from mycelium.config import WIDGET_LOOK, StatuslineConfig, StatusWidget, widget_look

#: The event the supervisor sends the app with every change.
EVENT = "widgets"
#: How much of the first line a value or an error keeps.
LINE_CHARS = 200
#: The variable every widget command is given the hub's port in.
HUB_PORT_ENV = "MYCELIUM_HUB_PORT"
#: How long a command kept running waits to be started again after it exits:
#: the first wait, doubled each time it exits quickly, up to the most.
RESTART_FIRST_S = 1.0
RESTART_MOST_S = 60.0
#: A command that ran this long before it exited waits only the first wait.
STEADY_S = 60.0
#: How long a command kept running is given to stop when asked, before it's killed.
STOP_GRACE_S = 2.0
#: How long after it starts a kept command's command line is read, to know it again.
SEEN_AFTER_S = 1.0
#: Where the commands kept running are written down, beside ``config.toml``.
KEPT_FILE = "desktop-widgets.json"


@dataclass
class Run:
    """How a widget's last run went."""

    ok: bool
    #: The first line it printed, or the ``text`` of the JSON it printed. For a
    #: command kept running, the last line it printed.
    value: str | None = None
    #: The look fields its JSON set for this run, over the config's.
    fields: dict[str, Any] = field(default_factory=dict)
    #: Why a field it printed was left out.
    notes: list[str] = field(default_factory=list)
    exit: int | None = None
    timed_out: bool = False
    #: The first line of what it printed to stderr, when it failed. For a
    #: command kept running, the last line, once it has stopped.
    error: str | None = None
    #: When it finished, as an ISO time; for a command kept running and
    #: running now, when it started.
    ran_at: str | None = None
    #: Whether it's running now: only a command kept running is.
    running: bool = False


def default_path() -> Path:
    return Path.home() / ".mycelium" / "config.toml"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _first_line(text: str) -> str | None:
    line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    return line[:LINE_CHARS] or None


def read_output(out: str) -> Run:
    """A successful run's output: one JSON object sets its text and look for
    the run; anything else is plain, and its first line is the text."""
    stripped = out.strip()
    if stripped.startswith("{"):
        try:
            printed = json.loads(stripped)
        except ValueError as e:
            # Shown as plain text, as it would be anyway, with why it wasn't read.
            note = f"What it printed starts like JSON but isn't: {e}. Shown as plain text."
            return Run(ok=True, value=_first_line(out), exit=0, notes=[note[:LINE_CHARS]])
        if isinstance(printed, dict):
            fields, notes = widget_look(printed)
            text = printed.get("text")
            if text is not None and not isinstance(text, str):
                notes.append(f"text {str(text)[:40]!r} was ignored: it should be text.")
                text = None
            unknown = sorted(k for k in printed if k != "text" and k not in WIDGET_LOOK)
            if unknown:
                notes.append(f"{', '.join(unknown)} isn't a widget field, so it was ignored.")
            return Run(
                ok=True,
                exit=0,
                value=_first_line(text) if text else None,
                fields=fields,
                notes=notes,
            )
    return Run(ok=True, value=_first_line(out), exit=0)


def _first_problem(e: ValidationError) -> str:
    """The first thing wrong, said as the person wrote it: which widget, which key."""
    err = e.errors()[0]
    where = [str(p) for p in err["loc"]]
    if len(where) >= 2 and where[0] == "widget" and where[1].isdigit():
        where = [f"widget {int(where[1]) + 1}", *where[2:]]
    msg = err["msg"].removeprefix("Value error, ")
    # A whole-widget check already names the widget by its label.
    return f"{' '.join(where)}: {msg}" if where and not msg.startswith("widget ") else msg


def _env(hub_port: int | None = None) -> dict[str, str]:
    """This process's environment, with the folders a terminal usually adds
    after its PATH, since the app starts without a terminal's PATH, and the
    hub's port when the app runs one."""
    from mycelium.runner.frameworks import install_dirs

    env = dict(os.environ)
    extra = [str(d) for d in install_dirs() if d.is_dir()]
    env["PATH"] = os.pathsep.join([env.get("PATH", os.defpath), *extra])
    if hub_port is not None:
        env[HUB_PORT_ENV] = str(hub_port)
    return env


def _stop_tree(proc: subprocess.Popen) -> None:
    """Stop ``proc`` and everything it started: its process group on macOS and
    Linux, its process tree on Windows (where killing the shell alone would
    leave what it started running)."""
    if sys.platform == "win32":
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run(  # noqa: S603 - a fixed command on the pid we started
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],  # noqa: S607 - Windows' own
                capture_output=True,
                timeout=10,
                check=False,
            )
    else:
        with contextlib.suppress(OSError):
            os.killpg(proc.pid, signal.SIGKILL)
    with contextlib.suppress(OSError):
        proc.kill()


def _popen(command: str, env: dict[str, str] | None) -> subprocess.Popen:
    """Start ``command`` in the shell, in a process group of its own, so it
    can be stopped with what it started."""
    return subprocess.Popen(  # noqa: S602 - the person's own command, from their own file
        command,
        shell=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env if env is not None else _env(),
        start_new_session=sys.platform != "win32",
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )


def run_command(command: str, timeout: float, env: dict[str, str] | None = None) -> Run:
    """Run ``command`` in the shell, stopping it (and what it started) after ``timeout``."""
    try:
        proc = _popen(command, env)
    except OSError as e:
        return Run(ok=False, error=str(e)[:LINE_CHARS])
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _stop_tree(proc)
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.communicate(timeout=5)
        return Run(ok=False, timed_out=True)
    if proc.returncode != 0:
        return Run(ok=False, exit=proc.returncode, error=_first_line(err))
    return read_output(out)


class Kept:
    """A command kept running (``every = "always"``), and the last line it
    printed on each of its outputs."""

    def __init__(self, proc: subprocess.Popen, *, port: int | None, started: float) -> None:
        self.proc = proc
        #: The hub's port it was given.
        self.port = port
        #: When it started, by the widgets' clock and as an ISO time.
        self.started = started
        self.started_at = _now()
        #: The last line it printed on either output, and on stderr alone.
        self.out: str | None = None
        self.err: str | None = None
        #: Whether it printed a line since the app was last told.
        self.news = False
        #: Its command line once it's running, to know it again in a later run
        #: of the app; ``""`` when it couldn't be read.
        self.seen: str | None = None
        self._readers = [
            threading.Thread(target=self._read, args=(s, name), daemon=True)
            for s, name in ((proc.stdout, "out"), (proc.stderr, "err"))
            if s is not None
        ]
        for reader in self._readers:
            reader.start()

    def _read(self, stream: IO[str], which: str) -> None:
        with contextlib.suppress(OSError, ValueError):
            for line in stream:
                if text := line.strip()[:LINE_CHARS]:
                    # A program like ssh -N says everything on stderr, a
                    # warning while it runs included, so the row shows both.
                    self.out = text
                    if which == "err":
                        self.err = text
                    self.news = True

    def drain(self, timeout: float = 1.0) -> None:
        """Wait for what it printed before it exited to be read."""
        for reader in self._readers:
            reader.join(timeout)

    def stop(self) -> None:
        """Ask it to stop, then stop it and everything it started."""
        if self.proc.poll() is None and sys.platform != "win32":
            with contextlib.suppress(OSError):
                os.killpg(self.proc.pid, signal.SIGTERM)
            with contextlib.suppress(subprocess.TimeoutExpired):
                self.proc.wait(STOP_GRACE_S)
        _stop_tree(self.proc)
        with contextlib.suppress(subprocess.TimeoutExpired):
            self.proc.wait(5)
        self.drain(0.5)

    def run(self) -> Run:
        """How it's going, for the app: running, and the last line it printed."""
        return Run(ok=True, running=True, value=self.out, ran_at=self.started_at)


class Widgets:
    """The widgets in ``path``, run on their intervals, or kept running, by
    :meth:`tick`. The supervisor sets :attr:`hub_port` to its hub's port."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        run: Any = run_command,
        keep: Any = _popen,
        clock: Any = time.monotonic,
        kept_path: Path | None = None,
    ) -> None:
        self.path = path or default_path()
        self.kept_path = kept_path or self.path.parent / KEPT_FILE
        self._run = run
        self._keep_cmd = keep
        self._clock = clock
        self._lock = threading.Lock()
        self._mtime: float | None = None
        self.widgets: list[StatusWidget] = []
        self.error: str | None = None
        #: The port of the hub the app runs, given to every command; ``None``
        #: when it runs none.
        self.hub_port: int | None = None
        #: By position, since a label can repeat.
        self._runs: dict[int, Run] = {}
        self._due: dict[int, float] = {}
        self._running: set[int] = set()
        #: The commands kept running, and when and how long each waits to start again.
        self._kept: dict[int, Kept] = {}
        self._restart_at: dict[int, float] = {}
        self._wait: dict[int, float] = {}
        self._leftovers_stopped = False
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
            except ValidationError as e:
                error = f"[statusline] in {self.path} isn't valid: {_first_problem(e)}"
            except Exception as e:  # noqa: BLE001 - a bad file runs nothing and says why
                error = f"[statusline] in {self.path} isn't valid: {e}".splitlines()[0]
        with self._lock:
            if [w.model_dump() for w in widgets] != [w.model_dump() for w in self.widgets]:
                # A command kept running whose widget changed or went is stopped;
                # one whose widget is the same keeps running where it is.
                for n in list(self._kept):
                    if n >= len(widgets) or widgets[n] != self.widgets[n]:
                        self._kept.pop(n).stop()
                self._write_kept()
                self._runs.clear()
                self._due.clear()
                self._restart_at.clear()
                self._wait.clear()
            self.widgets, self.error = widgets, error
            self._changed = True

    def tick(self) -> bool:
        """Start every command that's due, and keep the ones kept running up;
        ``True`` when there's news to send."""
        if not self._leftovers_stopped:
            self._leftovers_stopped = True
            self._stop_leftovers()
        self._load()
        now = self._clock()
        with self._lock:
            for n, widget in enumerate(self.widgets):
                if widget.command is None:
                    continue
                if widget.always():
                    self._keep(n, widget, now)
                    continue
                if n in self._running or now < self._due.get(n, 0.0):
                    continue
                self._running.add(n)
                self._due[n] = now + widget.seconds()
                threading.Thread(
                    target=self._run_one,
                    args=(n, widget, _env(self.hub_port)),
                    name=f"widget-{n}",
                    daemon=True,
                ).start()
            changed, self._changed = self._changed, False
        return changed

    def _keep(self, n: int, widget: StatusWidget, now: float) -> None:
        """Keep widget ``n``'s command running: note what it printed, start it
        again after a wait when it has exited, and at once when the hub moved."""
        kept = self._kept.get(n)
        if kept is not None:
            code = kept.proc.poll()
            if code is None and kept.port == self.hub_port:
                if kept.news:
                    kept.news, self._changed = False, True
                if kept.seen is None and now - kept.started >= SEEN_AFTER_S:
                    from mycelium.desktop.supervisor import command_of

                    kept.seen = command_of(kept.proc.pid) or ""
                    self._write_kept()
                return
            del self._kept[n]
            if code is None:
                # The hub is on another port now: started again with the new one.
                kept.stop()
                self._wait.pop(n, None)
            else:
                kept.drain()
                self._stopped(n, now, ran_for=now - kept.started)
                self._runs[n] = Run(ok=False, exit=code, error=kept.err, ran_at=_now())
            self._write_kept()
            self._changed = True
        if now < self._restart_at.get(n, 0.0):
            return
        try:
            proc = self._keep_cmd(widget.command, _env(self.hub_port))
        except OSError as e:
            self._stopped(n, now, ran_for=0.0)
            self._runs[n] = Run(ok=False, error=str(e)[:LINE_CHARS], ran_at=_now())
            self._changed = True
            return
        self._kept[n] = Kept(proc, port=self.hub_port, started=now)
        self._runs.pop(n, None)
        self._write_kept()
        self._changed = True

    def _stopped(self, n: int, now: float, *, ran_for: float) -> None:
        """When widget ``n``'s command starts again: after the first wait if it
        ran steadily, else after twice the last wait, up to the most."""
        last = 0.0 if ran_for >= STEADY_S else self._wait.get(n, 0.0)
        wait = min(max(last * 2, RESTART_FIRST_S), RESTART_MOST_S)
        self._wait[n] = wait
        self._restart_at[n] = now + wait

    def _write_kept(self) -> None:
        """Write down what's kept running, for a later run of the app to stop."""
        entries = [{"pid": k.proc.pid, "command": k.seen} for k in self._kept.values() if k.seen]
        with contextlib.suppress(OSError):
            if not entries:
                self.kept_path.unlink(missing_ok=True)
                return
            self.kept_path.parent.mkdir(parents=True, exist_ok=True)
            self.kept_path.write_text(json.dumps({"kept": entries}, indent=2) + "\n")

    def _stop_leftovers(self) -> None:
        """Stop what an earlier run of the app kept running and didn't stop,
        as when it was killed: only a pid still running the same command line,
        so one reused since by another program is left alone."""
        try:
            entries = json.loads(self.kept_path.read_text()).get("kept") or []
        except (OSError, ValueError, AttributeError):
            return
        from mycelium.desktop.supervisor import command_of, stop_pid

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            pid, command = entry.get("pid"), entry.get("command")
            if not isinstance(pid, int) or pid <= 0 or pid == os.getpid() or not command:
                continue
            if command_of(pid) == command:
                stop_pid(pid, grace_s=STOP_GRACE_S)
        with contextlib.suppress(OSError):
            self.kept_path.unlink(missing_ok=True)

    def stop(self) -> None:
        """Stop every command kept running, as the app stops."""
        with self._lock:
            kept, self._kept = list(self._kept.values()), {}
        for k in kept:
            k.stop()
        with contextlib.suppress(OSError):
            self.kept_path.unlink(missing_ok=True)

    def _run_one(self, n: int, widget: StatusWidget, env: dict[str, str]) -> None:
        run = self._run(widget.command, widget.timeout, env)
        run.ran_at = _now()
        with self._lock:
            self._running.discard(n)
            if n < len(self.widgets) and self.widgets[n] == widget:
                self._runs[n] = run
                self._changed = True

    def snapshot(self) -> dict[str, Any]:
        """The event the app is sent: the file, any error, and each widget with
        its last run (``None`` before its first, and for fixed text); a command
        kept running and running now, with the last line it printed."""
        with self._lock:
            runs = {**self._runs, **{n: k.run() for n, k in self._kept.items()}}
            return {
                "type": EVENT,
                "config": str(self.path),
                "error": self.error,
                "widgets": [
                    {**w.model_dump(), "run": asdict(runs[n]) if n in runs else None}
                    for n, w in enumerate(self.widgets)
                ],
            }
