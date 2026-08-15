# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium herdr`` — bind mycelium handles to persistent herdr agent panes.

herdr (https://herdr.dev) is an *optional* persistent-runtime layer: it keeps
coding-agent sessions alive and addressable across detach. mycelium coordinates
agents through rooms; herdr gives those agents a place to *live* so a
non-resident ``agent invoke`` has something to wake instead of queuing forever on
the durable cursor.

This group is the durable ``handle -> pane`` registry plus manual wake/inspect
commands. The registry is what turns herdr's ephemeral, exit-clearing agent names
into a stable mycelium binding. Auto-wake on ``agent invoke`` (opt-in via
``herdr.autowake``) reuses the same registry + bridge.

Everything is fail-soft: if herdr isn't installed or its server is down, these
commands say so and exit cleanly rather than erroring the way a hard dependency
would.
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from mycelium.commands.room import _resolve_room
from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref
from mycelium.error_handler import print_error
from mycelium.integrations.herdr import (
    HerdrBridge,
    HerdrError,
    HerdrPaneMapping,
    build_wake_prompt,
)

app = typer.Typer(
    help="Bind mycelium handles to persistent herdr agent panes (optional wake layer).",
    no_args_is_help=True,
)
console = Console()


def _bridge() -> HerdrBridge:
    return HerdrBridge()


@doc_ref(
    usage="mycelium herdr map <handle> <pane> [--room <room>] [--kind <kind>]",
    desc="Bind a mycelium handle to a herdr agent pane (e.g. w2:pV).",
    group="agent",
)
@app.command("map")
def herdr_map(
    ctx: typer.Context,
    handle: str = typer.Argument(..., help="Mycelium agent handle (without leading @)."),
    pane: str = typer.Argument(..., help="herdr pane id hosting the agent, e.g. w2:pV."),
    room: str | None = typer.Option(None, "--room", "-r", help="Room (defaults to active)."),
    kind: str | None = typer.Option(None, "--kind", help="herdr agent kind (claude, pi, …)."),
) -> None:
    """Record a durable ``handle -> pane`` binding used by wake.

    Validates the pane against herdr's live agent list when herdr is reachable
    (a warning, not a hard failure — you can map ahead of starting the agent).
    """
    try:
        config = MyceliumConfig.load()
        room_name = _resolve_room(config, room)
        bridge = _bridge()

        resolved_kind = kind
        if bridge.available():
            agent = bridge.get_agent(pane)
            if agent is None:
                console.print(
                    f"[yellow]Note:[/yellow] no live agent at pane [cyan]{pane}[/cyan] yet — "
                    "mapping saved; wake will re-check at call time."
                )
            else:
                resolved_kind = resolved_kind or agent.get("agent")
        else:
            console.print("[dim]herdr not reachable — saving mapping without validation.[/dim]")

        bridge.registry.set(
            HerdrPaneMapping(room=room_name, handle=handle, pane=pane, kind=resolved_kind)
        )
        console.print(
            f"[green]Mapped[/green] [cyan]@{handle.lstrip('@')}[/cyan] → "
            f"[cyan]{pane}[/cyan][dim] in {room_name}"
            + (f" ({resolved_kind})" if resolved_kind else "")
            + "[/dim]"
        )
    except typer.Exit:
        raise
    except Exception as e:
        print_error(e, verbose=bool(ctx.obj and ctx.obj.get("verbose")))
        raise typer.Exit(1) from None


@doc_ref(
    usage="mycelium herdr unmap <handle> [--room <room>]",
    desc="Remove a handle → pane binding.",
    group="agent",
)
@app.command("unmap")
def herdr_unmap(
    ctx: typer.Context,
    handle: str = typer.Argument(..., help="Mycelium agent handle."),
    room: str | None = typer.Option(None, "--room", "-r", help="Room (defaults to active)."),
) -> None:
    """Forget a ``handle -> pane`` binding."""
    try:
        config = MyceliumConfig.load()
        room_name = _resolve_room(config, room)
        removed = _bridge().registry.remove(room_name, handle)
        if removed:
            console.print(
                f"[green]Unmapped[/green] @{handle.lstrip('@')} [dim]in {room_name}[/dim]"
            )
        else:
            console.print(f"[yellow]No mapping[/yellow] for @{handle.lstrip('@')} in {room_name}")
            raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as e:
        print_error(e, verbose=bool(ctx.obj and ctx.obj.get("verbose")))
        raise typer.Exit(1) from None


@doc_ref(
    usage="mycelium herdr ls [--room <room>]",
    desc="List handle → pane bindings with live herdr liveness.",
    group="agent",
)
@app.command("ls")
def herdr_ls(
    ctx: typer.Context,
    room: str | None = typer.Option(None, "--room", "-r", help="Only this room."),
) -> None:
    """Show the registry joined against herdr's live agent state.

    The liveness column is what cold-spawn could never report: ``idle`` /
    ``working`` / ``blocked`` per mapped agent, or ``—`` when herdr is unreachable
    or the pane is empty (a stale mapping).
    """
    try:
        bridge = _bridge()
        mappings = bridge.registry.all()
        if room:
            config = MyceliumConfig.load()
            room_name = _resolve_room(config, room)
            mappings = [m for m in mappings if m.room == room_name]

        if not mappings:
            console.print(
                "[dim]No herdr mappings. Bind one with `mycelium herdr map <handle> <pane>`.[/dim]"
            )
            return

        live: dict[str, str] = {}
        if bridge.available():
            for a in bridge.list_agents():
                pane = a.get("pane_id")
                if pane:
                    live[pane] = str(a.get("agent_status") or "unknown")

        table = Table(title="herdr ↔ mycelium bindings", show_lines=False)
        table.add_column("room", style="dim")
        table.add_column("handle", style="cyan")
        table.add_column("pane", style="cyan")
        table.add_column("kind", style="dim")
        table.add_column("liveness")
        for m in mappings:
            status = live.get(m.pane, "—")
            colour = {
                "idle": "green",
                "done": "green",
                "working": "yellow",
                "blocked": "red",
            }.get(status, "dim")
            table.add_row(
                m.room, f"@{m.handle}", m.pane, m.kind or "—", f"[{colour}]{status}[/{colour}]"
            )
        console.print(table)
    except typer.Exit:
        raise
    except Exception as e:
        print_error(e, verbose=bool(ctx.obj and ctx.obj.get("verbose")))
        raise typer.Exit(1) from None


@doc_ref(
    usage="mycelium herdr status",
    desc="Show whether herdr is installed and reachable.",
    group="agent",
)
@app.command("status")
def herdr_status(ctx: typer.Context) -> None:
    """Report herdr availability — the precondition for the wake path."""
    try:
        bridge = _bridge()
        if not bridge.binary_present():
            console.print("[yellow]herdr not installed[/yellow] — the wake layer is unavailable.")
            console.print(
                "[dim]Install from https://herdr.dev; mycelium works fine without it.[/dim]"
            )
            raise typer.Exit(1)
        if not bridge.available():
            console.print("[yellow]herdr installed but server unreachable.[/yellow]")
            raise typer.Exit(1)
        agents = bridge.list_agents()
        console.print(
            f"[green]herdr reachable[/green] — {len(agents)} live agent(s), "
            f"{len(bridge.registry.all())} mycelium binding(s)."
        )
    except typer.Exit:
        raise
    except Exception as e:
        print_error(e, verbose=bool(ctx.obj and ctx.obj.get("verbose")))
        raise typer.Exit(1) from None


@doc_ref(
    usage="mycelium herdr wake <handle> [--room <room>] [--timeout-ms N]",
    desc="Wake a mapped agent to run one mycelium coordination turn.",
    group="agent",
)
@app.command("wake")
def herdr_wake(
    ctx: typer.Context,
    handle: str = typer.Argument(..., help="Mycelium agent handle to wake."),
    room: str | None = typer.Option(None, "--room", "-r", help="Room (defaults to active)."),
    timeout_ms: int = typer.Option(120000, "--timeout-ms", help="Wake wait budget (ms)."),
) -> None:
    """Prompt the mapped herdr pane to drain its pending mycelium turn.

    The agent wakes *in place* with full context and replies through the room.
    Fail-soft: an unreachable herdr, missing mapping, stale pane, or busy agent
    all report cleanly and exit non-zero (the message stays on the cursor).
    """
    try:
        config = MyceliumConfig.load()
        room_name = _resolve_room(config, room)
        bridge = _bridge()

        if not bridge.available():
            console.print(
                "[yellow]herdr not reachable[/yellow] — cannot wake; message stays on the cursor."
            )
            raise typer.Exit(1)

        mapping = bridge.registry.get(room_name, handle)
        if mapping is None:
            console.print(
                f"[yellow]No herdr pane mapped[/yellow] for @{handle.lstrip('@')} in {room_name}.\n"
                f"[dim]Bind one: mycelium herdr map {handle.lstrip('@')} <pane> --room {room_name}[/dim]"
            )
            raise typer.Exit(1)

        console.print(f"[dim]Waking @{mapping.handle} at {mapping.pane}…[/dim]")
        result = bridge.wake(
            mapping, build_wake_prompt(room_name, mapping.handle), timeout_ms=timeout_ms
        )
        if result.ok:
            console.print(f"[green]Woke[/green] @{mapping.handle} [dim]— {result.detail}[/dim]")
        else:
            console.print(f"[yellow]Not woken[/yellow] [dim]— {result.detail}[/dim]")
            raise typer.Exit(1)
    except typer.Exit:
        raise
    except HerdrError as e:
        console.print(f"[red]herdr error:[/red] {e}")
        raise typer.Exit(1) from None
    except Exception as e:
        print_error(e, verbose=bool(ctx.obj and ctx.obj.get("verbose")))
        raise typer.Exit(1) from None
