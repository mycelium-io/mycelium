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
from mycelium.client import hub_client
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
    cfg = MyceliumConfig.load()
    try:
        with hub_client(cfg, timeout=30) as client:
            resp = client.get(f"/api/rooms/{room}/waiting", params={"for": handle})
    except httpx.HTTPError as e:
        console.print(f"[red]✗[/red] hub unreachable: {e}")
        raise typer.Exit(1) from e
    if resp.status_code >= 400:
        console.print(f"[red]✗[/red] HTTP {resp.status_code}: {resp.text[:200]}")
        raise typer.Exit(1)
    read = resp.json()
    if ctx.obj and ctx.obj.get("json"):
        sys.stdout.write(json.dumps(read, indent=2) + "\n")
        return
    items = read.get("items") or []
    if not items:
        console.print(f"Nothing is waiting on @{read.get('handle', handle)} in {room}.")
        return
    count = len(items)
    heading = Text()
    heading.append(f"Waiting on @{read.get('handle', handle)} in {room}", style="bold")
    heading.append(f"  {count}", style="dim")
    console.print(heading)
    for item in items:
        console.print(waiting_line(item))
        task = f" --task {item['key']}" if item.get("key") else ""
        console.print(
            Text(f'    Answer: mycelium respond --room {room}{task} --body "…"', style="dim")
        )
