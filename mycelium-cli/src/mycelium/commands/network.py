# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium network``: who is in each room, and what reaches it from outside.

Lists the hub's rooms (``/api/rooms``) and, per room, who is present
(``/api/rooms/{room}/sessions/members``): server-held ``await`` participants and
herdr members. The hub is the authority on room membership.

A room can also reach agents that are *not* its members: A2A agents, bridged over
HTTP by the hub. They're rendered in their own block per room (from
``/api/rooms/{room}/a2a/state``) rather than mixed into the members column,
because the distinction is the point: a bridged agent is proxied by the hub, not
a member of the room. This is the CLI half of the same surface the GUI's Network
pane shows.
"""

from __future__ import annotations

import json as json_module
from typing import TYPE_CHECKING

import httpx
import typer

from mycelium.client import typed_client
from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref
from mycelium.error_handler import print_error
from mycelium.ui_status import print_title

if TYPE_CHECKING:
    from mycelium_backend_client import Client

#: Bridge exchanges shown per room — a tail for context, not a log.
_RECENT_EXCHANGES = 3


def _fetch_a2a(client: Client, room: str) -> dict | None:
    """A room's A2A bridge state, or None when it has none (or the read fails).

    Fail-soft on purpose: this is a decoration on the fabric view, so an older
    backend without the route, or a transient error, must not take the whole
    command down with it. Handed on as the hub's record: it's printed as told
    and passed through ``--json``.
    """
    from mycelium_backend_client.api.a2a import a2a_state_api_rooms_room_name_a2a_state_get
    from mycelium_backend_client.models import A2ABridgeState

    try:
        resp = a2a_state_api_rooms_room_name_a2a_state_get.sync_detailed(room, client=client)
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(resp.parsed, A2ABridgeState):
        return None
    state = resp.parsed.to_dict()
    exposure = state.get("exposure") or {}
    touched = exposure.get("card_fetches") or exposure.get("messages")
    if not state.get("agents") and not state.get("exchanges") and not touched:
        return None  # nothing bridged and nothing inbound — print nothing
    return state


def _clip(text: str | None, width: int = 60) -> str:
    cleaned = " ".join((text or "").split())
    return cleaned if len(cleaned) <= width else cleaned[: width - 1] + "…"


def _print_a2a(room: str, state: dict) -> None:
    """One room's bridge block: bridged agents, the room's exposure, last calls."""
    typer.secho(f"  A2A bridge · {room}", fg=typer.colors.BRIGHT_BLACK)
    typer.echo("    bridged agents are proxied by the hub over HTTP: not members of the")
    typer.echo("    room, and the hub sees their traffic in plaintext")

    agents = state.get("agents") or []
    if agents:
        name_w = max(len("AGENT"), *(len(a.get("handle", "")) + 1 for a in agents))
        typer.secho(
            f"    {'AGENT':<{name_w}}  {'ENDPOINT':<40}  CALLS      SKILLS",
            fg=typer.colors.BRIGHT_BLACK,
        )
        for agent in agents:
            calls = f"{agent.get('calls_ok', 0)}✓/{agent.get('calls_failed', 0)}✗"
            skills = ", ".join(agent.get("skills") or []) or "-"
            endpoint = agent.get("endpoint") or agent.get("card") or "-"
            typer.echo(
                f"    {'@' + agent.get('handle', ''):<{name_w}}  "
                f"{endpoint:<40}  {calls:<9}  {skills}"
            )

    exposure = state.get("exposure") or {}
    if exposure.get("card_url"):
        fetches = exposure.get("card_fetches", 0)
        messages = exposure.get("messages", 0)
        typer.echo(
            f"    inbound: card at {exposure['card_url']}  "
            f"({fetches} fetch{'' if fetches == 1 else 'es'}, "
            f"{messages} message{'' if messages == 1 else 's'})"
        )

    exchanges = (state.get("exchanges") or [])[-_RECENT_EXCHANGES:]
    for exchange in exchanges:
        arrow = "→" if exchange.get("direction") == "outbound" else "←"
        ok = exchange.get("status") == "ok"
        detail = exchange.get("reply") if ok else (exchange.get("detail") or "no answer")
        took = f" {exchange['duration_ms']}ms" if exchange.get("duration_ms") is not None else ""
        line = (
            f"    {arrow} @{exchange.get('handle', '')} "
            f"{'ok' if ok else 'failed'}{took}  {_clip(detail)}"
        )
        typer.secho(line, fg=None if ok else typer.colors.RED)
    typer.echo()


def _fetch_rooms(client: Client) -> list[str]:
    """The names of the rooms the hub lists for this caller."""
    from mycelium.client import answered
    from mycelium_backend_client.api.rooms import list_rooms_api_rooms_get as list_api

    rooms = answered(list_api.sync_detailed(client=client), list)
    return [r.name for r in rooms]


def _fetch_members(client: Client, room: str) -> list[dict]:
    """Who is present in a room, as ``{handle, kind}``; empty when the read fails."""
    from mycelium_backend_client.api.sessions import (
        list_members_api_rooms_room_name_sessions_members_get as members_api,
    )
    from mycelium_backend_client.models import RoomPresenceRead

    try:
        present = members_api.sync(room, client=client)
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return []
    if not isinstance(present, RoomPresenceRead):
        return []
    return [{"handle": m.handle, "kind": m.kind} for m in present.members]


@doc_ref(
    usage="mycelium network [room]",
    desc="Show who is present in each room, and the A2A agents bridged into it.",
    group="setup",
)
def network(
    ctx: typer.Context,
    room: str | None = typer.Argument(None, help="Only show this room"),
) -> None:
    """
    Show who is present in each room, and the A2A agents bridged into it.

    Lists the hub's rooms and, per room, who is present: server-held ``await``
    participants (``lease``) and herdr members (``herdr``).

    Rooms with an A2A bridge get a block of their own: the bridged agents with
    their endpoint and advertised skills, whether the room's own Agent Card is
    being read, and the last exchanges either way.

    Examples:
        mycelium network
        mycelium network handshake
        mycelium network --json
    """
    try:
        json_output = ctx.obj.get("json", False) if ctx.obj else False

        config = MyceliumConfig.load()

        with typed_client(config, timeout=30, raise_on_unexpected_status=False) as client:
            names = _fetch_rooms(client)
            if room:
                names = [n for n in names if n == room]
            present = {n: _fetch_members(client, n) for n in sorted(names)}
            a2a = {n: state for n in names if (state := _fetch_a2a(client, n)) is not None}

        if json_output:
            # `a2a` is null for a room with no bridge and no inbound traffic:
            # the same rooms the rendered view leaves undecorated.
            rooms = [{"room": n, "members": m, "a2a": a2a.get(n)} for n, m in present.items()]
            typer.echo(json_module.dumps({"rooms": rooms}, indent=2, default=str))
            return

        print_title("Mycelium Network", subtitle=config.server.api_url)

        if not present:
            suffix = f" matching '{room}'" if room else ""
            typer.echo(f"  no rooms{suffix}")
            return

        name_w = max(len("ROOM"), *(len(n) for n in present))
        typer.secho(f"  {'ROOM':<{name_w}}  MEMBERS", fg=typer.colors.BRIGHT_BLACK)
        for name, members in present.items():
            listed = ", ".join(f"{m['handle']} ({m['kind']})" for m in members)
            typer.echo(f"  {name:<{name_w}}  {listed or '-'}")
        typer.echo()

        for name in sorted(a2a):
            _print_a2a(name, a2a[name])

    except (typer.Exit, typer.Abort):
        raise
    except httpx.HTTPError as exc:
        cfg = MyceliumConfig.load()
        print_error(f"Cannot reach the backend at {cfg.server.api_url}: {exc}")
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
