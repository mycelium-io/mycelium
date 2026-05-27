# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Daemon commands — manage the mycelium-cc-daemon service.

The daemon subscribes to room SSE and dispatches ``@handle`` mentions to
Claude Code spawns. It is installed via
``mycelium adapter add claude-code --step=daemon`` and exposes a unix-socket
health endpoint that these commands consume.
"""

from __future__ import annotations

import json as json_module
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from mycelium.daemon.config import DaemonConfig, daemon_log_path
from mycelium.daemon.health import read_health_blocking
from mycelium.doc_ref import doc_ref
from mycelium.error_handler import print_error

app = typer.Typer(
    help=(
        "Manage the mycelium-cc-daemon — the userlevel service that dispatches "
        "@handle mentions to Claude Code agents."
    ),
    no_args_is_help=True,
)
console = Console()

_DAEMON_LABEL = "io.mycelium.cc-daemon"
_DAEMON_SERVICE = "mycelium-cc-daemon"


def _format_age(ts: float | None) -> str:
    if not ts:
        return "—"
    delta = time.time() - float(ts)
    if delta < 60:
        return f"{int(delta)}s ago"
    if delta < 3600:
        return f"{int(delta / 60)}m ago"
    if delta < 86400:
        return f"{int(delta / 3600)}h ago"
    return f"{int(delta / 86400)}d ago"


@doc_ref(
    usage="mycelium daemon status",
    desc="Show daemon liveness, subscribed rooms, and last dispatch.",
    group="daemon",
)
@app.command("status")
def status(ctx: typer.Context) -> None:
    """Show daemon health, subscribed rooms, and last dispatch."""
    try:
        json_output = ctx.obj.get("json", False) if ctx.obj else False
        health = read_health_blocking(timeout=2.0)

        if json_output:
            typer.echo(json_module.dumps(health, indent=2, default=str))
            return

        if health is None:
            console.print(
                "[red]Daemon not responding[/red] (health socket unreachable).\n"
                "  Install or restart with: mycelium adapter add claude-code --step=daemon"
            )
            raise typer.Exit(1)

        uptime_s = int(health.get("uptime_s") or 0)
        rooms_cfg = health.get("rooms_configured") or []
        rooms_sub = health.get("rooms_subscribed") or []
        agents = health.get("agents_registered") or 0
        last = health.get("last_dispatch")
        last_err = health.get("last_error")
        errs_hr = health.get("errors_last_hour") or 0

        console.print("[bold green]✓ daemon running[/bold green]")
        console.print(f"  uptime:   {uptime_s // 3600}h {uptime_s % 3600 // 60}m {uptime_s % 60}s")
        console.print(f"  rooms:    {len(rooms_sub)}/{len(rooms_cfg)} connected")
        if rooms_cfg:
            for r in rooms_cfg:
                mark = "[green]●[/green]" if r in rooms_sub else "[yellow]○[/yellow]"
                console.print(f"            {mark} {r}")
        console.print(f"  agents:   {agents} registered")

        if last:
            ts = _format_age(last.get("ts"))
            console.print(
                f"  last run: @{last.get('agent')} in {last.get('room')} "
                f"({ts}, {last.get('duration_s', 0):.1f}s, "
                f"result={last.get('result')})"
            )
        else:
            console.print("  last run: —")

        console.print(f"  errors:   {errs_hr} in last hour")
        if last_err:
            console.print(
                f"            [red]{last_err.get('where')}[/red]: "
                f"{last_err.get('type')} — {last_err.get('msg')}"
            )
    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None


@doc_ref(
    usage="mycelium daemon subscribe <room>",
    desc="Add a room to the daemon's SSE subscription list and restart it.",
    group="daemon",
)
@app.command("subscribe")
def subscribe(
    ctx: typer.Context,
    room: str = typer.Argument(..., help="Room name to subscribe to."),
) -> None:
    """Tell the daemon to subscribe to ``room``.

    Writes the room into ``~/.mycelium/cc-daemon.toml`` and triggers a restart
    so the new subscription takes effect. Idempotent — adding the same room
    twice is a no-op.
    """
    try:
        cfg = DaemonConfig.load()
        if room in cfg.rooms:
            console.print(f"[dim]Already subscribed to {room}.[/dim]")
            return
        cfg.rooms.append(room)
        cfg.save()
        console.print(f"[green]Added[/green] {room} to daemon subscriptions.")
        _restart_service_quiet()
        console.print("[dim]Restarted daemon. Verify with: mycelium daemon status[/dim]")
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None


@doc_ref(
    usage="mycelium daemon unsubscribe <room>",
    desc="Remove a room from the daemon's SSE subscription list.",
    group="daemon",
)
@app.command("unsubscribe")
def unsubscribe(
    ctx: typer.Context,
    room: str = typer.Argument(..., help="Room name to unsubscribe from."),
) -> None:
    """Stop the daemon from watching ``room``."""
    try:
        cfg = DaemonConfig.load()
        if room not in cfg.rooms:
            console.print(f"[dim]Not subscribed to {room}.[/dim]")
            return
        cfg.rooms.remove(room)
        cfg.save()
        console.print(f"[green]Removed[/green] {room} from daemon subscriptions.")
        _restart_service_quiet()
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None


@doc_ref(
    usage="mycelium daemon ls",
    desc="List rooms the daemon is configured to subscribe to.",
    group="daemon",
)
@app.command("ls")
def ls(ctx: typer.Context) -> None:
    """List the daemon's configured room subscriptions."""
    try:
        json_output = ctx.obj.get("json", False) if ctx.obj else False
        cfg = DaemonConfig.load()
        health = read_health_blocking(timeout=1.0)
        connected: set[str] = set(health.get("rooms_subscribed") or []) if health else set()

        if json_output:
            typer.echo(
                json_module.dumps(
                    {"rooms": cfg.rooms, "connected": sorted(connected)},
                    indent=2,
                    default=str,
                )
            )
            return

        if not cfg.rooms:
            console.print(
                "[dim]No rooms subscribed.[/dim]\n  Add one with: mycelium daemon subscribe <room>"
            )
            return

        table = Table(title="daemon subscriptions", show_lines=False)
        table.add_column("Room", style="cyan")
        table.add_column("Status")
        for r in cfg.rooms:
            status_str = (
                "[green]connected[/green]" if r in connected else "[yellow]waiting[/yellow]"
            )
            table.add_row(r, status_str)
        console.print(table)
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None


