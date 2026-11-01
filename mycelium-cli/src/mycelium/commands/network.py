# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium network``: SLIM coordination fabric status.

Surfaces the backend's live coordination telemetry (from ``/health``): the SLIM
node endpoint, channel/provision counters, and, per room, who is present plus the
durable-inbox counters. This is the read-only observability view over the fabric:
who is on the channel and how each room's channel is doing.

The backend is the authority on room membership: the SLIM node only forwards
ciphertext and cannot report rosters, so "who is on the network" is the backend's
union of SLIM-connected members and server-held ``await`` participants.

A room can also reach members that are *not* on the channel: A2A agents, bridged
over HTTP by the hub. They're rendered in their own block per room (from
``/api/rooms/{room}/a2a/state``) rather than mixed into the members column, because
the distinction is the point — a bridged agent is proxied by the hub and holds no
group key, so it is not a member of the room's encrypted group. This is the CLI
half of the same surface the GUI's Network pane shows.
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
from mycelium.exceptions import MyceliumError
from mycelium.hub_check import health
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
    typer.echo("    bridged agents are proxied by the hub over HTTP — not members of the")
    typer.echo("    room's encrypted group, and the hub sees their traffic in plaintext")

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


@doc_ref(
    usage="mycelium network [room]",
    desc="Show SLIM fabric status: node, channels, members, and A2A bridges.",
    group="setup",
)
def network(
    ctx: typer.Context,
    room: str | None = typer.Argument(None, help="Only show this room"),
) -> None:
    """
    Show the SLIM coordination fabric status.

    Renders the backend's live coordination telemetry: the SLIM node endpoint,
    live-channel and provision counters, and (per room) who is present (SLIM
    members plus server-held ``await`` participants), invites an active episode is
    holding, whether an episode is active, and durable-inbox counters (re-serves,
    receive errors).

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

        said = health(config.server.api_url, timeout=30)
        if not said.answered:
            print_error(f"Cannot reach the backend at {config.server.api_url}: {said.error}")
            return
        if said.read is None:
            raise MyceliumError(f"the hub at {said.url} didn't say: {said.error}")
        # The hub's telemetry, printed as told and passed through ``--json``.
        coord = said.coordination.to_dict() if said.coordination else {}
        with typed_client(config, timeout=30, raise_on_unexpected_status=False) as client:
            rooms = coord.get("rooms") or []
            if room:
                rooms = [r for r in rooms if r.get("room") == room]

            a2a = {
                name: state
                for name in (r.get("room", "") for r in rooms)
                if name and (state := _fetch_a2a(client, name)) is not None
            }

        if json_output:
            # `a2a` is null for a room with no bridge and no inbound traffic —
            # the same rooms the rendered view leaves undecorated.
            enriched = [{**r, "a2a": a2a.get(r.get("room", ""))} for r in rooms]
            typer.echo(json_module.dumps({**coord, "rooms": enriched}, indent=2, default=str))
            return

        endpoint = coord.get("endpoint") or "-"
        enabled = bool(coord.get("slim_enabled"))
        print_title("Mycelium Network", subtitle=f"SLIM node {endpoint}")

        dot = typer.style("●", fg=typer.colors.GREEN if enabled else typer.colors.RED)
        typer.echo(
            f"  {dot} fabric {'enabled' if enabled else 'disabled'}   "
            f"channels: {coord.get('channels_live', 0)} live   "
            f"provisions: {coord.get('provisions_ok', 0)} ok / "
            f"{coord.get('provisions_failed', 0)} failed   "
            f"invite failures: {coord.get('invite_failures', 0)}"
        )
        typer.echo()

        if not rooms:
            suffix = f" matching '{room}'" if room else ""
            typer.echo(f"  no provisioned rooms{suffix}")
            return

        # MEMBERS goes last so a long roster extends the line instead of breaking
        # the fixed columns before it.
        name_w = max(len("ROOM"), *(len(r.get("room", "")) for r in rooms))
        typer.secho(
            f"  {'ROOM':<{name_w}}  DEFER  EPISODE  RESRV  RECV-ERR  MEMBERS",
            fg=typer.colors.BRIGHT_BLACK,
        )
        for r in sorted(rooms, key=lambda x: x.get("room", "")):
            members = r.get("members") or []
            episode = "active" if r.get("episode_active") else "idle"
            typer.echo(
                f"  {r.get('room', ''):<{name_w}}  "
                f"{r.get('deferred_invites', 0):>5}  "
                f"{episode:<7}  "
                f"{r.get('reserves', 0):>5}  "
                f"{r.get('receive_errors', 0):>8}  "
                f"{', '.join(members) if members else '-'}"
            )
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
