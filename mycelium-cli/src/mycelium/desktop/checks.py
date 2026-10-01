# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""What ``mycelium doctor --mode desktop`` checks: the pieces the desktop app runs.

The app runs no containers, so the Docker-shaped checks don't apply. These
look at what it does run, in the order a problem would show: the SLIM node,
the hub, the UI, the runner and herdr under it, the agent CLIs herdr can
start, whether ``mycelium`` and ``herdr`` are on PATH for the agents that
call them, and what ``mycelium machine`` finds wrong with the agents here. Which of them apply depends on the app's own setting: a Mac that
joins a hub elsewhere runs no SLIM node, hub or UI.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from mycelium.desktop.supervisor import HOST, HUB_PORT, SLIM_PORT, UI_PORT, Locator, port_open
from mycelium.ui_status import CheckResult

if TYPE_CHECKING:
    from mycelium.machine import Report

SETTINGS = Path.home() / ".mycelium" / "desktop.json"


def settings() -> dict[str, Any] | None:
    """The app's setting (``~/.mycelium/desktop.json``), or ``None`` before its first run."""
    try:
        data = json.loads(SETTINGS.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def app_setting() -> CheckResult:
    s = settings()
    if s is None:
        return CheckResult(
            name="Desktop app",
            status="warning",
            message="not set up yet",
            details=["Open Mycelium and choose how this Mac takes part."],
        )
    if s.get("mode") == "client":
        return CheckResult(name="Desktop app", status="ok", message=f"joins {s.get('hubUrl')}")
    return CheckResult(name="Desktop app", status="ok", message="runs a hub on this Mac")


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
            message="the hub hasn't heard from this Mac",
            details=["Without it the app can't start agents here."],
        )
    seen = resp.json()
    if not seen.get("connected"):
        return CheckResult(name="Runner", status="error", message="stopped checking in")
    return CheckResult(name="Runner", status="ok", message=f"connected as {rid}")


def herdr(here: Report | None = None) -> CheckResult:
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
    update = next((p for p in here.problems if p.kind == "herdr_update"), None) if here else None
    if update and here:
        return CheckResult(
            name="herdr",
            status="warning",
            message=f"server {here.herdr_server}, client {here.herdr_client}",
            details=[update.text, f"Fix: {update.fix}"],
        )
    version = bridge.version()
    return CheckResult(
        name="herdr", status="ok", message=f"running{f' ({version})' if version else ''}"
    )


def agents_here(here: Report) -> CheckResult:
    """The machine's agents: stopped ones, lost panes, workspaces nothing syncs."""
    problems = [p for p in here.problems if p.kind not in ("herdr_update", "herdr_down")]
    count = len(here.agents)
    if not problems:
        return CheckResult(
            name="Agents here",
            status="ok",
            message=f"{count} agent{'' if count == 1 else 's'}, nothing to fix",
        )
    details = []
    for p in problems:
        details.append(p.text)
        if p.fix:
            details.append(f"  Fix: {p.fix}")
    return CheckResult(
        name="Agents here",
        status="warning",
        message=f"{len(problems)} problem{'' if len(problems) == 1 else 's'}",
        details=[*details, "See them all with `mycelium machine`."],
    )


def _report() -> Report | None:
    from mycelium.config import MyceliumConfig
    from mycelium.machine import report

    try:
        return report(MyceliumConfig.load())
    except Exception:  # noqa: BLE001 - a check that can't read the machine reports nothing
        return None


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
            'Add this to your shell profile: export PATH="$HOME/.local/bin:$PATH"',
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
    if not client:
        services.append(ui())
    if api_url:
        services.append(runner(api_url))
    here = _report()
    agents = [herdr(here), agent_clis(), on_path()]
    if here is not None:
        agents.append(agents_here(here))
    if not client:
        agents.append(embedding_model())
    return [("This Mac", services), ("Agents", agents)]
