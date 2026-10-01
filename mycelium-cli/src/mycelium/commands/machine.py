# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium machine``: the agents on this machine, and what to do about them.

Every agent here, wherever it runs (a herdr pane, an Omnigent session) and
however it got there, with its state, its folder, the session it can be
resumed in and who keeps its workspace synced, then the problems found and
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
    find_session,
    rename,
    report,
    resume,
    resume_command,
    save_session,
    set_runner_sync,
    stop,
    unbind,
)

app = typer.Typer(
    help="The agents on this machine: their state, sessions and sync, and actions on them.",
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
        for col in ("agent", "room", "state", "folder", "session", "where"):
            table.add_column(col)
        for a in w.agents:
            word, color = _STATE.get(a.state, (a.state, "white"))
            table.add_row(
                f"@{escape(a.handle)}",
                escape(a.room),
                f"[{color}]{word}[/{color}]",
                escape(_short_path(a.folder)),
                escape(_short_id(a.session))
                if a.session
                else "[dim]not saved[/dim]"
                if a.resumes
                else "[dim]can't resume[/dim]",
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


def _short_id(session: str) -> str:
    return f"{session[:4]}…{session[-4:]}" if len(session) > 12 else session


def _short_path(path: str | None) -> str:
    if not path:
        return "unknown"
    from pathlib import Path

    home = str(Path.home())
    return "~" + path[len(home) :] if path.startswith(home) else path


@doc_ref(
    usage="mycelium machine [--json]",
    desc="Show every agent on this machine: its state, folder, saved session and who keeps it synced, then the problems found and how to fix each.",
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
    stopped rather than as missing, with the session it can be resumed in.
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
    usage="mycelium machine resume <handle>... | --all [--room <room>] [--yes]",
    desc="Start stopped agents again in their own folders and saved sessions, as themselves.",
    group="agent",
)
@app.command("resume")
def resume_cmd(
    handles: list[str] = typer.Argument(None, help="Agents to resume (@ optional)."),
    every: bool = typer.Option(False, "--all", help="Resume every stopped agent that can be."),
    room: str | None = typer.Option(
        None, "--room", "-r", help="The room, when two share a handle."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Don't ask first."),
) -> None:
    """Resume stopped agents where they left off.

    Each starts in its own pane (or a new one beside it, if its pane is gone),
    in its folder, with its handle and room set, picking up its saved session.
    Shows what it will run and asks first.
    """
    config = MyceliumConfig.load()
    r = _read(config)
    try:
        if every:
            agents = [a for a in r.agents if a.resumable]
        elif handles:
            agents = [r.find(h, room) for h in handles]
        else:
            _fail(MachineError("Say which agents to resume, or --all."))
            return
    except MachineError as e:
        _fail(e)
        return
    if not agents:
        console.print("[dim]Nothing to resume: no stopped agent here has a saved session.[/dim]")
        return
    not_ready = [a for a in agents if not a.resumable]
    for a in not_ready:
        why = (
            "its agent CLI can't be resumed"
            if not a.resumes
            else "session saved"
            if a.session
            else "no session saved"
        )
        console.print(
            f"[yellow]skip[/yellow] @{escape(a.handle)}: can't be resumed ({a.state}, {why})"
        )
    agents = [a for a in agents if a.resumable]
    if not agents:
        raise typer.Exit(1)
    console.print(f"Resume {len(agents)} on {escape(r.machine)}:")
    for a in agents:
        console.print(f"  [cyan]{escape(resume_command(a))}[/cyan]")
    if not yes and not typer.confirm("Start them?", default=True):
        raise typer.Exit(1)
    failed = 0
    for a in agents:
        try:
            pane = resume(config, a)
        except MachineError as e:
            failed += 1
            console.print(f"[red]✗[/red] @{escape(a.handle)}: {escape(str(e))}")
            continue
        console.print(f"[green]resumed[/green] @{escape(a.handle)} in {escape(a.room)} → {pane}")
    if failed:
        raise typer.Exit(1)


@doc_ref(
    usage="mycelium machine stop <handle> [--room <room>]",
    desc="End an agent's session. Its pane stays open and it stays in its room, so it can be resumed.",
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
    desc="Forget which herdr pane an agent is (or every agent whose pane is gone with nothing to resume). They stay in their rooms.",
    group="agent",
)
@app.command("unbind")
def unbind_cmd(
    handle: str | None = typer.Argument(None, help="The agent (@ optional)."),
    gone: bool = typer.Option(
        False, "--gone", help="Every agent whose pane is gone and has no saved session."
    ),
    room: str | None = typer.Option(
        None, "--room", "-r", help="The room, when two share a handle."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Don't ask first."),
) -> None:
    """Unbind an agent from its herdr pane."""
    if gone:
        r = _read(MyceliumConfig.load())
        agents = [a for a in r.agents if a.state == "gone" and not a.resumable]
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
    usage="mycelium machine session <handle> [<session-id> | --find] [--room <room>]",
    desc="Show, set or find the saved session an agent resumes in.",
    group="agent",
)
@app.command("session")
def session_cmd(
    handle: str = typer.Argument(..., help="The agent (@ optional)."),
    session: str | None = typer.Argument(None, help="The session id to save for it."),
    find: bool = typer.Option(
        False, "--find", help="Look for its newest conversation in its folder."
    ),
    room: str | None = typer.Option(
        None, "--room", "-r", help="The room, when two share a handle."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Save what --find found without asking."),
) -> None:
    """The session an agent resumes in.

    Mycelium saves it when it starts an agent. For a pane you started yourself,
    ``--find`` looks for the newest session its agent CLI keeps for its folder
    and shows it before saving.
    """
    _config, agent = _agent(handle, room)
    if find:
        found = find_session(agent)
        if found is None:
            _fail(MachineError(f"No session found in {_short_path(agent.folder)}."))
            return
        console.print(
            f"Newest conversation in {escape(_short_path(agent.folder))}: "
            f"[cyan]{found.id}[/cyan] [dim](last written {found.modified}, {escape(found.path)})[/dim]"
        )
        if not yes and not typer.confirm(f"Save it as @{agent.handle}'s session?", default=True):
            raise typer.Exit(1)
        session = found.id
    if not session:
        console.print(agent.session or "[dim]no session saved[/dim]")
        return
    try:
        save_session(agent, session)
    except MachineError as e:
        _fail(e)
    console.print(f"saved [cyan]{session}[/cyan] as @{escape(agent.handle)}'s session")


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
