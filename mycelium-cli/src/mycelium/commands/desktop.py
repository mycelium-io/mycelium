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


def _log_line(event: dict[str, Any]) -> str:
    """One event as a line of the log file."""
    import time

    stamp = time.strftime("%H:%M:%S")
    kind = event.get("type")
    if kind == "log":
        return f"{stamp} {event['component']:>6} | {event['line']}"
    if kind == "error":
        return f"{stamp} {event['component']:>6} ! {event['message']}"
    if kind == "warning":
        return f"{stamp}   warn ! {event['message']}"
    if kind != "status":
        return f"{stamp} {json.dumps(event)}"
    states = ", ".join(
        f"{name} {c['state']}" + (f" ({c['detail']})" if c.get("detail") else "")
        for name, c in event.get("components", {}).items()
        if c["state"] != "disabled"
    )
    return f"{stamp} status - {states}"


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
    elif kind == "warning":
        console.print(f"[yellow]![/] {event['message']}")


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
    share_usage: bool | None = typer.Option(
        None,
        "--share-usage/--no-share-usage",
        help="Send the hub's anonymous usage stats (default: config.toml's telemetry setting)",
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

    from mycelium.desktop.supervisor import LOG_PATH

    lock = threading.Lock()
    # One log per run: what every part said, and each change of state.
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log_file = LOG_PATH.open("w", encoding="utf-8")

    def emit(event: dict[str, Any]) -> None:
        with lock:
            log_file.write(_log_line(event) + "\n")
            log_file.flush()
            if json_out:
                sys.stdout.write(json.dumps(event) + "\n")
                sys.stdout.flush()
        if not json_out and event.get("type") != "log":
            _human(event)

    roots = [p.expanduser().resolve() for p in (root or [Path.home()])]
    sup = Supervisor(
        cast("Mode", mode), hub_url=hub_url, roots=roots, emit=emit, share_usage=share_usage
    )

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


def model_view(llm: Any) -> dict[str, Any]:
    """The model settings as the app shows them. The key itself never leaves:
    only whether one is saved and its last four characters, to recognise it by."""
    key = (llm.api_key or "").strip()
    return {
        "model": llm.model or None,
        "base_url": llm.base_url or None,
        "has_key": bool(key),
        "key_hint": key[-4:] if len(key) >= 8 else None,
    }


def apply_model(llm: Any, body: dict[str, Any]) -> None:
    """Write ``body`` onto ``llm``. A field that is absent stays as it is; an
    empty one clears it. So the app can change the model without resending a
    key it was never shown."""
    if "model" in body:
        model = str(body["model"] or "").strip()
        if model and "/" not in model.strip("/"):
            msg = f"{model!r} isn't provider/model, like anthropic/claude-sonnet-4-6"
            raise ValueError(msg)
        llm.model = model or None
    if "api_key" in body:
        llm.api_key = str(body["api_key"] or "").strip() or None
    if "base_url" in body:
        llm.base_url = str(body["base_url"] or "").strip() or None


@doc_ref(
    usage="mycelium desktop model [--set]",
    desc="The model the hub on this machine runs its agents with, as JSON. With --set, reads new settings as JSON on stdin.",
    group="agent",
)
@app.command("model")
def model(
    set_: bool = typer.Option(
        False,
        "--set",
        help='Read {"model", "api_key", "base_url"} as JSON on stdin and save them',
    ),
) -> None:
    """The model settings (``llm.*`` in config.toml) the hub's own agents use.

    What the desktop app's settings read and write. The key is read from stdin
    rather than taken as an argument, so it never shows in the process list.
    A field left out of the JSON keeps its saved value; an empty one clears it.

    Examples:
        mycelium desktop model
        echo '{"model": "anthropic/claude-sonnet-4-6", "api_key": "sk-ant-..."}' | mycelium desktop model --set
    """
    from mycelium.config import MyceliumConfig

    config = MyceliumConfig.load()
    if set_:
        try:
            body = json.loads(sys.stdin.read() or "{}")
        except json.JSONDecodeError:
            console.print("[red]--set reads a JSON object on stdin.[/]")
            raise typer.Exit(2) from None
        if not isinstance(body, dict):
            console.print("[red]--set reads a JSON object on stdin.[/]")
            raise typer.Exit(2)
        try:
            apply_model(config.llm, body)
        except ValueError as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(2) from None
        config.save()
    sys.stdout.write(json.dumps(model_view(config.llm)) + "\n")


@doc_ref(
    usage="mycelium desktop experiences [--add ID PATH] [--remove ID]",
    desc="The experiences on this machine, as JSON. --add adds one's content from a .zip or folder; --remove takes it off.",
    group="agent",
)
@app.command("experiences")
def experiences(
    add: tuple[str, Path] | None = typer.Option(
        None, "--add", help="An experience's id and the .zip or folder its content comes in"
    ),
    remove: str | None = typer.Option(None, "--remove", help="Take an experience off this machine"),
) -> None:
    """Ready-made rooms to explore, added from a file: what the desktop app's
    Experiences section reads and writes.

    Adding one points the hub at its content (``patterns.dir``, personas only);
    the hub reads it the next time it starts.

    Examples:
        mycelium desktop experiences
        mycelium desktop experiences --add patterns-explorer ~/Downloads/patterns.zip
        mycelium desktop experiences --remove patterns-explorer
    """
    from mycelium.config import MyceliumConfig
    from mycelium.desktop import experiences as xp

    config = MyceliumConfig.load()
    try:
        if add is not None:
            xp.add(config, add[0], add[1])
            config.save()
        elif remove is not None:
            xp.remove(config, remove)
            config.save()
    except xp.ExperienceError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(2) from None
    sys.stdout.write(json.dumps(xp.view(config)) + "\n")
