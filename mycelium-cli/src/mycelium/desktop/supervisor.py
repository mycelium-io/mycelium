# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Run Mycelium on this machine without Docker, and keep it running.

Two modes, which are what the desktop app offers on its first screen:

- **hub**: this machine runs the hub. herdr's server, a SLIM node
  (``slimctl slim start``), the hub's API, the UI server, and the runner, each
  started in order once the one before it answers.
- **client**: another machine runs the hub. herdr's server, the UI server and
  the runner, pointed at it. The window shows this machine's own UI in both
  modes; a hub elsewhere is reached through it, never by showing its pages.

herdr's server is started only when none is running, and is left running
when the supervisor stops: agents live in its panes. So after the app is
updated, the server still running is the old one, and macOS can refuse it and
its terminals access to protected folders such as ``~/Documents``. The
supervisor checks for that once a minute (``herdr_server``), says so in its
status, and asks once per server, through the app, whether to restart it.
herdr is never restarted without a yes, since that stops the agents in it.

Everything the app shows comes from here as JSON lines on stdout (a status
object on every change, log lines, errors), so the app is a window over this
process and the same thing runs from a terminal with ``mycelium desktop
serve``. A process that exits is started again, backing off, and one that
keeps failing is left failed with the reason. A port something else already
answers on counts as running, so the app sits beside a Docker stack rather
than fighting it for its ports. The UI is the exception: the window opens on
it, so one the supervisor didn't start is never used. When its port is taken
the UI goes on another, said in its status, and it counts as running only
once it proves it holds this launch's token (:func:`proves_token`).

Each program's output is a pipe, drained by a thread per program. A program
whose pipe nobody drains blocks on its next write, so a reader survives
anything that happens to a line, one that dies anyway is replaced, and the
events it hands on are written from a thread of their own
(:mod:`mycelium.desktop.events`), never in its way. The hub is also watched
while it runs: when it hasn't answered ``/health`` for :data:`HUNG_S`, the
status says so (``hung``) and the person is asked, once per process, whether
to restart it, with its last lines.

A hub the app didn't start is never used without saying so. Before starting
anything in hub mode the supervisor looks for every hub on this machine
(``mycelium.hubs``), warns when there is more than one, and reports the one
on its port (its owner, version and data folder) in its status. It never
stops one: that hub may be someone's on purpose, so the person decides.

The exception is the app's own, left running by an earlier run. An app that
updates itself in place replaces its files under its running programs without
stopping them, and a hub running the old version over the new files breaks in
odd ways (an import loads the new copy of a library into the old process). So
each program the supervisor starts is written down (:data:`STARTED_FILE`), and
the next supervisor stops what is still running of them before it starts.
A hub on its port running the app's own hub program (from a version that wrote
nothing down) is stopped the same way.

Where each program comes from, first found wins: an environment override,
the app bundle (the directory this binary runs from, and where each platform's
bundle keeps its resources), then a checkout of the repository, then ``PATH``.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import os
import secrets
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import httpx

from mycelium import themes

Mode = Literal["hub", "client"]
State = Literal["starting", "running", "stopped", "failed", "disabled"]

HOST = "127.0.0.1"
SLIM_PORT = 46357
HUB_PORT = 8000
UI_PORT = 3717
#: Tells the UI server its launch token is on its stdin. Only the flag is in the
#: environment; the token is never in one (any program as this user can read it).
UI_TOKEN_STDIN_ENV = "MYCELIUM_UI_TOKEN_STDIN"
#: How long a component may take to answer before it counts as failed.
READY_TIMEOUT_S = 90.0
#: Restarts after a crash wait this long, doubling, up to the last value.
BACKOFF_S = (1.0, 2.0, 4.0, 8.0, 16.0)
#: A component that crashes this many times in a row is left failed.
MAX_RESTARTS = len(BACKOFF_S)
#: What the hub leaves in its data folder before it exits to be restarted with
#: new settings (`contracts/hub-settings.json`'s `restart_marker`).
HUB_RESTART_MARKER = ".hub-restart-requested"
#: The programs a supervisor started and is running (pid and program), in
#: ``~/.mycelium``. An app that updates itself in place replaces its files under
#: them without stopping them, so the next supervisor reads this to stop what
#: was the app's own and start it again from the new files.
STARTED_FILE = "desktop-started.json"
#: How often the supervisor looks at its processes.
TICK_S = 0.5
#: How many lines of each component's output are kept to explain a crash.
TAIL_LINES = 40
#: How many of a program's last lines the log repeats when it stops on its own.
LAST_LINES = 8
#: Everything the supervisor says, for when something goes wrong.
LOG_PATH = Path.home() / ".mycelium" / "logs" / "desktop.log"
#: How often the running herdr server is checked for a replaced program.
HERDR_CHECK_S = 60.0
#: How long the question about restarting herdr waits for an answer.
HERDR_ASK_S = 6 * 3600.0
#: Where the supervisor's own questions to the app are written.
REQUESTS_BASE = Path.home() / ".mycelium" / "desktop"
#: What the app, the log and the health check say about a herdr server from
#: before the app was updated.
STALE_HERDR_WARNING = (
    "herdr, which runs your agents' terminals, was started before Mycelium was "
    "updated. Until it restarts, macOS can refuse it and its terminals access to "
    'folders like Documents, so commands there fail with "Operation not permitted".'
)
#: How often a running program that is watched (the hub) is checked.
WATCH_S = 15.0
#: How long it may go without answering before it counts as stopped.
HUNG_S = 60.0
#: How many of its last lines the question about restarting it shows.
HUNG_LINES = 8


def how_it_exited(code: int) -> str:
    """An exit status said plainly: its code, or the signal that ended it
    (a negative return code, as `subprocess` reports one)."""
    if code < 0:
        try:
            return f"was stopped by {signal.Signals(-code).name}"
        except ValueError:
            return f"was stopped by signal {-code}"
    return f"exited with code {code}"


def hung_warning(name: str) -> str:
    """What the app, the log and the status say about a program that stopped answering."""
    return (
        f"The {name} stopped responding: it hasn't answered for over a minute, so "
        "agents can't read or post. Restarting it usually fixes this."
    )


