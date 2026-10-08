# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Run Mycelium on this machine without Docker, and keep it running.

Two modes, which are what the desktop app offers on its first screen:

- **hub**: this machine runs the hub. herdr's server, a SLIM node
  (``slimctl slim start``), the hub's API, the UI server, and the runner, each
  started in order once the one before it answers.
- **client**: another machine runs the hub. herdr's server and the runner,
  pointed at it.

herdr's server is started only when none is running, and is left running
when the supervisor stops: agents live in its panes.

Everything the app shows comes from here as JSON lines on stdout (a status
object on every change, log lines, errors), so the app is a window over this
process and the same thing runs from a terminal with ``mycelium desktop
serve``. A process that exits is started again, backing off, and one that
keeps failing is left failed with the reason. A port something else already
answers on counts as running, so the app sits beside a Docker stack rather
than fighting it for its ports.

A hub the app didn't start is never used without saying so. Before starting
anything in hub mode the supervisor looks for every hub on this machine
(``mycelium.hubs``), warns when there is more than one, and reports the one
on its port (its owner, version and data folder) in its status. It never
stops one: that hub may be someone's on purpose, so the person decides.

Where each program comes from, first found wins: an environment override,
the app bundle (the directory this binary runs from, and where each platform's
bundle keeps its resources), then a checkout of the repository, then ``PATH``.
"""

from __future__ import annotations

import contextlib
import json
import os
import shlex
import shutil
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

Mode = Literal["hub", "client"]
State = Literal["starting", "running", "stopped", "failed", "disabled"]

HOST = "127.0.0.1"
SLIM_PORT = 46357
HUB_PORT = 8000
UI_PORT = 3717
#: How long a component may take to answer before it counts as failed.
READY_TIMEOUT_S = 90.0
#: Restarts after a crash wait this long, doubling, up to the last value.
BACKOFF_S = (1.0, 2.0, 4.0, 8.0, 16.0)
#: A component that crashes this many times in a row is left failed.
MAX_RESTARTS = len(BACKOFF_S)
#: How often the supervisor looks at its processes.
TICK_S = 0.5
#: How many lines of each component's output are kept to explain a crash.
TAIL_LINES = 40
#: Everything the supervisor says, for when something goes wrong.
LOG_PATH = Path.home() / ".mycelium" / "logs" / "desktop.log"
WINDOWS = sys.platform == "win32"
#: Pi's JavaScript entry point inside the app's resources, which the hub runs
#: on node on Windows (see ``Locator.pi``).
PI_ENTRY = "pi/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js"


class LocateError(Exception):
    """A program the chosen mode needs could not be found, said as a sentence."""


# ── finding the programs ─────────────────────────────────────────────────────


def bundle_dir() -> Path | None:
    """The directory this binary runs from, when it is a bundled (frozen) build."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return None


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

    def ui(self) -> tuple[list[str], Path | None]:
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
                argv = ["pnpm", "exec", "next", "dev", "-H", HOST, "-p", str(UI_PORT)]
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


def port_open(port: int, host: str = HOST, timeout: float = 0.3) -> bool:
    with contextlib.suppress(OSError), socket.create_connection((host, port), timeout=timeout):
        return True
    return False


def http_ok(url: str, timeout: float = 1.0) -> bool:
    try:
        return httpx.get(url, timeout=timeout).status_code < 500
    except httpx.HTTPError:
        return False


