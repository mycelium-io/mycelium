# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium runner``: let the app start agents on this machine.

Run it once and leave it running. It looks for the agent CLIs installed here,
tells the hub what it found, and starts agents in herdr when someone asks for
one from the app (a single agent, or a whole swarm). It only ever dials out to
the hub, so it works the same against a hub on this laptop or one elsewhere.

The app can only start what the scan found, in folders you allowed with
``--root`` (default: the folder you run it from).
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref

app = typer.Typer(
    help="Let the app start agents on this machine: scan for agent CLIs, take launches.",
    invoke_without_command=True,
)
console = Console()


def _pid_path() -> Path:
    from mycelium.runner.daemon import runner_dir

    return runner_dir() / "runner.pid"


def _log_path() -> Path:
    from mycelium.runner.daemon import runner_dir

    return runner_dir() / "runner.log"


def running_pid() -> int | None:
    """The pid of this machine's runner, when one is running."""
    try:
        pid = int(_pid_path().read_text().strip())
    except (OSError, ValueError):
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    except PermissionError:
        return pid
    return pid


def _scan_table(found: list, *, herdr: bool) -> Table:
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("Agent CLI")
    table.add_column("Version")
    table.add_column("Can start", justify="center")
    table.add_column("Note", style="dim")
    for f in found:
        if not f.installed:
            continue
        table.add_row(
            f.name, f.version or "", "[green]yes[/]" if f.launchable else "no", f.note or ""
        )
    if not any(f.installed for f in found):
        table.add_row("[dim]none found[/]", "", "", "")
    if not herdr:
        table.caption = "herdr isn't running here, so nothing can be started. https://herdr.dev"
    return table


@doc_ref(
    usage="mycelium runner [--root <folder>]... [--detach]",
    desc="Let the app start agents on this machine: scan for agent CLIs, take launches from the hub.",
    group="agent",
)
@app.callback()
def runner(
    ctx: typer.Context,
    root: list[Path] = typer.Option(
        None,
        "--root",
        help="A folder agents may be started in (repeatable; default: this folder)",
    ),
    detach: bool = typer.Option(False, "--detach", "-d", help="Run in the background"),
) -> None:
    """Connect this machine to the hub so the app can start agents on it.

    Examples:
        mycelium runner
        mycelium runner --root ~/code --detach
        mycelium runner status
    """
    if ctx.invoked_subcommand is not None:
        return
    from mycelium.runner.daemon import Runner

    roots = [p.expanduser().resolve() for p in (root or [Path.cwd()])]
    if (pid := running_pid()) is not None and pid != os.getpid():
        console.print(
            f"[yellow]A runner is already running here[/yellow] (pid {pid}). "
            "See it with: mycelium runner status"
        )
        raise typer.Exit(1)

    if detach:
        args = [sys.argv[0], "runner", *(a for r in roots for a in ("--root", str(r)))]
        with _log_path().open("ab") as log:
            proc = subprocess.Popen(  # noqa: S603 - this same CLI, code-built arguments
                args,
                stdout=log,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        console.print(
            f"[green]Runner started[/green] in the background (pid {proc.pid}). "
            f"Log: {_log_path()}\nStop it with: mycelium runner stop"
        )
        return

    config = MyceliumConfig.load()
    daemon = Runner(config, roots=roots)
    _pid_path().write_text(f"{os.getpid()}\n")

    def _terminate(*_: object) -> None:
        daemon.stop()
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _terminate)
    found = daemon.scan()
    console.print(f"[bold]{daemon.label}[/bold] · runner [cyan]{daemon.id}[/cyan]")
    console.print(_scan_table(found, herdr=daemon.herdr))
    console.print(f"[dim]Agents may be started in: {', '.join(str(r) for r in daemon.roots)}[/dim]")
    console.print("[dim]Open the app to start agents here. Ctrl-C to disconnect.[/dim]\n")
    try:
        daemon.run()
    except KeyboardInterrupt:
        daemon.stop()
        daemon.goodbye()
        console.print("\n[dim]Disconnected. Agents already started keep running in herdr.[/dim]")
    finally:
        try:
            if running_pid() == os.getpid():
                _pid_path().unlink()
        except OSError:
            pass


@doc_ref(
    usage="mycelium runner status",
    desc="Show whether this machine's runner is running and connected to the hub.",
    group="agent",
)
@app.command("status")
def runner_status() -> None:
    """Whether this machine's runner is running, and what the hub sees of it."""
    import httpx

    from mycelium.client import hub_client
    from mycelium.runner.daemon import runner_id

    pid = running_pid()
    rid = runner_id()
    console.print(
        f"runner [cyan]{rid}[/cyan]: " + (f"running (pid {pid})" if pid else "not running")
    )
    try:
        with hub_client(MyceliumConfig.load(), timeout=5) as client:
            resp = client.get(f"/api/runners/{rid}")
    except httpx.HTTPError as e:
        console.print(f"[yellow]hub unreachable:[/yellow] {e}")
        raise typer.Exit(1) from None
    if resp.status_code == 404:
        console.print("[dim]The hub hasn't heard from it.[/dim]")
        return
    seen = resp.json()
    state = "[green]connected[/]" if seen.get("connected") else "[yellow]not connected[/]"
    console.print(f"hub: {state} · herdr {'yes' if seen.get('herdr') else 'no'}")
    for a in seen.get("agents") or []:
        console.print(f"  @{a['handle']} in {a['room']} · {a['framework']} · {a['status']}")


@doc_ref(
    usage="mycelium runner stop",
    desc="Stop this machine's background runner. Agents it started keep running in herdr.",
    group="agent",
)
@app.command("stop")
def runner_stop() -> None:
    """Stop the runner. Agents it started keep running in herdr."""
    pid = running_pid()
    if pid is None:
        console.print("[dim]No runner is running here.[/dim]")
        return
    os.kill(pid, signal.SIGTERM)
    console.print(f"[green]Stopped[/green] the runner (pid {pid}).")


@doc_ref(
    usage="mycelium runner scan",
    desc="List the agent CLIs on this machine and which of them herdr can start.",
    group="agent",
)
@app.command("scan")
def runner_scan(
    json_out: bool = typer.Option(False, "--json", help="Print the scan as JSON"),
) -> None:
    """What the runner would report: the agent CLIs here, and which herdr can start."""
    import json

    from mycelium.integrations.herdr import HerdrBridge
    from mycelium.runner import frameworks

    bridge = HerdrBridge()
    herdr = bridge.available()
    found = frameworks.scan(bridge.supported_kinds() if herdr else None)
    if json_out:
        print(json.dumps({"herdr": herdr, "frameworks": [f.wire() for f in found]}))
        return
    console.print(_scan_table(found, herdr=herdr))
