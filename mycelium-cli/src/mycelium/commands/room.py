"""
Room management commands for Mycelium CLI.

Commands:
- (default): Show current active room
- ls: List rooms
- create: Create a new room
- set: Set active room context
- delete: Delete a room
- join: Join coordination backchannel (blocks until first coordination tick)
- watch: Stream messages from a room via SSE
- respond: Post a message to a room
- delegate: Delegate a task to an agent in a room
"""

import json as json_module
import os
import sys
from pathlib import Path

import typer

from mycelium.config import MyceliumConfig
from mycelium.error_handler import print_error
from mycelium.exceptions import ConfigNotFoundError, MyceliumError
from mycelium.http_client import MyceliumHTTPClient  # kept for SSE streaming only


def _typed_client(config: MyceliumConfig):
    """Get a typed OpenAPI client."""
    from mycelium_backend_client import Client
    return Client(base_url=config.server.api_url, raise_on_unexpected_status=True)

app = typer.Typer(help="Room management commands", invoke_without_command=True)


@app.callback(invoke_without_command=True)
def room_main(ctx: typer.Context) -> None:
    """Show current active room or manage rooms."""
    if ctx.invoked_subcommand is not None:
        return

    try:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False  # noqa: F841
        json_output = ctx.obj.get("json", False) if ctx.obj else False

        config = MyceliumConfig.load()
        active_room = config.get_active_room()

        if not active_room:
            if json_output:
                typer.echo(json_module.dumps({"active_room": None}))
            else:
                typer.secho("No active room set.", fg=typer.colors.YELLOW)
                typer.echo("Set a room with: mycelium room set <name>")
            raise typer.Exit(1)

        from mycelium_backend_client.api.rooms import list_rooms_rooms_get as list_api

        with _typed_client(config) as client:
            result = list_api.sync(client=client, name=active_room, limit=1)
            rooms_data = [r.to_dict() for r in result] if result else []

        if not rooms_data:
            typer.secho(f"Active room '{active_room}' not found on server.", fg=typer.colors.RED)
            raise typer.Exit(1)

        room = rooms_data[0]
        if json_output:
            typer.echo(json_module.dumps(room, indent=2, default=str))
        else:
            typer.secho(f"Current Room: {room['name']}", fg=typer.colors.GREEN, bold=True)
            typer.echo(f"  ID:      {room.get('id')}")
            typer.echo(f"  Created: {str(room.get('created_at', ''))[:10]}")

    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


@app.command("ls")
def list_rooms(
    ctx: typer.Context,
    limit: int = typer.Option(20, "--limit", "-l"),
    name: str | None = typer.Option(None, "--name", "-n"),
) -> None:
    """List available rooms."""
    try:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False  # noqa: F841
        json_output = ctx.obj.get("json", False) if ctx.obj else False

        config_path = MyceliumConfig.get_config_path()
        if not config_path.exists():
            raise ConfigNotFoundError(str(config_path))

        config = MyceliumConfig.load()

        params: dict[str, str | int] = {"limit": limit}
        if name:
            params["name"] = name

        from mycelium_backend_client.api.rooms import list_rooms_rooms_get as list_api

        with _typed_client(config) as client:
            result = list_api.sync(client=client, name=name, limit=limit)
            rooms_data = [r.to_dict() for r in result] if result else []

        if json_output:
            typer.echo(json_module.dumps(rooms_data, indent=2, default=str))
        else:
            if not rooms_data:
                typer.echo("No rooms found.")
                typer.echo("Create a room with: mycelium room create <name>")
                return

            active_room = config.get_active_room()
            typer.secho(f"Rooms ({len(rooms_data)})", bold=True)
            typer.echo("")

            for room in rooms_data:
                is_active = room["name"] == active_room
                created_at = str(room.get("created_at", ""))[:10]
                if is_active:
                    typer.secho(f"  * {room['name']}", fg=typer.colors.GREEN, bold=True, nl=False)
                    typer.echo(f"  (created {created_at})")
                else:
                    typer.echo(f"    {room['name']}  (created {created_at})")

            typer.echo("")
            typer.echo("Use 'mycelium room set <name>' to set the active room")

    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