@doc_ref(
    usage="mycelium daemon logs [--follow]",
    desc="Print the daemon's log file.",
    group="daemon",
)
@app.command("logs")
def logs(
    ctx: typer.Context,
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow the log (tail -f)."),
    lines: int = typer.Option(50, "--lines", "-n", help="Number of trailing lines to show."),
) -> None:
    """Print the daemon's log file at ``~/.mycelium/logs/cc-daemon.log``."""
    try:
        path = daemon_log_path()
        if not path.exists():
            console.print(f"[yellow]No log file at {path}.[/yellow]")
            return
        cmd = (
            ["tail", "-f", "-n", str(lines), str(path)]
            if follow
            else [
                "tail",
                "-n",
                str(lines),
                str(path),
            ]
        )
        subprocess.run(cmd)
    except KeyboardInterrupt:
        return
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None


@doc_ref(
    usage="mycelium daemon restart",
    desc="Restart the daemon service.",
    group="daemon",
)
@app.command("restart")
def restart(ctx: typer.Context) -> None:
    """Restart the daemon service via the platform's service manager."""
    try:
        _restart_service_quiet(verbose=True)
        console.print("[dim]Verify with: mycelium daemon status[/dim]")
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None


@doc_ref(
    usage="mycelium daemon run --foreground",
    desc="Run the daemon in the foreground (debug mode).",
    group="daemon",
)
@app.command("run")
def run(
    ctx: typer.Context,
    foreground: bool = typer.Option(
        False, "--foreground", help="Run in the foreground for debugging."
    ),
) -> None:
    """Run the daemon directly without going through the service manager.

    Useful for development and debugging — logs stream to stdout, signals
    (Ctrl-C) shut the daemon down cleanly.
    """
    try:
        if not foreground:
            console.print(
                "[yellow]Refusing to run detached from this command.[/yellow]\n"
                "  Use the service manager: mycelium adapter add claude-code --step=daemon\n"
                "  Or pass --foreground to run in this terminal."
            )
            raise typer.Exit(1)
        # Exec into the daemon process — replaces this Python process so
        # signals reach the asyncio loop directly.
        os.execvp(sys.executable, [sys.executable, "-m", "mycelium.daemon", "--foreground"])
    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None


# ── service-manager helpers ──────────────────────────────────────────────────


def _restart_service_quiet(verbose: bool = False) -> None:
    """Restart the daemon via the platform's service manager.

    No-op (with a hint) when the service isn't installed, so callers can
    use it as a "kick the daemon" primitive without first checking install
    state.
    """
    system = platform.system()
    if system == "Darwin":
        plist = Path.home() / "Library" / "LaunchAgents" / f"{_DAEMON_LABEL}.plist"
        if not plist.exists():
            if verbose:
                console.print(
                    "[yellow]Daemon service not installed (no launchd unit found).[/yellow]\n"
                    "  Install with: mycelium adapter add claude-code --step=daemon"
                )
            return
        target = f"gui/{os.getuid()}/{_DAEMON_LABEL}"
        subprocess.run(["launchctl", "kickstart", "-k", target], capture_output=True)
        if verbose:
            console.print(f"[green]Kicked[/green] launchd service {_DAEMON_LABEL}")
    elif system == "Linux":
        unit = Path.home() / ".config" / "systemd" / "user" / f"{_DAEMON_SERVICE}.service"
        if not unit.exists():
            if verbose:
                console.print(
                    "[yellow]Daemon service not installed (no systemd unit found).[/yellow]\n"
                    "  Install with: mycelium adapter add claude-code --step=daemon"
                )
            return
        subprocess.run(
            ["systemctl", "--user", "restart", f"{_DAEMON_SERVICE}.service"],
            capture_output=True,
        )
        if verbose:
            console.print(f"[green]Restarted[/green] systemd service {_DAEMON_SERVICE}")
    else:
        console.print(f"[yellow]Service restart not wired up for platform '{system}'.[/yellow]")
