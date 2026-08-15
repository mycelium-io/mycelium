# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``join`` — enroll this machine as a member of a room hosted on another.

``mycelium connect`` points this machine at a hub's SLIM node; ``mycelium join``
is what actually puts it on a room's channel and keeps it there. The process is a
resident foreground member: it holds membership and writes every ``knowledge``
envelope the hub broadcasts into this machine's own store, so a ``memory set`` on
the hub lands here.

It is a **member**, never a moderator. The hub that provisioned the room is its
sole moderator; a second moderator would be a second MLS group, which is why two
backends on one node never converged. See :mod:`mycelium.spoke`.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import typer

from mycelium.commands.room import _resolve_room
from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref
from mycelium.error_handler import print_error
from mycelium.identity import get_current_handle
from mycelium.spoke import SpokeCounters, run_spoke

if TYPE_CHECKING:
    from mycelium.filesystem import KnowledgeApplyResult


@doc_ref(
    usage="mycelium join [--room <room>] [--handle <handle>]",
    desc="Join a hub-hosted room as a member and apply its memory writes to this machine.",
    group="other",
)
def join(
    ctx: typer.Context,
    room: str | None = typer.Option(None, "--room", "-r", help="Room (default: active room)"),
    handle: str | None = typer.Option(
        None, "--handle", help="Handle to join as (default: your configured identity)"
    ),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Only report conflicts and errors"),
) -> None:
    """Stay resident on a room's channel, applying inbound memory writes locally.

    Runs until Ctrl-C. Memories that arrive are written to ~/.mycelium/rooms/<room>/
    but are not indexed for search until you run `mycelium sync` — the CLI has no
    local embedding index.
    """
    try:
        config = MyceliumConfig.load()
        room_name = _resolve_room(config, room)
        joining_as = handle or get_current_handle(config)
        if not joining_as:
            typer.secho(
                "  ⟫  no identity configured — pass --handle or run `mycelium iam <name>`",
                fg=typer.colors.RED,
            )
            raise typer.Exit(2)

        counters = SpokeCounters()

        def _on_joined() -> None:
            if not quiet:
                typer.secho(
                    f"  ⟫  @{joining_as} joined {room_name} as a member "
                    f"via {config.slim.node_endpoint} — applying memory writes "
                    "(Ctrl-C to stop)",
                    fg=typer.colors.CYAN,
                )

        def _on_apply(result: KnowledgeApplyResult) -> None:
            if result.conflict:
                current = result.current or {}
                typer.secho(
                    f"  ⟫  conflict on {result.key}: kept local v{current.get('version')} "
                    f"by {current.get('updated_by')!r}, rejected incoming v{result.version}",
                    fg=typer.colors.YELLOW,
                )
            elif result.applied and not quiet:
                typer.secho(f"  ⟫  applied {result.key} v{result.version}", fg=typer.colors.GREEN)

        try:
            asyncio.run(
                run_spoke(
                    api_url=config.server.api_url,
                    node_endpoint=config.slim.node_endpoint,
                    room=room_name,
                    handle=joining_as,
                    counters=counters,
                    on_joined=_on_joined,
                    on_apply=_on_apply,
                )
            )
        except KeyboardInterrupt:
            pass

        typer.echo(
            f"\n  [Left {room_name}] applied={counters.applied} "
            f"conflicts={counters.conflicts} ignored={counters.ignored}"
        )
    except typer.Exit:
        raise
    except KeyboardInterrupt:
        typer.echo("\n  [Stopped]")
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from e
