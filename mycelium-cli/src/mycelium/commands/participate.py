# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``await`` / ``respond``: first-class participation for awake callers.

Being a participant in a room (receiving coordination and replying) is two
plain, **stateless** HTTP calls. The backend holds the caller's membership
server-side (a presence lease) and uses the durable transcript as the delivery
queue, so the caller never holds a SLIM socket between turns:

    mycelium await   --room R --handle me --json   # long-poll: blocks until addressed
    # … the caller reasons …
    mycelium respond --room R --handle me "my position, moving toward 30% …"

``await`` long-polls until the next message addressed to the handle (an
engine's turn or an ``@``-mention) is served past a persistent per-handle cursor,
so a turn is never missed between one await and the next. ``respond`` posts the
reply, which the backend records as an ``exchange`` message.

No SLIM connection, no background process, no compound shell, which is exactly
what a headless / allowlisted agent (a Claude Code session, a subagent) can safely
issue. This is the whole agent-side participation surface: a resident runtime loops
``await`` → reason → ``respond`` (see ``await --loop``) to stay woken.
"""

from __future__ import annotations

import json as json_module
import os
import subprocess
from pathlib import Path
from typing import Any

import httpx
import typer

from mycelium import chat
from mycelium.cli_options import ACT_FLAGS, ACT_HELP, acts_as, emits_json, in_room, resolve_handle
from mycelium.client import answered, sent_unparsed, typed_client
from mycelium.commands.room import _resolve_room
from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref
from mycelium.error_handler import print_error
from mycelium.exceptions import MyceliumError
from mycelium.names import name_of
from mycelium.text_input import takes_text
from mycelium_backend_client.errors import UnexpectedStatus
from mycelium_backend_client.models import (
    AssignmentsRenewed,
    AssignmentWatchRead,
    AwaitAskRead,
    AwaitDeliveredRead,
    AwaitTurn,
    ConfirmBody,
    RenewBody,
    ReplyBody,
    ReplyRead,
)
from mycelium_backend_client.types import UNSET

#: Statuses a resident loop stops on: the hub rejected the caller's identity
#: (401) or refused it this handle (403). Everything else is treated as a blip.
_TERMINAL_STATUSES = frozenset({401, 403})
#: ``await``'s exit code when the hub refuses who it is waiting as. 0 is a
#: turn, 1 nothing within ``--timeout`` (or an error worth waiting again on).
EXIT_REFUSED = 3


#: The longest one request waits on the hub. Proxies cut a request that sends
#: nothing for a while (nginx's default is 60 seconds), so a long wait is made
#: of short ones, each picking up where the last left off.
WAIT_CHUNK_S = 45
#: What a proxy answers when it gave up on the hub, rather than the hub refusing.
_PROXY_STATUSES = frozenset({502, 503, 504})
#: Errors the generated client raises while reading an answer it can't take.
_UNREADABLE = (ValueError, KeyError, TypeError)


class _NotTheHub(Exception):
    """An answer that isn't JSON at all: a proxy's page, on a status the route
    declares, so the generated client fails reading it rather than handing it
    back as that status. Waited again, like a proxy's 502."""


def _status(e: BaseException) -> int | None:
    """The status a refused hub call came back with, or ``None`` for any other error."""
    return e.status_code if isinstance(e, UnexpectedStatus) else None


#: A connection that dropped mid-wait, which means waiting again.
_DROPPED = (httpx.RemoteProtocolError, httpx.ReadError, httpx.ReadTimeout)


def _await_once(
    config: MyceliumConfig,
    room_name: str,
    handle: str,
    timeout: int,
    episode: str | None = None,
) -> AwaitTurn | None:
    """Wait up to ``timeout`` seconds (0 = for good) for a turn. Returns the
    turn, or ``None`` on timeout.

    The wait is made of requests of at most :data:`WAIT_CHUNK_S`, and one
    that drops (a proxy's idle limit) is waited again, so neither ends the
    wait early. Each asks the hub to keep what it hands over unread until
    it is confirmed (``confirm``), and the turn is confirmed once it is
    here: a response lost on the way is handed over again, not lost. A hub
    from before that marks it read itself and asks for no confirmation.
    """
    import time

    deadline = time.monotonic() + timeout if timeout > 0 else None
    while True:
        left = WAIT_CHUNK_S if deadline is None else int(deadline - time.monotonic())
        if left <= 0:
            return None
        wait = min(left, WAIT_CHUNK_S)
        started = time.monotonic()
        try:
            data = _await_request(config, room_name, handle, wait, episode)
        except (*_DROPPED, _NotTheHub):
            data = None
        except UnexpectedStatus as e:
            if e.status_code not in _PROXY_STATUSES:
                raise
            data = None
        if data is not None:
            _confirm(config, room_name, handle, data)
            return data
        # Back well before its wait was up (a drop, a proxy, a hub with no
        # channel for the room): pause, so waiting again never spins.
        if time.monotonic() - started < wait - 1:
            time.sleep(1.0)


def _await_request(
    config: MyceliumConfig, room_name: str, handle: str, wait: int, episode: str | None
) -> AwaitTurn | None:
    """One long-poll of up to ``wait`` seconds: the turn, or ``None``."""
    from mycelium_backend_client.api.participate import (
        await_message_api_rooms_room_name_await_get as await_api,
    )

    key = _pending_key(config, room_name, handle, episode)
    owed = _pending().get(key)
    timeout = float(wait) + 15.0
    with typed_client(
        config, timeout=timeout, handle=handle, raise_on_unexpected_status=False
    ) as client:
        try:
            resp = await_api.sync_detailed(
                room_name,
                client=client,
                handle=handle,
                timeout=wait,
                confirm=True,
                episode=episode or UNSET,
                confirmed=owed if owed is not None else UNSET,
            )
        except json_module.JSONDecodeError as e:
            raise _NotTheHub from e
        except _UNREADABLE as e:
            # The hub's own JSON, in a shape this CLI doesn't know: waiting again
            # would be handed the same turn, unconfirmed, for as long as it runs.
            raise MyceliumError(_mismatch(config)) from e
    if resp.status_code >= 400:  # noqa: PLR2004
        raise UnexpectedStatus(resp.status_code, resp.content)
    if owed is not None:
        _set_pending(key, None)
    return resp.parsed if isinstance(resp.parsed, AwaitTurn) else None


def _mismatch(config: MyceliumConfig) -> str:
    """Why ``await`` stopped on an answer it can't read, with both versions."""
    from mycelium import __version__
    from mycelium.hub_check import health

    hub = health(config.server.api_url).version or "unknown"
    return (
        f"the hub's answer to await doesn't match this CLI (hub {hub}, CLI {__version__}). "
        "Update whichever is older."
    )


def _confirm(config: MyceliumConfig, room_name: str, handle: str, turn: AwaitTurn) -> None:
    """Tell the hub ``turn`` arrived, so it marks it read. If that fails, the
    position is kept on this machine and sent with the next ``await``, which
    confirms it there: the turn may be shown twice, never over and over."""
    from mycelium_backend_client.api.participate import (
        confirm_delivery_api_rooms_room_name_await_confirm_post as confirm_api,
    )

    delivered = turn.delivered
    if not isinstance(delivered, AwaitDeliveredRead):
        return
    body = ConfirmBody(handle=handle, position=delivered.position, episode=delivered.episode)
    try:
        with typed_client(
            config, timeout=15, handle=handle, raise_on_unexpected_status=False
        ) as client:
            # Confirmed once the hub takes it; what it answers with isn't read,
            # so a hub a version apart doesn't make a landed confirm look lost.
            resp = sent_unparsed(confirm_api, client, room_name, body=body)
        if resp.status_code >= 400:  # noqa: PLR2004
            raise UnexpectedStatus(resp.status_code, resp.content)
    except (httpx.HTTPError, UnexpectedStatus):
        key = _pending_key(config, room_name, handle, delivered.episode or None)
        _set_pending(key, delivered.position)


def _pending_file() -> Path:
    """Where confirmations that didn't land wait for the next ``await``."""
    return MyceliumConfig.get_agent_state_dir() / "await-pending.json"


def _pending_key(config: MyceliumConfig, room: str, handle: str, episode: str | None) -> str:
    return "|".join([config.server.api_url.rstrip("/"), room, handle, episode or ""])


def _pending() -> dict[str, int]:
    try:
        data = json_module.loads(_pending_file().read_text())
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, int)} if isinstance(data, dict) else {}


