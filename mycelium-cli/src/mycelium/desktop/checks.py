# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""What ``mycelium doctor --mode desktop`` checks: the pieces the desktop app runs.

The app runs no containers, so the Docker-shaped checks don't apply. These
look at what it does run, in the order a problem would show: the SLIM node,
the hub (and any other hub on this Mac), the UI, the runner and herdr under it, the agent CLIs herdr can
start, and whether ``mycelium`` and ``herdr`` are on PATH for the agents that
call them. Which of them apply depends on the app's own setting: a Mac that
joins a hub elsewhere runs no SLIM node, hub or UI.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

import httpx

from mycelium.desktop.supervisor import HOST, HUB_PORT, SLIM_PORT, UI_PORT, Locator, port_open
from mycelium.ui_status import CheckResult

SETTINGS = Path.home() / ".mycelium" / "desktop.json"


def settings() -> dict[str, Any] | None:
    """The app's setting (``~/.mycelium/desktop.json``), or ``None`` before its first run."""
    try:
        data = json.loads(SETTINGS.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def app_hub() -> bool:
    """Whether the desktop app runs this machine's hub: set up, and not joining one elsewhere."""
    s = settings()
    return s is not None and s.get("mode") != "client"


def start_hub() -> str:
    """How to start the hub here: the app when it runs it, else the Docker stack."""
    return "open the Mycelium app" if app_hub() else "mycelium up"


def app_setting() -> CheckResult:
    s = settings()
    if s is None:
        return CheckResult(
            name="Desktop app",
            status="warning",
            message="not set up yet",
            details=["Open Mycelium and choose how this computer takes part."],
        )
    if s.get("mode") == "client":
        return CheckResult(name="Desktop app", status="ok", message=f"joins {s.get('hubUrl')}")
    return CheckResult(name="Desktop app", status="ok", message="runs a hub on this computer")


def slim_node() -> CheckResult:
    if port_open(SLIM_PORT):
        return CheckResult(
            name="SLIM node", status="ok", message=f"listening on {HOST}:{SLIM_PORT}"
        )
    return CheckResult(
        name="SLIM node",
        status="error",
        message=f"nothing on {HOST}:{SLIM_PORT}",
        details=["Rooms can't carry messages without it. Quit Mycelium and open it again."],
    )


def _get(url: str, timeout: float = 3.0) -> httpx.Response | None:
    try:
        return httpx.get(url, timeout=timeout)
    except httpx.HTTPError:
        return None


def hub(api_url: str) -> CheckResult:
    base = api_url.rstrip("/")
    resp = _get(f"{base}/health")
    # A hub reached at its UI's address answers only under /api, where the UI
    # maps /api/health onto the hub's /health.
    if resp is not None and resp.status_code == 404:
        resp = _get(f"{base}/api/health")
    if resp is not None and resp.status_code == 200:
        return CheckResult(name="Hub", status="ok", message=f"answering at {api_url}")
    return CheckResult(
        name="Hub",
        status="error",
        message=f"no answer from {api_url}",
        details=["Is Mycelium running? Its menu bar icon shows each part's state."],
    )


def hubs_here(*, client: bool = False) -> CheckResult:
    """Every hub on this Mac: more than one, someone else's store, or an old one is a warning."""
    from mycelium import __version__
    from mycelium.config import MyceliumConfig
    from mycelium.hubs import at_port, find_hubs, warnings

    found = find_hubs(HUB_PORT)
    data_dir = MyceliumConfig.load().get_data_dir()
    said = warnings(found, data_dir, __version__)
    listed = [h.describe() for h in found]
    if not found:
        return CheckResult(
            name="Hubs on this computer",
            status="info" if client else "error",
            message="none running",
        )
    if client:
        # Joined elsewhere: a hub here gets nothing from the app.
        return CheckResult(
            name="Hubs on this computer",
            status="info",
            message=f"{len(found)} running, not used by the app",
            details=listed,
        )
    there = at_port(found, HUB_PORT)
    if not said:
        return CheckResult(name="Hubs on this computer", status="ok", message=listed[0])
    fix = []
    if there is not None:
        stop = (
            f"`docker compose -p {there.project} down`"
            if there.source == "docker" and there.project
            else f"`docker stop {there.container}`"
            if there.source == "docker" and there.container
            else f"`kill {there.pid}`"
            if there.source == "process" and there.pid
            else f"stop whatever is on port {there.port or HUB_PORT}"
        )
        fix.append(f"To use Mycelium's own hub: {stop}, then reopen Mycelium.")
    return CheckResult(
        name="Hubs on this computer",
        status="warning",
        message=said[0],
        details=[*said[1:], *listed, *fix],
    )


def ui() -> CheckResult:
    resp = _get(f"http://{HOST}:{UI_PORT}/")
    if resp is not None and resp.status_code < 500:
        return CheckResult(name="App UI", status="ok", message=f"serving on {HOST}:{UI_PORT}")
    return CheckResult(name="App UI", status="error", message=f"nothing on {HOST}:{UI_PORT}")


def runner(api_url: str) -> CheckResult:
    from mycelium.runner.daemon import runner_id

    rid = runner_id()
    resp = _get(f"{api_url.rstrip('/')}/api/runners/{rid}")
    if resp is None or resp.status_code == 404:
        return CheckResult(
            name="Runner",
            status="error",
            message="the hub hasn't heard from this computer",
            details=["Without it the app can't start agents here."],
        )
    seen = resp.json()
    if not seen.get("connected"):
        return CheckResult(name="Runner", status="error", message="stopped checking in")
    return CheckResult(name="Runner", status="ok", message=f"connected as {rid}")


def pairings() -> CheckResult | None:
    """The devices paired with this machine's runner and when each ends; ``None`` with none."""
    from datetime import UTC, datetime, timedelta

    from mycelium.runner import pairing

    found = pairing.load()
    if not found:
        return None
    now = datetime.now(UTC)
    soon = now + timedelta(days=7)
    lines, ending = [], 0
    for p in found:
        ends = p.limits.expires_at
        if ends is None:
            lines.append(f"{p.name}: no expiry")
            continue
        at = datetime.fromisoformat(ends)
        if at <= now:
            ending += 1
            lines.append(f"{p.name}: expired {ends[:10]}")
        else:
            ending += at <= soon
            lines.append(f"{p.name}: expires {ends[:10]}")
    n = len(found)
    message = f"{n} paired computer{'s' if n != 1 else ''}"
    if ending:
        lines.append("Renew with `mycelium runner pair`, or remove with `mycelium runner unpair`.")
        return CheckResult(
            name="Paired computers", status="warning", message=message, details=lines
        )
    return CheckResult(name="Paired computers", status="ok", message=message, details=lines)


def herdr() -> CheckResult:
    from mycelium.integrations.herdr import HerdrBridge

    bridge = HerdrBridge()
    if not bridge.binary_present():
        return CheckResult(
            name="herdr",
            status="error",
            message="not installed",
            details=["Agents run in herdr. Reinstall Mycelium, or get it from https://herdr.dev"],
        )
    if not bridge.available():
        return CheckResult(
            name="herdr",
            status="error",
            message="installed, but its server isn't running",
            details=["Open herdr once (run `herdr` in a terminal), then check again."],
        )
    from mycelium.integrations.herdr.bridge import MIN_VERSION, too_old

    server, client = bridge.server_version(), bridge.version()
    if too_old(client) or too_old(server):
        fix = (
            "Update it with `herdr update`."
            if too_old(client)
            else "Restart its server to start the newer one: `herdr server stop`."
        )
        return CheckResult(
            name="herdr",
            status="error",
            message=f"{server or client} is out of date (Mycelium needs {MIN_VERSION} or newer)",
            details=[fix, "`mycelium machine` says which agents that stops."],
        )
    version = server or client
    return CheckResult(
        name="herdr", status="ok", message=f"running{f' ({version})' if version else ''}"
    )


def agent_clis() -> CheckResult:
    from mycelium.integrations.herdr import HerdrBridge
    from mycelium.runner import frameworks

    bridge = HerdrBridge()
    found = frameworks.scan(bridge.supported_kinds() if bridge.available() else None)
    startable = [f.name for f in found if f.launchable]
    installed = [f.name for f in found if f.installed and not f.launchable]
    if startable:
        details = [f"installed, but herdr can't start: {', '.join(installed)}"] if installed else []
        return CheckResult(
            name="Agent CLIs",
            status="ok",
            message=", ".join(startable),
            details=details,
        )
    return CheckResult(
        name="Agent CLIs",
        status="warning",
        message="none that herdr can start",
        details=[
            "Install one, like Claude Code (https://claude.com/claude-code), then check again."
        ],
    )


def on_path() -> CheckResult:
    missing = [name for name in ("mycelium", "herdr") if shutil.which(name) is None]
    if not missing:
        return CheckResult(name="On your PATH", status="ok", message="mycelium and herdr")
    return CheckResult(
        name="On your PATH",
        status="error",
        message=f"missing: {', '.join(missing)}",
        details=[
            "Agents run these commands, so they must be on PATH.",
            "Open Mycelium again, which adds its folder to your PATH, then open a new terminal."
            if sys.platform == "win32"
            else 'Add this to your shell profile: export PATH="$HOME/.local/bin:$PATH"',
        ],
    )


def pi() -> CheckResult:
    found = Locator().pi()
    if found:
        return CheckResult(name="Pi", status="ok", message=found)
    return CheckResult(
        name="Pi",
        status="warning",
        message="not found; engines like the aligner can't think without it",
        details=["Reinstall Mycelium, or: npm install -g @earendil-works/pi-coding-agent"],
    )


def embedding_model() -> CheckResult:
    models = Locator().models()
    if models.is_dir() and any(models.iterdir()):
        return CheckResult(name="Search model", status="ok", message=str(models))
    return CheckResult(
        name="Search model",
        status="info",
        message="downloads on first use",
        details=[f"about 64 MB, into {models}"],
    )


def desktop_checks() -> list[tuple[str, list[CheckResult]]]:
    """Every check for this Mac as the app runs it, grouped for display."""
    s = settings() or {}
    client = s.get("mode") == "client"
    api_url = str(s.get("hubUrl") or "") if client else f"http://{HOST}:{HUB_PORT}"
    services: list[CheckResult] = [app_setting()]
    if not client:
        services.append(slim_node())
    services.append(hub(api_url) if api_url else app_setting())
    services.append(hubs_here(client=client))
    if not client:
        services.append(ui())
    if api_url:
        services.append(runner(api_url))
    agents = [herdr(), agent_clis(), on_path()]
    if (paired := pairings()) is not None:
        agents.append(paired)
    if not client:
        agents.append(embedding_model())
    here = "This Mac" if sys.platform == "darwin" else "This computer"
    return [(here, services), ("Agents", agents)]
