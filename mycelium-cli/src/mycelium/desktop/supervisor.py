# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Run Mycelium on this machine without Docker, and keep it running.

Two modes, which are what the desktop app offers on its first screen:

- **hub**: this machine runs the hub. A SLIM node (``slimctl slim start``),
  the hub's API, the UI server, and the runner, each started in order once the
  one before it answers.
- **client**: another machine runs the hub. Only the runner, pointed at it.

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
        if bundled := self._bundled("mycelium-hub"):
            return [str(bundled), "--host", HOST, "--port", str(HUB_PORT)], None
        if self.repo is not None and shutil.which("uv"):
            backend = self.repo / "fastapi-backend"
            argv = ["uv", "run", "--project", str(backend), "uvicorn", "app.main:app"]
            return [*argv, "--host", HOST, "--port", str(HUB_PORT)], backend
        raise LocateError(
            "This build doesn't include the hub, and there's no Mycelium checkout to run "
            "it from. Use the desktop app, or run the hub with Docker (mycelium up)."
        )

    def ui(self) -> tuple[list[str], Path | None]:
        node = os.environ.get("MYCELIUM_NODE") or self._bundled("node") or shutil.which("node")
        ui_dir = os.environ.get("MYCELIUM_UI_DIR") or self._bundled("ui")
        if ui_dir and node:
            return [str(node), "server.js"], Path(ui_dir)
        if self.repo is not None:
            frontend = self.repo / "mycelium-frontend"
            standalone = frontend / ".next" / "standalone" / "server.js"
            if standalone.exists() and node:
                return [str(node), "server.js"], standalone.parent
            if shutil.which("pnpm"):
                return ["pnpm", "exec", "next", "dev", "-p", str(UI_PORT)], frontend
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
    state: State = "stopped"
    detail: str | None = None
    proc: subprocess.Popen | None = None
    restarts: int = 0
    started_at: float = 0.0
    retry_at: float = 0.0

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
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._last: str | None = None
        self.runner: Any = None
        self.runner_state: State = "stopped"
        self.runner_detail: str | None = None
        self.components: list[Component] = self._components() if mode == "hub" else []

    # ── what runs ────────────────────────────────────────────────────────────

    @property
    def api_url(self) -> str:
        return f"http://{HOST}:{HUB_PORT}" if self.mode == "hub" else str(self.hub_url)

    @property
    def ui_url(self) -> str:
        return f"http://{HOST}:{UI_PORT}" if self.mode == "hub" else str(self.hub_url)

    def _components(self) -> list[Component]:
        loc = self.locator
        hub_env_vars = {
            **self.env,
            "SLIM_NODE_ENDPOINT": f"http://{HOST}:{SLIM_PORT}",
            "MYCELIUM_SLIM_ENDPOINT": f"http://{HOST}:{SLIM_PORT}",
        }
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
                self._set(c, "failed", f"{c.name} keeps exiting (last exit code {code})")
                return False
            wait = BACKOFF_S[min(c.restarts, len(BACKOFF_S)) - 1]
            c.retry_at = time.monotonic() + wait
            self._set(c, "starting", f"exited with code {code}; starting again in {wait:.0f}s")
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
        from mycelium.runner.daemon import Runner

        config = self.config or MyceliumConfig.load()
        config.server.api_url = self.api_url
        # stdout is the status stream; what the runner says goes to stderr.
        self.runner = Runner(config, roots=self.roots, log=Console(stderr=True))
        self.runner_state, self.runner_detail = "starting", None
        self._publish()

        def run() -> None:
            try:
                self.runner.run()
            except Exception as e:  # noqa: BLE001 - reported, never raised into the supervisor
                self.runner_state, self.runner_detail = "failed", str(e)
                self._publish()

        threading.Thread(target=run, daemon=True).start()

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
            if c.proc is not None:
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
