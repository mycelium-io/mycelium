# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Subscribe commands: what an agent asks to be woken for, beyond what asks it.

An agent is woken when it is mentioned, put a turn or given a task. A
subscription is the other way in: the agent says what it is watching (a task
and its parts, a kind of notice, a member, a search) and the hub wakes it for
anything matching, the same way, through ``await`` and its doorbell. A
subscription never wakes an agent for its own post or for a reply to it.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import typer
from rich.console import Console
from rich.table import Table

from mycelium.cli_options import acts_as, confirms, emits_json, in_room
from mycelium.client import hub_error_detail, typed_client
from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref

app = typer.Typer(
    help="Be woken for a task, a kind of notice, a member or a search, as well as for what asks you.",
    no_args_is_help=True,
)
console = Console()

_FOR_HELP = "How long it lasts: 2h, 3d, or never (a member or search one lasts 24h unless told)"


def _call(fn: Callable[..., Any], **kwargs: Any) -> Any:
    """Call a typed-client endpoint; say the hub's reason and exit on a refusal."""
    with typed_client() as client:
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


def _ends(raw: str | None) -> str:
    """``in 23h`` / ``with its task`` / ``never``."""
    if not raw:
        return "never"
    stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    seconds = max(0, int((stamp - datetime.now(UTC)).total_seconds()))
    if seconds < 3600:
        return f"in {seconds // 60}m"
    if seconds < 172800:
        return f"in {seconds // 3600}h"
    return f"in {seconds // 86400}d"


def _subscribe(
    room: str | None,
    handle: str | None,
    kind: str,
    target: str,
    *,
    as_json: bool,
    parts: bool = False,
    task: str | None = None,
    span: str | None = None,
) -> None:
    from mycelium_backend_client.api.subscriptions import (
        subscribe_api_rooms_room_name_subscriptions_post as subscribe_api,
    )
    from mycelium_backend_client.models import WakeSubscriptionCreate, WakeSubscriptionCreateKind

    assert room is not None
    body = WakeSubscriptionCreate(
        handle=(handle or "").lstrip("@"),
        kind=WakeSubscriptionCreateKind(kind),
        target=target,
        parts=parts,
        task=task,
        span=span,
    )
    data = _call(subscribe_api.sync_detailed, room_name=room, body=body)
    if as_json:
        typer.echo(json.dumps(data, indent=2))
        return
    ends = (
        "ends with its task"
        if data["kind"] == "task" and not data.get("until")
        else f"ends {_ends(data.get('until'))}"
    )
    console.print(
        f"[green]Subscribed[/green] @{data['handle']} to {data['describe']} "
        f"[dim]({ends}; id {data['id']})[/dim]"
    )


@doc_ref(
    usage="mycelium subscribe task <row> [--parts] [--for 3d]",
    desc=(
        "Be woken when a task's thread moves or the board says something about it. "
        "<code>--parts</code> covers its parts too, including ones filed later. "
        "Ends by itself once the task (and its parts) are done."
    ),
    group="subscribe",
)
@app.command(name="task")
@in_room("room")
@acts_as("handle", fallback=None)
@emits_json("as_json")
def subscribe_task(
    key: str = typer.Argument(..., help="The task's key, like work/release-3-1"),
    parts: bool = typer.Option(False, "--parts", help="Its parts too, including later ones"),
    span: str | None = typer.Option(None, "--for", help=_FOR_HELP),
    room: str | None = None,
    handle: str | None = None,
    as_json: bool = False,
) -> None:
    """Be woken when a task, or its parts, moves."""
    _subscribe(room, handle, "task", key, parts=parts, span=span, as_json=as_json)


@doc_ref(
    usage="mycelium subscribe notice <kind> [--task <row>] [--for 3d]",
    desc=(
        "Be woken for one kind of notice: a board one (<code>filed</code>, <code>claimed</code>, "
        "<code>resolved</code>, <code>blocked</code>...) or a pull request's change "
        "(<code>upstream:merged</code>, <code>upstream:ci_failed</code>...). "
        "<code>--task</code> keeps it to one task."
    ),
    group="subscribe",
)
@app.command(name="notice")
@in_room("room")
@acts_as("handle", fallback=None)
@emits_json("as_json")
def subscribe_notice(
    kind: str = typer.Argument(..., help="A notice kind, or upstream:<change>"),
    task: str | None = typer.Option(None, "--task", "-t", help="Only notices about this task"),
    span: str | None = typer.Option(None, "--for", help=_FOR_HELP),
    room: str | None = None,
    handle: str | None = None,
    as_json: bool = False,
) -> None:
    """Be woken for one kind of notice."""
    _subscribe(room, handle, "notice", kind, task=task, span=span, as_json=as_json)