def _set_pending(key: str, position: int | None) -> None:
    """Keep ``position`` owed for ``key`` (never lower than one already owed),
    or forget it with ``None``."""
    owed = _pending()
    if position is None:
        if owed.pop(key, None) is None:
            return
    else:
        owed[key] = max(position, owed.get(key, 0))
    try:
        path = _pending_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json_module.dumps(owed))
    except OSError:
        pass  # not kept: the hub hands the turn over again, which is the old behavior


def _task_episode(room_name: str, row_id: str) -> str:
    """The thread inside a board row, resolved once.

    Resolved here rather than per poll: a resident loop that re-read the board
    every few seconds to answer a question whose answer cannot change (a task is
    bound to one thread for its life) would spend six hub reads a minute to
    learn the same URN.
    """
    from mycelium.commands.board import _thread

    return _thread(room_name, row_id)[1]


def _renew_assignments(config: MyceliumConfig, room_name: str, handle: str) -> list[str]:
    """Tell the hub this handle is still here, on behalf of every row it holds.

    This is what makes a claim a lease rather than a fact: the loop is the thing
    that keeps saying so, and when the loop stops — the container reclaimed, the
    session timed out — the claims drain on their own.  Quiet on the hub side: a
    lease still in its first half is left alone, and the writes it does make
    broadcast nothing.
    """
    from mycelium_backend_client.api.assignments import (
        renew_assignments_api_rooms_room_name_assignments_renew_post as renew_api,
    )

    with typed_client(config, timeout=15, handle=handle, raise_on_unexpected_status=False) as c:
        resp = renew_api.sync_detailed(room_name, client=c, body=RenewBody(handle=handle))
    return [row.key for row in answered(resp, AssignmentsRenewed).renewed]


