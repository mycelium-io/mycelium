# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium machine``: the agents on this machine, and what to do about them.

The same report and actions as the app's Machines page; see ``mycelium.machine``.
"""

from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from mycelium.cli_options import confirms, emits_json, in_room
from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref
from mycelium.machine import (
    Agent,
    MachineError,
    Report,
    decline_integrations,
    install_integrations,
    integrations,
    rename,
    report,
    restart,
    restart_command,
    unbind,
)

app = typer.Typer(
    help="The agents on this machine, what's wrong with them, and what to do about it.",
    invoke_without_command=True,
)
console = Console()

#: How each state reads, and its color.
_STATE = {
    "working": ("working", "cyan"),
    "idle": ("idle", "white"),
    "blocked": ("blocked", "yellow"),
    "stopped": ("stopped, pane open", "red"),
    "gone": ("pane gone", "bright_black"),
    "unknown": ("unknown", "bright_black"),
}
#: What happens to an agent if herdr's server restarts.
_RESTORES = {True: "comes back", False: "[yellow]stops[/yellow]", None: "[dim]-[/dim]"}


def _fail(message: str) -> None:
    console.print(f"[red]{escape(message)}[/red]")
    raise typer.Exit(1)


def _print(r: Report) -> None:
    herdr = f"herdr {r.herdr_server}" if r.herdr else "[yellow]herdr not running[/yellow]"
    runner = "runner running" if r.runner else "[yellow]runner not running[/yellow]"
    console.print(f"[bold]{escape(r.machine)}[/bold] [dim]·[/dim] {herdr} [dim]·[/dim] {runner}\n")
    if not r.workspaces:
        console.print("[dim]No agents on this machine yet.[/dim]")
    for w in r.workspaces:
        room = f" → {w.room}" if w.room else ""
        console.print(f"[bold]{escape(w.label)}[/bold][dim]{escape(room)}[/dim]")
        if not w.agents:
            console.print("  [dim]no agents bound[/dim]\n")
            continue
        table = Table(box=None, pad_edge=False, header_style="dim")
        for col in ("agent", "room", "state", "cli", "folder", "if herdr restarts"):
            table.add_column(col)
        for a in w.agents:
            word, color = _STATE[a.state]
            table.add_row(
                f"@{escape(a.handle)}",
                escape(a.room),
                f"[{color}]{word}[/{color}]",
                escape(a.kind or "?"),
                escape(_tilde(a.folder)),
                _RESTORES[a.restores],
            )
        console.print(table)
        console.print()
    if not r.problems:
        console.print("[green]Nothing to fix.[/green]")
        return
    console.print(f"[bold]{len(r.problems)} to fix[/bold]")
    for p in r.problems:
        console.print(f"  [yellow]![/yellow] {escape(p.text)}")
        if p.fix:
            console.print(f"      [cyan]{escape(p.fix)}[/cyan]")


def _tilde(path: str | None) -> str:
    if not path:
        return "unknown"
    from pathlib import Path

    home = str(Path.home())
    return "~" + path[len(home) :] if path.startswith(home) else path


def _find(handle: str, room: str | None) -> Agent:
    try:
        return report().find(handle, room)
    except MachineError as e:
        _fail(str(e))
        raise


# --room here only tells apart two agents with one handle, so it is never resolved
# to the active room: without it, a handle names the agent in whichever room it is.


@doc_ref(
    usage="mycelium machine [--json]",
    desc="Show every agent on this machine, its state, and whether herdr brings it back after a restart; then what's wrong and how to fix it.",
    group="agent",
)
@app.callback()
@emits_json("as_json")
def machine(
    ctx: typer.Context,
    as_json: bool = False,
) -> None:
    """Every agent on this machine, and what's wrong.

    An agent whose pane is open but empty (herdr's server restarted, say) shows
    as stopped, ready to restart, rather than missing.
    """
    if ctx.invoked_subcommand is not None:
        return
    r = report()
    if as_json:
        typer.echo(json.dumps(r.wire()))
        return
    _print(r)


@doc_ref(
    usage="mycelium machine restart <handle>... | --all [--room <room>] [--yes]",
    desc="Start stopped agents again in their own folders, as themselves, to catch up from the room.",
    group="agent",
)
@app.command("restart")
@in_room("room", resolve=False)
@confirms("yes")
def restart_cmd(
    handles: list[str] = typer.Argument(None, help="Agents to restart (@ optional)."),
    every: bool = typer.Option(False, "--all", help="Every stopped agent that can be."),
    room: str | None = None,
    yes: bool = False,
) -> None:
    """Restart stopped agents.

    Each starts in its own pane (or a new one beside its room's, if its pane is
    gone), in its folder, with its handle and room set, and is told to catch up
    from the room: it doesn't remember its last session. After herdr itself
    restarts, agents with herdr's integration come back on their own; see
    `mycelium machine integrations`.
    """
    r = report()
    try:
        if every:
            agents = [a for a in r.agents if a.restartable]
        elif handles:
            agents = [r.find(h, room) for h in handles]
        else:
            _fail("Say which agents to restart, or --all.")
            return
    except MachineError as e:
        _fail(str(e))
        return
    for a in [a for a in agents if not a.restartable]:
        why = "it's running" if a.state not in ("stopped", "gone") else "no folder or CLI on record"
        console.print(f"[yellow]skip[/yellow] @{escape(a.handle)}: {why}")
    agents = [a for a in agents if a.restartable]
    if not agents:
        console.print("[dim]Nothing to restart.[/dim]")
        return
    console.print(f"Restart {len(agents)} on {escape(r.machine)}:")
    for a in agents:
        console.print(f"  [cyan]{escape(restart_command(a))}[/cyan]")
    if not yes and not typer.confirm("Start them?", default=True):
        raise typer.Exit(1)
    config = MyceliumConfig.load()
    failed = False
    for a in agents:
        try:
            pane = restart(config, a)
        except MachineError as e:
            failed = True
            console.print(f"[red]✗[/red] {escape(str(e))}")
            continue
        console.print(f"[green]restarted[/green] @{escape(a.handle)} in {escape(a.room)} → {pane}")
    if failed:
        raise typer.Exit(1)


@doc_ref(
    usage="mycelium machine rename <handle> <name> [--room <room>]",
    desc="Set the name herdr shows for an agent. Its handle in the room doesn't change.",
    group="agent",
)
@app.command("rename")
@in_room("room", resolve=False)
def rename_cmd(
    handle: str = typer.Argument(..., help="The agent (@ optional)."),
    name: str = typer.Argument(..., help="The name herdr should show."),
    room: str | None = None,
) -> None:
    """Rename an agent in herdr."""
    agent = _find(handle, room)
    try:
        rename(agent, name)
    except MachineError as e:
        _fail(str(e))
    console.print(f"herdr now calls @{escape(agent.handle)} [bold]{escape(name)}[/bold]")


@doc_ref(
    usage="mycelium machine unbind <handle> [--room <room>] | --gone [--yes]",
    desc="Forget which herdr pane an agent is, or every pane that's gone with nothing to restart. They stay in their rooms.",
    group="agent",
)
@app.command("unbind")
@in_room("room", resolve=False)
@confirms("yes")
def unbind_cmd(
    handle: str | None = typer.Argument(None, help="The agent (@ optional)."),
    gone: bool = typer.Option(
        False, "--gone", help="Every pane that's gone with nothing to restart."
    ),
    room: str | None = None,
    yes: bool = False,
) -> None:
    """Unbind an agent from its herdr pane. It stays a member of its room."""
    if gone:
        agents = [a for a in report().agents if a.state == "gone" and not a.restartable]
        if not agents:
            console.print("[dim]No gone panes to forget.[/dim]")
            return
        names = ", ".join(f"@{a.handle} ({a.room})" for a in agents)
        console.print(
            f"Forget {len(agents)} pane{'s' if len(agents) != 1 else ''}: {escape(names)}"
        )
        if not yes and not typer.confirm("Unbind them?", default=True):
            raise typer.Exit(1)
        for a in agents:
            unbind(a)
        console.print(f"unbound {len(agents)}")
        return
    if not handle:
        _fail("Say which agent to unbind, or --gone.")
        return
    agent = _find(handle, room)
    unbind(agent)
    console.print(f"unbound @{escape(agent.handle)} from {escape(agent.pane)}")


@doc_ref(
    usage="mycelium machine integrations [--install | --decline] [--yes] [--json]",
    desc="Show whether herdr can bring this machine's agents back after it restarts, and install its integrations.",
    group="agent",
)
@app.command("integrations")
@confirms("yes")
@emits_json("as_json")
def integrations_cmd(
    install: bool = typer.Option(False, "--install", help="Install them for the agent CLIs here."),
    decline: bool = typer.Option(False, "--decline", help="Don't, and don't ask again."),
    yes: bool = False,
    as_json: bool = False,
) -> None:
    """herdr's integrations for the agent CLIs here.

    With an agent CLI's integration installed, herdr brings each of its agents
    back in its own session after herdr's server restarts. Installing one adds
    a hook to that CLI's own settings (for Claude Code, ~/.claude/settings.json),
    so it's only done when you say so. The answer is remembered either way.
    """
    if install and decline:
        _fail("Say --install or --decline, not both.")
    if decline:
        decline_integrations()
        console.print("[dim]Not installing herdr's integrations; you won't be asked again.[/dim]")
        return
    state = integrations()
    if as_json:
        typer.echo(json.dumps(state.wire()))
        return
    if install:
        if not state.missing:
            console.print("herdr's integrations are already current for every agent CLI here.")
            return
        console.print(
            f"Install herdr's integration for {escape(', '.join(state.missing))}? Each adds a "
            "hook to that agent CLI's settings, so herdr can bring its agents back after "
            "herdr restarts."
        )
        if not yes and not typer.confirm("Install?", default=True):
            raise typer.Exit(1)
        try:
            done = install_integrations()
        except MachineError as e:
            _fail(str(e))
            return
        console.print(f"[green]installed[/green] {escape(', '.join(done))}")
        return
    version = state.herdr_server or state.herdr_client or "not found"
    console.print(f"herdr {escape(version)} [dim](Mycelium needs {state.minimum} or newer)[/dim]")
    if state.server_out_of_date or state.client_out_of_date:
        console.print("[red]herdr is out of date.[/red] `mycelium machine` says how to update it.")
    if not state.current:
        console.print("[dim]No agent CLI here that herdr has an integration for.[/dim]")
        return
    for name, ok in sorted(state.current.items()):
        console.print(
            f"  {escape(name)}: {'[green]current[/green]' if ok else '[yellow]not installed[/yellow]'}"
        )
    if state.missing:
        console.print("Install them with `mycelium machine integrations --install`.")