@dataclass
class Component:
    """One program the supervisor keeps running, and what it last said about it."""

    name: str
    argv: Callable[[], tuple[list[str], Path | None]]
    ready: Callable[[], bool]
    env: dict[str, str] = field(default_factory=dict)
    #: A check that something outside the supervisor already provides this.
    external: Callable[[], bool] | None = None
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
        look: Callable[[], list[Any]] | None = None,
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
        self.start_runner = start_runner
        #: The Mac app's answer to "share usage stats", which wins over
        #: config.toml for the hub it starts. None leaves config.toml's.
        self.share_usage = share_usage
        #: How the hubs on this machine are found (``mycelium.hubs.find_hubs``).
        self.look = look
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
        self.components: list[Component] = [self._herdr()]
        if mode == "hub":
            self.components += self._components()

    # ── what runs ────────────────────────────────────────────────────────────

    @property
    def api_url(self) -> str:
        return f"http://{HOST}:{HUB_PORT}" if self.mode == "hub" else str(self.hub_url)

    @property
    def ui_url(self) -> str:
        return f"http://{HOST}:{UI_PORT}" if self.mode == "hub" else str(self.hub_url)

    def _herdr(self) -> Component:
        """herdr's server, which agents run in: started when it isn't already.

        It outlives the supervisor, since quitting Mycelium must not end the
        agents' sessions.
        """
        from mycelium.integrations.herdr import HerdrBridge

        def up() -> bool:
            try:
                return HerdrBridge().available()
            except Exception:  # noqa: BLE001 - "can't tell" reads as not up
                return False

        return Component(
            name="herdr",
            argv=lambda: (self.locator.herdr(), None),
            ready=up,
            external=up,
            outlives=True,
        )

    def _components(self) -> list[Component]:
        loc = self.locator
        hub_env_vars = {
            **self.env,
            "SLIM_NODE_ENDPOINT": f"http://{HOST}:{SLIM_PORT}",
            "MYCELIUM_SLIM_ENDPOINT": f"http://{HOST}:{SLIM_PORT}",
            "FASTEMBED_CACHE_PATH": str(loc.models()),
            "MYCELIUM_HUB_MODE": "desktop",
        }
        if self.share_usage is not None:
            hub_env_vars["TELEMETRY_SEND_PRODUCT_ANALYTICS"] = (
                "true" if self.share_usage else "false"
            )
        if pi := loc.pi():
            hub_env_vars["ALIGNER_PI_BINARY"] = pi
        ui_env = {
            "PORT": str(UI_PORT),
            "HOSTNAME": HOST,
            "MYCELIUM_INTERNAL_API_URL": f"http://{HOST}:{HUB_PORT}",
            # Only read by `next dev` (a checkout); it refuses pages opened
            # from a host it wasn't told about.
            "MYCELIUM_ALLOWED_DEV_ORIGINS": f"{HOST},localhost",
        }
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
            ),
            Component(
                name="ui",
                argv=loc.ui,
                ready=lambda: http_ok(f"http://{HOST}:{UI_PORT}/"),
                env=ui_env,
                external=lambda: http_ok(f"http://{HOST}:{UI_PORT}/"),
            ),
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
            "warnings": self.warnings,
            "hubs": self.hubs,
            # The hub on the app's port that the app is using but didn't start.
            "existing_hub": self.adopted_hub,
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
        for raw in iter(stream.readline, ""):
            line = raw.rstrip()
            if line:
                c.tail.append(line)
                self.emit({"type": "log", "component": c.name, "line": line})

    def _spawn(self, c: Component) -> None:
        if c.external is not None and c.restarts == 0 and c.external():
            self._set(c, "running", c.adopted or "already running (not started by the app)")
            return
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
                stdin=subprocess.DEVNULL,
                text=True,
                **_own_group(),
            )
        except OSError as e:
            self._set(c, "failed", f"could not start {c.name}: {e}")
            return
        c.started_at = time.monotonic()
        threading.Thread(target=self._pipe, args=(c, c.proc.stdout), daemon=True).start()
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
        if code is not None:
            c.proc = None
            c.restarts += 1
            if c.restarts > MAX_RESTARTS:
                why = c.last_words()
                self._set(
                    c,
                    "failed",
                    f"{c.name} keeps exiting (last exit code {code})" + (f": {why}" if why else ""),
                )
                return False
            wait = BACKOFF_S[min(c.restarts, len(BACKOFF_S)) - 1]
            c.retry_at = time.monotonic() + wait
            why = c.last_words()
            self._set(
                c,
                "starting",
                f"exited with code {code}"
                + (f" ({why})" if why else "")
                + f"; starting again in {wait:.0f}s",
            )
            return False
        if c.state == "starting":
            if c.ready():
                c.restarts = 0
                self._set(c, "running")
            elif time.monotonic() - c.started_at > READY_TIMEOUT_S:
                self._set(c, "failed", f"{c.name} did not answer within {READY_TIMEOUT_S:.0f}s")
                self._terminate(c)
                return False
        return c.state == "running"

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

    # ── a hub this supervisor didn't start ───────────────────────────────────

    def data_dir(self) -> Path:
        """Where the hub this supervisor starts keeps its data."""
        return Path(self.env.get("MYCELIUM_DATA_DIR") or Path.home() / ".mycelium").expanduser()

    def _preflight(self) -> None:
        """Before anything starts: every hub here, and the one on our port, reported."""
        from mycelium import __version__
        from mycelium.hubs import at_port, find_hubs, same_store, store_id, warnings

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
        self._publish()


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
