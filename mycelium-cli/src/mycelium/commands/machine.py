# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium machine``: the agents on this machine, and what to do about them.

Every agent here, wherever it runs (a herdr pane, an Omnigent session) and
however it got there, with its state, its folder, whether herdr brings it back
after a restart and who keeps its workspace synced, then the problems found and
the command that fixes each. The same report and actions as the app's
Machines page; see ``mycelium.machine``.
"""

from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

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
    set_runner_sync,
    stop,
    unbind,
)

app = typer.Typer(
    help="The agents on this machine: their state, sync and herdr's integrations, and actions on them.",
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


def _read(config: MyceliumConfig) -> Report:
    return report(config)


def _fail(e: Exception) -> None:
    console.print(f"[red]{escape(str(e))}[/red]")
    raise typer.Exit(1)


def _synced(w) -> str:  # noqa: ANN001 - a machine.Workspace
    if w.synced_by == "runner":
        return "kept synced by this machine's runner"
    if w.synced_by == "terminal":
        return "synced by a `herdr sync` loop"
    if w.runner_keeps:
        return "kept synced by the runner (not running)"
    return "[yellow]not synced[/yellow]"


def _print(r: Report) -> None:
    herdr = (
        f"herdr {r.herdr_server}"
        + (f" · client {r.herdr_client}" if r.herdr_client != r.herdr_server else "")
        if r.herdr
        else "herdr not running"
    )
    extra = f" · Omnigent at {r.omnigent_url}" if r.omnigent_url else ""
    console.print(f"[bold]{escape(r.machine)}[/bold] [dim]· {escape(herdr)}{escape(extra)}[/dim]\n")
    if not r.workspaces:
        console.print("[dim]No agents on this machine yet.[/dim]")
    for w in r.workspaces:
        where = f"{w.host} · {w.label}" if w.host == "herdr" else w.label
        room = f" → {w.room}" if w.room else ""
        console.print(f"[bold]{escape(where)}[/bold][dim]{escape(room)} · {_synced(w)}[/dim]")
        if not w.agents:
            console.print("  [dim]no agents bound[/dim]\n")
            continue
        table = Table(box=None, pad_edge=False, show_header=True, header_style="dim")
        for col in ("agent", "room", "state", "cli", "folder", "if herdr restarts", "where"):
            table.add_column(col)
        for a in w.agents:
            word, color = _STATE.get(a.state, (a.state, "white"))
            table.add_row(
                f"@{escape(a.handle)}",
                escape(a.room),
                f"[{color}]{word}[/{color}]",
                escape(a.kind or "?"),
                escape(_short_path(a.folder)),
                _RESTORES[a.restores],
                f"[dim]{escape(a.ref)}[/dim]",
            )
        console.print(table)
        console.print()
    if not r.problems:
        console.print("[green]No problems.[/green]")
        return
    console.print(f"[bold]{len(r.problems)} problem{'s' if len(r.problems) != 1 else ''}[/bold]")
    for p in r.problems:
        mark = {"stopped": "[red]✗[/red]", "herdr_down": "[red]✗[/red]"}.get(
            p.kind, "[yellow]![/yellow]"
        )
        console.print(f"  {mark} {escape(p.text)}")
        if p.fix:
            console.print(f"      [cyan]{escape(p.fix)}[/cyan]")


#: What happens to an agent if herdr's server restarts, by whether herdr restores it.
_RESTORES = {
    True: "comes back",
    False: "[yellow]stops[/yellow]",
    None: "[dim]unknown[/dim]",
}


def _short_path(path: str | None) -> str:
    if not path:
        return "unknown"
    from pathlib import Path

    home = str(Path.home())
    return "~" + path[len(home) :] if path.startswith(home) else path


@doc_ref(
    usage="mycelium machine [--json]",
    desc="Show every agent on this machine: its state, folder, whether herdr brings it back after a restart, and who keeps it synced, then the problems found and how to fix each.",
    group="agent",
)
@app.callback()
def machine(
    ctx: typer.Context,
    as_json: bool = typer.Option(False, "--json", help="Print the report as JSON."),
) -> None:
    """Every agent on this machine, and what's wrong.

    Reads herdr's bindings, the runner's state and the hosts themselves, so an
    agent whose pane is open but empty (herdr's server restarted, say) shows as
    stopped rather than as missing, ready to be restarted.
    """
    if ctx.invoked_subcommand is not None:
        return
    r = _read(MyceliumConfig.load())
    if as_json:
        console.print_json(json.dumps(r.wire()))
        return
    _print(r)


def _agent(handle: str, room: str | None) -> tuple[MyceliumConfig, Agent]:
    config = MyceliumConfig.load()
    try:
        return config, _read(config).find(handle, room)
    except MachineError as e:
        _fail(e)
        raise


@doc_ref(
    usage="mycelium machine restart <handle>... | --all [--room <room>] [--yes]",
    desc="Start stopped agents again in their own folders, as themselves, to catch up from the room.",
    group="agent",
)
@app.command("restart")
def restart_cmd(
    handles: list[str] = typer.Argument(None, help="Agents to restart (@ optional)."),
    every: bool = typer.Option(False, "--all", help="Restart every stopped agent that can be."),
    room: str | None = typer.Option(
        None, "--room", "-r", help="The room, when two share a handle."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Don't ask first."),
) -> None:
    """Restart stopped agents.

    Each starts in its own pane (or a new one beside it, if its pane is gone),
    in its folder, with its handle and room set, and is told to catch up from
    the room: it doesn't remember its last session. (After herdr itself
    restarts, agents with herdr's integration come back in their own session
    without this; see `mycelium machine integrations`.) Says what it will start
    and asks first.
    """
    config = MyceliumConfig.load()
    r = _read(config)
    try:
        if every:
            agents = [a for a in r.agents if a.restartable]
        elif handles:
            agents = [r.find(h, room) for h in handles]
        else:
            _fail(MachineError("Say which agents to restart, or --all."))
            return
    except MachineError as e:
        _fail(e)
        return
    if not agents:
        console.print("[dim]Nothing to restart: no agent here has stopped.[/dim]")
        return
    for a in [a for a in agents if not a.restartable]:
        why = (
            "it's running" if a.state not in ("stopped", "gone") else "no folder or kind on record"
        )
        console.print(f"[yellow]skip[/yellow] @{escape(a.handle)}: can't be restarted ({why})")
    agents = [a for a in agents if a.restartable]
    if not agents:
        raise typer.Exit(1)
    console.print(f"Restart {len(agents)} on {escape(r.machine)}:")
    for a in agents:
        console.print(f"  [cyan]{escape(restart_command(a))}[/cyan]")
    if not yes and not typer.confirm("Start them?", default=True):
        raise typer.Exit(1)
    failed = 0
    for a in agents:
        try:
            pane = restart(config, a)
        except MachineError as e:
            failed += 1
            console.print(f"[red]✗[/red] @{escape(a.handle)}: {escape(str(e))}")
            continue
        console.print(f"[green]restarted[/green] @{escape(a.handle)} in {escape(a.room)} → {pane}")
    if failed:
        raise typer.Exit(1)


@doc_ref(
    usage="mycelium machine stop <handle> [--room <room>]",
    desc="End an agent's session. Its pane stays open and it stays in its room, so it can be restarted.",
    group="agent",
)
@app.command("stop")
def stop_cmd(
    handle: str = typer.Argument(..., help="The agent (@ optional)."),
    room: str | None = typer.Option(
        None, "--room", "-r", help="The room, when two share a handle."
    ),
) -> None:
    """Stop an agent, keeping its pane and its place in the room."""
    _config, agent = _agent(handle, room)
    try:
        stop(agent)
    except MachineError as e:
        _fail(e)
    console.print(f"[yellow]stopped[/yellow] @{escape(agent.handle)} in {escape(agent.room)}")


@doc_ref(
    usage="mycelium machine rename <handle> <name> [--room <room>]",
    desc="Set the name herdr shows for an agent. Its handle in the room doesn't change.",
    group="agent",
)
@app.command("rename")
def rename_cmd(
    handle: str = typer.Argument(..., help="The agent (@ optional)."),
    name: str = typer.Argument(..., help="The name herdr should show."),
    room: str | None = typer.Option(
        None, "--room", "-r", help="The room, when two share a handle."
    ),
) -> None:
    """Rename an agent in herdr."""
    _config, agent = _agent(handle, room)
    try:
        rename(agent, name)
    except MachineError as e:
        _fail(e)
    console.print(f"herdr now calls @{escape(agent.handle)} [bold]{escape(name)}[/bold]")


@doc_ref(
    usage="mycelium machine unbind <handle> [--room <room>] | --gone [--yes]",
    desc="Forget which herdr pane an agent is (or every agent whose pane is gone with nothing to restart). They stay in their rooms.",
    group="agent",
)
@app.command("unbind")
def unbind_cmd(
    handle: str | None = typer.Argument(None, help="The agent (@ optional)."),
    gone: bool = typer.Option(
        False, "--gone", help="Every agent whose pane is gone with nothing to restart it from."
    ),
    room: str | None = typer.Option(
        None, "--room", "-r", help="The room, when two share a handle."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Don't ask first."),
) -> None:
    """Unbind an agent from its herdr pane."""
    if gone:
        r = _read(MyceliumConfig.load())
        agents = [a for a in r.agents if a.state == "gone" and not a.restartable]
        if not agents:
            console.print("[dim]No gone panes to forget.[/dim]")
            return
        names = ", ".join(f"@{a.handle} ({a.room})" for a in agents)
        console.print(
            f"Forget {len(agents)} pane{'s' if len(agents) != 1 else ''}: {escape(names)}"
        )
        if not yes and not typer.confirm("Unbind them?", default=True):
            raise typer.Exit(1)
        for agent in agents:
            unbind(agent)
        console.print(f"unbound {len(agents)}")
        return
    if not handle:
        _fail(MachineError("Say which agent to unbind, or --gone."))
        return
    _config, agent = _agent(handle, room)
    try:
        unbind(agent)
    except MachineError as e:
        _fail(e)
    console.print(f"unbound @{escape(agent.handle)} from {escape(agent.ref)}")


@doc_ref(
    usage="mycelium machine integrations [--install | --decline] [--yes] [--json]",
    desc="Show whether herdr can bring this machine's agents back after it restarts, and install its integrations for them.",
    group="agent",
)
@app.command("integrations")
def integrations_cmd(
    install: bool = typer.Option(
        False, "--install", help="Install herdr's integration for each agent CLI here."
    ),
    decline: bool = typer.Option(
        False, "--decline", help="Don't install them, and don't ask again."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Install without asking first."),
    as_json: bool = typer.Option(False, "--json", help="Print the state as JSON."),
) -> None:
    """herdr's integrations for the agent CLIs here.

    With an agent CLI's integration installed, herdr brings each of its agents
    back in its own session after herdr's server restarts. Installing one adds
    a hook to that CLI's own settings (for Claude Code, ~/.claude/settings.json),
    so it is only done when you say so. The answer is remembered either way.
    """
    if install and decline:
        _fail(MachineError("Say --install or --decline, not both."))
    if decline:
        decline_integrations()
        console.print("[dim]Not installing herdr's integrations; you won't be asked again.[/dim]")
        return
    state = integrations()
    if install:
        if not state.missing:
            console.print("herdr's integrations are already current for every agent CLI here.")
            return
        console.print(
            f"Install herdr's integration for {escape(', '.join(state.missing))}? Each adds "
            "a hook to that agent CLI's settings, so herdr can bring its agents back in "
            "their own session after herdr restarts."
        )
        if not yes and not typer.confirm("Install?", default=True):
            raise typer.Exit(1)
        try:
            done = install_integrations()
        except MachineError as e:
            _fail(e)
            return
        console.print(f"[green]installed[/green] {escape(', '.join(done))}")
        return
    if as_json:
        # Plain, for the Mac app to read.
        typer.echo(json.dumps(state.wire()))
        return
    version = state.herdr_server or state.herdr_client or "not found"
    console.print(f"herdr {escape(version)} [dim](Mycelium needs {state.minimum} or newer)[/dim]")
    if state.out_of_date:
        console.print(
            "[red]herdr is out of date.[/red] Run `mycelium machine` for how to update it."
        )
    if not state.current:
        console.print("[dim]No agent CLI here that herdr has an integration for.[/dim]")
        return
    for name, ok in sorted(state.current.items()):
        mark = "[green]current[/green]" if ok else "[yellow]not installed[/yellow]"
        console.print(f"  {escape(name)}: {mark}")
    if state.missing:
        console.print("Install them with `mycelium machine integrations --install`.")


@doc_ref(
    usage="mycelium machine sync <workspace> on|off",
    desc="Choose whether this machine's runner keeps a herdr workspace synced (presence up, wakes down).",
    group="agent",
)
@app.command("sync")
def sync_cmd(
    workspace: str = typer.Argument(..., help="The herdr workspace id (from `mycelium machine`)."),
    state: str = typer.Argument(..., help="on or off."),
) -> None:
    """Have the runner keep a workspace synced, or stop.

    Kept synced, its agents hear their mentions and the room sees whether
    they're busy, without a `herdr sync` loop open in a terminal. Only one
    thing syncs a workspace: a terminal loop leaves alone one the runner keeps.
    """
    if state not in ("on", "off"):
        _fail(MachineError("Say on or off."))
    set_runner_sync(workspace, state == "on")
    from mycelium.commands.runner import running_pid

    if state == "on":
        tail = (
            "" if running_pid() else " Start the runner (`mycelium runner`) for it to take effect."
        )
        console.print(f"The runner will keep {escape(workspace)} synced.{tail}")
    else:
        console.print(f"The runner won't sync {escape(workspace)} any more.")
