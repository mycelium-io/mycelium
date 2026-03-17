"""
Message coordination commands for Mycelium CLI.

Commands:
- propose: Submit an offer for the current negotiate/propose tick
- respond: Accept, reject, or end the current negotiate/respond tick
- query:   Post a raw response (advanced / non-negotiate scenarios)

Uses the generated OpenAPI client for type-safe API access.
"""

import json as json_module

import typer

from mycelium.config import MyceliumConfig
from mycelium.error_handler import print_error

app = typer.Typer(help="Coordination message commands", invoke_without_command=True)


@app.callback(invoke_without_command=True)
def message_main(ctx: typer.Context) -> None:
    """Coordination message commands."""
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


# ── Shared helpers ────────────────────────────────────────────────────────────

def _post(ctx: typer.Context, channel: str | None, handle: str | None, content: str) -> None:
    from mycelium_backend_client import Client
    from mycelium_backend_client.api.messages import send_message_rooms_room_name_messages_post as send_api
    from mycelium_backend_client.models import MessageCreate

    from mycelium.commands.room import _resolve_room

    json_output = ctx.obj.get("json", False) if ctx.obj else False

    config = MyceliumConfig.load()
    room_name = _resolve_room(config, channel)
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

@app.command("propose")
def propose(
    ctx: typer.Context,
    assignments: list[str] = typer.Argument(
        ...,
        help="Issue assignments as KEY=VALUE pairs, e.g. budget=medium timeline=standard",
    ),
    channel: str | None = typer.Option(
        None, "--channel", "-c", help="Channel/room to respond in (overrides MYCELIUM_CHANNEL_ID)"
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
        mycelium message propose budget=medium timeline=standard scope=standard quality=standard
        mycelium message propose budget=high scope=full --channel my-room --handle julia-agent
    """
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

        content = json_module.dumps({"offer": offer})
        _post(ctx, channel, handle, content)

    except (typer.Exit, typer.Abort):
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


# ── respond ───────────────────────────────────────────────────────────────────

VALID_ACTIONS = {"accept", "reject", "end"}


@app.command("respond")
def respond(
    ctx: typer.Context,
    action: str = typer.Argument(
        ...,
        help="Your response: accept | reject | end",
    ),
    channel: str | None = typer.Option(
        None, "--channel", "-c", help="Channel/room to respond in (overrides MYCELIUM_CHANNEL_ID)"
    ),
    handle: str | None = typer.Option(
        None, "--handle", "-H", help="Your agent handle (overrides identity config)"
    ),
) -> None:
    """
    Accept, reject, or end the negotiation for the current respond tick.

    Examples:
        mycelium message respond accept
        mycelium message respond reject --channel my-room
        mycelium message respond end    --handle julia-agent
    """
    try:
        action = action.strip().lower()
        if action not in VALID_ACTIONS:
            typer.echo(
                f"  Error: action must be one of {', '.join(sorted(VALID_ACTIONS))}, got '{action}'",
                err=True,
            )
            raise typer.Exit(1)

        content = json_module.dumps({"action": action})
        _post(ctx, channel, handle, content)

    except (typer.Exit, typer.Abort):
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


# ── query (raw / advanced) ────────────────────────────────────────────────────

@app.command("query")
def query(
    ctx: typer.Context,
    text: str = typer.Argument(..., help="Raw JSON payload to post as your coordination response"),
    channel: str | None = typer.Option(
        None, "--channel", "-c", help="Channel/room to respond in (overrides MYCELIUM_CHANNEL_ID)"
    ),
    handle: str | None = typer.Option(
        None, "--handle", "-H", help="Your agent handle (overrides identity config)"
    ),
) -> None:
    """
    Post a raw JSON response (advanced use — prefer 'propose' or 'respond' for negotiate ticks).

    Examples:
        mycelium message query '{"offer": {"budget": "high", "scope": "extended"}}'
        mycelium message query '{"action": "accept"}' --channel my-experiment
    """
    try:
        _post(ctx, channel, handle, text)
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