@doc_ref(
    usage="mycelium subscribe member <handle> [--for 3d|never]",
    desc="Be woken for anything one member says, in the room or its threads. Lasts 24h unless told.",
    group="subscribe",
)
@app.command(name="member")
@in_room("room")
@acts_as("handle", fallback=None)
@emits_json("as_json")
def subscribe_member(
    member: str = typer.Argument(..., help="The member's handle"),
    span: str | None = typer.Option(None, "--for", help=_FOR_HELP),
    room: str | None = None,
    handle: str | None = None,
    as_json: bool = False,
) -> None:
    """Be woken for what one member says."""
    _subscribe(room, handle, "member", member, span=span, as_json=as_json)


@doc_ref(
    usage='mycelium subscribe search "<query>" [--for 3d|never]',
    desc=(
        "Be woken for each new message matching a <code>mycelium room search</code> query, "
        "in the same grammar (no <code>after:</code>, <code>before:</code>, <code>on:</code> "
        "or <code>sort:</code>). Lasts 24h unless told."
    ),
    group="subscribe",
)
@app.command(name="search")
@in_room("room")
@acts_as("handle", fallback=None)
@emits_json("as_json")
def subscribe_search(
    query: str = typer.Argument(..., help='A room search query, like "from:reviewer approved"'),
    span: str | None = typer.Option(None, "--for", help=_FOR_HELP),
    room: str | None = None,
    handle: str | None = None,
    as_json: bool = False,
) -> None:
    """Be woken for new messages matching a search."""
    _subscribe(room, handle, "search", query, span=span, as_json=as_json)


@doc_ref(
    usage="mycelium subscribe ls [--all]",
    desc="What you are subscribed to, with ids and when each ends. <code>--all</code>: everyone's in the room.",
    group="subscribe",
)
@app.command(name="ls")
@in_room("room")
@acts_as("handle")
@emits_json("as_json")
def subscribe_ls(
    everyone: bool = typer.Option(False, "--all", "-a", help="Everyone's in the room"),
    room: str | None = None,
    handle: str | None = None,
    as_json: bool = False,
) -> None:
    """List subscriptions."""
    from mycelium_backend_client.api.subscriptions import (
        list_subscriptions_api_rooms_room_name_subscriptions_get as list_api,
    )

    assert room is not None
    who = None if everyone else (handle or "").lstrip("@")
    data = _call(list_api.sync_detailed, room_name=room, handle=who)
    items = data.get("subscriptions", [])
    if as_json:
        typer.echo(json.dumps(items, indent=2))
        return
    if not items:
        whose = "anyone" if everyone else f"@{who}"
        console.print(f"[dim]No subscriptions for {whose} in {room}[/dim]")
        return
    table = Table(box=None, pad_edge=False, header_style="dim")
    for col in ("id", "agent", "subscribed to", "ends"):
        table.add_column(col, no_wrap=col in ("id", "agent"))
    for s in items:
        ends = (
            "with its task" if s["kind"] == "task" and not s.get("until") else _ends(s.get("until"))
        )
        table.add_row(f"[cyan]{s['id']}[/cyan]", f"@{s['handle']}", s["describe"], ends)
    console.print(table)


@doc_ref(
    usage="mycelium subscribe rm (<id> | --all)",
    desc="Drop one of your subscriptions, or all of them.",
    group="subscribe",
)
@app.command(name="rm")
@in_room("room")
@acts_as("handle", fallback=None)
@confirms("yes")
@emits_json("as_json")
def subscribe_rm(
    sub_id: str | None = typer.Argument(None, help="The subscription's id (from ls)"),
    everything: bool = typer.Option(False, "--all", "-a", help="Every one of yours"),
    room: str | None = None,
    handle: str | None = None,
    yes: bool = False,
    as_json: bool = False,
) -> None:
    """Drop a subscription, or all of yours."""
    from mycelium_backend_client.api.subscriptions import (
        unsubscribe_api_rooms_room_name_subscriptions_delete as delete_api,
    )

    assert room is not None
    if bool(sub_id) == everything:
        console.print("[red]Error:[/red] name one subscription's id, or pass --all")
        raise typer.Exit(1)
    me = (handle or "").lstrip("@")
    if everything and not yes and not typer.confirm(f"Drop every subscription of @{me} in {room}?"):
        raise typer.Exit(0)
    data = _call(delete_api.sync_detailed, room_name=room, handle=me, id=sub_id)
    gone = data.get("removed", [])
    if as_json:
        typer.echo(json.dumps(gone, indent=2))
        return
    for s in gone:
        console.print(f"[green]Unsubscribed[/green] @{me} from {s['describe']}")
    if not gone:
        console.print(f"[dim]@{me} had no subscriptions in {room}[/dim]")
