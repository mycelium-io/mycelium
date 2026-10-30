# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
``mycelium waiting``: what is waiting on you in a room.

The same hub read the app's "Waiting on you" draws
(``GET /rooms/{room}/waiting?for=<handle>``): a message that asks you where you
haven't posted since, a flow step whose turn is yours, and an open task you
hold that waits on nothing. For an agent it's what's waiting on it.
"""

from __future__ import annotations

import json
import sys

import httpx
import typer
from rich.console import Console
from rich.text import Text

from mycelium.board.epics import waiting_line
from mycelium.cli_options import acts_as, emits_json, in_room
from mycelium.client import typed_client
from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref

console = Console()


@doc_ref(
    usage="mycelium waiting [--as <handle>]",
    desc="What is waiting on you: asks you haven't answered, your turn in a flow, and your open tasks.",
    group="board",
)
@in_room()
@acts_as()
@emits_json()
def waiting(ctx: typer.Context, room: str, handle: str) -> None:
    """Show what is waiting on you in the room."""
    from mycelium_backend_client.api.board import read_waiting_api_rooms_room_name_waiting_get
    from mycelium_backend_client.models import WaitingRead

    cfg = MyceliumConfig.load()
    try:
        with typed_client(cfg, timeout=30, raise_on_unexpected_status=False) as client:
            resp = read_waiting_api_rooms_room_name_waiting_get.sync_detailed(
                room, client=client, for_=handle
            )
    except httpx.HTTPError as e:
        console.print(f"[red]✗[/red] hub unreachable: {e}")
        raise typer.Exit(1) from e
    read = resp.parsed
    if not isinstance(read, WaitingRead):
        said = resp.content.decode(errors="replace")
        console.print(f"[red]✗[/red] HTTP {resp.status_code}: {said[:200]}")
        raise typer.Exit(1)
    if ctx.obj and ctx.obj.get("json"):
        sys.stdout.write(json.dumps(read.to_dict(), indent=2) + "\n")
        return
    if not read.items:
        console.print(f"Nothing is waiting on @{read.handle} in {room}.")
        return
    heading = Text()
    heading.append(f"Waiting on @{read.handle} in {room}", style="bold")
    heading.append(f"  {len(read.items)}", style="dim")
    console.print(heading)
    for item in read.items:
        console.print(waiting_line(item))
        # A question or a turn wants a reply; a task that's yours wants opening;
        # an approval is answered on its card.
        if item.kind == "approve":
            how = "Approve or decline it on its card in the app."
        elif item.kind == "task" and item.key:
            how = f"Open: mycelium board messages {item.key} --room {room}"
        else:
            task = f" --task {item.key}" if item.key else ""
            how = f'Reply: mycelium respond --room {room}{task} --body "…"'
        console.print(Text(f"    {how}", style="dim"))
