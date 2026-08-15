# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``l9 send`` / ``slim send`` — hidden dev/testing plumbing.

There's no way to put **L9 wire traffic** (or arbitrary SLIM messages) into a
room without running a full aligner-mediated negotiation. These two commands
are ``git cat-file``-style escape hatches for exercising the real path (SLIM
channel -> backend persister -> bus -> SSE) directly — QA'ing the frontend L9
Inspector, demoing the AOP layer, reproducing protocol edge cases (odd
subkinds, deep ``parents`` chains, missing metrics).

Deliberately **undocumented**: registered ``hidden=True`` and never
``@doc_ref``'d, so they never show up in ``mycelium --help`` or the generated
docs site. They bypass the aligner entirely and are for testing/demo only —
never a coordination shortcut.
"""

from __future__ import annotations

import asyncio
import json as json_module

import typer

from mycelium.commands.room import _resolve_room
from mycelium.config import MyceliumConfig
from mycelium.error_handler import print_error
from mycelium.slim import l9
from mycelium.slim.client import SlimError
from mycelium.slim.member import DEFAULT_WORKSPACE, publish_once

_BANNER = (
    "bypasses the aligner — real SLIM wire traffic for testing/demo only, "
    "never a coordination shortcut"
)

l9_app = typer.Typer(hidden=True, help="Inject L9 wire traffic into a room (dev/testing).")
slim_app = typer.Typer(hidden=True, help="Inject raw SLIM messages into a room (dev/testing).")


def _split_csv(raw: str | None) -> list[str]:
    return [part.strip().lstrip("@") for part in raw.split(",") if part.strip()] if raw else []


def _parse_json_object(raw: str | None, *, label: str) -> dict:
    if raw is None:
        return {}
    try:
        parsed = json_module.loads(raw)
    except json_module.JSONDecodeError as exc:
        typer.secho(f"  ⟫  --{label} is not valid JSON: {exc}", fg=typer.colors.RED)
        raise typer.Exit(2) from exc
    if not isinstance(parsed, dict):
        typer.secho(f"  ⟫  --{label} must be a JSON object", fg=typer.colors.RED)
        raise typer.Exit(2)
    return parsed


def _run_publish(
    config: MyceliumConfig, room: str, handle: str, payload: bytes, workspace: str | None
) -> None:
    asyncio.run(
        publish_once(
            api_url=config.server.api_url,
            node_endpoint=config.slim.node_endpoint,
            room=room,
            handle=handle,
            payload=payload,
            workspace=workspace or DEFAULT_WORKSPACE,
        )
    )


@l9_app.command("send")
def l9_send(
    ctx: typer.Context,
    room: str | None = typer.Option(None, "--room", "-r", help="Room (default: active room)"),
    as_handle: str = typer.Option(..., "--as", "--handle", help="Sender handle to publish as"),
    kind: str = typer.Option(..., "--kind", help=f"L9 kind ({', '.join(sorted(l9.VALID_KINDS))})"),
    subkind: str | None = typer.Option(None, "--subkind", help="L9 subkind (kind-specific)"),
    data: str | None = typer.Option(None, "--data", help="Payload data as a JSON object"),
    text: str = typer.Option("", "--text", help="Human-facing text body"),
    recipients: str | None = typer.Option(None, "--to", help="Comma-separated recipient handles"),
    episode: str | None = typer.Option(
        None, "--episode", help="Episode URN (default: the room's live episode)"
    ),
    parents: str | None = typer.Option(
        None, "--parents", help="Comma-separated parent message ids"
    ),
    payload_type: str = typer.Option("data", "--payload-type", help="L9 payload.type"),
    message_id: str | None = typer.Option(None, "--message-id", help="Explicit L9 message id"),
    workspace: str | None = typer.Option(
        None, "--workspace", help="SLIM workspace (default: the shared dev workspace)"
    ),
) -> None:
    """Publish a hand-crafted L9 envelope into a room as ``--as``, over the real SLIM wire.

    Built with the same envelope primitives every connector uses
    (``mycelium.slim.l9``), so the wire shape matches
    ``contracts/slim-l9-wire.json`` exactly. Kind/subkind are validated before
    anything touches the wire.

    Example:
        mycelium l9 send --room design --as @julia --kind commit --subkind resolved \\
            --data '{"assignments": {"cap": "30"}}'
    """
    try:
        l9.validate_kind(kind)
        l9.validate_subkind(kind, subkind)
    except l9.L9ValidationError as e:
        typer.secho(f"  ⟫  {e}", fg=typer.colors.RED)
        raise typer.Exit(2) from e

    payload_data = _parse_json_object(data, label="data")
    sender = as_handle.lstrip("@")

    try:
        config = MyceliumConfig.load()
        room_name = _resolve_room(config, room)
        episode_urn = episode or l9.room_episode(room_name)

        content = l9.build_envelope_content(
            kind=kind,
            subkind=subkind,
            sender=sender,
            recipients=_split_csv(recipients),
            episode=episode_urn,
            parents=_split_csv(parents),
            topic=l9.room_topic(room_name),
            text=text,
            message_id=message_id,
            payload_type=payload_type,
            payload_data=payload_data,
        )

        typer.secho(f"  ⚠  {_BANNER}", fg=typer.colors.YELLOW)
        _run_publish(config, room_name, sender, l9.serialize(content), workspace)
        label = f"{kind}:{subkind}" if subkind else kind
        typer.secho(f"  ⟫  @{sender} → {room_name}: {label}", fg=typer.colors.GREEN)
    except (typer.Exit, typer.Abort):
        raise
    except SlimError as e:
        typer.secho(f"  ⟫  {e}", fg=typer.colors.RED)
        raise typer.Exit(1) from e
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from e


@slim_app.command("send")
def slim_send(
    ctx: typer.Context,
    room: str | None = typer.Option(None, "--room", "-r", help="Room (default: active room)"),
    as_handle: str = typer.Option(..., "--as", "--handle", help="Sender handle to publish as"),
    text: str | None = typer.Option(None, "--text", help="Raw text payload"),
    json_payload: str | None = typer.Option(None, "--json", help="Raw JSON payload"),
    workspace: str | None = typer.Option(
        None, "--workspace", help="SLIM workspace (default: the shared dev workspace)"
    ),
) -> None:
    """Publish an arbitrary raw message onto a room's SLIM channel as ``--as``.

    No L9 semantics — the lowest-level escape hatch. Exercises the real channel:
    other SLIM members and the moderator see it, and the persister decides
    how/whether it surfaces.

    Example:
        mycelium slim send --room design --as @julia --text "hello channel"
    """
    if (text is None) == (json_payload is None):
        typer.secho("  ⟫  pass exactly one of --text or --json", fg=typer.colors.RED)
        raise typer.Exit(2)

    if json_payload is not None:
        try:
            json_module.loads(json_payload)
        except json_module.JSONDecodeError as e:
            typer.secho(f"  ⟫  --json is not valid JSON: {e}", fg=typer.colors.RED)
            raise typer.Exit(2) from e
        payload = json_payload.encode("utf-8")
    else:
        payload = (text or "").encode("utf-8")

    sender = as_handle.lstrip("@")

    try:
        config = MyceliumConfig.load()
        room_name = _resolve_room(config, room)

        typer.secho(f"  ⚠  {_BANNER}", fg=typer.colors.YELLOW)
        _run_publish(config, room_name, sender, payload, workspace)
        typer.secho(
            f"  ⟫  @{sender} → {room_name}: raw SLIM message published", fg=typer.colors.GREEN
        )
    except (typer.Exit, typer.Abort):
        raise
    except SlimError as e:
        typer.secho(f"  ⟫  {e}", fg=typer.colors.RED)
        raise typer.Exit(1) from e
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from e
