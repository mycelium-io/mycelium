# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium network`` — SLIM coordination fabric status.

Surfaces the backend's live coordination telemetry (from ``/health``): the SLIM
node endpoint, channel/provision counters, and, per room, who is present plus the
durable-inbox counters. This is the read-only observability view over the fabric —
who is on the channel and how each room's channel is doing.

The backend is the authority on room membership: the SLIM node only forwards
ciphertext and cannot report rosters, so "who is on the network" is the backend's
union of SLIM-connected members and server-held ``await`` participants.
"""

from __future__ import annotations

import json as json_module

import httpx
import typer

from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref
from mycelium.error_handler import print_error
from mycelium.exceptions import ConfigNotFoundError
from mycelium.http_client import MyceliumHTTPClient
from mycelium.ui_status import print_title


@doc_ref(
    usage="mycelium network [room]",
    desc="Show SLIM fabric status: node, channels, and per-room members.",
    group="setup",
)
def network(
    ctx: typer.Context,
    room: str | None = typer.Argument(None, help="Only show this room"),
) -> None:
    """
    Show the SLIM coordination fabric status.

    Renders the backend's live coordination telemetry: the SLIM node endpoint,
    live-channel and provision counters, and — per room — who is present (SLIM
    members plus server-held ``await`` participants), open consent invites, whether
    an episode is active, and durable-inbox counters (re-serves, receive errors).

    Examples:
        mycelium network
        mycelium network handshake
        mycelium network --json
    """
    try:
        json_output = ctx.obj.get("json", False) if ctx.obj else False

        config_path = MyceliumConfig.get_config_path()
        if not config_path.exists():
            raise ConfigNotFoundError(str(config_path))
        config = MyceliumConfig.load()

        with MyceliumHTTPClient(config=config) as client:
            resp = client.get("/health")
            health = resp.json()

        coord = (health or {}).get("coordination") or {}
        rooms = coord.get("rooms") or []
        if room:
            rooms = [r for r in rooms if r.get("room") == room]

        if json_output:
            typer.echo(json_module.dumps({**coord, "rooms": rooms}, indent=2, default=str))
            return

        endpoint = coord.get("endpoint") or "—"
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
            f"  {'ROOM':<{name_w}}  PEND  EPISODE  RESRV  RECV-ERR  MEMBERS",
            fg=typer.colors.BRIGHT_BLACK,
        )
        for r in sorted(rooms, key=lambda x: x.get("room", "")):
            members = r.get("members") or []
            episode = "active" if r.get("episode_active") else "idle"
            typer.echo(
                f"  {r.get('room', ''):<{name_w}}  "
                f"{r.get('pending_invites', 0):>4}  "
                f"{episode:<7}  "
                f"{r.get('reserves', 0):>5}  "
                f"{r.get('receive_errors', 0):>8}  "
                f"{', '.join(members) if members else '—'}"
            )
        typer.echo()

    except (typer.Exit, typer.Abort):
        raise
    except ConfigNotFoundError:
        raise
    except httpx.HTTPError as exc:
        cfg = MyceliumConfig.load()
        print_error(f"Cannot reach the backend at {cfg.server.api_url}: {exc}")
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