def _await_lease(
    config: MyceliumConfig, room_name: str, key: str, since: str | None, timeout: int
) -> AssignmentWatchRead:
    """One long-poll on a lease's transitions."""
    from mycelium_backend_client.api.assignments import (
        await_assignment_api_rooms_room_name_assignments_await_get as watch_api,
    )

    client_timeout = float(timeout) + 15.0 if timeout > 0 else None
    with typed_client(config, timeout=client_timeout, raise_on_unexpected_status=False) as c:
        resp = watch_api.sync_detailed(
            room_name,
            client=c,
            key=key,
            timeout=timeout,
            since=since if since is not None else UNSET,
        )
    return answered(resp, AssignmentWatchRead)


def _print_lease(state: AssignmentWatchRead) -> None:
    holder = f"@{state.owner}" if state.owner else "nobody"
    line = f"  ⟫  {state.key}: {state.assignment} by {holder}"
    if note := state.assignment_note:
        line += f" — {note}"
    typer.secho(line, fg=typer.colors.CYAN)


def _lease_watch(
    config: MyceliumConfig,
    room_name: str,
    key: str,
    timeout: int,
    loop: bool,
    exec_cmd: str | None,
    json_output: bool,
) -> None:
    """Wake on one lease's transitions, and on nothing else.

    Awaiting the room's channel to follow a handoff is the wrong subscription: a
    dozen unrelated messages wake you for nothing.  The lease is already a state
    machine whose transitions are exactly what a handoff cares about, so it is
    the thing to subscribe to.

    The first read is orientation — the row's state comes straight back rather
    than blocking — because an agent does not need a push, it needs the row
    current the next time it exists.
    """
    since: str | None = None
    while True:
        state = _await_lease(config, room_name, key, since, timeout)
        since = state.since
        if json_output:
            typer.echo(json_module.dumps(state.to_dict()))
        else:
            _print_lease(state)
        if exec_cmd and state.changed:
            # A lease change carries no ask, so only the room and its key are said.
            _exec(exec_cmd, state.to_dict(), room_name, key, asks=1)
        if not loop:
            return


