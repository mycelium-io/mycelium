# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
Structured negotiation commands for Mycelium CLI.

Commands:
- propose: Submit an offer for the current negotiate/propose tick
- respond: Accept, reject, or end the current negotiate/respond tick
- query:   Post a raw response (advanced / non-negotiate scenarios)

All three are reply-to-tick commands — you run them after CognitiveEngine
addressed you in an active session. They route through the session sub-room
so `coordination.on_agent_response` sees the reply.

For cross-agent chat messages (not negotiation), use `mycelium room send`.

Uses the generated OpenAPI client for type-safe API access. Outgoing
payloads are validated against SSTP wire-format models (mycelium.sstp)
before posting, so the CLI is statically forced to adhere to the protocol.
"""

import json as json_module

import httpx
import typer
from pydantic import ValidationError

from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref
from mycelium.error_handler import print_error
from mycelium.sstp import ProposeReply, RespondReply

app = typer.Typer(
    help="Respond to CognitiveEngine during structured negotiation (propose/respond/query).",
    no_args_is_help=True,
)


# ── Shared helpers ────────────────────────────────────────────────────────────


def _resolve_active_session_room(config: "MyceliumConfig", room_name: str) -> str:
    """If room_name is a namespace room with an active negotiating session sub-room,
    return the session room so agent replies route to the coordination service."""
    import httpx

    try:
        resp = httpx.get(
            f"{config.server.api_url}/rooms",
            params={"limit": 200},
            timeout=5,
        )
        if resp.status_code != 200:
            return room_name
        prefix = f"{room_name}:session:"
        session_rooms = [r["name"] for r in resp.json() if r.get("name", "").startswith(prefix)]
        if not session_rooms:
            return room_name
        # Pick the most-recently-created session room (last in list by created_at)
        # If there are multiple, prefer the one in 'negotiating' state
        for sr in reversed(session_rooms):
            try:
                r = httpx.get(f"{config.server.api_url}/rooms/{sr}", timeout=5)
                if r.status_code == 200 and r.json().get("coordination_state") == "negotiating":
                    return sr
            except Exception:
                pass
    except Exception:
        pass
    return room_name


def _post(ctx: typer.Context, room: str | None, handle: str | None, content: str) -> None:
    from mycelium.commands.room import _resolve_room
    from mycelium_backend_client import Client
    from mycelium_backend_client.api.messages import (
        send_message_rooms_room_name_messages_post as send_api,
    )
    from mycelium_backend_client.models import MessageCreate

    json_output = ctx.obj.get("json", False) if ctx.obj else False

    config = MyceliumConfig.load()
    room_name = _resolve_room(config, room)
    # If this is a namespace room, route the reply to the active session sub-room
    # so coordination.on_agent_response sees it.
    room_name = _resolve_active_session_room(config, room_name)
    handle = handle or config.get_current_identity()

    client = Client(base_url=config.server.api_url, raise_on_unexpected_status=True)
    with client:
        body = MessageCreate(
            sender_handle=handle,
            message_type="direct",
            content=content,
        )
        result = send_api.sync(room_name=room_name, client=client, body=body)

    if json_output and result:
        msg_dict = result.to_dict() if hasattr(result, "to_dict") else str(result)
        typer.echo(json_module.dumps(msg_dict, indent=2, default=str))
        return

    typer.echo(f"  ↑  {handle}: {content[:80]}")
    typer.echo("  Response submitted. CognitiveEngine will address you here when ready.")


# ── propose ───────────────────────────────────────────────────────────────────


@doc_ref(
    usage="mycelium negotiate propose KEY=VALUE [KEY=VALUE ...] [-r <room>] [-H <handle>]",
    desc="Make a negotiation proposal with issue values. Only valid after <code>session await</code> returns <code>action: propose</code>.",
    group="negotiate",
)
@app.command("propose")
def propose(
    ctx: typer.Context,
    assignments: list[str] = typer.Argument(
        ...,
        help="Issue assignments as KEY=VALUE pairs, e.g. budget=medium timeline=standard",
    ),
    room: str | None = typer.Option(
        None, "--room", "-r", help="Room to respond in (overrides MYCELIUM_ROOM_ID)"
    ),
    handle: str | None = typer.Option(
        None, "--handle", "-H", help="Your agent handle (overrides identity config)"
    ),
) -> None:
    """
    Submit an offer for the current negotiate/propose tick.

    Pass issue assignments as KEY=VALUE pairs.  The CLI wraps them in the
    correct wire format so you never have to write JSON by hand.

    Examples:
        mycelium negotiate propose budget=medium timeline=standard scope=standard quality=standard
        mycelium negotiate propose budget=high scope=full --room my-room --handle julia-agent
    """
    from mycelium.commands.room import _resolve_room

    try:
        offer: dict[str, str] = {}
        for pair in assignments:
            if "=" not in pair:
                typer.echo(f"  Error: expected KEY=VALUE, got '{pair}'", err=True)
                raise typer.Exit(1)
            key, _, value = pair.partition("=")
            offer[key.strip()] = value.strip()

        if not offer:
            typer.echo("  Error: at least one KEY=VALUE assignment is required.", err=True)
            raise typer.Exit(1)

        # Validate keys against live negotiation state before posting.
        config = MyceliumConfig.load()
        room_name = _resolve_room(config, room)
        session_room = _resolve_active_session_room(config, room_name)
        try:
            resp = httpx.get(
                f"{config.server.api_url}/rooms/{session_room}/negotiation",
                timeout=5,
            )
            if resp.status_code == 200:
                neg = resp.json()
                current_offer = neg.get("current_offer") or {}
                if current_offer:
                    bad_keys = sorted(set(offer) - set(current_offer))
                    if bad_keys:
                        typer.echo("  Error: counter-offer contains unrecognised issue keys:", err=True)
                        for bk in bad_keys:
                            # fuzzy suggestion: case-insensitive match
                            suggestion = next(
                                (v for v in current_offer if v.lower() == bk.lower()), None
                            )
                            hint = f'  →  did you mean "{suggestion}"?' if suggestion else ""
                            typer.echo(f'    "{bk}"{hint}', err=True)
                        typer.echo("", err=True)
                        typer.echo("  Valid keys for this session:", err=True)
                        for vk in sorted(current_offer):
                            typer.echo(f'    "{vk}"', err=True)
                        raise typer.Exit(1)
        except (httpx.RequestError, typer.Exit):
            raise
        except Exception:
            pass  # validation is best-effort; backend enforces authoritatively

        try:
            reply = ProposeReply(offer=offer)
        except ValidationError as exc:
            typer.echo(f"  Error: invalid propose payload — {exc}", err=True)
            raise typer.Exit(1) from exc

        content = json_module.dumps(reply.model_dump())
        _post(ctx, room, handle, content)

    except (typer.Exit, typer.Abort):
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


# ── respond ───────────────────────────────────────────────────────────────────

# Kept in sync with RespondReply.action Literal for the help text / error message.
VALID_ACTIONS = {"accept", "reject", "end", "counter_offer"}


@doc_ref(
    usage="mycelium negotiate respond <accept|reject> -r <room> -H <handle>",
    desc="Accept or reject the current proposal. Only valid after <code>session await</code> returns <code>action: respond</code>.",
    group="negotiate",
)
@app.command("respond")
def respond(
    ctx: typer.Context,
    action: str = typer.Argument(
        ...,
        help="Your response: accept | reject | end",
    ),
    room: str | None = typer.Option(
        None, "--room", "-r", help="Room to respond in (overrides MYCELIUM_ROOM_ID)"
    ),
    handle: str | None = typer.Option(
        None, "--handle", "-H", help="Your agent handle (overrides identity config)"
    ),
) -> None:
    """
    Accept, reject, or end the negotiation for the current respond tick.

    Examples:
        mycelium negotiate respond accept
        mycelium negotiate respond reject --room my-room
        mycelium negotiate respond end    --handle julia-agent
    """
    try:
        action = action.strip().lower()

        try:
            reply = RespondReply(action=action)  # type: ignore[arg-type]
        except ValidationError:
            typer.echo(
                f"  Error: action must be one of {', '.join(sorted(VALID_ACTIONS))}, got '{action}'",
                err=True,
            )
            raise typer.Exit(1) from None

        content = json_module.dumps(reply.model_dump())
        _post(ctx, room, handle, content)

    except (typer.Exit, typer.Abort):
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


# ── query (raw / advanced) ────────────────────────────────────────────────────


@doc_ref(
    usage="mycelium negotiate query <json> [-r <room>] [-H <handle>]",
    desc="Post a raw JSON response (advanced — prefer <code>propose</code> or <code>respond</code>).",
    group="negotiate",
)
@app.command("query")
def query(
    ctx: typer.Context,
    text: str = typer.Argument(..., help="Raw JSON payload to post as your coordination response"),
    room: str | None = typer.Option(
        None, "--room", "-r", help="Room to respond in (overrides MYCELIUM_ROOM_ID)"
    ),
    handle: str | None = typer.Option(
        None, "--handle", "-H", help="Your agent handle (overrides identity config)"
    ),
) -> None:
    """
    Post a raw JSON response (advanced use — prefer 'propose' or 'respond' for negotiate ticks).

    Examples:
        mycelium negotiate query '{"offer": {"budget": "high", "scope": "extended"}}'
        mycelium negotiate query '{"action": "accept"}' --room my-experiment
    """
    try:
        _post(ctx, room, handle, text)
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


# ── status ────────────────────────────────────────────────────────────────────


@doc_ref(
    usage="mycelium negotiate status [-r <room>]",
    desc="Show the current negotiation state: round, issues, current offer, and per-agent reply status.",
    group="negotiate",
)
@app.command("status")
def status(
    ctx: typer.Context,
    room: str | None = typer.Option(
        None, "--room", "-r", help="Room to check (overrides MYCELIUM_ROOM_ID)"
    ),
) -> None:
    """
    Show live negotiation state for the active session in a room.

    Displays the current round, canonical issue list, standing offer, and which
    agents have submitted replies this round.

    Examples:
        mycelium negotiate status
        mycelium negotiate status --room sprint-plan
    """
    from mycelium.commands.room import _resolve_room

    json_output = ctx.obj.get("json", False) if ctx.obj else False

    try:
        config = MyceliumConfig.load()
        room_name = _resolve_room(config, room)
        room_name = _resolve_active_session_room(config, room_name)

        resp = httpx.get(
            f"{config.server.api_url}/rooms/{room_name}/negotiation",
            timeout=5,
        )
        if resp.status_code == 404:
            typer.echo("  Room not found.", err=True)
            raise typer.Exit(1)
        resp.raise_for_status()
        data = resp.json()

        if json_output:
            typer.echo(json_module.dumps(data, indent=2))
            return

        if not data.get("active"):
            typer.echo("  No active negotiation.")
            return

        typer.echo(f"  Round {data['round']}  —  {room_name}")
        typer.echo("")
        issues = data.get("issues") or []
        issue_options = data.get("issue_options") or {}
        current_offer = data.get("current_offer") or {}
        for issue in issues:
            opts = ", ".join(issue_options.get(issue, []))
            current = current_offer.get(issue, "—")
            typer.echo(f"  {issue}")
            typer.echo(f"    current: {current}")
            if opts:
                typer.echo(f"    options: {opts}")
        typer.echo("")
        for agent_handle, reply_status in (data.get("pending_replies") or {}).items():
            icon = "+" if reply_status == "received" else "."
            typer.echo(f"  [{icon}] {agent_handle}")

    except (typer.Exit, typer.Abort):
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