@app.command()
def create(
    ctx: typer.Context,
    name: str | None = typer.Argument(None, help="Room name"),
    public: bool = typer.Option(True, "--public/--private"),
    mode: str = typer.Option("sync", "--mode", "-m", help="Room mode: sync, async, or hybrid"),
    trigger: str | None = typer.Option(None, "--trigger", help="Trigger config (e.g. 'threshold:5' or 'explicit')"),
    persistent: bool = typer.Option(False, "--persistent", help="Room persists after coordination completes"),
) -> None:
    """Create a new room."""
    try:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False  # noqa: F841
        json_output = ctx.obj.get("json", False) if ctx.obj else False

        config_path = MyceliumConfig.get_config_path()
        if not config_path.exists():
            raise ConfigNotFoundError(str(config_path))

        config = MyceliumConfig.load()

        if name is None:
            name = typer.prompt("Room name")

        # Parse trigger config
        trigger_config = None
        if trigger:
            if ":" in trigger:
                ttype, tval = trigger.split(":", 1)
                trigger_config = {"type": ttype, "min_contributions": int(tval)}
            else:
                trigger_config = {"type": trigger}

        # Auto-set persistent for async/hybrid rooms
        if mode in ("async", "hybrid"):
            persistent = True

        from mycelium_backend_client.api.rooms import create_room_rooms_post as create_api
        from mycelium_backend_client.models import RoomCreate

        with _typed_client(config) as client:
            body = RoomCreate(
                name=name,
                is_public=public,
                mode=mode,
                trigger_config=trigger_config,
                is_persistent=persistent,
            )
            result = create_api.sync(client=client, body=body)
            room_data = result.to_dict() if result and hasattr(result, "to_dict") else {}

        if json_output:
            typer.echo(json_module.dumps(room_data, indent=2, default=str))
        else:
            typer.secho(f"Created room: {room_data['name']} (mode={room_data.get('mode', 'sync')})", fg=typer.colors.GREEN)
            typer.echo(f"  ID:      {room_data.get('id')}")
            typer.echo(f"  Created: {str(room_data.get('created_at', ''))[:10]}")
            typer.echo("")
            typer.echo(f"  Run 'mycelium room set {name}' to make it your active room")

    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


@app.command()
def synthesize(
    ctx: typer.Context,
    room_name: str | None = typer.Argument(None, help="Room to synthesize (default: active room)"),
) -> None:
    """Trigger CognitiveEngine synthesis for an async/hybrid room."""
    try:
        json_output = ctx.obj.get("json", False) if ctx.obj else False
        config = MyceliumConfig.load()
        name = room_name or _resolve_room(config)

        from mycelium_backend_client.api.rooms import synthesize_room_rooms_room_name_synthesize_post as synth_api

        with _typed_client(config) as client:
            result = synth_api.sync_detailed(room_name=name, client=client)
            data = result.parsed.to_dict() if result.parsed and hasattr(result.parsed, "to_dict") else json_module.loads(result.content)

        if json_output:
            typer.echo(json_module.dumps(data, indent=2, default=str))
        else:
            status = data.get("status", "unknown")
            if status == "complete":
                typer.secho(f"Synthesis complete: {data.get('key', '')}", fg=typer.colors.GREEN)
                typer.echo(f"  Memories synthesized: {data.get('memory_count', '?')}")
            else:
                typer.echo(f"  {data.get('message', 'No new memories to synthesize')}")

    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


@app.command()
def set(
    ctx: typer.Context,
    room_name: str = typer.Argument(..., help="Room name to set as active"),
) -> None:
    """Set active room for this project."""
    try:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False  # noqa: F841
        json_output = ctx.obj.get("json", False) if ctx.obj else False

        config = MyceliumConfig.load()

        from mycelium_backend_client.api.rooms import list_rooms_rooms_get as list_api

        with _typed_client(config) as client:
            result = list_api.sync(client=client, name=room_name, limit=1)
            rooms_data = [r.to_dict() for r in result] if result else []

            if not rooms_data:
                raise MyceliumError(
                    f"Room '{room_name}' not found",
                    suggestion=f"Create it first with: mycelium room create {room_name}",
                )

        config.init_project(room_name=room_name)
        config.save()

        if json_output:
            typer.echo(json_module.dumps({"room": room_name}))
        else:
            typer.secho(f"Room set: {room_name}", fg=typer.colors.GREEN)
            typer.echo("Next: Run 'mycelium room join -m <intent>' to join a coordination session")

    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


