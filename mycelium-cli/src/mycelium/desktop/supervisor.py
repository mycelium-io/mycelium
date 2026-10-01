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

Where each program comes from, first found wins: an environment override,
the app bundle (the directory this binary runs from, and its ``Resources``),
then a checkout of the repository, then ``PATH``.
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
#: How often a component that rechecks looks at the one provided from outside.
RECHECK_S = 5.0
#: How many lines of each component's output are kept to explain a crash.
TAIL_LINES = 40
#: Everything the supervisor says, for when something goes wrong.
LOG_PATH = Path.home() / ".mycelium" / "logs" / "desktop.log"


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
        if self.bundle is None:
            return None
        for place in (self.bundle, self.bundle.parent / "Resources"):
            candidate = place / name
            if candidate.exists():
                return candidate
        return None

    def slim(self) -> list[str]:
        exe = (
            os.environ.get("MYCELIUM_SLIMCTL")
            or self._bundled("slimctl")
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
        if bundled := self._bundled("hub/mycelium-hub") or self._bundled("mycelium-hub"):
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
        exe = self._bundled("herdr") or shutil.which("herdr")
        if not exe:
            raise LocateError(
                "herdr isn't installed, so no agent can start here. See https://herdr.dev"
            )
        return [str(exe), "server"]

    def pi(self) -> str | None:
        """Pi, which the engines think with: the app's own, else one on PATH."""
        return (
            os.environ.get("ALIGNER_PI_BINARY")
            or (str(bundled) if (bundled := self._bundled("pi/pi")) else None)
            or shutil.which("pi")
        )

    def models(self) -> Path:
        """Where the hub's embedding model is: the app's own copy, else a cache it fills.

        The container keeps it at ``/opt/fastembed``, which is no place on a Mac.
        """
        return self._bundled("models") or Path.home() / ".mycelium" / "models"

    def ui(self) -> tuple[list[str], Path | None]:
        node = os.environ.get("MYCELIUM_NODE") or self._bundled("node") or shutil.which("node")
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
    #: Keep checking one provided from outside, and start this one when it goes
    #: (herdr: a server stopped to update it is replaced by the app's own).
    rechecks: bool = False
    #: Left running when the supervisor stops (herdr: agents live in it).
    outlives: bool = False
    state: State = "stopped"
    detail: str | None = None
    proc: subprocess.Popen | None = None
    restarts: int = 0
    started_at: float = 0.0
    retry_at: float = 0.0
    #: When one provided from outside was last checked (with ``rechecks``).
    checked_at: float = 0.0
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
            rechecks=True,
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
            self._set(c, "running", "already running (not started by the app)")
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
                start_new_session=True,
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
            # Provided from outside. One that rechecks is looked at now and
            # then, and started here once it's gone.
            if not c.rechecks or c.external is None:
                return True
            if time.monotonic() - c.checked_at < RECHECK_S:
                return True
            c.checked_at = time.monotonic()
            if c.external():
                return True
            c.restarts = 1  # start this one, rather than look outside again
            self._set(c, "starting", f"{c.name} stopped outside the app; starting it")
            return False
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
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, 15)
        try:
            proc.wait(timeout=grace_s)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(proc.pid, 9)

    # ── the runner ───────────────────────────────────────────────────────────

    def _start_runner(self) -> None:
        from rich.console import Console

        from mycelium.config import MyceliumConfig
        from mycelium.runner.approvals import requests_dir
        from mycelium.runner.daemon import Runner

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

        threading.Thread(target=run, daemon=True).start()

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

    # ── the loop ─────────────────────────────────────────────────────────────

    def run(self) -> None:
        """Start everything and keep it up until :meth:`stop`."""
        if self.start_runner:
            from mycelium.runner.daemon import runner_id

            self.runner_id = runner_id()
        self._publish()
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
