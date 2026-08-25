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

``await`` long-polls until the next message addressed to the handle (a mediator
tick or an ``@``-mention) is served past a persistent per-handle cursor, so a tick
is never missed between one await and the next. ``respond`` posts the reply, which
the backend records as an L9 ``exchange`` the aligner scores as a position.

No SLIM connection, no background process, no compound shell, which is exactly
what a headless / allowlisted agent (a Claude Code session, a subagent) can safely
issue. This is the whole agent-side participation surface: a resident runtime loops
``await`` → reason → ``respond`` (see ``await --loop``) to stay woken.
"""

from __future__ import annotations

import json as json_module
import os
import subprocess

import httpx
import typer

from mycelium.client import hub_client
from mycelium.commands.room import _resolve_room
from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref
from mycelium.error_handler import print_error

#: Statuses a resident loop stops on: the hub rejected the caller's identity
#: (401) or refused it this handle (403). Everything else is treated as a blip.
_TERMINAL_STATUSES = frozenset({401, 403})


def _await_once(
    config: MyceliumConfig,
    room_name: str,
    handle: str,
    timeout: int,
    episode: str | None = None,
) -> dict | None:
    """One long-poll. Returns the turn dict, or ``None`` on timeout."""
    path = f"/api/rooms/{room_name}/await"
    # The server blocks up to `timeout`; give the client a little more headroom
    # (or no cap when waiting indefinitely).
    client_timeout = float(timeout) + 15.0 if timeout > 0 else None
    params: dict[str, str | int] = {"handle": handle, "timeout": timeout}
    if episode:
        params["episode"] = episode
    with hub_client(config, timeout=client_timeout, handle=handle) as client:
        resp = client.get(path, params=params)
    resp.raise_for_status()
    data = resp.json()
    return data if "prompt" in data else None


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
    with hub_client(config, timeout=15, handle=handle) as client:
        resp = client.post(f"/api/rooms/{room_name}/assignments/renew", json={"handle": handle})
    resp.raise_for_status()
    return [row.get("key", "") for row in resp.json().get("renewed", [])]


def _await_lease(
    config: MyceliumConfig, room_name: str, key: str, since: str | None, timeout: int
) -> dict:
    """One long-poll on a lease's transitions."""
    client_timeout = float(timeout) + 15.0 if timeout > 0 else None
    params: dict[str, str | int] = {"key": key, "timeout": timeout}
    if since is not None:
        params["since"] = since
    with hub_client(config, timeout=client_timeout) as client:
        resp = client.get(f"/api/rooms/{room_name}/assignments/await", params=params)
    resp.raise_for_status()
    return resp.json()


def _print_lease(state: dict) -> None:
    holder = f"@{state['owner']}" if state.get("owner") else "nobody"
    line = f"  ⟫  {state.get('key')}: {state.get('assignment')} by {holder}"
    if note := state.get("assignment_note"):
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
        since = state.get("since")
        if json_output:
            typer.echo(json_module.dumps(state))
        else:
            _print_lease(state)
        if exec_cmd and state.get("changed"):
            _run_exec(exec_cmd, state, room_name, key)
        if not loop:
            return


def _run_exec(exec_cmd: str, turn: dict, room_name: str, handle: str) -> None:
    """Hand a turn to the resident runtime: run ``exec_cmd`` with the turn on stdin.

    The command is the user's own reasoning runtime (an Agent-SDK loop, a script,
    etc.); it is expected to reason and call ``mycelium respond`` itself. The turn
    JSON is piped to stdin and the salient fields are exported as env vars for
    convenience. Run through the shell so the user can compose freely; this is a
    resident runner the user starts, not an allowlisted-subagent surface.
    """
    env = {
        **os.environ,
        "MYCELIUM_ROOM": room_name,
        "MYCELIUM_HANDLE": handle,
        "MYCELIUM_SENDER": str(turn.get("sender") or ""),
        "MYCELIUM_PROMPT": str(turn.get("prompt") or ""),
    }
    subprocess.run(  # noqa: S602 - user-supplied command, turn passed via stdin (no injection)
        exec_cmd,
        shell=True,
        env=env,
        input=json_module.dumps(turn),
        text=True,
        check=False,
    )