@app.command()
def delete(
    ctx: typer.Context,
    room_name: str = typer.Argument(..., help="Room name to delete"),
    force: bool = typer.Option(False, "--force", "-f"),
) -> None:
    """Delete a room."""
    try:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False  # noqa: F841
        config_path = MyceliumConfig.get_config_path()
        if not config_path.exists():
            raise ConfigNotFoundError(str(config_path))

        config = MyceliumConfig.load()

        if not force:
            confirm = typer.confirm(f"Delete room '{room_name}'? This cannot be undone.")
            if not confirm:
                typer.echo("Cancelled.")
                raise typer.Exit(0)

        from mycelium_backend_client.api.rooms import delete_room_rooms_room_name_delete as delete_api

        with _typed_client(config) as client:
            delete_api.sync_detailed(room_name=room_name, client=client)

        typer.secho(f"Room '{room_name}' deleted.", fg=typer.colors.GREEN)

    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


def _resolve_room(config: MyceliumConfig, channel: str | None = None) -> str:
    """
    Resolve the coordination room name.

    Priority:
      1. --channel flag (explicit override, used as-is)
      2. MYCELIUM_CHANNEL_ID env var (used as-is)
      3. config.rooms.active (set via 'mycelium room set')
      4. Error
    """
    if channel:
        return channel
    channel_id = os.getenv("MYCELIUM_CHANNEL_ID")
    if channel_id:
        return channel_id
    if config.rooms.active:
        return config.rooms.active
    raise MyceliumError(
        "No channel context found",
        suggestion=(
            "Pass --channel <room>, set MYCELIUM_CHANNEL_ID in your environment, "
            "or run: mycelium room set <name>"
        ),
    )


# Known stub options for NegMAS SAO issues (mirrors options_generation.py)
_ISSUE_OPTIONS: dict[str, list[str]] = {
    "budget":   ["minimal", "low", "medium", "high", "uncapped"],
    "timeline": ["express", "short", "standard", "extended", "long"],
    "scope":    ["core", "standard", "extended", "full"],
    "quality":  ["basic", "standard", "premium"],
}


def _render_coordination_event(msg: dict, current_identity: str) -> tuple[str | None, bool]:
    """
    Render a coordination SSE event for display.

    Returns (rendered_string | None, should_exit).
    should_exit=True means the CLI should print the message and exit.
    """
    mtype = msg.get("message_type", "")
    if not mtype:
        return None, False

    if mtype == "coordination_join":
        try:
            data = json_module.loads(msg.get("content", "{}"))
        except json_module.JSONDecodeError:
            data = {}
        handle = data.get("handle", "?")
        intent = data.get("intent")
        suffix = f" — {intent}" if intent else ""
        return f"  ⟫  {handle} joined{suffix}", False

    if mtype == "coordination_start":
        try:
            data = json_module.loads(msg.get("content", "{}"))
        except json_module.JSONDecodeError:
            data = {}
        n = data.get("agent_count", "?")
        return f"  ⟫  Session started — {n} agents joined. Beginning coordination…", False

    if mtype == "coordination_tick":
        try:
            data = json_module.loads(msg.get("content", "{}"))
        except json_module.JSONDecodeError:
            data = {}
        round_num = data.get("round", "?")
        kind = data.get("kind")

        if kind == "negotiate":
            action = data.get("action", "propose")
            participant_id = data.get("participant_id")

            # Tick not addressed to us — show informational, keep waiting
            if participant_id and participant_id != current_identity:
                return f"  ⟫  CognitiveEngine — waiting for {participant_id} ({action})…", False

            if action == "propose":
                history = data.get("history", [])
                issues: list[str] = []
                if history:
                    issues = list(history[-1].get("offer", {}).keys())
                if not issues:
                    issues = list(_ISSUE_OPTIONS.keys())
                lines = [f"  ⟫  CognitiveEngine [round {round_num}] — propose your offer:"]
                for issue in issues:
                    opts = _ISSUE_OPTIONS.get(issue, ["?"])
                    lines.append(f"        {issue}: {' | '.join(opts)}")
                example = {
                    issue: (_ISSUE_OPTIONS.get(issue, ["option"])[2]
                            if len(_ISSUE_OPTIONS.get(issue, [])) > 2 else "option")
                    for issue in issues
                }
                lines.append("")
                lines.append(
                    f"        Reply: mycelium message query "
                    f"'{{\"offer\": {json_module.dumps(example)}}}'"
                )
                return "\n".join(lines), True

            if action == "respond":
                current_offer = data.get("current_offer") or {}
                proposer = data.get("proposer_id", "?")
                lines = [
                    f"  ⟫  CognitiveEngine [round {round_num}] — respond to offer from {proposer}:"
                ]
                for k, v in current_offer.items():
                    lines.append(f"        {k}: {v}")
                lines.append("")
                lines.append(
                    "        Accept/reject/end: "
                    "mycelium message query '{\"action\": \"accept\"}'"
                )
                return "\n".join(lines), True

            return f"  ⟫  CognitiveEngine [round {round_num}] — {action} ({participant_id})", True

        # Legacy ambiguities format
        ambiguities = data.get("ambiguities", [])
        lines = [f"  ⟫  CognitiveEngine [tick {round_num}]:"]
        for i, q in enumerate(ambiguities, 1):
            lines.append(f"        {i}. {q}")
        return "\n".join(lines), True  # exit after printing

    if mtype == "coordination_consensus":
        try:
            data = json_module.loads(msg.get("content", "{}"))
        except json_module.JSONDecodeError:
            data = {}
        lines = ["  ⟫  CognitiveEngine [consensus]:"]
        if data.get("broken"):
            lines.append("        Negotiation ended without agreement.")
        else:
            assignments = data.get("assignments", {})
            assignment = assignments.get(current_identity)
            if assignment:
                lines.append(f"        Your assignment: {assignment}")
            elif assignments:
                for h, task in assignments.items():
                    lines.append(f"        {h}: {task}")
            plan = data.get("plan", "")
            if plan and not assignments:
                lines.append(f"        Plan: {plan}")
        return "\n".join(lines), True  # exit after printing

    # Regular message
    if mtype not in ("coordination_join", "coordination_start"):
        sender = msg.get("sender_handle", "?")
        content = msg.get("content", "")
        return f"  {sender}: {content}", False

    return None, False


