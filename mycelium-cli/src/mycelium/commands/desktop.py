# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium desktop``: run Mycelium on this machine without Docker.

What the desktop app runs underneath its window, and the same thing from a
terminal. ``serve --mode hub`` runs a hub here (SLIM node, API, UI) plus the
runner; ``serve --mode client --hub-url <url>`` runs only the runner, for a
hub elsewhere.
"""

from __future__ import annotations

import json
import os
import signal
import stat
import sys
import threading
from pathlib import Path
from typing import Any, cast

import typer
from rich.console import Console

from mycelium.doc_ref import doc_ref

app = typer.Typer(help="Run Mycelium on this machine without Docker (what the desktop app runs).")
console = Console(stderr=True)

_MARK = {"running": "[green]●[/]", "starting": "[yellow]◐[/]", "failed": "[red]✗[/]"}


def _human(event: dict[str, Any]) -> None:
    kind = event.get("type")
    if kind == "status":
        parts = []
        for name, c in event["components"].items():
            if c["state"] == "disabled":
                continue
            mark = _MARK.get(c["state"], "[dim]○[/]")
            detail = f" [dim]{c['detail']}[/]" if c.get("detail") else ""
            parts.append(f"{mark} {name}{detail}")
        console.print("  ".join(parts) + f"   [dim]{event['ui_url']}[/]")
    elif kind == "error":
        console.print(f"[red]{event['component']}:[/] {event['message']}")


@doc_ref(
    usage="mycelium desktop serve --mode hub|client [--hub-url <url>] [--root <folder>]... [--json]",
    desc="Run a hub on this machine without Docker, or only the runner for a hub elsewhere.",
    group="agent",
)
@app.command("serve")
def serve(
    mode: str = typer.Option(
        "hub", "--mode", help="hub: run a hub here. client: join one elsewhere"
    ),
    hub_url: str | None = typer.Option(None, "--hub-url", help="With --mode client: the hub's URL"),
    root: list[Path] = typer.Option(
        None, "--root", help="A folder agents may be started in (repeatable; default: your home)"
    ),
    json_out: bool = typer.Option(
        False, "--json", help="Status, logs and errors as JSON lines on stdout (for the app)"
    ),
) -> None:
    """Run Mycelium here and keep it running until stopped.

    Examples:
        mycelium desktop serve
        mycelium desktop serve --mode client --hub-url https://hub.example.com
    """
    from mycelium.desktop.supervisor import Mode, Supervisor

    if mode not in ("hub", "client"):
        console.print("[red]--mode is hub or client.[/]")
        raise typer.Exit(2)
    if mode == "client" and not hub_url:
        console.print("[red]--mode client needs --hub-url.[/]")
        raise typer.Exit(2)

    lock = threading.Lock()

    def emit(event: dict[str, Any]) -> None:
        if json_out:
            with lock:
                sys.stdout.write(json.dumps(event) + "\n")
                sys.stdout.flush()
        elif event.get("type") != "log":
            _human(event)

    roots = [p.expanduser().resolve() for p in (root or [Path.home()])]
    sup = Supervisor(cast("Mode", mode), hub_url=hub_url, roots=roots, emit=emit)

    def _stop(*_: object) -> None:
        sup.stop()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    if json_out and stat.S_ISFIFO(os.fstat(sys.stdin.fileno()).st_mode):
        # The app holds a pipe to our stdin; when it goes away, so do we.
        def watch_parent() -> None:
            for _ in sys.stdin:
                pass
            sup.stop()

        threading.Thread(target=watch_parent, daemon=True).start()
    sup.run()
