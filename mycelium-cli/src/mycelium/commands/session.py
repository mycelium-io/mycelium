# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
Session commands — breakout negotiation within rooms.

Sessions are ephemeral sync coordination spaces spawned within persistent rooms.
Agents join sessions with an initial position, then participate in structured
negotiation via the SSTP protocol (propose/respond/consensus).
"""

import json as json_module
from pathlib import Path

import typer

from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref
from mycelium.error_handler import print_error

app = typer.Typer(
    help="Breakout negotiation sessions within rooms. Spawn a session, join with your position, negotiate to consensus.",
)


def _typed_client(config: MyceliumConfig):
    from mycelium_backend_client import Client

    return Client(base_url=config.server.api_url, raise_on_unexpected_status=True)


def _resolve_room(config: MyceliumConfig, room: str | None = None) -> str:
    import os

    room_name = room or os.environ.get("MYCELIUM_ROOM_ID") or config.get_active_room()
    if not room_name:
        raise typer.BadParameter(
            "No room specified. Use --room, set MYCELIUM_ROOM_ID, or run 'mycelium room use <name>'"
        )
    return room_name


@doc_ref(
    usage="mycelium session create [-r <room>]",
    desc="Spawn a negotiation session within a room.",
    group="session",
)
@app.command()
def create(
    ctx: typer.Context,
    room: str | None = typer.Option(None, "--room", "-r", help="Room to spawn session in"),
) -> None:
    """Spawn a negotiation session within a room.

    Creates an ephemeral sync session. Other agents can then join it.

    Examples:
        mycelium session create -r sprint-plan
        mycelium session create  # uses active room
    """
    try:
        json_output = ctx.obj.get("json", False) if ctx.obj else False
        config = MyceliumConfig.load()
        room_name = _resolve_room(config, room)

        import httpx

        resp = httpx.post(
            f"{config.server.api_url}/rooms/{room_name}/sessions/spawn",
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        if json_output:
            typer.echo(json_module.dumps(data, indent=2))
        else:
            typer.secho(f"Session created: {data['session_room']}", fg=typer.colors.GREEN)
            typer.echo(f"  Room: {data['parent']}")
            typer.echo("")
            typer.echo(
                "  Agents can now join with: mycelium session join -H <handle> -m <position>"
            )

    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


@doc_ref(
    usage="mycelium session join -H <handle> -m <position> [-r <room>]",
    desc="Join a negotiation session with your initial position. Starts the 60s join window if you're the first.",
    group="session",
)
@app.command()
def join(
    ctx: typer.Context,
    message: str | None = typer.Option(
        None, "--message", "-m", help="Your position/intent for this negotiation"
    ),
    file: Path | None = typer.Option(None, "--file", "-f", help="Read position from a file"),
    room: str | None = typer.Option(None, "--room", "-r", help="Room (overrides active room)"),
    handle: str = typer.Option(
        ..., "--handle", "-H", help="Agent handle (your identity in this session)"
    ),
) -> None:
    """
    Join a negotiation session within a room.

    The backend auto-creates a session if one doesn't exist yet.
    Returns immediately — CognitiveEngine will address you via
    'session await' when it's your turn.

    Examples:
        mycelium session join -H julia-agent -m "Prioritize the migration" -r sprint-plan
        mycelium session join -H local-agent -f requirements.txt
    """
    try:
        json_output = ctx.obj.get("json", False) if ctx.obj else False

        config = MyceliumConfig.load()
        room_name = _resolve_room(config, room)

        # Resolve intent from -m or -f
        intent: str | None = None
        if message:
            intent = message
        elif file:
            intent = file.read_text().strip()

        from mycelium_backend_client.api.sessions import (
            join_room_rooms_room_name_sessions_post as join_api,
        )
        from mycelium_backend_client.models import SessionCreate

        with _typed_client(config) as client:
            body = SessionCreate(agent_handle=handle, intent=intent)
            result = join_api.sync(room_name=room_name, client=client, body=body)
            data = result.to_dict() if result and hasattr(result, "to_dict") else {}

        if json_output:
            typer.echo(json_module.dumps(data, indent=2, default=str))
            return

        session_room = data.get("room_name", room_name)
        typer.echo(f"  Joined session {session_room} as {handle}.")
        typer.echo("  CognitiveEngine will address you when it's your turn.")
        typer.echo("")
        typer.echo(f"  Next: mycelium session await -H {handle}")

    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


@doc_ref(
    usage="mycelium session await -H <handle> [-r <room>]",
    desc="Block and wait for a negotiation tick. Returns when CE has an action for your agent.",
    group="session",
)
@app.command(name="await")
def await_tick(
    ctx: typer.Context,
    handle: str = typer.Option(
        ..., "--handle", "-H", help="Your agent handle (listens for ticks addressed to you)"
    ),
    room: str | None = typer.Option(None, "--room", "-r", help="Room (overrides active room)"),
    timeout: int = typer.Option(120, "--timeout", "-t", help="Timeout in seconds (default 120)"),
) -> None:
    """
    Block until CognitiveEngine addresses you, then print the tick and exit.

    Call this in a loop to participate in negotiation:

    Flow:
        1. mycelium session join -H my-agent -m "my position"
        2. mycelium session await -H my-agent        # blocks
           → prints tick JSON when CE addresses you
        3. mycelium message propose budget=high       # respond
        4. mycelium session await -H my-agent        # wait for next tick
    """
    import time

    import httpx

    try:
        config = MyceliumConfig.load()
        resolved_room = _resolve_room(config, room)  # validate room exists

        # Check for a missed tick before opening the SSE stream — the tick may
        # have fired between join and await (race condition in CFN mode where
        # all agents are ticked simultaneously).
        if resolved_room:
            with httpx.Client(timeout=10) as http:
                try:
                    # Ticks are posted to session sub-rooms (e.g. room:session:xxxx).
                    # Find all session rooms under this namespace and scan them.
                    rooms_resp = http.get(
                        f"{config.server.api_url}/rooms",
                        params={"limit": 200},
                    )
                    rooms_to_scan = [resolved_room]
                    if rooms_resp.status_code == 200:
                        prefix = f"{resolved_room}:session:"
                        for r in rooms_resp.json():
                            if r.get("name", "").startswith(prefix):
                                rooms_to_scan.append(r["name"])

                    for scan_room in rooms_to_scan:
                        resp = http.get(
                            f"{config.server.api_url}/rooms/{scan_room}/messages",
                            params={"limit": 20},
                        )
                        if resp.status_code != 200:
                            continue
                        body = resp.json()
                        msgs = body.get("messages", body) if isinstance(body, dict) else body
                        # Messages come newest-first. Check for consensus before ticks.
                        missed_tick: dict | None = None
                        for msg in msgs:
                            mtype = msg.get("message_type")
                            if mtype == "coordination_consensus":
                                try:
                                    data = json_module.loads(msg.get("content", "{}"))
                                except json_module.JSONDecodeError:
                                    data = {}
                                typer.echo(
                                    json_module.dumps(
                                        {
                                            "type": "consensus",
                                            "room": msg.get("room_name"),
                                            "plan": data.get("plan"),
                                            "assignments": data.get("assignments"),
                                            "broken": data.get("broken", False),
                                            "replayed": True,
                                        }
                                    )
                                )
                                return
                            if mtype == "coordination_tick" and missed_tick is None:
                                try:
                                    data = json_module.loads(msg.get("content", "{}"))
                                except json_module.JSONDecodeError:
                                    continue
                                if "payload" in data and isinstance(data["payload"], dict):
                                    data = data["payload"]
                                participant = data.get("participant_id")
                                if participant == handle or participant is None:
                                    missed_tick = {
                                        "type": "tick",
                                        "room": msg.get("room_name"),
                                        "round": data.get("round"),
                                        "action": data.get("action"),
                                        "issue_options": data.get("issue_options", {}),
                                        "current_offer": data.get("current_offer"),
                                        "proposer_id": data.get("proposer_id"),
                                        "history": data.get("history"),
                                        "replayed": True,
                                    }
                        if missed_tick is not None:
                            typer.echo(json_module.dumps(missed_tick))
                            return
                except Exception:
                    pass  # fall through to SSE

        url = f"{config.server.api_url}/agents/{handle}/stream"
        start = time.time()

        with httpx.Client(timeout=None) as http, http.stream("GET", url) as response:
            for line in response.iter_lines():
                if timeout > 0 and (time.time() - start) >= timeout:
                    typer.echo(json_module.dumps({"type": "timeout", "seconds": timeout}))
                    raise typer.Exit(1)

                line = line.strip()
                if not line or line.startswith(":"):
                    continue
                if not line.startswith("data:"):
                    continue

                payload = line[5:].strip()
                try:
                    msg = json_module.loads(payload)
                except json_module.JSONDecodeError:
                    continue

                mtype = msg.get("message_type", "")

                if mtype == "coordination_tick":
                    try:
                        data = json_module.loads(msg.get("content", "{}"))
                    except json_module.JSONDecodeError:
                        data = {}
                    if "payload" in data and isinstance(data["payload"], dict):
                        data = data["payload"]
                    participant = data.get("participant_id")
                    if participant == handle or participant is None:
                        typer.echo(
                            json_module.dumps(
                                {
                                    "type": "tick",
                                    "room": msg.get("room_name"),
                                    "round": data.get("round"),
                                    "action": data.get("action"),
                                    "issue_options": data.get("issue_options", {}),
                                    "current_offer": data.get("current_offer"),
                                    "proposer_id": data.get("proposer_id"),
                                    "history": data.get("history"),
                                }
                            )
                        )
                        return

                if mtype == "coordination_consensus":
                    try:
                        data = json_module.loads(msg.get("content", "{}"))
                    except json_module.JSONDecodeError:
                        data = {}
                    typer.echo(
                        json_module.dumps(
                            {
                                "type": "consensus",
                                "room": msg.get("room_name"),
                                "plan": data.get("plan"),
                                "assignments": data.get("assignments"),
                                "broken": data.get("broken", False),
                            }
                        )
                    )
                    return

    except KeyboardInterrupt:
        typer.echo(json_module.dumps({"type": "interrupted"}))
        raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


@doc_ref(
    usage="mycelium session watch [-r <room>]",
    desc="Stream live messages from all sessions in a room. Waits if no session exists yet.",
    group="session",
)
@app.command(name="watch")
def watch_session(
    ctx: typer.Context,
    room: str | None = typer.Option(None, "--room", "-r", help="Room (overrides active room)"),
    timeout: int = typer.Option(0, "--timeout", "-t", help="Timeout in seconds (0=no timeout)"),
) -> None:
    """Stream live coordination events from all sessions in a room.

    Waits for a session to appear if none exists yet. Watches all sessions
    (existing and new) as they are created. Uses the same rich rendering as
    'room watch'.

    Examples:
        mycelium session watch -r home-sale
        mycelium session watch  # uses active room
    """
    import threading
    import time

    import httpx
    from rich.console import Console

    from mycelium.commands.room import _watch_room

    console = Console()

    try:
        config = MyceliumConfig.load()
        room_name = _resolve_room(config, room)
        prefix = f"{room_name}:session:"
        watched: set[str] = set()
        start = time.time()

        console.print(f"[dim]Watching {room_name} for sessions… (Ctrl+C to stop)[/dim]\n")

        while True:
            if timeout > 0 and (time.time() - start) >= timeout:
                break

            try:
                resp = httpx.get(f"{config.server.api_url}/rooms?limit=200", timeout=10)
                resp.raise_for_status()
                all_rooms = resp.json()
            except Exception:
                time.sleep(2)
                continue

            session_rooms = [r["name"] for r in all_rooms if r["name"].startswith(prefix)]
            for sr in session_rooms:
                if sr not in watched:
                    watched.add(sr)
                    console.print(f"[dim]  + {sr}[/dim]")
                    t = threading.Thread(
                        target=_watch_room, args=(config, sr, timeout), daemon=True
                    )
                    t.start()

            time.sleep(3)

    except KeyboardInterrupt:
        pass
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


@doc_ref(
    usage="mycelium session ls [-r <room>]",
    desc="List active sessions in a room.",
    group="session",
)
@app.command(name="ls")
def list_sessions(
    ctx: typer.Context,
    room: str | None = typer.Option(None, "--room", "-r", help="Room"),
) -> None:
    """List active negotiation sessions in a room."""
    try:
        json_output = ctx.obj.get("json", False) if ctx.obj else False
        config = MyceliumConfig.load()
        room_name = _resolve_room(config, room)

        from mycelium_backend_client.api.sessions import (
            list_sessions_rooms_room_name_sessions_get as list_api,
        )

        with _typed_client(config) as client:
            result = list_api.sync(room_name=room_name, client=client)
            if result and hasattr(result, "to_dict"):
                data = result.to_dict()
            else:
                data = {"sessions": [], "total": 0}

        if json_output:
            typer.echo(json_module.dumps(data, indent=2, default=str))
            return

        sessions = data.get("sessions", [])
        if not sessions:
            typer.echo(f"  No active sessions in {room_name}")
            return

        typer.echo(f"  {room_name} — {len(sessions)} session(s)\n")
        for s in sessions:
            typer.echo(
                f"    {s.get('agent_handle', '?')}  joined {str(s.get('joined_at', ''))[:16]}"
            )

    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
