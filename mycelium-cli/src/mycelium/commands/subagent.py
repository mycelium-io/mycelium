# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Subagent commands: give a subagent a handle of its own, and end it.

A subagent runs inside its parent's process, so it posts as its parent unless
it has its own handle. ``mycelium subagent start <name>`` makes
``<parent>:<name>`` a member of the room, recorded with its parent, and prints
three lines for the parent to put at the top of the subagent's prompt. It ends
on ``mycelium subagent end``, when its step in the parent's work ends (for a
CLI whose session the runner reads), when its parent stops, or after a while.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import typer
from rich.console import Console

from mycelium.cli_options import acts_as, emits_json, in_room
from mycelium.client import hub_error_detail, typed_client
from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref

app = typer.Typer(
    help="Give a subagent a handle of its own, so it posts as itself, and end it.",
    no_args_is_help=True,
)
console = Console()


def _call(fn: Callable[..., Any], *, acting: str | None = None, **kwargs: Any) -> Any:
    """Call a typed-client endpoint as ``acting``; say the hub's reason and exit
    on a refusal."""
    with typed_client(handle=acting) as client:
        try:
            resp = fn(client=client, **kwargs)
        except httpx.HTTPError as exc:
            url = MyceliumConfig.load().server.api_url
            console.print(f"[red]Error:[/red] can't reach the hub at {url}: {exc}")
            raise typer.Exit(1) from exc
    if resp.status_code >= 400:
        detail = hub_error_detail(resp.content) or f"HTTP {resp.status_code}"
        console.print(f"[red]Error:[/red] {detail}")
        raise typer.Exit(1)
    return json.loads(resp.content) if resp.content else None


def brief(room: str, handle: str, parent: str) -> list[str]:
    """The three lines a parent puts at the top of its subagent's prompt."""
    return [
        f"You are @{handle}, a subagent of @{parent}, in the Mycelium room {room}.",
        f"Post as yourself: add --as {handle} to every mycelium command that posts or "
        "changes something; commands that only read don't take it.",
        f"When you're done: mycelium subagent end {handle} --room {room}",
    ]


def check_in(room: str, handle: str) -> str:
    """The optional fourth line: a subagent has no wake of its own, so what's
    said to it wakes its parent. A parent that wants it to hear for itself adds
    this, and the subagent reads what came for it between its own steps."""
    return (
        "Between your steps, check for messages to you: "
        f"mycelium await --as {handle} --room {room} --timeout 5"
    )


@doc_ref(
    usage="mycelium subagent start <name>",
    desc=(
        "Give a subagent its own handle, <code>&lt;you&gt;:&lt;name&gt;</code>, so what it "
        "posts is its own. Prints three lines to put at the top of its prompt, and an "
        "optional fourth that has it check for messages to it between its steps."
    ),
    group="subagent",
)
@app.command(name="start")
@in_room("room")
@acts_as("parent", fallback=None)
@emits_json("as_json")
def subagent_start(
    name: str = typer.Argument(..., help="Its own name, like review"),
    room: str | None = None,
    parent: str | None = None,
    as_json: bool = False,
) -> None:
    """Start a subagent of yours with a handle of its own."""
    from mycelium_backend_client.api.subagents import (
        start_subagent_api_rooms_room_name_subagents_post as start_api,
    )
    from mycelium_backend_client.models import SubagentCreate

    assert room is not None
    body = SubagentCreate(name=name, parent=(parent or "").lstrip("@") or None)
    data = _call(start_api.sync_detailed, acting=parent, room_name=room, body=body)
    lines = brief(room, data["handle"], data["parent"])
    optional = check_in(room, data["handle"])
    if as_json:
        typer.echo(json.dumps({**data, "brief": lines, "check_in": optional}, indent=2))
        return
    console.print(f"[green]Started[/green] @{data['handle']}. Put these at the top of its prompt:")
    console.print()
    # Plain, never wrapped: these are copied into a prompt as they are.
    for line in lines:
        typer.echo(f"  {line}")
    console.print()
    console.print(
        "Messages to it wake you. To have it check for them itself, add this too:",
        soft_wrap=True,
    )
    console.print()
    typer.echo(f"  {optional}")


@doc_ref(
    usage="mycelium subagent end <handle>",
    desc="End a subagent: it leaves the room's members, and its messages stay its own.",
    group="subagent",
)
@app.command(name="end")
@in_room("room")
@acts_as("actor", optional=True)
@emits_json("as_json")
def subagent_end(
    handle: str = typer.Argument(..., help="The subagent's handle, like builder:review"),
    room: str | None = None,
    actor: str | None = None,
    as_json: bool = False,
) -> None:
    """End a subagent: the subagent itself (its brief says to add ``--as`` to
    every command) or its parent."""
    from mycelium_backend_client.api.subagents import (
        end_subagent_api_rooms_room_name_subagents_handle_delete as end_api,
    )

    assert room is not None
    data = _call(end_api.sync_detailed, acting=actor, room_name=room, handle=handle.lstrip("@"))
    if as_json:
        typer.echo(json.dumps(data, indent=2))
        return
    console.print(f"[green]Ended[/green] @{data['handle']}.")