def _sender_name(turn: AwaitTurn) -> str | None:
    """The name the turn's sender gave themselves, so a person reads as
    themselves ("Julia Valenti") and not only as a handle."""
    return name_of(turn.sender) if turn.sender else None


def _as_json(turn: AwaitTurn) -> dict[str, Any]:
    """The turn as ``--json`` prints it and ``--exec`` reads it on stdin: the
    hub's own record, with ``sender_name`` added when the sender named themselves."""
    record = turn.to_dict()
    if name := _sender_name(turn):
        record["sender_name"] = name
    return record


def _sender_label(sender: str | None) -> str:
    """``Julia Valenti (@julia)``, or ``@julia`` when they have no name."""
    sender = sender or "?"
    name = name_of(sender) if sender != "?" else None
    return f"{name} (@{sender})" if name else f"@{sender}"


def _print_turn(turn: AwaitTurn, handle: str) -> None:
    """A turn as a person or an agent reads it: the hub's wake digest, the
    same text a herdr wake types, ready to hand to a model as its turn. A hub
    from before the digest gets what was said before it, then every message
    asking for the handle that this ``await`` handed over, each in a box
    (``chat.box``), oldest first, the turn last."""
    if isinstance(turn.digest, str) and turn.digest.strip():
        typer.echo(turn.digest)
        return
    if turn.earlier:
        typer.secho("  ⟫  earlier here:", fg=typer.colors.BRIGHT_BLACK)
        for e in turn.earlier:
            sender = e.sender or "?"
            name = name_of(sender) if sender != "?" else None
            who = f"{name} (@{sender})" if name else sender
            typer.echo(f"  {who}: {e.text}")
    asks = _asks_of(turn)
    if len(asks) > 1:
        typer.secho(
            f"  ⟫  {len(asks)} messages asking for @{handle}, oldest first; the last is the turn:",
            fg=typer.colors.BRIGHT_BLACK,
        )
    typer.echo("\n".join(f"  {line}" for line in _ask_boxes(asks, handle)))


def _asks_of(turn: AwaitTurn) -> list[AwaitAskRead | AwaitTurn]:
    """Every message an ``await`` handed over, oldest first, the turn last; a
    hub from before ``asks`` hands over the turn alone."""
    asks: list[AwaitAskRead | AwaitTurn] = [*(turn.asks or [])]
    if not asks:
        asks.append(turn)
    return asks


def _ask_boxes(asks: list[AwaitAskRead | AwaitTurn], handle: str) -> list[str]:
    """``asks``, each as a box (``chat.box``): who, where to reply, its id."""
    lines: list[str] = []
    for ask in asks:
        header = f"{_sender_label(ask.sender or None)} → @{handle}"
        if task := ask.task or None:
            header += f" · in task {task} (reply with --task {task})"
        if isinstance(ask, AwaitAskRead) and ask.id:
            header += f" · {ask.id[:8]}"
        lines += chat.box(header, ask.prompt)
    return lines


def _run_exec(exec_cmd: str, turn: AwaitTurn, room_name: str, handle: str) -> None:
    """Hand a turn to the resident runtime: run ``exec_cmd`` with the turn on stdin.

    The command is the user's own reasoning runtime (an Agent-SDK loop, a script,
    etc.); it is expected to reason and call ``mycelium respond`` itself. The turn
    JSON is piped to stdin and the salient fields are exported as env vars for
    convenience. Run through the shell so the user can compose freely; this is a
    resident runner the user starts, not an allowlisted-subagent surface.

    One ``await`` hands over every unread message asking for the handle. With
    one, ``MYCELIUM_PROMPT`` is its text; with several it is all of them, each
    in a box, oldest first, so a script that reads only the prompt still reads
    every ask (``MYCELIUM_ASKS`` says how many; stdin has them under ``asks``).
    """
    asks = _asks_of(turn)
    _exec(
        exec_cmd,
        _as_json(turn),
        room_name,
        handle,
        asks=len(asks),
        sender=turn.sender or "",
        sender_name=_sender_name(turn) or "",
        prompt=turn.prompt if len(asks) == 1 else "\n".join(_ask_boxes(asks, handle)),
        # What plain ``await`` prints: the wake digest, to hand a model as is.
        digest=turn.digest or "",
        # The row the turn was asked in, empty for the room: ``respond --task``.
        task=turn.task or "",
    )