@app.command()
def join(
    ctx: typer.Context,
    message: str | None = typer.Option(
        None, "--message", "-m", help="Your requirements/intent for this coordination session"
    ),
    file: Path | None = typer.Option(
        None, "--file", "-f", help="Read requirements from a file"
    ),
    channel: str | None = typer.Option(
        None, "--channel", "-c", help="Channel/room to join (overrides MYCELIUM_CHANNEL_ID)"
    ),
    handle: str = typer.Option(
        ..., "--handle", "-H", help="Agent handle (your identity in this coordination session)"
    ),
) -> None:
    """
    Join the coordination backchannel for the current channel.

    Room is resolved from --channel, MYCELIUM_CHANNEL_ID env var, or 'mycelium room set'.
    Returns immediately after joining — CognitiveEngine will address you in this channel
    when the session starts and when it is your turn to respond.

    Examples:
        mycelium room join --handle julia-agent -m "My human wants to visit Hawaii"
        mycelium room join --handle local-agent -m "..." --channel my-experiment
        mycelium room join --handle local-agent -f requirements.txt
    """
    try:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False  # noqa: F841
        json_output = ctx.obj.get("json", False) if ctx.obj else False

        config = MyceliumConfig.load()
        room_name = _resolve_room(config, channel)

        # Resolve intent from -m or -f
        intent: str | None = None
        if message:
            intent = message
        elif file:
            intent = file.read_text().strip()

        from mycelium_backend_client.api.sessions import join_room_rooms_room_name_sessions_post as join_api
        from mycelium_backend_client.models import SessionCreate

        with _typed_client(config) as client:
            body = SessionCreate(agent_handle=handle, intent=intent)
            result = join_api.sync(room_name=room_name, client=client, body=body)
            data = result.to_dict() if result and hasattr(result, "to_dict") else {}

        if json_output:
            typer.echo(json_module.dumps(data, indent=2, default=str))
            return

        typer.echo(f"  Joined {room_name} as {handle}.")
        typer.echo(f"  CognitiveEngine will address you here when it is your turn.")

    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


