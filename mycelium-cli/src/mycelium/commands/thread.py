# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Thread commands: a conversation scope inside a room (#631).

A room is one broadcast transcript, so past two participants it tangles — which
reply answers which prompt becomes guesswork. A **thread** is the unit smaller
than the whole room: something to read, follow, and address on its own.

Threads are derived, not stored. A reply already names what it answers (the L9
causal parents every message carries), and that edge *is* the thread — so a
thread appears the moment someone replies, and a transcript written before
threads existed reads as threaded now. ``thread new`` is for the one case
causality can't express yet: opening a scope before anyone has replied into it.

The whole surface is additive. ``await``/``respond``/``room messages`` take an
optional ``--thread``; without one, everything behaves exactly as before.
"""

from __future__ import annotations

import json as json_module

import typer
from rich.console import Console

from mycelium.client import hub_client
from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref
from mycelium.error_handler import print_error

app = typer.Typer(
    help="Read and open threads: conversation scopes inside a room, derived from what each message replies to.",
    no_args_is_help=True,
)
console = Console()


def _resolve_room(config: MyceliumConfig, room: str | None) -> str:
    from mycelium.commands.room import _resolve_room as resolve

    return resolve(config, room)


def _short(thread_id: str) -> str:
    """The handle a person actually types: threads resolve by id prefix."""
    return thread_id[:8]


@doc_ref(
    usage="mycelium thread ls [--room <room>]",
    desc="List a room's threads, most recently active first.",
    group="thread",
)
@app.command("ls")
def thread_ls(
    ctx: typer.Context,
    room: str | None = typer.Option(None, "--room", "-r", help="Room (default: active room)"),
    limit: int = typer.Option(20, "--limit", "-l", help="Max threads to show"),
) -> None:
    """List a room's threads, most recently active first.

    Examples:
        mycelium thread ls
        mycelium thread ls --room design-review
    """
    try:
        config = MyceliumConfig.load()
        room_name = _resolve_room(config, room)
        with hub_client(config) as client:
            resp = client.get(f"/api/rooms/{room_name}/threads", params={"limit": limit})
        resp.raise_for_status()
        found = resp.json().get("threads", [])

        if ctx.obj and ctx.obj.get("json"):
            typer.echo(json_module.dumps(found, indent=2))
            return
        if not found:
            console.print(f"[dim]{room_name}: no threads yet[/dim]")
            return
        console.print(
            f"\n[bold cyan]  {room_name}[/bold cyan]  [dim]({len(found)} threads)[/dim]\n"
        )
        for t in found:
            kind = "negotiation" if t["kind"] == "episode" else "chat"
            console.print(f"  [cyan]{_short(t['id'])}[/cyan]  {t['title']}")
            console.print(
                f"            [dim]{kind} · {t['message_count']} messages · "
                f"{', '.join(t['participants']) or 'nobody'}[/dim]"
            )
        console.print()
    except typer.Exit:
        raise
    except Exception as e:
        print_error(e, verbose=bool(ctx.obj and ctx.obj.get("verbose")))
        raise typer.Exit(1) from e


@doc_ref(
    usage="mycelium thread show <id> [--room <room>]",
    desc="Read one thread end to end. The id may be a prefix.",
    group="thread",
)
@app.command("show")
def thread_show(
    ctx: typer.Context,
    thread_id: str = typer.Argument(..., help="Thread id (a prefix is enough)"),
    room: str | None = typer.Option(None, "--room", "-r", help="Room (default: active room)"),
) -> None:
    """Read one thread's messages, oldest first.

    Examples:
        mycelium thread show 3f9a1c2d
        mycelium thread show 3f9a --room design-review
    """
    try:
        config = MyceliumConfig.load()
        room_name = _resolve_room(config, room)
        with hub_client(config) as client:
            resp = client.get(f"/api/rooms/{room_name}/threads/{thread_id}")
        resp.raise_for_status()
        thread = resp.json()

        if ctx.obj and ctx.obj.get("json"):
            typer.echo(json_module.dumps(thread, indent=2))
            return
        console.print(f"\n[bold cyan]  {thread['title']}[/bold cyan]")
        console.print(
            f"  [dim]{thread['id']} · {thread['kind']} · {thread['message_count']} messages[/dim]\n"
        )
        for m in thread.get("messages", []):
            stamp = str(m.get("created_at", ""))[11:19]
            first, *rest = (m.get("content") or "").split("\n")
            console.print(f"  {stamp}  [bold]{m['sender_handle']}[/bold]: {first}")
            for line in rest:
                console.print(f"              {line}")
        console.print()
    except typer.Exit:
        raise
    except Exception as e:
        print_error(e, verbose=bool(ctx.obj and ctx.obj.get("verbose")))
        raise typer.Exit(1) from e


@doc_ref(
    usage='mycelium thread new "<opening message>" [--room <room>] [--handle <handle>]',
    desc="Open a thread by posting its first message; prints the thread id to scope later replies with.",
    group="thread",
)
@app.command("new")
def thread_new(
    ctx: typer.Context,
    title: str = typer.Argument(..., help="The opening message; its first line titles the thread"),
    room: str | None = typer.Option(None, "--room", "-r", help="Room (default: active room)"),
    handle: str | None = typer.Option(
        None, "--handle", "-H", help="Your sender handle (defaults to identity config)"
    ),
) -> None:
    """Open a thread and print its id.

    The opening message is posted to the room like any other, so ``@``-mentions in
    it wake the agents they name — into the thread they just opened.

    Examples:
        mycelium thread new "Cache TTL: what should it be?"
        mycelium thread new "@rowan-agent @avery-agent let's settle the rollout order"
    """
    try:
        config = MyceliumConfig.load()
        room_name = _resolve_room(config, room)
        sender = handle or config.get_current_identity()
        with hub_client(config, handle=sender) as client:
            resp = client.post(
                f"/api/rooms/{room_name}/threads",
                json={"title": title, "sender_handle": sender},
            )
        resp.raise_for_status()
        thread = resp.json()

        if ctx.obj and ctx.obj.get("json"):
            typer.echo(json_module.dumps(thread, indent=2))
            return
        console.print(f"[green]Thread opened:[/green] {thread['title']}")
        console.print(f"  [cyan]{thread['id']}[/cyan]")
        console.print(
            f"  [dim]reply into it with: mycelium respond --thread {_short(thread['id'])} "
            f'--handle <you> "…"[/dim]'
        )
    except typer.Exit:
        raise
    except Exception as e:
        print_error(e, verbose=bool(ctx.obj and ctx.obj.get("verbose")))
        raise typer.Exit(1) from e