def _exec(
    exec_cmd: str,
    stdin: dict[str, Any],
    room_name: str,
    handle: str,
    *,
    asks: int,
    sender: str = "",
    sender_name: str = "",
    prompt: str = "",
    digest: str = "",
    task: str = "",
) -> None:
    """Run ``exec_cmd`` with ``stdin`` as JSON and the salient fields in its environment."""
    env = {
        **os.environ,
        "MYCELIUM_ROOM": room_name,
        "MYCELIUM_HANDLE": handle,
        "MYCELIUM_SENDER": sender,
        "MYCELIUM_SENDER_NAME": sender_name,
        "MYCELIUM_PROMPT": prompt,
        "MYCELIUM_ASKS": str(asks),
        "MYCELIUM_DIGEST": digest,
        "MYCELIUM_TASK": task,
    }
    subprocess.run(  # noqa: S602 - user-supplied command, turn passed via stdin (no injection)
        exec_cmd,
        shell=True,
        env=env,
        input=json_module.dumps(stdin),
        text=True,
        check=False,
    )


@doc_ref(
    usage="mycelium await --room <room> [--handle <handle> | --lease <key>] [--task <id>] [--loop] [--exec CMD] [--timeout N] [--json]",
    desc="Long-poll a room until a message is addressed to the handle — or until a named lease changes hands.",
    group="other",
)
@in_room()
@emits_json("json_output")
def await_room(
    ctx: typer.Context,
    room: str | None = None,
    handle: str | None = typer.Option(None, *ACT_FLAGS, help=ACT_HELP),
    lease: str | None = typer.Option(
        None,
        "--lease",
        help="Wake on this lease's transitions instead of on messages (e.g. work/auth-spike)",
    ),
    task: str | None = typer.Option(
        None,
        "--task",
        "-u",
        help="Wake only on one board row's thread (e.g. t3, work/auth) instead of the whole room",
    ),
    timeout: int = typer.Option(
        0, "--timeout", "-t", help="Seconds to wait before giving up (0 = wait indefinitely)"
    ),
    loop: bool = typer.Option(
        False,
        "--loop",
        help="Stay resident: keep re-awaiting after each turn instead of exiting.",
    ),
    exec_cmd: str | None = typer.Option(
        None,
        "--exec",
        help=(
            "With --loop: run this command per turn (turn JSON on stdin); it should call "
            "`respond`. A turn carries every unread ask: $MYCELIUM_PROMPT holds them all, boxed, "
            "when there are several."
        ),
    ),
    json_output: bool = False,
) -> None:
    """Block until a message addressed to the handle arrives, print it, and exit.

    A stateless long-poll against the backend: the caller is a server-held
    room member for the purpose of the room's roster, without holding any
    connection. It prints the wake message, the same text a herdr wake types,
    ready to hand to a model as its turn (``--json`` for scripts). It exits 0
    with a turn, 1 with none within ``--timeout`` (or on an error), and 3 when
    the hub refuses the handle. A dropped connection is waited again, and a
    message counts as read only once it arrived.

    With ``--loop`` it becomes a **resident runner**: it re-awaits after every turn,
    so the handle stays present (its lease refreshes each poll) and never misses a
    tick. Pair with ``--exec`` to drive a reasoning runtime per turn; the command
    receives the turn JSON on stdin and is expected to call ``mycelium respond``.
    This is the supported way to keep a turn-based agent (Claude Code, Cursor) woken
    without writing your own service.

    With ``--task`` it narrows the wake to one board row's thread: the handle is
    woken only when that task moves, and mentions of it elsewhere in the room
    keep their place in its own queue rather than being consumed. Only the wake
    narrows — the presence lease stays room-scoped, because a member of a thread
    is a member of the room.

    With ``--lease`` it waits on one row's assignment instead: claimed, lapsed,
    released, resolved. That is a different subscription on purpose — waking on
    channel traffic to follow a handoff means a dozen unrelated messages wake you
    for nothing, while a lease's transitions are exactly the events a handoff is
    about. The first read returns the row's current state rather than blocking,
    so a fresh session orients before it waits.

    Examples:
        mycelium await --room design --handle me
        mycelium await --room design --handle me --json --timeout 120
        mycelium await --room design --handle bot --loop --exec ./drive-agent.sh
        mycelium await --room design --handle me --task t3 --loop
        mycelium await --room design --lease work/auth-spike --loop
    """
    try:
        config = MyceliumConfig.load()
        room_name = _resolve_room(config, room)

        if lease:
            _lease_watch(config, room_name, lease, timeout, loop, exec_cmd, json_output)
            return

        # Resolved here rather than by `acts_as`, because a lease watch needs no
        # handle. A turn does: with nothing to say who is waiting, it errors
        # rather than waiting as a placeholder.
        handle = resolve_handle(config, handle, fallback=None)

        # Resolved before the first poll, so a row id that names nothing is
        # refused now rather than after an hour of waiting on a thread that
        # was never going to speak.
        episode = _task_episode(room_name, task) if task else None

        if loop:
            _await_loop(config, room_name, handle, timeout, exec_cmd, json_output, episode)
            return

        if exec_cmd:
            typer.secho("  ⟫  --exec requires --loop", fg=typer.colors.RED)
            raise typer.Exit(2)

        data = _await_once(config, room_name, handle, timeout, episode)
        if data is None:  # timed out; backend returned {"message": null}
            if json_output:
                typer.echo(
                    json_module.dumps({"room": room_name, "handle": handle, "message": None})
                )
            else:
                typer.secho(f"  ⟫  no message for @{handle} within timeout", fg=typer.colors.YELLOW)
            raise typer.Exit(1)
        if json_output:
            typer.echo(json_module.dumps(_as_json(data)))
        else:
            _print_turn(data, handle)
    except typer.Exit:
        raise
    except KeyboardInterrupt:
        typer.echo("\n  [Stopped]")
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        # A refused identity gets its own code, so a harness that waits again
        # on anything else stops on this one: waiting again can't fix it.
        refused = _status(e) in _TERMINAL_STATUSES
        code = EXIT_REFUSED if refused else 1
        print_error(e, verbose=verbose, exit_code=code)
        raise typer.Exit(code) from e