def _watch_room(config: MyceliumConfig, room_name: str, timeout: int) -> None:
    """Core SSE watch loop — pretty-renders all message types."""
    import time

    import httpx

    C = {
        "cyan":   "\x1b[36m",
        "green":  "\x1b[32m",
        "yellow": "\x1b[33m",
        "blue":   "\x1b[34m",
        "magenta":"\x1b[35m",
        "dim":    "\x1b[2m",
        "bold":   "\x1b[1m",
        "reset":  "\x1b[0m",
    }

    def ts() -> str:
        return C["dim"] + time.strftime("%H:%M:%S") + C["reset"]

    def rule() -> str:
        return C["dim"] + "  " + "─" * 54 + C["reset"]

    def render(msg: dict) -> str | None:
        mtype = msg.get("message_type", "")
        sender = msg.get("sender_handle", "?")

        try:
            data = json_module.loads(msg.get("content", "{}"))
        except (json_module.JSONDecodeError, TypeError):
            data = {}

        if mtype == "coordination_join":
            intent = data.get("intent")
            handle = data.get("handle", sender)
            suffix = f"  {C['dim']}— {intent}{C['reset']}" if intent else ""
            return f"  {ts()}  {C['cyan']}{handle}{C['reset']} joined{suffix}"

        if mtype == "coordination_start":
            n = data.get("agent_count", "?")
            return (
                f"\n{rule()}\n"
                f"  {ts()}  {C['bold']}{C['cyan']}⟫ Session started{C['reset']} — "
                f"{n} agents joined. Beginning coordination…\n"
            )

        if mtype == "coordination_tick":
            round_num = data.get("round", "?")
            kind = data.get("kind")

            if kind == "negotiate":
                action = data.get("action", "propose")
                participant_id = data.get("participant_id", "?")

                if action == "propose":
                    history = data.get("history", [])
                    issues: list[str] = []
                    if history:
                        issues = list(history[-1].get("offer", {}).keys())
                    if not issues:
                        issues = list(_ISSUE_OPTIONS.keys())
                    lines = [
                        f"\n  {ts()}  {C['bold']}{C['cyan']}⟫ CognitiveEngine "
                        f"[round {round_num}] → {participant_id} — propose{C['reset']}"
                    ]
                    for issue in issues:
                        opts = _ISSUE_OPTIONS.get(issue, ["?"])
                        lines.append(
                            f"              {C['dim']}{issue}:{C['reset']} {' | '.join(opts)}"
                        )
                elif action == "respond":
                    current_offer = data.get("current_offer") or {}
                    proposer = data.get("proposer_id", "?")
                    lines = [
                        f"\n  {ts()}  {C['bold']}{C['cyan']}⟫ CognitiveEngine "
                        f"[round {round_num}] → {participant_id} — respond "
                        f"(offer from {proposer}){C['reset']}"
                    ]
                    for k, v in current_offer.items():
                        lines.append(f"              {C['dim']}{k}:{C['reset']} {v}")
                else:
                    lines = [
                        f"\n  {ts()}  {C['bold']}{C['cyan']}⟫ CognitiveEngine "
                        f"[round {round_num}] → {participant_id} — {action}{C['reset']}"
                    ]
            else:
                questions = data.get("ambiguities", [])
                lines = [
                    f"\n  {ts()}  {C['bold']}{C['cyan']}⟫ CognitiveEngine "
                    f"[tick {round_num}]{C['reset']}"
                ]
                for i, q in enumerate(questions, 1):
                    lines.append(f"              {C['dim']}{i}.{C['reset']} {q}")
            return "\n".join(lines)

        if mtype == "coordination_consensus":
            plan = data.get("plan", "")
            assignments = data.get("assignments", {})
            lines = [
                f"\n{rule()}",
                f"  {ts()}  {C['bold']}{C['green']}⟫ CognitiveEngine [consensus]{C['reset']}",
            ]
            if plan:
                lines.append(f"              {C['dim']}Plan:{C['reset']} {plan}")
            if assignments:
                lines.append(f"              {C['dim']}Assignments:{C['reset']}")
                for handle, task in assignments.items():
                    lines.append(f"                {C['cyan']}{handle}{C['reset']}: {task}")
            lines.append(f"\n{rule()}")
            return "\n".join(lines)

        if mtype == "delegate":
            recipient = msg.get("recipient_handle", "?")
            content = msg.get("content", "")
            return (
                f"  {ts()}  {C['magenta']}{sender}{C['reset']} "
                f"{C['dim']}→{C['reset']} {C['cyan']}{recipient}{C['reset']}: {content}"
            )

        if mtype in ("direct", "broadcast", "announce"):
            content = msg.get("content", "")
            color = C["yellow"] if mtype == "broadcast" else C["blue"]
            return f"  {ts()}  {color}{sender}{C['reset']}: {content}"

        return None

    url = f"{config.server.api_url}/rooms/{room_name}/messages/stream"

    typer.echo(f"\n  {C['bold']}Watching{C['reset']} {C['cyan']}{room_name}{C['reset']}  "
               f"{C['dim']}(Ctrl+C to stop){C['reset']}\n")
    typer.echo(rule())

    start = time.time()

    with httpx.Client(timeout=None) as http:
        with http.stream("GET", url) as response:
            for line in response.iter_lines():
                if timeout > 0 and (time.time() - start) >= timeout:
                    typer.echo(f"\n  {C['dim']}[Timeout after {timeout}s]{C['reset']}")
                    return
                line = line.strip()
                if not line or line.startswith(":"):
                    continue
                if line.startswith("data:"):
                    payload = line[5:].strip()
                    try:
                        msg = json_module.loads(payload)
                    except json_module.JSONDecodeError:
                        continue
                    rendered = render(msg)
                    if rendered:
                        typer.echo(rendered)


