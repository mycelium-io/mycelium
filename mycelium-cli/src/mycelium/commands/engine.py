# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium engine``: manage first-party Cognition Engines as room citizens.

An engine is *not* an external-runtime agent (claude_code/cursor/…). It's a
first-party mycelium Cognition Engine (our NEGMAS loop, our brain) registered
as a real room participant so it's visible, routable, and invokable like anyone
else. ``--kind`` selects the CE (``aligner`` today; more later).

This is thin sugar over the shared agent-manifest plumbing: an engine writes the
same ``agents/<handle>`` manifest as any agent, with ``adapter="engine"`` and a
``kind``. That keeps engines first-class in room membership + dispatch while
giving them their own, correctly-named front door.
"""

from __future__ import annotations

import json as json_module

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from mycelium.commands.agent import (
    _load_manifest_remote,
    _persist_and_describe,
    _resolve_room,
    _room_manifests,
    _typed_client,
)
from mycelium.config import MyceliumConfig
from mycelium.error_handler import print_error
from mycelium.integrations import AddOptions, get_adapter
from mycelium.protocol import ENGINE_KINDS

app = typer.Typer(help="Manage first-party Cognition Engines (aligner, …) as room citizens.")
console = Console()


@app.command("create")
def engine_create(
    ctx: typer.Context,
    handle: str = typer.Argument(..., help="Engine handle (lowercase slug, e.g. 'mediator-1')."),
    kind: str = typer.Option(
        "aligner",
        "--kind",
        help=f"Which cognition engine to run. Known: {', '.join(sorted(ENGINE_KINDS))}.",
    ),
    room: str | None = typer.Option(
        None, "--room", "-r", help="Room to register in (defaults to active room)."
    ),
    description: str = typer.Option(
        "", "--description", "-d", help="One-paragraph statement of what this engine does."
    ),
    allow_from: str | None = typer.Option(
        None,
        "--allow-from",
        help="Comma-separated sender handles allowed to summon (e.g. '@avery').",
    ),
    handle_flag: str = typer.Option(
        "cli-user", "--as", "-H", help="Your own handle (recorded as created_by)."
    ),
) -> None:
    """Create a first-party cognition engine in a room.

    Example:
        mycelium engine create mediator-1 --kind aligner --room portfolio
    """
    try:
        config = MyceliumConfig.load()
        if kind not in ENGINE_KINDS:
            known = ", ".join(sorted(ENGINE_KINDS))
            typer.secho(f"Unknown engine kind '{kind}'. Known: {known}.", fg=typer.colors.RED)
            raise typer.Exit(1)

        room_name = _resolve_room(config, room)
        allow_list: list[str] = [a.strip() for a in (allow_from or "").split(",") if a.strip()]

        impl = get_adapter("engine", engine_kind=kind)
        try:
            manifest = impl.build_manifest(
                handle=handle,
                opts=AddOptions(room=room_name),
                description=description,
                allow_from=allow_list,
            )
        except ValidationError as exc:
            typer.secho(f"Invalid engine manifest: {exc}", fg=typer.colors.RED)
            raise typer.Exit(1) from exc

        _persist_and_describe(
            impl=impl,
            manifest=manifest,
            config=config,
            room_name=room_name,
            handle_flag=handle_flag,
            action="created",
        )
    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None


@app.command("ls")
def engine_ls(
    ctx: typer.Context,
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
) -> None:
    """List the cognition engines registered in a room."""
    try:
        config = MyceliumConfig.load()
        room_name = _resolve_room(config, room)

        engines = [m for m in _room_manifests(room_name) if m.adapter == "engine"]

        if ctx.obj and ctx.obj.get("json"):
            console.print(
                json_module.dumps([m.model_dump() for m in engines], indent=2, default=str)
            )
            return

        if not engines:
            console.print(f"[dim]No engines registered in {room_name}.[/dim]")
            console.print(
                f"  Create one with: mycelium engine create <handle> --kind aligner "
                f"--room {room_name}"
            )
            return

        table = Table(title=f"{room_name} engines", show_lines=False)
        table.add_column("handle", style="cyan")
        table.add_column("kind")
        table.add_column("description")
        for m in engines:
            table.add_row(f"@{m.handle}", m.kind or "?", m.description or "")
        console.print(table)
    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None


@app.command("invoke")
def engine_invoke(
    ctx: typer.Context,
    handle: str = typer.Argument(..., help="Engine handle (without leading @)."),
    message: str = typer.Argument(
        "please mediate us to an agreement.",
        help="Summon message (defaults to a generic mediate request).",
    ),
    room: str | None = typer.Option(
        None, "--room", "-r", help="Room to summon in (defaults to active room)."
    ),
    handle_flag: str | None = typer.Option(
        None, "--as", "-H", help="Your sender handle (defaults to identity config)."
    ),
) -> None:
    """Summon a registered cognition engine by posting an ``@handle`` message.

    Fills gap #4: the built-in aligner previously had no CLI surface (you had to
    hit the REST API directly). The backend recognises a registered ``engine``
    and runs it as that handle.

    Example:
        mycelium engine invoke mediator-1 "converge on tech allocation and the cap"
    """
    try:
        config = MyceliumConfig.load()
        room_name = _resolve_room(config, room)

        from mycelium_backend_client.api.messages import (
            send_message_api_rooms_room_name_messages_post as send_api,
        )
        from mycelium_backend_client.models import MessageCreate, MessageCreateMessageType

        with _typed_client(config) as client:
            manifest = _load_manifest_remote(client, room_name, handle)
            if manifest is None:
                console.print(
                    f"[red]Not found:[/red] no engine named '{handle}' in room '{room_name}'.\n"
                    f"  Create one with: mycelium engine create {handle} --kind aligner "
                    f"--room {room_name}"
                )
                raise typer.Exit(1)
            if manifest.adapter != "engine":
                console.print(
                    f"[red]'{handle}' is a {manifest.adapter} agent, not an engine.[/red]\n"
                    f'  Use: mycelium agent invoke {handle} "..."'
                )
                raise typer.Exit(1)

            sender_handle = handle_flag or config.get_current_identity()
            body = MessageCreate(
                sender_handle=sender_handle,
                message_type=MessageCreateMessageType.BROADCAST,
                content=f"@{manifest.handle} {message}",
            )
            send_api.sync(room_name=room_name, client=client, body=body)

        console.print(
            f"[green]Summoned[/green] [dim]({sender_handle} → [/dim]"
            f"[cyan]@{manifest.handle}[/cyan][dim] in {room_name})[/dim]"
        )
        console.print(
            f"\n[dim]The backend runs the {manifest.kind} engine and replies in {room_name}.[/dim]"
        )
    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None