def _await_loop(
    config: MyceliumConfig,
    room_name: str,
    handle: str,
    timeout: int,
    exec_cmd: str | None,
    json_output: bool,
    episode: str | None = None,
) -> None:
    """Resident-runner loop: re-await forever, dispatching each turn.

    A timeout is not terminal here; it just means "nothing yet," so we re-await
    (keeping the presence lease warm). Ctrl-C is the clean stop. Errors on a single
    poll are surfaced and the loop backs off briefly rather than dying, so a blip in
    the backend doesn't drop the agent out of the room. A rejected identity is the
    exception: retrying can't earn a credential, so 401/403 ends the loop.
    """
    import time

    if not json_output:
        typer.secho(
            f"  ⟫  @{handle} resident in {room_name}"
            + (f" thread {episode.rsplit(':', 1)[-1]}" if episode else "")
            + ", awaiting"
            + (f", driving `{exec_cmd}` per turn" if exec_cmd else "")
            + " (Ctrl-C to stop)",
            fg=typer.colors.CYAN,
        )
    while True:
        try:
            # Before waiting again, say we are still here. A resident agent's
            # claims are kept alive by the same loop that keeps it woken, so
            # residency and assignment stop being two things to remember.
            renewed = _renew_assignments(config, room_name, handle)
            if renewed and not json_output:
                typer.secho(f"  ⟫  renewed {', '.join(renewed)}", fg=typer.colors.BLUE)
        except Exception as e:  # noqa: BLE001 - a lease blip must not drop residency
            typer.secho(f"  ⟫  renew error: {e}; continuing", fg=typer.colors.YELLOW)
        try:
            data = _await_once(config, room_name, handle, timeout, episode)
        except KeyboardInterrupt:
            typer.echo("\n  [Stopped]")
            return
        except UnexpectedStatus as e:
            if e.status_code not in _TERMINAL_STATUSES:
                typer.secho(f"  ⟫  await error: {e}; retrying…", fg=typer.colors.YELLOW)
                time.sleep(2.0)
                continue
            # A refused identity is not a blip; no amount of re-polling turns a
            # wrong or ungranted credential into an accepted one, and a resident
            # loop that kept trying would hammer the hub for as long as it ran.
            print_error(e)
        except MyceliumError as e:
            # The hub and this CLI disagree on what a turn is: waiting again
            # would be handed the same unreadable turn for as long as it ran.
            print_error(e)
        except Exception as e:  # noqa: BLE001 - a poll blip must not drop residency
            typer.secho(f"  ⟫  await error: {e}; retrying…", fg=typer.colors.YELLOW)
            time.sleep(2.0)
            continue
        if data is None:
            continue  # timeout → nothing addressed yet; re-await, lease stays warm
        try:
            if json_output:
                typer.echo(json_module.dumps(_as_json(data)))
            else:
                _print_turn(data, handle)
            if exec_cmd:
                _run_exec(exec_cmd, data, room_name, handle)
        except KeyboardInterrupt:
            typer.echo("\n  [Stopped]")
            return


