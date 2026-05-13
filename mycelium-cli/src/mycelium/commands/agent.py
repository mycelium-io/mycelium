# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
Agent commands — name an addressable, durable agent inside a room.

An agent is just two memory entries plus an adapter route:

    <room>/agents/<handle>            ← manifest (this command writes it)
    <room>/agents/<handle>/notes      ← persistent brain, agent-curated
    <room>/agents/<handle>/log/<ts>   ← per-invocation transcript (daemon writes)

The corresponding daemon (``mycelium-cc-daemon``, installed via
``mycelium adapter add claude-code --step=daemon``) watches each room's SSE
stream, dispatches ``@handle`` mentions to the right runtime, and posts the
reply back to the room as ``@handle``.

These commands are typing comfort on top of ``memory`` and ``room send``:
``agent add`` is ``memory set agents/<handle>`` with validation, ``agent
invoke`` is ``room send "@handle ..."``. The primitives don't change.
"""

from __future__ import annotations

import json as json_module

import typer
import yaml
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref
from mycelium.error_handler import print_error
from mycelium.filesystem import get_room_dir, list_memories, read_memory
from mycelium.sstp import AGENT_ADAPTERS, AgentManifest

app = typer.Typer(
    help=(
        "Name an addressable agent inside a room. "
        "An agent is a memory entry plus an adapter route — `agent add` writes the "
        "manifest, `agent invoke` sends an @handle message into its home room."
    ),
    no_args_is_help=True,
)
console = Console()


def _typed_client(config: MyceliumConfig):
    from mycelium_backend_client import Client

    return Client(base_url=config.server.api_url, raise_on_unexpected_status=True)


def _resolve_room(config: MyceliumConfig, room: str | None) -> str:
    if room:
        return room
    active = getattr(config.rooms, "active", None)
    if active:
        return active
    typer.secho(
        "No room specified and no active room set. "
        "Use --room or `mycelium config set rooms.active <name>`.",
        fg=typer.colors.RED,
    )
    raise typer.Exit(1)


def _load_manifest(room_name: str, handle: str) -> AgentManifest | None:
    """Read the manifest off the local filesystem and rehydrate the model."""
    room_dir = get_room_dir(room_name)
    result = read_memory(room_dir, f"agents/{handle}")
    if result is None:
        return None
    _, content = result
    try:
        data = yaml.safe_load(content) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    data.setdefault("handle", handle)
    try:
        return AgentManifest(**data)
    except ValidationError:
        return None


def _write_manifest(
    config: MyceliumConfig, room_name: str, manifest: AgentManifest, created_by: str
) -> None:
    """Upsert the manifest into the backend AND mirror it to the local filesystem.

    The daemon resolves manifests by reading the local filesystem (single-machine
    v0), so the backend write alone isn't enough — we mirror via the same
    ``filesystem.write_memory`` helper that the rest of the CLI uses for local
    copies of API-written memories.
    """
    from mycelium.filesystem import write_memory
    from mycelium_backend_client.api.memory import (
        create_memories_api_rooms_room_name_memory_post as create_api,
    )
    from mycelium_backend_client.models import MemoryBatchCreate, MemoryCreate

    body = manifest.model_dump(exclude={"handle"})
    yaml_body = yaml.safe_dump(body, sort_keys=False, default_flow_style=False).strip()
    item = MemoryCreate(
        key=manifest.memory_key,
        value=yaml_body,
        created_by=created_by,
        embed=True,
        content_text=f"agent {manifest.handle}: {manifest.description[:200]}",
        tags=["agent-manifest"],
    )
    batch = MemoryBatchCreate(items=[item])
    with _typed_client(config) as client:
        result = create_api.sync(room_name=room_name, client=client, body=batch)

    # Mirror locally so `agent ls/show/invoke` + the daemon's filesystem lookup
    # find the manifest without a round-trip.
    room_dir = get_room_dir(room_name)
    version = 1
    if result and isinstance(result, list) and result:
        version = getattr(result[0], "version", 1) or 1
    write_memory(
        room_dir,
        manifest.memory_key,
        yaml_body,
        created_by=created_by,
        version=version,
        tags=["agent-manifest"],
    )


# ── add ──────────────────────────────────────────────────────────────────────


@doc_ref(
    usage="mycelium agent add <handle> --adapter <name> --cwd <path> [--room <room>]",
    desc=(
        "Register an addressable agent in a room. Writes a manifest under "
        "<code>agents/&lt;handle&gt;</code>. The daemon dispatches "
        "<code>@handle</code> mentions to the configured adapter."
    ),
    group="agent",
)
@app.command("add")
def agent_add(
    ctx: typer.Context,
    handle: str = typer.Argument(
        ..., help="Agent handle (lowercase slug, e.g. 'release-agent'). Used as @-mention target."
    ),
    adapter: str = typer.Option(
        "claude_code",
        "--adapter",
        help=f"Adapter that hosts this agent. Known: {', '.join(sorted(AGENT_ADAPTERS))}.",
    ),
    cwd: str = typer.Option(
        ..., "--cwd", help="Working directory the adapter spawns the agent in."
    ),
    room: str | None = typer.Option(
        None, "--room", "-r", help="Room to register in (defaults to active room)."
    ),
    description: str = typer.Option(
        "", "--description", "-d", help="One-paragraph statement of what this agent does."
    ),
    budget: float = typer.Option(
        5.0, "--budget", help="Monthly USD spend cap enforced by the daemon."
    ),
    allow_from: str | None = typer.Option(
        None,
        "--allow-from",
        help="Comma-separated sender handles allowed to invoke (e.g. '@julia,@docs-agent').",
    ),
    handle_flag: str = typer.Option(
        "cli-user", "--as", "-H", help="Your own handle (recorded as created_by)."
    ),
) -> None:
    """Register an addressable agent in a room.

    Examples:
        mycelium agent add release-agent --cwd ~/repos/mycelium
        mycelium agent add docs-agent --cwd ~/repos/docs \\
            --description "Edits the docs site" --allow-from "@julia"
    """
    try:
        if adapter not in AGENT_ADAPTERS:
            known = ", ".join(sorted(AGENT_ADAPTERS))
            typer.secho(f"Unknown adapter '{adapter}'. Known: {known}.", fg=typer.colors.RED)
            raise typer.Exit(1)

        allow_list: list[str] = []
        if allow_from:
            allow_list = [a.strip() for a in allow_from.split(",") if a.strip()]

        try:
            manifest = AgentManifest(
                handle=handle,
                adapter=adapter,  # type: ignore[arg-type]
                cwd=cwd,
                description=description,
                budget_usd_per_month=budget,
                allow_from=allow_list,
            )
        except ValidationError as exc:
            typer.secho(f"Invalid agent manifest: {exc}", fg=typer.colors.RED)
            raise typer.Exit(1) from exc

        config = MyceliumConfig.load()
        room_name = _resolve_room(config, room)

        _write_manifest(config, room_name, manifest, created_by=handle_flag)

        console.print(
            f"[green]Agent registered:[/green] [cyan]@{manifest.handle}[/cyan] "
            f"in room [bold]{room_name}[/bold]"
        )
        console.print(f"  adapter: {manifest.adapter}")
        console.print(f"  cwd:     {manifest.cwd}")
        if manifest.allow_from:
            console.print(f"  allow:   {', '.join(manifest.allow_from)}")
        console.print(
            "\n[dim]Seed the agent's brain (optional):[/dim]\n"
            f'  mycelium memory set agents/{manifest.handle}/notes "..." --room {room_name}\n'
            "[dim]Then invoke it:[/dim]\n"
            f'  mycelium agent invoke {manifest.handle} "..."'
        )
    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None


# ── ls ───────────────────────────────────────────────────────────────────────


@doc_ref(
    usage="mycelium agent ls [--room <room>]",
    desc="List all registered agents in a room.",
    group="agent",
)
@app.command("ls")
def agent_ls(
    ctx: typer.Context,
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
) -> None:
    """List registered agents in a room."""
    try:
        config = MyceliumConfig.load()
        room_name = _resolve_room(config, room)
        room_dir = get_room_dir(room_name)

        entries = list_memories(room_dir, prefix="agents/", limit=200)
        # Drop notes + log children — manifests only live at agents/<handle>
        # without further path segments.
        manifests: list[AgentManifest] = []
        for key, _meta, _content in entries:
            handle = key.removeprefix("agents/")
            if "/" in handle:
                continue
            m = _load_manifest(room_name, handle)
            if m is not None:
                manifests.append(m)

        json_output = ctx.obj.get("json", False) if ctx.obj else False
        if json_output:
            typer.echo(
                json_module.dumps([m.model_dump() for m in manifests], indent=2, default=str)
            )
            return

        if not manifests:
            console.print(f"[dim]No agents registered in {room_name}.[/dim]")
            console.print(
                f"  Register one with: mycelium agent add <handle> --cwd <path> --room {room_name}"
            )
            return

        table = Table(title=f"{room_name} — agents", show_lines=False)
        table.add_column("Handle", style="cyan", no_wrap=True)
        table.add_column("Adapter", style="magenta")
        table.add_column("Cwd")
        table.add_column("Budget", justify="right")
        table.add_column("Description", overflow="fold")
        for m in manifests:
            table.add_row(
                f"@{m.handle}",
                m.adapter,
                m.cwd,
                f"${m.budget_usd_per_month:.2f}/mo",
                (m.description or "")[:80],
            )
        console.print(table)
    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None


# ── show ─────────────────────────────────────────────────────────────────────


@doc_ref(
    usage="mycelium agent show <handle> [--room <room>]",
    desc="Show an agent's manifest, notes, and most recent invocation log.",
    group="agent",
)
@app.command("show")
def agent_show(
    ctx: typer.Context,
    handle: str = typer.Argument(..., help="Agent handle"),
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
) -> None:
    """Inspect a registered agent — manifest + notes + last invocation."""
    try:
        config = MyceliumConfig.load()
        room_name = _resolve_room(config, room)
        room_dir = get_room_dir(room_name)

        manifest = _load_manifest(room_name, handle)
        if manifest is None:
            console.print(f"[red]Not found:[/red] no agent named '{handle}' in room '{room_name}'.")
            raise typer.Exit(1)

        console.print(f"[bold cyan]@{manifest.handle}[/bold cyan]  [dim]({manifest.adapter})[/dim]")
        console.print(f"  cwd: {manifest.cwd}")
        console.print(f"  budget: ${manifest.budget_usd_per_month:.2f}/mo")
        if manifest.allow_from:
            console.print(f"  allow_from: {', '.join(manifest.allow_from)}")
        if manifest.description:
            console.print(f"\n[bold]description[/bold]\n{manifest.description}")

        notes_result = read_memory(room_dir, manifest.notes_key)
        if notes_result is not None:
            _, notes_content = notes_result
            console.print("\n[bold]notes[/bold]")
            console.print(notes_content)
        else:
            console.print(
                f"\n[dim]No notes yet. Seed with: "
                f'mycelium memory set {manifest.notes_key} "..." --room {room_name}[/dim]'
            )

        log_entries = list_memories(room_dir, prefix=f"agents/{handle}/log/", limit=1)
        if log_entries:
            log_key, log_meta, log_content = log_entries[0]
            ts = str(log_meta.get("updated_at", ""))[:19].replace("T", " ")
            console.print(f"\n[bold]last invocation[/bold]  [dim]{ts}[/dim]")
            preview = log_content[:400] if log_content else ""
            console.print(preview + ("..." if log_content and len(log_content) > 400 else ""))
    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None


# ── invoke ───────────────────────────────────────────────────────────────────


@doc_ref(
    usage='mycelium agent invoke <handle> "<prompt>" [--room <room>]',
    desc=(
        "Send an addressed message to a registered agent. "
        'Desugars to <code>mycelium room send "@handle &lt;prompt&gt;"</code>.'
    ),
    group="agent",
)
@app.command("invoke")
def agent_invoke(
    ctx: typer.Context,
    handle: str = typer.Argument(..., help="Agent handle (without leading @)"),
    prompt: str = typer.Argument(..., help="Message body to send the agent."),
    room: str | None = typer.Option(
        None, "--room", "-r", help="Room to send into (defaults to active room)."
    ),
    handle_flag: str | None = typer.Option(
        None, "--as", "-H", help="Your sender handle (defaults to identity config)."
    ),
) -> None:
    """Send an @-addressed message to a registered agent.

    Typing comfort over `mycelium room send "@handle ..."`. The daemon picks
    up the message on its SSE subscription and dispatches it to the right
    adapter.

    Examples:
        mycelium agent invoke release-agent "pull latest, new release"
        mycelium agent invoke docs-agent "regen the cli reference"
    """
    try:
        config = MyceliumConfig.load()
        room_name = _resolve_room(config, room)

        manifest = _load_manifest(room_name, handle)
        if manifest is None:
            console.print(
                f"[red]Not found:[/red] no agent named '{handle}' in room '{room_name}'.\n"
                f"  Register one with: mycelium agent add {handle} --cwd <path> --room {room_name}"
            )
            raise typer.Exit(1)

        sender_handle = handle_flag or config.get_current_identity()
        content = f"@{manifest.handle} {prompt}"

        from mycelium_backend_client.api.messages import (
            send_message_api_rooms_room_name_messages_post as send_api,
        )
        from mycelium_backend_client.models import MessageCreate

        with _typed_client(config) as client:
            body = MessageCreate(
                sender_handle=sender_handle,
                message_type="broadcast",
                content=content,
            )
            send_api.sync(room_name=room_name, client=client, body=body)

        console.print(
            f"[green]Sent[/green] [dim]({sender_handle} → [/dim]"
            f"[cyan]@{manifest.handle}[/cyan][dim] in {room_name})[/dim]"
        )
        console.print(f"  {prompt[:200]}")
        console.print(
            f"\n[dim]The daemon will dispatch via {manifest.adapter} and reply in "
            f"{room_name} as @{manifest.handle}.[/dim]"
        )
    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None


# ── rm ───────────────────────────────────────────────────────────────────────


@doc_ref(
    usage="mycelium agent rm <handle> [--room <room>] [--force]",
    desc="Unregister an agent. Removes the manifest only — notes and logs are kept.",
    group="agent",
)
@app.command("rm")
def agent_rm(
    ctx: typer.Context,
    handle: str = typer.Argument(..., help="Agent handle"),
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
) -> None:
    """Unregister an agent (deletes the manifest, keeps notes/logs).

    Notes and logs are preserved so the agent can be re-registered later
    without losing accumulated knowledge. To wipe everything, delete the
    `agents/<handle>` namespace manually with `mycelium memory rm`.
    """
    try:
        config = MyceliumConfig.load()
        room_name = _resolve_room(config, room)

        manifest = _load_manifest(room_name, handle)
        if manifest is None:
            console.print(f"[red]Not found:[/red] no agent named '{handle}' in room '{room_name}'.")
            raise typer.Exit(1)

        if not force:
            confirm = typer.confirm(
                f"Unregister @{handle} from room '{room_name}'? (notes + logs are preserved)"
            )
            if not confirm:
                raise typer.Exit(0)

        from mycelium_backend_client.api.memory import (
            delete_memory_api_rooms_room_name_memory_key_delete as delete_api,
        )

        with _typed_client(config) as client:
            delete_api.sync_detailed(room_name=room_name, key=manifest.memory_key, client=client)
        console.print(f"[green]Unregistered:[/green] @{handle} from {room_name}")
    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None


# Re-export for completeness — daemon and doctor reuse these.
__all__ = [
    "_load_manifest",
    "app",
]