@app.command()
def watch(
    ctx: typer.Context,
    room_name: str | None = typer.Argument(None, help="Room to watch (default: active room)"),
    timeout: int = typer.Option(0, "--timeout", "-t", help="Timeout in seconds (0=no timeout)"),
) -> None:
    """
    Stream live messages from a room.

    Auto-resolves the active room — no argument needed.
    Renders coordination events, agent joins, ticks, and consensus.

    Examples:
        mycelium room watch
        mycelium room watch my-room
        mycelium room watch --timeout 120
    """
    try:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False  # noqa: F841
        config = MyceliumConfig.load()
        name = room_name or _resolve_room(config)
        _watch_room(config, name, timeout)
    except KeyboardInterrupt:
        typer.echo("\n  [Stopped]")
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


@app.command()
def respond(
    ctx: typer.Context,
    session_id: str = typer.Argument(..., help="Room session/name"),
    agent: str = typer.Option(..., "--agent", "-a", help="Agent handle sending the response"),
    response_text: str = typer.Option(..., "--response", "-r", help="Response message text"),
) -> None:
    """
    Post a message to a room (triggers NOTIFY).

    Examples:
        mycelium room respond my-room --agent alpha#a1b2 --response "Task complete"
    """
    try:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False  # noqa: F841
        json_output = ctx.obj.get("json", False) if ctx.obj else False

        config = MyceliumConfig.load()

        from mycelium_backend_client.api.messages import send_message_rooms_room_name_messages_post as send_api
        from mycelium_backend_client.models import MessageCreate

        with _typed_client(config) as client:
            body = MessageCreate(sender_handle=agent, message_type="direct", content=response_text)
            result = send_api.sync(room_name=session_id, client=client, body=body)
            data = result.to_dict() if result and hasattr(result, "to_dict") else {}

        if json_output:
            typer.echo(json_module.dumps(data, indent=2, default=str))
        else:
            typer.secho("Message sent", fg=typer.colors.GREEN)
            typer.echo(f"  {agent}: {response_text[:80]}")

    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


@app.command()
def delegate(
    ctx: typer.Context,
    session_id: str = typer.Argument(..., help="Room session/name"),
    to: str = typer.Option(..., "--to", help="Target agent handle"),
    task: str = typer.Option(..., "--task", "-t", help="Task description to delegate"),
) -> None:
    """
    Delegate a task to an agent in a room.

    Posts a 'delegate' type message to the room.

    Examples:
        mycelium room delegate my-room --to cfn-agent --task "Scan CVE-2024-1234"
    """
    try:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False  # noqa: F841
        json_output = ctx.obj.get("json", False) if ctx.obj else False

        config = MyceliumConfig.load()
        sender = config.get_current_identity()

        from mycelium_backend_client.api.messages import send_message_rooms_room_name_messages_post as send_api
        from mycelium_backend_client.models import MessageCreate

        with _typed_client(config) as client:
            body = MessageCreate(sender_handle=sender, message_type="delegate", content=task, recipient_handle=to)
            result = send_api.sync(room_name=session_id, client=client, body=body)
            data = result.to_dict() if result and hasattr(result, "to_dict") else {}

        if json_output:
            typer.echo(json_module.dumps(data, indent=2, default=str))
        else:
            typer.secho("Task delegated", fg=typer.colors.GREEN)
            typer.echo(f"  {sender} -> {to}: {task[:80]}")

    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