@doc_ref(
    usage='mycelium respond --room <room> --handle <handle> [--task <id>] "<text>" | --body "<markdown>" | --file <path>',
    desc="Publish a reply as the handle, in the room or in one task's thread. The reply is markdown: give it as the argument, <code>--body</code>, or <code>--file</code> (<code>-</code> reads stdin).",
    group="other",
)
@takes_text("text", "The reply, in markdown.", noun="reply")
@in_room()
@acts_as(fallback=None)
@emits_json("json_output")
def respond(
    ctx: typer.Context,
    text: str = typer.Argument(..., help="The reply / position text to publish"),
    room: str | None = None,
    handle: str | None = None,
    task: str | None = typer.Option(
        None,
        "--task",
        "-u",
        help="Reply into one board row's thread (e.g. t3, work/auth); without it the reply lands in the room",
    ),
    json_output: bool = False,
) -> None:
    """Publish the caller's reply, in the room or in one task's thread.

    A marker may be appended to the text (e.g. `[[mycelium: stance=accept]]`);
    the backend lifts it onto the payload so a conductor flow can read it, and
    strips it from the posted prose.

    Where a reply lands is the flags, never a guess: with ``--task`` it lands in
    that row's thread, without it in the room. To answer a turn asked in a task's
    thread, name the task ``await`` reported for it. A reply that lands somewhere
    other than the turn that woke you was asked is not an answer to it, so its
    causal edge back to that turn is dropped.

    Examples:
        mycelium respond --room design --handle me "I can move to 30% if the timeline slips."
        mycelium respond --room design --handle me --task t3 "claiming this; starting on the schema."
        mycelium respond --room design --handle me --body "Two options:

        - ship today, refunds manual
        - wait a day for automatic refunds"
        mycelium respond --room design --handle me --file reply.md
    """
    try:
        config = MyceliumConfig.load()
        room_name = _resolve_room(config, room)
        from mycelium_backend_client.api.participate import (
            post_reply_api_rooms_room_name_reply_post as reply_api,
        )

        body = ReplyBody(
            handle=handle or "",
            text=text,
            episode=_task_episode(room_name, task) if task else UNSET,
        )
        with typed_client(
            config, timeout=30.0, handle=handle, raise_on_unexpected_status=False
        ) as client:
            replied = answered(
                reply_api.sync_detailed(room_name, client=client, body=body), ReplyRead
            )
        if json_output:
            typer.echo(json_module.dumps(replied.to_dict()))
        else:
            where = f"{room_name}/{task}" if task else room_name
            typer.secho(f"  ⟫  @{handle} replied in {where}", fg=typer.colors.GREEN)
    except KeyboardInterrupt:
        typer.echo("\n  [Stopped]")
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from e