@doc_ref(
    usage="mycelium await --room <room> [--handle <handle> | --lease <key>] [--task <id>] [--loop] [--exec CMD] [--timeout N] [--json]",
    desc="Long-poll a room until a message is addressed to the handle — or until a named lease changes hands.",
    group="other",
)
def await_room(
    ctx: typer.Context,
    room: str | None = typer.Option(None, "--room", "-r", help="Room (default: active room)"),
    handle: str = typer.Option("", "--handle", help="Handle to participate as"),
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
        help="With --loop: run this command per turn (turn JSON on stdin); it should call `respond`.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit the message as JSON for agents"),
) -> None:
    """Block until a message addressed to the handle arrives, print it, and exit.

    A single stateless long-poll against the backend: the caller is a server-held
    room member for the purpose of the aligner's roster, without holding any
    connection. On timeout, exits non-zero with no message.

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

        if not handle:
            typer.secho("  ⟫  await needs --handle (or --lease <key>)", fg=typer.colors.RED)
            raise typer.Exit(2)

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
            typer.echo(json_module.dumps(data))
        else:
            typer.secho(f"  ⟫  {data.get('sender') or '?'} → @{handle}:", fg=typer.colors.CYAN)
            typer.echo(data.get("prompt") or "")
    except typer.Exit:
        raise
    except KeyboardInterrupt:
        typer.echo("\n  [Stopped]")
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from e


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
        except httpx.HTTPStatusError as e:
            if e.response.status_code not in _TERMINAL_STATUSES:
                typer.secho(f"  ⟫  await error: {e}; retrying…", fg=typer.colors.YELLOW)
                time.sleep(2.0)
                continue
            # A refused identity is not a blip; no amount of re-polling turns a
            # wrong or ungranted credential into an accepted one, and a resident
            # loop that kept trying would hammer the hub for as long as it ran.
            print_error(e)
        except Exception as e:  # noqa: BLE001 - a poll blip must not drop residency
            typer.secho(f"  ⟫  await error: {e}; retrying…", fg=typer.colors.YELLOW)
            time.sleep(2.0)
            continue
        if data is None:
            continue  # timeout → nothing addressed yet; re-await, lease stays warm
        try:
            if json_output:
                typer.echo(json_module.dumps(data))
            else:
                typer.secho(f"  ⟫  {data.get('sender') or '?'} → @{handle}:", fg=typer.colors.CYAN)
                typer.echo(data.get("prompt") or "")
            if exec_cmd:
                _run_exec(exec_cmd, data, room_name, handle)
        except KeyboardInterrupt:
            typer.echo("\n  [Stopped]")
            return


@doc_ref(
    usage='mycelium respond --room <room> --handle <handle> [--task <id>] "<text>"',
    desc="Publish a reply as the handle; the backend records it as a position for the aligner.",
    group="other",
)
def respond(
    ctx: typer.Context,
    text: str = typer.Argument(..., help="The reply / position text to publish"),
    room: str | None = typer.Option(None, "--room", "-r", help="Room (default: active room)"),
    handle: str = typer.Option(..., "--handle", help="Handle to publish the reply as"),
    task: str | None = typer.Option(
        None,
        "--task",
        "-u",
        help="Reply into one board row's thread (e.g. t3, work/auth) rather than where you were asked",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit the result as JSON for agents"),
) -> None:
    """Publish the caller's reply; the backend threads it onto the last awaited turn.

    A position marker may be appended to the text (e.g.
    `[[mycelium: confidence=0.85 stance=accept]]`); the backend lifts it onto the L9
    payload so the aligner can score it, and strips it from the posted prose.

    Without ``--task`` a reply lands where the turn that woke you was asked, which
    is what keeps a resident loop threaded without tracking URNs. Name a task to
    answer somewhere else — and expect the causal edge back to that turn to be
    dropped, because a reply redirected into another thread is not an answer to it.

    Examples:
        mycelium respond --room design --handle me "I can move to 30% if the timeline slips."
        mycelium respond --room design --handle me --task t3 "claiming this; starting on the schema."
    """
    try:
        config = MyceliumConfig.load()
        room_name = _resolve_room(config, room)
        body: dict[str, str] = {"handle": handle, "text": text}
        if task:
            body["episode"] = _task_episode(room_name, task)
        with hub_client(config, timeout=30.0, handle=handle) as client:
            resp = client.post(f"/api/rooms/{room_name}/reply", json=body)
        resp.raise_for_status()
        data = resp.json()
        if json_output:
            typer.echo(json_module.dumps(data))
        else:
            where = f"{room_name}/{task}" if task else room_name
            typer.secho(f"  ⟫  @{handle} replied in {where}", fg=typer.colors.GREEN)
    except KeyboardInterrupt:
        typer.echo("\n  [Stopped]")
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from e
