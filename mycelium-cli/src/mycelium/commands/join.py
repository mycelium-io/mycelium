# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium join <code>`` and ``mycelium leave``: this folder's membership of a room.

Whoever started an agent asks the hub for a join code (``POST
/api/rooms/{room}/joins``) and hands it to the agent in its first message. The
agent runs ``mycelium join <code>`` in the folder it works in, and from then on
every ``mycelium`` command run there acts as that member of that room, against
that hub, with the token the hub gave it. Nothing about the machine has to be
set up first, which is the point: an agent whose host passes it no environment
has no other way to be told who it is. See ``mycelium.caller``
for where a membership sits among the other ways a command learns who it is.
"""

from __future__ import annotations

import json as json_module
from datetime import datetime
from pathlib import Path

import httpx
import typer
from rich.console import Console

from mycelium import caller
from mycelium.agent_credentials import redeem_join_code
from mycelium.client import hub_error_detail
from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref
from mycelium_backend_client.models import MembershipRead

console = Console()


@doc_ref(
    usage="mycelium join <code> [--hub <url>] [--replace]",
    desc="Join a room as the member a join code names; commands in this folder then act as it.",
    group="agent",
)
def join(
    ctx: typer.Context,
    code: str = typer.Argument(..., help="The join code, e.g. abcd-efgh-jkmn."),
    hub: str | None = typer.Option(
        None, "--hub", help="The hub that issued the code (default: the configured hub)."
    ),
    replace: bool = typer.Option(
        False, "--replace", help="Replace this folder's membership if it has another one."
    ),
) -> None:
    """Redeem a join code and save the membership in this folder.

    The code is single-use and short-lived. The saved membership (hub, room,
    handle and, on a hub with auth on, a token) is readable only by you and
    ignored by git. Run `mycelium whoami --sources` to see it take effect.
    """
    json_output = bool(ctx.obj and ctx.obj.get("json"))
    folder = Path.cwd()
    existing = caller.find_membership(folder)
    here = existing is not None and existing.folder == folder.resolve()
    if here and existing is not None and not replace:
        # Checked before the code is spent: which member the code names isn't
        # known until it's redeemed, and a redeemed code can't be used again.
        console.print(
            f"[yellow]This folder already belongs to @{existing.handle} in "
            f"{existing.room}.[/yellow] Each member needs its own folder. Join from "
            "another one, or pass --replace (also how a member renews its token)."
        )
        raise typer.Exit(1)
    hub_url = (hub or MyceliumConfig.load().server.api_url).rstrip("/")

    try:
        resp = redeem_join_code(hub_url, code)
    except httpx.HTTPError as e:
        console.print(f"[red]Couldn't reach the hub at {hub_url}:[/red] {e}")
        raise typer.Exit(1) from e
    joined = resp.parsed
    if not isinstance(joined, MembershipRead):
        detail = hub_error_detail(resp.content) or f"HTTP {resp.status_code}"
        console.print(f"[red]The hub didn't accept that code:[/red] {detail}")
        raise typer.Exit(1)
    expires = joined.token_expires_at
    member = caller.save_membership(
        folder,
        hub=hub_url,
        room=joined.room,
        handle=joined.handle,
        token=joined.token or None,
        token_expires_at=expires.isoformat() if isinstance(expires, datetime) else None,
    )
    if json_output:
        typer.echo(
            json_module.dumps(
                {
                    "room": member.room,
                    "handle": member.handle,
                    "hub": member.hub,
                    "folder": str(member.folder),
                    "token": bool(member.token),
                }
            )
        )
        return
    console.print(
        f"[green]You're @{member.handle}[/green] in [cyan]{member.room}[/cyan] on {member.hub}."
    )
    console.print(
        f"[dim]Saved in {member.path}. Every mycelium command run in {member.folder} "
        "or below now acts as this member.[/dim]"
    )


@doc_ref(
    usage="mycelium leave",
    desc="Forget this folder's membership, so commands here act as this machine again.",
    group="agent",
)
def leave(ctx: typer.Context) -> None:
    """Remove the membership `mycelium join` saved in this folder."""
    member = caller.find_membership()
    if member is None:
        console.print("This folder hasn't joined a room.")
        return
    caller.remove_membership(member.folder)
    console.print(
        f"Left: {member.folder} is no longer @{member.handle} in {member.room}. "
        "The member itself is still in the room."
    )