WINDOWS = sys.platform == "win32"
#: Pi's JavaScript entry point inside the app's resources, which the hub runs
#: on node on Windows (see ``Locator.pi``).
PI_ENTRY = "pi/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js"


class LocateError(Exception):
    """A program the chosen mode needs could not be found, said as a sentence."""


# ── finding the programs ─────────────────────────────────────────────────────


#: The folder the app ships ``mycelium`` in, among its resources: a PyInstaller
#: directory build, which unpacks nothing at run time (#1269).
CLI_DIR = "cli"


def bundle_dir() -> Path | None:
    """Where the app's programs are, when this is a bundled (frozen) build.

    A standalone binary's own folder. The app's ``mycelium`` runs from its
    ``cli`` folder among the resources, so its programs are found from there:
    ``Contents/MacOS`` on a Mac, ``usr/bin`` in an AppImage (resources in
    ``usr/lib/Mycelium``), and the install folder on Windows.
    """
    if not getattr(sys, "frozen", False):
        return None
    return programs_dir(Path(sys.executable).resolve().parent)


def programs_dir(here: Path) -> Path:
    """The app's programs folder, for a ``mycelium`` that runs from ``here``."""
    if here.name != CLI_DIR:
        return here
    resources = here.parent
    if resources.name == "Resources" and resources.parent.name == "Contents":
        return resources.parent / "MacOS"
    if resources.name == "Mycelium" and resources.parent.name == "lib":
        return resources.parent.parent / "bin"
    return resources


def repo_root(start: Path | None = None) -> Path | None:
    """A checkout of the repository this code is running from, for development."""
    env = os.environ.get("MYCELIUM_REPO")
    if env and (Path(env) / "fastapi-backend" / "app" / "main.py").exists():
        return Path(env)
    here = (start or Path(__file__)).resolve()
    for parent in here.parents:
        if (parent / "fastapi-backend" / "app" / "main.py").exists():
            return parent
    return None


def runnable_ui(ui_dir: Path) -> bool:
    """A standalone UI build that can serve pages: its server and its static files."""
    return (ui_dir / "server.js").exists() and (ui_dir / ".next" / "static").is_dir()


@dataclass
class Locator:
    """Where the programs a mode needs are, resolved the same way every time."""

    bundle: Path | None = field(default_factory=bundle_dir)
    repo: Path | None = field(default_factory=repo_root)

    def _bundled(self, name: str) -> Path | None:
        """A file the app carries. Programs sit beside this one; resources are
        there too on Windows, in ``Contents/Resources`` on a Mac, and in
        ``usr/lib/Mycelium`` in a Linux AppImage."""
        if self.bundle is None:
            return None
        places = (
            self.bundle,
            self.bundle.parent / "Resources",
            self.bundle.parent / "lib" / "Mycelium",
        )
        for place in places:
            candidate = place / name
            if candidate.exists():
                return candidate
        return None

    def _program(self, name: str) -> Path | None:
        """A program the app carries, by the name it has on this platform."""
        return self._bundled(f"{name}.exe" if WINDOWS else name)

    def slim(self) -> list[str]:
        exe = (
            os.environ.get("MYCELIUM_SLIMCTL")
            or self._program("slimctl")
            or shutil.which("slimctl")
        )
        if not exe:
            raise LocateError(
                "slimctl isn't installed, so the hub has no SLIM node. "
                "Install it with: brew tap agntcy/slim https://github.com/agntcy/slim.git "
                "&& brew install slimctl"
            )
        return [str(exe), "slim", "start", "--endpoint", f"{HOST}:{SLIM_PORT}"]

    def hub(self) -> tuple[list[str], Path | None]:
        if cmd := os.environ.get("MYCELIUM_HUB_CMD"):
            return shlex.split(cmd), None
        if bundled := self._program("hub/mycelium-hub") or self._program("mycelium-hub"):
            return [str(bundled), "--host", HOST, "--port", str(HUB_PORT)], None
        if self.repo is not None and shutil.which("uv"):
            backend = self.repo / "fastapi-backend"
            argv = ["uv", "run", "--project", str(backend), "uvicorn", "app.main:app"]
            return [*argv, "--host", HOST, "--port", str(HUB_PORT)], backend
        raise LocateError(
            "This build doesn't include the hub, and there's no Mycelium checkout to run "
            "it from. Use the desktop app, or run the hub with Docker (mycelium up)."
        )

    def herdr(self) -> list[str]:
        exe = self._program("herdr") or shutil.which("herdr")
        if not exe:
            raise LocateError(
                "herdr isn't installed, so no agent can start here. See https://herdr.dev"
            )
        return [str(exe), "server"]

    def app_herdr(self) -> Path | None:
        """The app's own herdr, or ``None`` outside the app (a checkout)."""
        return self._program("herdr")

    def app_hub(self) -> Path | None:
        """The app's own hub program, or ``None`` outside the app (a checkout)."""
        return self._program("hub/mycelium-hub") or self._program("mycelium-hub")

    def pi(self) -> str | None:
        """Pi, which the engines think with: the app's own, else one on PATH.

        On Windows the app's Pi is its JavaScript entry point, which the hub
        runs on the app's node (``pi_session.pi_argv``): a batch-file launcher
        would pass every prompt through ``cmd.exe``, which mangles it.
        """
        return (
            os.environ.get("ALIGNER_PI_BINARY")
            or (
                str(bundled)
                if (bundled := self._bundled(PI_ENTRY if WINDOWS else "pi/pi"))
                else None
            )
            or shutil.which("pi")
        )

    def models(self) -> Path:
        """Where the hub's embedding model is: the app's own copy, else a cache it fills.

        The container keeps it at ``/opt/fastembed``, which is no place on a Mac.
        """
        return self._bundled("models") or Path.home() / ".mycelium" / "models"

    def ui(self, port: int = UI_PORT) -> tuple[list[str], Path | None]:
        node = os.environ.get("MYCELIUM_NODE") or self._program("node") or shutil.which("node")
        ui_dir = os.environ.get("MYCELIUM_UI_DIR") or self._bundled("ui")
        if ui_dir and node and runnable_ui(Path(ui_dir)):
            return [str(node), "server.js"], Path(ui_dir)
        if self.repo is not None:
            frontend = self.repo / "mycelium-frontend"
            standalone = frontend / ".next" / "standalone"
            # `next build` leaves the static files beside the standalone
            # server, not in it; without them every page renders blank.
            if node and runnable_ui(standalone):
                return [str(node), "server.js"], standalone
            if shutil.which("pnpm"):
                # `next dev` ignores HOSTNAME and listens on every interface
                # unless told; the hub's UI stays on this machine.
                argv = ["pnpm", "exec", "next", "dev", "-H", HOST, "-p", str(port)]
                return argv, frontend
        raise LocateError(
            "This build doesn't include the UI, and there's no Mycelium checkout to run it from."
        )


