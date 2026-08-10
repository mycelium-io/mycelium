# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``await`` / ``respond`` — first-class participation for awake callers.

Being a participant in a room — receiving coordination and replying — is two
plain, **stateless** HTTP calls. The backend holds the caller's membership
server-side (a presence lease) and uses the durable transcript as the delivery
queue, so the caller never holds a SLIM socket between turns:

    mycelium await   --room R --handle me --json   # long-poll: blocks until addressed
    # … the caller reasons …
    mycelium respond --room R --handle me "my position, moving toward 30% …"

``await`` long-polls until the next message addressed to the handle (a mediator
tick or an ``@``-mention) is served past a persistent per-handle cursor, so a tick
is never missed between one await and the next. ``respond`` posts the reply, which
the backend records as an L9 ``exchange`` the aligner scores as a position.

No SLIM connection, no background process, no compound shell — which is exactly
what a headless / allowlisted agent (a Claude Code session, a subagent) can safely
issue. The member-session core (:mod:`mycelium.slim.member`) still backs the
daemon's cold-spawn path; these commands are the server-held path for an already-
awake caller.
"""

from __future__ import annotations

import json as json_module

import httpx
import typer

from mycelium.commands.room import _resolve_room
from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref
from mycelium.error_handler import print_error


@doc_ref(
    usage="mycelium await --room <room> --handle <handle> [--timeout N] [--json]",
    desc="Long-poll a room as a server-held member until a message is addressed to the handle.",
    group="other",
)
def await_room(
    ctx: typer.Context,
    room: str | None = typer.Option(None, "--room", "-r", help="Room (default: active room)"),
    handle: str = typer.Option(..., "--handle", help="Handle to participate as"),
    timeout: int = typer.Option(
        0, "--timeout", "-t", help="Seconds to wait before giving up (0 = wait indefinitely)"
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit the message as JSON for agents"),
) -> None:
    """Block until a message addressed to the handle arrives, print it, and exit.

    A single stateless long-poll against the backend — the caller is a server-held
    room member for the purpose of the aligner's roster, without holding any
    connection. On timeout, exits non-zero with no message.

    Examples:
        mycelium await --room design --handle me
        mycelium await --room design --handle me --json --timeout 120
    """
    try:
        config = MyceliumConfig.load()
        room_name = _resolve_room(config, room)
        url = f"{config.server.api_url}/api/rooms/{room_name}/await"
        # The server blocks up to `timeout`; give the client a little more headroom
        # (or no cap when waiting indefinitely).
        client_timeout = float(timeout) + 15.0 if timeout > 0 else None
        resp = httpx.get(
            url, params={"handle": handle, "timeout": timeout}, timeout=client_timeout
        )
        resp.raise_for_status()
        data = resp.json()
        if "prompt" not in data:  # timed out — backend returned {"message": null}
            if json_output:
                typer.echo(json_module.dumps({"room": room_name, "handle": handle, "message": None}))
            else:
                typer.secho(f"  ⟫  no message for @{handle} within timeout", fg=typer.colors.YELLOW)
            raise typer.Exit(1)
        if json_output:
            typer.echo(json_module.dumps(data))
        else:
            typer.secho(f"  ⟫  {data.get('sender') or '?'} → @{handle}:", fg=typer.colors.CYAN)
            typer.echo(data.get("prompt") or "")
    except typer.Exit:
        raise
    except KeyboardInterrupt:
        typer.echo("\n  [Stopped]")
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from e


@doc_ref(
    usage='mycelium respond --room <room> --handle <handle> "<text>"',
    desc="Publish a reply as the handle; the backend records it as a position for the aligner.",
    group="other",
)
def respond(
    ctx: typer.Context,
    text: str = typer.Argument(..., help="The reply / position text to publish"),
    room: str | None = typer.Option(None, "--room", "-r", help="Room (default: active room)"),
    handle: str = typer.Option(..., "--handle", help="Handle to publish the reply as"),
    json_output: bool = typer.Option(False, "--json", help="Emit the result as JSON for agents"),
) -> None:
    """Publish the caller's reply; the backend threads it onto the last awaited turn.

    A position marker may be appended to the text (e.g.
    `[[mycelium: confidence=0.85 stance=accept]]`); the backend lifts it onto the L9
    payload so the aligner can score it, and strips it from the posted prose.

    Examples:
        mycelium respond --room design --handle me "I can move to 30% if the timeline slips."
    """
    try:
        config = MyceliumConfig.load()
        room_name = _resolve_room(config, room)
        url = f"{config.server.api_url}/api/rooms/{room_name}/reply"
        resp = httpx.post(url, json={"handle": handle, "text": text}, timeout=30.0)
        resp.raise_for_status()
        data = resp.json()
        if json_output:
            typer.echo(json_module.dumps(data))
        else:
            typer.secho(f"  ⟫  @{handle} replied in {room_name}", fg=typer.colors.GREEN)
    except KeyboardInterrupt:
        typer.echo("\n  [Stopped]")
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from e
