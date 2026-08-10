# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``await`` / ``respond`` — first-class SLIM participation for awake callers.

Being a *participant* in a room — a SLIM channel member that receives
coordination and replies — is a plain foreground primitive, not something only
the daemon can do. An already-awake caller (a Claude Code session, a subagent, a
shell script) coordinates by looping:

    mycelium await   --room R --handle me --json   # blocks until addressed
    # … the caller reasons …
    mycelium respond --room R --handle me "my position, moving toward 30% …"

``await`` joins the room's SLIM group as ``--handle``, blocks until a message
addressed to that handle arrives (a mediator tick or an ``@``-mention), prints it,
and exits — genuine membership for the duration, so the aligner sees the caller in
``members(room)``. ``respond`` publishes the caller's reply as an L9 ``exchange``
parented on the awaited message, which the aligner records as a position.

Both sit on the shared member-session core (:mod:`mycelium.slim.member`), the same
one the daemon runs in the background — so the CLI path and the daemon path can't
drift. Because the two commands are separate processes, ``await`` records the
message it surfaced to a small per-``(room, handle)`` file so ``respond`` can
thread its reply onto it without the caller having to carry any state.
"""

from __future__ import annotations

import asyncio
import contextlib
import json as json_module
import os
import sys
import time
from pathlib import Path

import typer

from mycelium.commands.room import _resolve_room
from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref
from mycelium.error_handler import print_error
from mycelium.filesystem import get_mycelium_dir
from mycelium.slim import l9
from mycelium.slim.member import (
    MemberSession,
    await_addressed,
    build_reply,
    publish_reply,
    should_wake,
)

# ── Streaming-await state (a held membership across rounds) ───────────────────
# `await --stream` holds ONE membership for the whole negotiation (so the caller
# stays in the aligner's roster and never churns) and drains an outbox that
# `respond` writes to — so a reply goes out on the *held* session, not a fresh
# connection. State lives per `(room, handle)` under the mycelium dir.


def _stream_dir(room: str, handle: str) -> Path:
    return get_mycelium_dir() / "await" / room / handle


def _pidfile(room: str, handle: str) -> Path:
    return _stream_dir(room, handle) / "stream.pid"


def _outbox_dir(room: str, handle: str) -> Path:
    return _stream_dir(room, handle) / "outbox"


def _stream_alive(room: str, handle: str) -> bool:
    """True if a `await --stream` process for this (room, handle) is running."""
    pid_path = _pidfile(room, handle)
    try:
        pid = int(pid_path.read_text())
    except (OSError, ValueError):
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _await_state_path(room: str, handle: str):
    """The file where ``await`` records the message it surfaced for ``respond``."""
    return get_mycelium_dir() / "await" / room / f"{handle}.json"


def _save_awaited(room: str, handle: str, content: dict) -> None:
    path = _await_state_path(room, handle)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json_module.dumps(content))


def _load_awaited(room: str, handle: str) -> dict | None:
    path = _await_state_path(room, handle)
    if not path.exists():
        return None
    try:
        loaded = json_module.loads(path.read_text())
    except (OSError, json_module.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _describe(room: str, handle: str, content: dict) -> dict:
    """The machine-readable view of an awaited message."""
    return {
        "room": room,
        "handle": handle,
        "prompt": l9.human_text_of(content),
        "sender": l9.sender_of(content),
        "episode": l9.episode_of(content),
        "topic": l9.topic_of(content),
        "message_id": l9.message_id_of(content),
    }


async def _run_stream(config: MyceliumConfig, room: str, handle: str) -> None:
    """Hold ONE membership for the whole negotiation, emitting each addressed
    message as an NDJSON line and publishing any reply ``respond`` drops.

    This is the robust multi-round primitive: the caller stays in the aligner's
    roster continuously (no per-turn churn, no missed tick between an old
    ``await`` and the next), and replies go out on the *held* session. Run it in
    the background; a following ``respond`` writes to the outbox this drains.
    """
    outbox = _outbox_dir(room, handle)
    outbox.mkdir(parents=True, exist_ok=True)
    _pidfile(room, handle).parent.mkdir(parents=True, exist_ok=True)
    _pidfile(room, handle).write_text(str(os.getpid()))
    stopping = asyncio.Event()
    session = MemberSession(config, room, handle, stopping=stopping)
    # The most recent addressed tick — replies parent on it so they land in the
    # right episode. A mutable holder so the drain task sees updates.
    last: dict[str, dict] = {"woke": {}}

    async def _drain() -> None:
        while not stopping.is_set():
            for f in sorted(outbox.glob("*.json")):
                try:
                    text = json_module.loads(f.read_text()).get("text", "")
                except (OSError, json_module.JSONDecodeError):
                    f.unlink(missing_ok=True)
                    continue
                reply = build_reply(handle=handle, room=room, woke=last["woke"], text=text)
                try:
                    await session.publish(reply)
                except Exception:  # noqa: BLE001 - session mid-reconnect; retry next tick
                    break  # leave the file; drain it once the session is live again
                f.unlink(missing_ok=True)
            await asyncio.sleep(0.3)

    drain_task = asyncio.create_task(_drain())
    try:
        async for content in session.messages():
            if not should_wake(content, handle):
                continue
            last["woke"] = content
            typer.echo(json_module.dumps(_describe(room, handle, content)))
            sys.stdout.flush()
    finally:
        stopping.set()
        drain_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await drain_task
        await session.aclose()
        _pidfile(room, handle).unlink(missing_ok=True)


@doc_ref(
    usage="mycelium await --room <room> --handle <handle> [--stream] [--timeout N] [--json]",
    desc="Join a room as a SLIM member and block until a message is addressed to the handle.",
    group="other",
)
def await_room(
    ctx: typer.Context,
    room: str | None = typer.Option(None, "--room", "-r", help="Room (default: active room)"),
    handle: str = typer.Option(..., "--handle", help="Handle to join and listen as"),
    timeout: int = typer.Option(
        0, "--timeout", "-t", help="Seconds to wait before giving up (0 = wait indefinitely)"
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit the message as JSON for agents"),
    stream: bool = typer.Option(
        False,
        "--stream",
        help="Hold membership across rounds, emitting each addressed message as an "
        "NDJSON line (run in the background; `respond` publishes on the held session).",
    ),
) -> None:
    """Join a room's channel and wait for a message addressed to the handle.

    Blocks until a mediator tick or an @handle mention arrives, prints it, and
    exits. The surfaced message is recorded so a following `mycelium respond`
    threads its reply onto it. On timeout, exits without a message.

    Examples:
        mycelium await --room design --handle me
        mycelium await --room design --handle me --json --timeout 300
    """
    try:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False  # noqa: F841
        config = MyceliumConfig.load()
        room_name = _resolve_room(config, room)
        if stream:
            # Long-lived: hold membership and emit every addressed message until
            # interrupted. Meant to run in the background while the caller loops
            # read-tick → reason → `mycelium respond`.
            asyncio.run(_run_stream(config, room_name, handle))
            return
        content = asyncio.run(await_addressed(config, room_name, handle, timeout_s=timeout or None))
        if content is None:
            if json_output:
                typer.echo(
                    json_module.dumps({"room": room_name, "handle": handle, "message": None})
                )
            else:
                typer.secho(f"  ⟫  no message for @{handle} within timeout", fg=typer.colors.YELLOW)
            raise typer.Exit(1)
        _save_awaited(room_name, handle, content)
        if json_output:
            typer.echo(json_module.dumps(_describe(room_name, handle, content)))
        else:
            info = _describe(room_name, handle, content)
            sender = info["sender"] or "?"
            typer.secho(f"  ⟫  {sender} → @{handle}:", fg=typer.colors.CYAN)
            typer.echo(info["prompt"])
    except typer.Exit:
        raise
    except KeyboardInterrupt:
        typer.echo("\n  [Stopped]")
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from e


@doc_ref(
    usage='mycelium respond --room <room> --handle <handle> "<text>"',
    desc="Publish an L9 exchange reply as the handle, parented on the last awaited message.",
    group="other",
)
def respond(
    ctx: typer.Context,
    text: str = typer.Argument(..., help="The reply / position text to publish"),
    room: str | None = typer.Option(None, "--room", "-r", help="Room (default: active room)"),
    handle: str = typer.Option(..., "--handle", help="Handle to publish the reply as"),
    json_output: bool = typer.Option(False, "--json", help="Emit the result as JSON for agents"),
) -> None:
    """Publish the caller's reply as an L9 exchange for the handle.

    By default the reply is threaded onto the message the last `mycelium await`
    surfaced for this room and handle — so the aligner records it as a position in
    the right episode. A position marker may be appended to the text (e.g.
    `[[mycelium: confidence=0.85 stance=accept]]`); it is lifted onto the L9
    payload and stripped from the posted prose.

    Examples:
        mycelium respond --room design --handle me "I can move to 30% if timeline slips."
    """
    try:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False  # noqa: F841
        config = MyceliumConfig.load()
        room_name = _resolve_room(config, room)
        # If a `await --stream` is holding membership for this handle, hand the
        # reply to it (published on the held session — no fresh connection, no
        # membership churn). Otherwise fall back to a one-shot join+publish.
        if _stream_alive(room_name, handle):
            outbox = _outbox_dir(room_name, handle)
            outbox.mkdir(parents=True, exist_ok=True)
            (outbox / f"{time.time_ns()}.json").write_text(json_module.dumps({"text": text}))
            if json_output:
                typer.echo(json_module.dumps({"room": room_name, "handle": handle, "queued": True}))
            else:
                typer.secho(f"  ⟫  @{handle} reply queued (streamed)", fg=typer.colors.GREEN)
            return
        woke = _load_awaited(room_name, handle) or {}
        reply = build_reply(handle=handle, room=room_name, woke=woke, text=text)
        asyncio.run(publish_reply(config, room_name, handle, reply))
        if json_output:
            typer.echo(
                json_module.dumps(
                    {
                        "room": room_name,
                        "handle": handle,
                        "message_id": l9.message_id_of(reply),
                        "parents": reply["l9"]["header"]["message"]["parents"],
                    }
                )
            )
        else:
            typer.secho(f"  ⟫  @{handle} replied in {room_name}", fg=typer.colors.GREEN)
    except KeyboardInterrupt:
        typer.echo("\n  [Stopped]")
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from e