# ── one process ──────────────────────────────────────────────────────────────


def _own_group() -> dict[str, Any]:
    """Start a program in a group of its own, so stopping it stops what it started."""
    if WINDOWS:
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _signal_group(proc: subprocess.Popen[str], *, force: bool) -> None:
    """Ask a program and everything it started to stop; ``force`` kills them."""
    if WINDOWS:
        # Windows has no process groups to signal; taskkill walks the tree.
        # Always /F: without it taskkill only asks a window to close, and these
        # programs have none, so a polite ask would just wait out the timeout
        # and push the app past its own stop grace.
        argv = ["taskkill", "/PID", str(proc.pid), "/T", "/F"]
        subprocess.run(argv, capture_output=True, check=False)  # noqa: S603, S607
        return
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, 9 if force else 15)


def command_of(pid: int) -> str | None:
    """The command line running as ``pid``, or ``None`` when nothing is (on
    Windows, its program's file name, which is all ``tasklist`` gives)."""
    if WINDOWS:
        argv = ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"]
    else:
        argv = ["ps", "-o", "command=", "-p", str(pid)]
    try:
        done = subprocess.run(  # noqa: S603 - fixed argv, a pid we wrote down
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    out = done.stdout.strip()
    if WINDOWS:
        # `"mycelium.exe","1234",...`, or a line saying no task matched.
        return out.split('","', 1)[0].strip('"') if out.startswith('"') else None
    return out or None


def runs_program(pid: int, program: str) -> bool:
    """Whether ``pid`` is running ``program`` (a path): by its whole path where
    the command line is known, by its file name on Windows."""
    running = command_of(pid)
    if not running:
        return False
    return Path(program).name.lower() == running.lower() if WINDOWS else program in running


def stop_pid(pid: int, *, grace_s: float = 5.0) -> None:
    """Stop ``pid`` and what it started, as :func:`_signal_group` does for a
    program this process holds: asked first, killed if it outlasts ``grace_s``."""
    if WINDOWS:
        argv = ["taskkill", "/PID", str(pid), "/T", "/F"]
        subprocess.run(argv, capture_output=True, check=False)  # noqa: S603, S607
        return
    _signal_pid(pid, 15)
    deadline = time.monotonic() + grace_s
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except (ProcessLookupError, PermissionError):
            return
        time.sleep(0.1)
    _signal_pid(pid, 9)


def _signal_pid(pid: int, sig: int) -> None:
    """Signal ``pid``'s group, which it leads when this app started it; ``pid``
    alone when it leads none, so a program started some other way still stops."""
    try:
        os.killpg(pid, sig)
    except (ProcessLookupError, PermissionError):
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(pid, sig)


def port_open(port: int, host: str = HOST, timeout: float = 0.3) -> bool:
    with contextlib.suppress(OSError), socket.create_connection((host, port), timeout=timeout):
        return True
    return False


def http_ok(url: str, timeout: float = 1.0) -> bool:
    try:
        return httpx.get(url, timeout=timeout).status_code < 500
    except httpx.HTTPError:
        return False


def port_free(port: int, host: str = HOST) -> bool:
    """Whether nothing answers on ``port`` and it can be bound here."""
    if port_open(port, host):
        return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


def free_port(host: str = HOST) -> int:
    """A port the system says is free now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return int(s.getsockname()[1])


#: Where the UI server answers the readiness question (``lib/ui-guard.ts``).
UI_READY_PATH = "/.mycelium/ready"


def ui_proof(nonce: str, token: str) -> str:
    """What the UI server holding ``token`` answers for ``nonce``."""
    return hmac.new(token.encode(), f"ready\n{nonce}".encode(), hashlib.sha256).hexdigest()


def proves_token(base_url: str, token: str, timeout: float = 1.0) -> bool:
    """Whether the server at ``base_url`` holds ``token``: it answers a fresh
    nonce with the HMAC only that token makes. The token never crosses the
    wire, so a program that took the port learns nothing by being asked."""
    nonce = secrets.token_hex(16)
    try:
        resp = httpx.get(f"{base_url}{UI_READY_PATH}", params={"nonce": nonce}, timeout=timeout)
    except httpx.HTTPError:
        return False
    return resp.status_code == 200 and hmac.compare_digest(
        resp.text.strip(), ui_proof(nonce, token)
    )


@dataclass
class Component:
    """One program the supervisor keeps running, and what it last said about it."""

    name: str
    argv: Callable[[], tuple[list[str], Path | None]]
    ready: Callable[[], bool]
    env: dict[str, str] = field(default_factory=dict)
    #: Written to its stdin when it starts, then closed: how a secret reaches
    #: it without sitting in an environment any program as this user can read.
    stdin: str | None = None
    #: A check that something outside the supervisor already provides this.
    external: Callable[[], bool] | None = None
    #: Run before each start (the UI picks its port here).
    prepare: Callable[[], None] | None = None
    #: What its status says while it runs.
    running_detail: str | None = None
    #: Left running when the supervisor stops (herdr: agents live in it).
    outlives: bool = False
    #: What to say when something outside provides it, in place of the default.
    adopted: str | None = None
    state: State = "stopped"
    detail: str | None = None
    proc: subprocess.Popen | None = None
    restarts: int = 0
    started_at: float = 0.0
    retry_at: float = 0.0
    #: Its last lines of output, so a crash can say why.
    tail: deque[str] = field(default_factory=lambda: deque(maxlen=TAIL_LINES))
    #: The thread draining its output. A program whose output nobody reads
    #: blocks on its next write once the pipe fills, so a dead one is replaced.
    reader: threading.Thread | None = None
    #: Checked while it runs, not only until it first answers: a program that
    #: stops answering for :data:`HUNG_S` is reported, and restarted on a yes.
    watch: bool = False
    checked_at: float = 0.0
    #: When it last stopped answering, or 0 while it answers.
    unanswered_since: float = 0.0
    #: The process the person was asked about, so each hang is asked once.
    hang_asked: int | None = None
    #: Set by a yes to restarting it; the supervisor's loop does the restart.
    restart_now: bool = False

    def last_words(self) -> str:
        """The line most likely to say why it stopped: its last error-looking line, else its last."""
        for line in reversed(self.tail):
            if any(w in line for w in ("Error", "error", "Traceback", "panic", "FATAL")):
                return line.strip()[:240]
        return self.tail[-1].strip()[:240] if self.tail else ""

    def wire(self) -> dict[str, Any]:
        return {"state": self.state, "detail": self.detail}


class Supervisor:
    """Start a mode's components in order, keep them up, and say what they are doing."""

    def __init__(
        self,
        mode: Mode,
        *,
        hub_url: str | None = None,
        roots: list[Path] | None = None,
        emit: Callable[[dict[str, Any]], None],
        locator: Locator | None = None,
        config: Any = None,
        env: dict[str, str] | None = None,
        start_runner: bool = True,
        share_usage: bool | None = None,
        voice: bool | None = None,
        voice_model: str | None = None,
        ui_token: str | None = None,
        look: Callable[[], list[Any]] | None = None,
        stale_herdr: Callable[[], Any] | None = None,
        restart_herdr: Callable[[Any], None] | None = None,
        requests_base: Path | None = None,
        started_path: Path | None = None,
    ) -> None:
        if mode == "client" and not hub_url:
            raise ValueError("client mode needs the hub's URL")
        self.mode: Mode = mode
        self.hub_url = (hub_url or "").rstrip("/") or None
        self.roots = roots or [Path.home()]
        self.emit = emit
        self.locator = locator or Locator()
        self.config = config
        self.env = env if env is not None else hub_env(config)
        # The app's token for this launch (read from our stdin), for the UI
        # server alone, on its stdin: never in an environment, where herdr, the
        # runner and every agent pane would inherit it and `ps` would show it.
        self.ui_token = ui_token
        #: The port the UI server listens on: :data:`UI_PORT` unless something
        #: else holds it (:meth:`_choose_ui_port`).
        self.ui_port = UI_PORT
        #: Whether the hub's settings came from config.toml, so a restart the
        #: Hub page asks for reads it again (an env passed in is kept as is).
        self._env_from_config = env is None
        self.start_runner = start_runner
        #: The desktop app's answer to "share usage stats", which wins over
        #: config.toml for the hub it starts. None leaves config.toml's.
        self.share_usage = share_usage
        #: The Mac app's voice switch, which wins over config.toml's
        #: ``voice.enabled`` for the hub it starts. None leaves config.toml's.
        self.voice = voice
        #: The app's choice of speech model (``fast`` or ``accurate``), which
        #: wins over ``voice.model`` the same way. None leaves config.toml's.
        self.voice_model = voice_model
        #: How the hubs on this machine are found (``mycelium.hubs.find_hubs``).
        self.look = look
        #: Where the programs this supervisor started are written down, so the
        #: next one (after an update, or a crash) knows them as the app's own.
        self.started_path = started_path or Path.home() / ".mycelium" / STARTED_FILE
        #: Every hub seen at start, what deserves a look about them, and the
        #: one on the app's port when the app is using it.
        self.hubs: list[dict[str, Any]] = []
        self.warnings: list[str] = []
        self.adopted_hub: dict[str, Any] | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._last: str | None = None
        self.runner: Any = None
        #: This machine's runner id, known from the first status so the app can
        #: tell the page which machine is this one before the runner is up.
        self.runner_id: str | None = None
        self.runner_state: State = "stopped"
        self.runner_detail: str | None = None
        #: How a herdr server from before the app was updated is found and
        #: restarted (``herdr_server.stale`` and ``herdr_server.restart``).
        self.find_stale_herdr = stale_herdr
        self.restart_herdr = restart_herdr
        self.requests_base = requests_base or REQUESTS_BASE
        #: The herdr server whose program was replaced after it started, as wire.
        self.stale_herdr: dict[str, Any] | None = None
        #: The program that stopped answering, by name, until it answers again.
        self.hung: str | None = None
        self._herdr_checked_at = 0.0
        #: The servers already asked about, so each is asked once.
        self._herdr_asked: set[int] = set()
        self.components: list[Component] = [self._herdr()]
        if mode == "hub":
            self.components += self._components()
        else:
            self.components.append(self._ui())

    # ── what runs ────────────────────────────────────────────────────────────

    @property
    def api_url(self) -> str:
        return f"http://{HOST}:{HUB_PORT}" if self.mode == "hub" else str(self.hub_url)

    @property
    def ui_url(self) -> str:
        """The app's own UI, on this machine, whichever hub it talks to."""
        return f"http://{HOST}:{self.ui_port}"

    def _choose_ui_port(self, c: Component) -> None:
        """Before each start of the UI: :data:`UI_PORT`, else the port it had,
        else any free one. A UI already on a port is never used, since the
        window and this launch's token would go to whatever answers there."""
        if port_free(UI_PORT):
            self.ui_port, c.running_detail = UI_PORT, None
        else:
            if self.ui_port == UI_PORT or not port_free(self.ui_port):
                self.ui_port = free_port()
            c.running_detail = f"on port {self.ui_port}: another program is using port {UI_PORT}"
        c.env["PORT"] = str(self.ui_port)

    def _ui_ready(self) -> bool:
        """The UI answers, and (in the app) proves it's the one this
        supervisor handed its token to."""
        if self.ui_token:
            return proves_token(self.ui_url, self.ui_token)
        return http_ok(f"{self.ui_url}/")

    def _herdr(self) -> Component:
        """herdr's server, which agents run in: started when it isn't already.

        It outlives the supervisor, since quitting Mycelium must not end the
        agents' sessions.
        """
        from mycelium.integrations.herdr import HerdrBridge
        from mycelium.integrations.herdr.bridge import skip_first_run

        def up() -> bool:
            try:
                return HerdrBridge().available()
            except Exception:  # noqa: BLE001 - "can't tell" reads as not up
                return False

        def argv() -> tuple[list[str], None]:
            # Set up the first time, so the agents' terminals aren't behind
            # herdr's own first-run screens.
            skip_first_run()
            return self.locator.herdr(), None

        return Component(
            name="herdr",
            argv=argv,
            ready=up,
            external=up,
            outlives=True,
        )

    def _hub_env_vars(self) -> dict[str, str]:
        """The hub's environment: its settings from config.toml, then the app's own."""
        loc = self.locator
        hub_env_vars = {
            **self.env,
            "SLIM_NODE_ENDPOINT": f"http://{HOST}:{SLIM_PORT}",
            "MYCELIUM_SLIM_ENDPOINT": f"http://{HOST}:{SLIM_PORT}",
            "FASTEMBED_CACHE_PATH": str(loc.models()),
            "MYCELIUM_HUB_MODE": "desktop",
            # The CLI the hub's Hub page saves settings through
            # (`config set`), so a change takes the one validated path.
            "MYCELIUM_CONFIG_CLI": json.dumps(own_cli()),
            # Files read and written as UTF-8 on Windows too (the bundled
            # hub is built in this mode; a checkout's `uv run` needs telling).
            "PYTHONUTF8": "1",
        }
        if self.share_usage is not None:
            hub_env_vars["TELEMETRY_SEND_PRODUCT_ANALYTICS"] = (
                "true" if self.share_usage else "false"
            )
        if self.voice is not None:
            hub_env_vars["VOICE_ENABLED"] = "true" if self.voice else "false"
        if self.voice_model is not None:
            hub_env_vars["VOICE_MODEL"] = self.voice_model
        if pi := loc.pi():
            hub_env_vars["ALIGNER_PI_BINARY"] = pi
        return hub_env_vars

    def _ui(self) -> Component:
        """The app's own UI server, talking to the hub this app uses.

        In both modes: a hub elsewhere is reached through this machine's UI,
        never by showing that hub's own pages. One already answering on the
        port is never used (:meth:`_choose_ui_port`).
        """
        ui_env = {
            "PORT": str(UI_PORT),
            "HOSTNAME": HOST,
            "MYCELIUM_INTERNAL_API_URL": self.api_url,
            # Only read by `next dev` (a checkout); it refuses pages opened
            # from a host it wasn't told about.
            "MYCELIUM_ALLOWED_DEV_ORIGINS": f"{HOST},localhost",
            # A build folder of its own in a checkout, so it runs beside a
            # `pnpm dev` there (Next allows one dev server per build folder).
            "MYCELIUM_UI_DIST_DIR": ".next/desktop",
            # This machine's themes (`mycelium theme`), which the app shows and
            # follows. Only a UI the desktop app runs for its own person reads
            # them; one serving many people never gets this.
            "MYCELIUM_THEMES_DIR": str(themes.folder()),
            **self._login_env(),
        }
        if self.ui_token:
            # What the UI server asks of every request (`lib/ui-guard.ts`),
            # handed over on its stdin (`instrumentation.ts` reads it once).
            ui_env[UI_TOKEN_STDIN_ENV] = "1"
        ui = Component(
            name="ui",
            argv=lambda: self.locator.ui(self.ui_port),
            ready=self._ui_ready,
            env=ui_env,
            stdin=self.ui_token,
        )
        ui.prepare = lambda: self._choose_ui_port(ui)
        return ui

    def _login_env(self) -> dict[str, str]:
        """How the UI signs in to a hub that asks: the same client as `mycelium login`.

        The issuer is the one the hub names in ``/health``, found by the UI
        when it's needed. The client is the CLI's, which an issuer already
        lets sign in through this machine's loopback address.
        """
        from mycelium.config import MyceliumConfig

        try:
            login = (self.config or MyceliumConfig.load()).login
        except Exception:  # noqa: BLE001 - an unreadable config leaves the defaults
            return {}
        env = {"MYCELIUM_OIDC_CLIENT_ID": login.client_id}
        if login.audience:
            env["MYCELIUM_OIDC_AUDIENCE"] = login.audience
        return env

    def _components(self) -> list[Component]:
        loc = self.locator
        hub_env_vars = self._hub_env_vars()
        return [
            Component(
                name="slim",
                argv=lambda: (loc.slim(), None),
                ready=lambda: port_open(SLIM_PORT),
                external=lambda: port_open(SLIM_PORT),
            ),
            Component(
                name="hub",
                argv=loc.hub,
                ready=lambda: http_ok(f"http://{HOST}:{HUB_PORT}/health"),
                env=hub_env_vars,
                external=lambda: http_ok(f"http://{HOST}:{HUB_PORT}/health"),
                watch=True,
            ),
            self._ui(),
        ]

    # ── status ───────────────────────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        components = {c.name: c.wire() for c in self.components}
        for name in ("slim", "hub", "ui"):
            components.setdefault(name, {"state": "disabled", "detail": None})
        components["runner"] = {"state": self.runner_state, "detail": self.runner_detail}
        return {
            "type": "status",
            "mode": self.mode,
            "ui_url": self.ui_url,
            "api_url": self.api_url,
            # So the app can tell the page which machine is this one.
            "runner_id": self.runner_id,
            "components": components,
            # More than one hub here, a hub on someone else's store, an old one.
            "warnings": self.warnings
            + ([STALE_HERDR_WARNING] if self.stale_herdr else [])
            + ([hung_warning(self.hung)] if self.hung else []),
            # A program the supervisor started that stopped answering.
            "hung": self.hung,
            "hubs": self.hubs,
            # The hub on the app's port that the app is using but didn't start.
            "existing_hub": self.adopted_hub,
            # A herdr server from before the app was updated.
            "stale_herdr": self.stale_herdr,
        }

    def _publish(self) -> None:
        status = self.status()
        key = json.dumps(status, sort_keys=True)
        with self._lock:
            if key == self._last:
                return
            self._last = key
        self.emit(status)

    def _set(self, c: Component, state: State, detail: str | None = None) -> None:
        c.state, c.detail = state, detail
        self._publish()

    # ── processes ────────────────────────────────────────────────────────────

    def _pipe(self, c: Component, stream: Any) -> None:
        """Drain ``c``'s output for as long as it has any. Nothing that happens to
        a line stops the reading: a program whose pipe isn't drained blocks on
        its next write, and a hub blocked there answers nothing."""
        try:
            for raw in iter(stream.readline, ""):
                line = raw.rstrip()
                if not line:
                    continue
                c.tail.append(line)
                try:
                    self.emit({"type": "log", "component": c.name, "line": line})
                except Exception:  # noqa: BLE001, S112 - a lost line, never a stopped reader
                    continue
        except (OSError, ValueError):
            return  # the pipe closed with the program

    def _last_lines(self, c: Component, code: int) -> None:
        """Say in the log that ``c`` stopped on its own, how, and the last lines
        it wrote, so a crash reads plainly there even when its output was long."""
        said = list(c.tail)[-LAST_LINES:]
        self.emit({"type": "log", "component": c.name, "line": f"{c.name} {how_it_exited(code)}"})
        for line in said:
            self.emit({"type": "log", "component": c.name, "line": f"  last: {line}"})

    def _read(self, c: Component) -> None:
        """Start a thread draining ``c``'s output."""
        if c.proc is None or c.proc.stdout is None:
            return
        c.reader = threading.Thread(
            target=self._pipe, args=(c, c.proc.stdout), name=f"read-{c.name}", daemon=True
        )
        c.reader.start()

    def _spawn(self, c: Component) -> None:
        if c.external is not None and c.restarts == 0 and c.external():
            self._set(c, "running", c.adopted or "already running (not started by the app)")
            return
        if c.prepare is not None:
            c.prepare()
        try:
            argv, cwd = c.argv()
        except LocateError as e:
            self._set(c, "failed", str(e))
            self.emit({"type": "error", "component": c.name, "message": str(e)})
            return
        try:
            c.proc = subprocess.Popen(  # noqa: S603 - argv is resolved above, never a shell string
                argv,
                cwd=cwd,
                env={**os.environ, **c.env},
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE if c.stdin is not None else subprocess.DEVNULL,
                text=True,
                # Not the code page Windows would otherwise decode with.
                encoding="utf-8",
                errors="replace",
                **_own_group(),
            )
        except OSError as e:
            self._set(c, "failed", f"could not start {c.name}: {e}")
            return
        if c.stdin is not None and c.proc.stdin is not None:
            with contextlib.suppress(OSError):
                c.proc.stdin.write(c.stdin + "\n")
                c.proc.stdin.close()
        if not c.outlives:
            self._remember(c.name, c.proc.pid, argv[0])
        c.started_at = time.monotonic()
        c.unanswered_since = 0.0
        self._read(c)
        self._set(c, "starting")

    def _tick(self, c: Component) -> bool:
        """Advance one component; ``True`` once it is running."""
        if c.state in ("failed", "disabled") and c.retry_at == 0.0:
            return False
        if c.state == "running" and c.proc is None:
            return True  # provided from outside
        if c.proc is None:
            if c.retry_at and time.monotonic() < c.retry_at:
                return False
            c.retry_at = 0.0
            self._spawn(c)
            return c.state == "running"
        code = c.proc.poll()
        if code is not None and c.name == "hub" and self._hub_asked_to_restart():
            # The Hub page saved settings and asked for a restart: start it
            # again at once with config.toml read afresh, not as a crash.
            c.proc = None
            c.restarts = 0
            c.retry_at = 0.0
            if self._env_from_config:
                self.env = hub_env(None)
            c.env = self._hub_env_vars()
            self._set(c, "starting", "restarting to apply new settings")
            return False
        if code is not None:
            c.proc = None
            c.restarts += 1
            self._last_lines(c, code)
            if c.restarts > MAX_RESTARTS:
                why = c.last_words()
                self._set(
                    c,
                    "failed",
                    f"{c.name} keeps exiting (last time it {how_it_exited(code)})"
                    + (f": {why}" if why else ""),
                )
                return False
            wait = BACKOFF_S[min(c.restarts, len(BACKOFF_S)) - 1]
            c.retry_at = time.monotonic() + wait
            why = c.last_words()
            self._set(
                c,
                "starting",
                how_it_exited(code)
                + (f" ({why})" if why else "")
                + f"; starting again in {wait:.0f}s",
            )
            return False
        # Still running: its output must keep being read.
        if c.reader is not None and not c.reader.is_alive():
            self._read(c)
        if c.restart_now:
            c.restart_now = False
            c.hang_asked = None
            self._terminate(c)
            c.restarts = 0
            self.hung = None
            self._set(c, "starting", "restarting: it stopped responding")
            return False
        if c.state == "starting":
            if c.ready():
                c.restarts = 0
                self._set(c, "running", c.running_detail)
            elif time.monotonic() - c.started_at > READY_TIMEOUT_S:
                self._set(c, "failed", f"{c.name} did not answer within {READY_TIMEOUT_S:.0f}s")
                self._terminate(c)
                return False
        elif c.state == "running" and c.watch:
            self._watch(c)
        return c.state == "running"

    def _watch(self, c: Component, now: float | None = None) -> None:
        """Every :data:`WATCH_S`, see that a running program still answers. One
        that hasn't for :data:`HUNG_S` is said in the status, and the person is
        asked, once per process, whether to restart it."""
        now = time.monotonic() if now is None else now
        if c.checked_at and now - c.checked_at < WATCH_S:
            return
        c.checked_at = now
        if c.ready():
            c.unanswered_since = 0.0
            if self.hung == c.name:
                self.hung = None
                self._publish()
            return
        if not c.unanswered_since:
            c.unanswered_since = now
            return
        pid = c.proc.pid if c.proc is not None else None
        if now - c.unanswered_since < HUNG_S or pid is None or c.hang_asked == pid:
            return
        c.hang_asked = pid
        self.hung = c.name
        self.emit({"type": "warning", "message": hung_warning(c.name)})
        self._publish()
        self._ask_to_restart(c)

    def _ask_to_restart(self, c: Component) -> None:
        """Ask the person, through the app, whether to restart ``c``, showing its
        last lines of output; a yes restarts it on the next tick."""
        import secrets

        from mycelium.runner import approvals

        lines = "\n".join(list(c.tail)[-HUNG_LINES:]) or "(it said nothing)"
        job = secrets.token_hex(8)
        request = approvals.ask(
            job,
            {
                "title": f"The {c.name} stopped responding",
                "message": f"{hung_warning(c.name)}\n\nIts last lines:\n{lines}",
                "yes": f"Restart the {c.name}",
                "no": "Wait",
            },
            base=self.requests_base,
        )
        folder = approvals.requests_dir(self.requests_base)
        self.emit({"type": "request", "request": request, "folder": str(folder)})

        def wait() -> None:
            try:
                yes = approvals.wait(job, self._stop, timeout=HERDR_ASK_S, base=self.requests_base)
            finally:
                approvals.forget(job, base=self.requests_base)
            if yes:
                c.restart_now = True

        threading.Thread(target=wait, name=f"{c.name}-restart", daemon=True).start()

    @staticmethod
    def _terminate(c: Component, grace_s: float = 5.0) -> None:
        proc, c.proc = c.proc, None
        if proc is None or proc.poll() is not None:
            return
        _signal_group(proc, force=False)
        try:
            proc.wait(timeout=grace_s)
        except subprocess.TimeoutExpired:
            _signal_group(proc, force=True)

    # ── the runner ───────────────────────────────────────────────────────────

    def _start_runner(self) -> None:
        from rich.console import Console

        from mycelium.config import MyceliumConfig
        from mycelium.runner.approvals import requests_dir
        from mycelium.runner.daemon import APP, Runner, registered

        # One machine runs one runner. One started in a terminal keeps the
        # machine, and the app's starts once that one stops (this is asked
        # again every tick until it does).
        found = registered()
        if found is not None and found[0] != os.getpid():
            whose = "another copy of the app" if found[1] == APP else "`mycelium runner`"
            detail = f"a runner started by {whose} is running (pid {found[0]})"
            if (self.runner_state, self.runner_detail) != ("stopped", detail):
                self.runner_state, self.runner_detail = "stopped", detail
                self._publish()
            return

        config = self.config or MyceliumConfig.load()
        config.server.api_url = self.api_url
        # stdout is the status stream; what the runner says goes to stderr.
        # Launches go ahead without asking only from the hub this supervisor
        # started, which listens on 127.0.0.1 alone; a hub elsewhere, or one
        # that was already running here (Docker publishes to the network),
        # could be reached by anyone, so each launch from it waits for a yes
        # in the app.
        self.runner = Runner(
            config,
            roots=self.roots,
            rid=self.runner_id,
            log=Console(stderr=True),
            trust_hub=self._own_hub(),
            started_by=APP,
            # The app answers by writing the answer file into this folder.
            on_request=lambda request: self.emit(
                {"type": "request", "request": request, "folder": str(requests_dir())}
            ),
        )
        self.runner_state, self.runner_detail = "starting", None
        self._publish()

        def run() -> None:
            try:
                self.runner.run()
            except Exception as e:  # noqa: BLE001 - reported, never raised into the supervisor
                self.runner_state, self.runner_detail = "failed", str(e)
                self._publish()

        threading.Thread(target=run, name="runner", daemon=True).start()

    def _own_hub(self) -> bool:
        """Whether the hub is one this supervisor started (and so only this machine reaches)."""
        hub = next((c for c in self.components if c.name == "hub"), None)
        return self.mode == "hub" and hub is not None and hub.proc is not None

    def _tick_runner(self) -> None:
        if self.runner is None:
            return
        if self.runner.connected:
            state: State = "running"
            detail = None if self.runner.herdr else "herdr isn't running, so agents can't start"
        else:
            state, detail = "starting", f"connecting to {self.api_url}"
        if (state, detail) != (self.runner_state, self.runner_detail):
            self.runner_state, self.runner_detail = state, detail
            self._publish()

    # ── a herdr server from before the app was updated ───────────────────────

    def _watch_herdr(self, *, now: float | None = None) -> None:
        """Once a minute while herdr runs: is its server from before an update?"""
        herdr = next((c for c in self.components if c.name == "herdr"), None)
        if herdr is None or herdr.state != "running":
            return
        now = time.monotonic() if now is None else now
        if self._herdr_checked_at and now - self._herdr_checked_at < HERDR_CHECK_S:
            return
        self._herdr_checked_at = now
        from mycelium.desktop import herdr_server

        find = self.find_stale_herdr or (lambda: herdr_server.stale(self.locator.app_herdr()))
        server = find()
        wire = server.wire() if server is not None else None
        if wire != self.stale_herdr:
            self.stale_herdr = wire
            if wire is not None:
                self.emit({"type": "warning", "message": STALE_HERDR_WARNING})
            self._publish()
        if server is not None and server.pid not in self._herdr_asked:
            self._herdr_asked.add(server.pid)
            self._ask_to_restart_herdr(server)

    def _ask_to_restart_herdr(self, server: Any) -> None:
        """Put the restart to the person through the app, and do it on a yes."""
        import secrets

        from mycelium.desktop import herdr_server
        from mycelium.runner import approvals

        job = secrets.token_hex(8)
        request = approvals.ask(
            job,
            {
                "title": "Restart herdr?",
                "message": f"{STALE_HERDR_WARNING}\n\n{herdr_server.agents_after_restart()}",
                "yes": "Restart herdr",
                "no": "Not now",
            },
            base=self.requests_base,
        )
        folder = approvals.requests_dir(self.requests_base)
        self.emit({"type": "request", "request": request, "folder": str(folder)})

        def wait() -> None:
            try:
                yes = approvals.wait(job, self._stop, timeout=HERDR_ASK_S, base=self.requests_base)
            finally:
                approvals.forget(job, base=self.requests_base)
            if yes:
                self._restart_herdr(server)

        threading.Thread(target=wait, name="herdr-restart", daemon=True).start()

    def _restart_herdr(self, server: Any) -> None:
        from mycelium.desktop import herdr_server

        restart = self.restart_herdr or herdr_server.restart
        self.emit({"type": "log", "component": "herdr", "line": "restarting herdr's server"})
        try:
            restart(server)
        except herdr_server.RestartError as e:
            self.emit({"type": "error", "component": "herdr", "message": str(e)})
        else:
            self.emit({"type": "log", "component": "herdr", "line": "herdr's server restarted"})
        # Look again on the next tick, so the warning clears once it's fixed.
        self._herdr_checked_at = 0.0

    # ── what an earlier run started and left running ────────────────────────

    def _started(self) -> dict[str, dict[str, Any]]:
        try:
            found = json.loads(self.started_path.read_text())
        except (OSError, ValueError):
            return {}
        return found if isinstance(found, dict) else {}

    def _remember(self, name: str, pid: int, program: str) -> None:
        """Write down that ``name`` runs as ``pid`` from ``program``."""
        started = {**self._started(), name: {"pid": pid, "program": program}}
        with contextlib.suppress(OSError):
            self.started_path.parent.mkdir(parents=True, exist_ok=True)
            self.started_path.write_text(json.dumps(started, indent=2) + "\n")

    def _stop_leftovers(self) -> None:
        """Stop what an earlier run of the app started and left running.

        An app that updates itself in place replaces its files under its running
        programs without stopping them: the hub then runs the old version with
        the new files under it, and the next supervisor would take it for
        another hub on its port and keep it. What an earlier run wrote down is
        the app's own, so it's stopped here and started again from the new
        files. A pid now running some other program (one reused since) is left
        alone: only a process still running the program written down is stopped.
        """
        started = self._started()
        if not started:
            return
        for name, entry in started.items():
            pid, program = entry.get("pid"), str(entry.get("program") or "")
            if not isinstance(pid, int) or pid <= 0 or pid == os.getpid() or not program:
                continue
            if not runs_program(pid, program):
                continue
            self.emit(
                {
                    "type": "log",
                    "component": name,
                    "line": f"stopping the {name} an earlier run of the app left running (pid {pid})",
                }
            )
            stop_pid(pid)
        with contextlib.suppress(OSError):
            self.started_path.unlink(missing_ok=True)

    def _runs_app_hub(self, pid: int) -> bool:
        """Whether ``pid`` is running this app's own hub program."""
        program = self.locator.app_hub()
        return program is not None and runs_program(pid, str(program))

    # ── a hub this supervisor didn't start ───────────────────────────────────

    def data_dir(self) -> Path:
        """Where the hub this supervisor starts keeps its data."""
        return Path(self.env.get("MYCELIUM_DATA_DIR") or Path.home() / ".mycelium").expanduser()

    def _hub_asked_to_restart(self) -> bool:
        """Whether the hub left the restart marker before it exited; takes it away."""
        marker = self.data_dir() / HUB_RESTART_MARKER
        if not marker.exists():
            return False
        marker.unlink(missing_ok=True)
        return True

    def _preflight(self) -> None:
        """Before anything starts: every hub here, and the one on our port, reported."""
        from mycelium import __version__
        from mycelium.hubs import at_port, find_hubs, same_store, store_id, warnings

        found = self.look() if self.look is not None else find_hubs(HUB_PORT)
        # The app's own hub program, still running from before the app updated
        # itself (one started by a version that wrote nothing down): the app's,
        # so stopped and started again from the new files, never kept.
        own = at_port(found, HUB_PORT)
        if own is not None and own.pid and self._runs_app_hub(own.pid):
            self.emit(
                {
                    "type": "log",
                    "component": "hub",
                    "line": f"stopping the app's hub from before it updated (pid {own.pid}, "
                    f"version {own.version or 'unknown'})",
                }
            )
            stop_pid(own.pid)
            found = self.look() if self.look is not None else find_hubs(HUB_PORT)
        data_dir = self.data_dir()
        self.hubs = [h.wire() for h in found]
        self.warnings = warnings(found, data_dir, __version__)
        for line in self.warnings:
            self.emit({"type": "warning", "message": line})
        there = at_port(found, HUB_PORT)
        hub = next((c for c in self.components if c.name == "hub"), None)
        if there is None or hub is None:
            self._publish()
            return
        hub.adopted = f"another hub on port {there.port or HUB_PORT}"
        self.adopted_hub = {
            **there.wire(),
            # False: it writes somewhere other than the app's data folder.
            "same_store": same_store(there, data_dir, store_id(data_dir, create=False)),
            "data_dir": str(data_dir),
            "app_version": __version__,
        }
        self.emit(
            {"type": "warning", "message": f"Using a hub the app didn't start: {there.describe()}"}
        )
        self._set(hub, "stopped")

    # ── the loop ─────────────────────────────────────────────────────────────

    def run(self) -> None:
        """Start everything and keep it up until :meth:`stop`."""
        if self.start_runner:
            from mycelium.runner.daemon import runner_id

            self.runner_id = runner_id()
        self._publish()
        self._stop_leftovers()
        if self.mode == "hub":
            self._preflight()
        try:
            while not self._stop.is_set():
                ready = True
                for c in self.components:
                    if not self._tick(c):
                        ready = False
                        break  # each waits on the one before it
                if ready and self.start_runner and self.runner is None:
                    self._start_runner()
                self._tick_runner()
                self._watch_herdr()
                self._stop.wait(TICK_S)
        finally:
            self._shutdown()

    def stop(self) -> None:
        self._stop.set()

    def _shutdown(self) -> None:
        if self.runner is not None:
            self.runner.stop()
            self.runner.goodbye()
            self.runner_state = "stopped"
        for c in reversed(self.components):
            if c.proc is not None and not c.outlives:
                self._terminate(c)
                c.state = "stopped"
        # Stopped cleanly: nothing of this run is left for the next to stop.
        with contextlib.suppress(OSError):
            self.started_path.unlink(missing_ok=True)
        self._publish()


def own_cli() -> list[str]:
    """How to run this same CLI again: the app's bundled program, or this Python
    with the package from a checkout."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "mycelium"]


def hub_env(config: Any) -> dict[str, str]:
    """The hub's settings from ``config.toml``, as ``mycelium config apply`` renders them."""
    if config is None:
        from mycelium.config import MyceliumConfig

        config = MyceliumConfig.load()
    from mycelium.docker_utils import generate_env_file

    env: dict[str, str] = {}
    for line in generate_env_file(config).splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            if value:
                env[key.strip()] = value
    return env
