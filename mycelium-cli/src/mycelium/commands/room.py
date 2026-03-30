"""
Room management commands for Mycelium CLI.

Commands:
- (default): Show current active room
- ls: List rooms
- create: Create a new room
- use: Switch active room context
- delete: Delete a room
- join: Join coordination backchannel (blocks until first coordination tick)
- watch: Stream messages from a room via SSE
- post: Post a message to a room
- delegate: Delegate a task to an agent in a room
- clone: Clone a room from a remote backend instance
"""

import json as json_module
import os

import typer

from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref
from mycelium.error_handler import print_error
from mycelium.exceptions import ConfigNotFoundError, MyceliumError


def _typed_client(config: MyceliumConfig):
    """Get a typed OpenAPI client."""
    from mycelium_backend_client import Client

    return Client(base_url=config.server.api_url, raise_on_unexpected_status=True)


app = typer.Typer(
    help="Shared spaces for agent coordination. Rooms are persistent namespaces for memory and coordination. Spawn sessions within rooms for real-time negotiation.",
    invoke_without_command=True,
)


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
                typer.echo("Set a room with: mycelium room use <name>")
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


@doc_ref(
    usage="mycelium room ls",
    desc="List all rooms with state and member count.",
    group="room",
)
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
            typer.echo("Use 'mycelium room use <name>' to set the active room")

    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


@doc_ref(
    usage="mycelium room create <name> [--trigger threshold:N]",
    desc="Create a new persistent coordination room.",
    group="room",
)
@app.command()
def create(
    ctx: typer.Context,
    name: str | None = typer.Argument(None, help="Room name"),
    public: bool = typer.Option(True, "--public/--private"),
    trigger: str | None = typer.Option(
        None, "--trigger", help="Trigger config (e.g. 'threshold:5' or 'explicit')"
    ),
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

        from mycelium_backend_client.api.rooms import create_room_rooms_post as create_api
        from mycelium_backend_client.models import RoomCreate

        with _typed_client(config) as client:
            body = RoomCreate(
                name=name,
                is_public=public,
                trigger_config=trigger_config,
            )
            result = create_api.sync(client=client, body=body)
            room_data = result.to_dict() if result and hasattr(result, "to_dict") else {}

        # The backend now creates the directory, but also create locally
        # in case the CLI is running on a different machine
        from mycelium.filesystem import ensure_room_structure, get_room_dir

        room_dir = get_room_dir(name)
        ensure_room_structure(room_dir)

        if json_output:
            typer.echo(json_module.dumps(room_data, indent=2, default=str))
        else:
            typer.secho(
                f"Created room: {room_data['name']}",
                fg=typer.colors.GREEN,
            )
            typer.echo(f"  ID:      {room_data.get('id')}")
            typer.echo(f"  Created: {str(room_data.get('created_at', ''))[:10]}")
            typer.echo(f"  Path:    {room_dir}")
            typer.echo("")
            typer.echo(f"  Run 'mycelium room use {name}' to make it your active room")

    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


@doc_ref(
    usage="mycelium synthesize",
    desc="Trigger CE to synthesize all memories in the active room into a structured summary.",
    group="other",
)
@app.command()
def synthesize(
    ctx: typer.Context,
    room_name: str | None = typer.Argument(None, help="Room to synthesize (default: active room)"),
    room: str | None = typer.Option(
        None, "--room", "-r", help="Room name (alternative to positional arg)"
    ),
) -> None:
    """Trigger CognitiveEngine synthesis for a room."""
    try:
        from rich.console import Console

        console = Console()
        json_output = ctx.obj.get("json", False) if ctx.obj else False
        config = MyceliumConfig.load()
        name = room_name or room or _resolve_room(config)

        from mycelium_backend_client.api.rooms import (
            synthesize_room_rooms_room_name_synthesize_post as synth_api,
        )

        with (
            console.status(f"[bold cyan]Synthesizing {name}...[/]", spinner="dots"),
            _typed_client(config) as client,
        ):
            result = synth_api.sync_detailed(room_name=name, client=client)
            data = (
                result.parsed.to_dict()
                if result.parsed and hasattr(result.parsed, "to_dict")
                else json_module.loads(result.content)
            )

        if json_output:
            typer.echo(json_module.dumps(data, indent=2, default=str))
        else:
            status = data.get("status", "unknown")
            if status == "complete":
                console.print(f"[bold green]Synthesis complete:[/] {data.get('key', '')}")
                console.print(f"  Memories synthesized: {data.get('memory_count', '?')}")
            else:
                console.print(f"  {data.get('message', 'No new memories to synthesize')}")

    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


@doc_ref(
    usage="mycelium room use <name>",
    desc="Switch active room. Subsequent <code>memory</code> and <code>message</code> commands use this room by default.",
    group="room",
)
@app.command("use")
def use(
    ctx: typer.Context,
    room_name: str = typer.Argument(..., help="Room name to set as active"),
) -> None:
    """Switch active room for this project."""
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
            typer.echo(
                "Next: Run 'mycelium session join -H <handle> -m <position>' to start negotiating"
            )

    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


@doc_ref(
    usage="mycelium room delete <name> [--force]",
    desc="Delete a room and all its data (memories, sessions, messages).",
    group="room",
)
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

        from mycelium_backend_client.api.rooms import (
            delete_room_rooms_room_name_delete as delete_api,
        )

        with _typed_client(config) as client:
            delete_api.sync_detailed(room_name=room_name, client=client)

        typer.secho(f"Room '{room_name}' deleted.", fg=typer.colors.GREEN)

    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


@doc_ref(
    usage="mycelium room clone <room-name> [--from <api-url>]",
    desc="Clone a room from a remote backend — fetches all memories via HTTP and writes them locally.",
    group="room",
)
@app.command("clone")
def clone_room(
    ctx: typer.Context,
    room_name: str = typer.Argument(..., help="Room name to clone"),
    from_url: str | None = typer.Option(
        None, "--from", help="Backend API URL (defaults to configured api_url)"
    ),
) -> None:
    """Clone a room from a remote backend instance via HTTP.

    Fetches all memories from the remote backend and writes them to the local
    .mycelium/rooms/ directory. Sets the room as active.

    Examples:
        mycelium room clone mycelium-dev
        mycelium room clone mycelium-dev --from http://18.216.86.206:8000
    """
    import json as _json

    import httpx

    from mycelium.filesystem import (
        ensure_room_structure,
        get_mycelium_dir,
        write_memory,
    )

    try:
        config = MyceliumConfig.load()
        api_url = from_url or config.server.api_url

        rooms_dir = get_mycelium_dir() / "rooms"
        rooms_dir.mkdir(parents=True, exist_ok=True)
        target = rooms_dir / room_name

        if target.exists():
            typer.secho(f"Room directory already exists: {target}", fg=typer.colors.RED)
            raise typer.Exit(1)

        typer.echo(f"Cloning {room_name} from {api_url}...")

        with httpx.Client(base_url=api_url, timeout=60) as client:
            resp = client.get(f"/rooms/{room_name}/memory", params={"limit": 1000})
            resp.raise_for_status()
            memories = resp.json()

        ensure_room_structure(target)

        written = 0
        for mem in memories:
            value = mem.get("value", "")
            if isinstance(value, dict):
                content = value.get("text", _json.dumps(value))
            else:
                content = str(value)
            write_memory(
                target,
                mem["key"],
                content,
                created_by=mem.get("created_by"),
                updated_by=mem.get("updated_by"),
                version=mem.get("version", 1),
                tags=mem.get("tags"),
                created_at=mem.get("created_at"),
                updated_at=mem.get("updated_at"),
            )
            written += 1

        typer.secho(f"Cloned room: {room_name} ({written} memories)", fg=typer.colors.GREEN)

        config.rooms.active = room_name
        config.save()

        # Reindex local copy against the configured backend
        typer.echo("Re-indexing...")
        try:
            with httpx.Client(base_url=config.server.api_url, timeout=120) as client:
                resp = client.post(f"/rooms/{room_name}/reindex")
                resp.raise_for_status()
                data = resp.json()
            typer.echo(f"  Indexed {data.get('indexed', 0)} memories")
        except Exception:
            typer.echo(
                "[dim]  Reindex skipped — run 'mycelium memory reindex' when backend is available[/dim]"
            )

        typer.echo(f"\nRoom '{room_name}' is now active. Run 'mycelium catchup' to get briefed.")

    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


def _resolve_room(config: MyceliumConfig, channel: str | None = None) -> str:
    """
    Resolve the coordination room name.

    Priority:
      1. --room flag (explicit override, used as-is)
      2. MYCELIUM_ROOM_ID env var (used as-is)
      3. config.rooms.active (set via 'mycelium room use')
      4. Error
    """
    if channel:
        return channel
    room_id = os.getenv("MYCELIUM_ROOM_ID") or os.getenv("MYCELIUM_CHANNEL_ID")
    if room_id:
        return room_id
    if config.rooms.active:
        return config.rooms.active
    raise MyceliumError(
        "No room context found",
        suggestion=(
            "Pass --room <room>, set MYCELIUM_ROOM_ID in your environment, "
            "or run: mycelium room use <name>"
        ),
    )


# Known stub options for NegMAS SAO issues (mirrors options_generation.py)
_ISSUE_OPTIONS: dict[str, list[str]] = {
    "budget": ["minimal", "low", "medium", "high", "uncapped"],
    "timeline": ["express", "short", "standard", "extended", "long"],
    "scope": ["core", "standard", "extended", "full"],
    "quality": ["basic", "standard", "premium"],
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
        # SSTP envelope: action fields live under data["payload"]
        if "payload" in data and isinstance(data["payload"], dict):
            data = data["payload"]
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
                    issue: (
                        _ISSUE_OPTIONS.get(issue, ["option"])[2]
                        if len(_ISSUE_OPTIONS.get(issue, [])) > 2
                        else "option"
                    )
                    for issue in issues
                }
                lines.append("")
                kv = " ".join(f"{k}={v}" for k, v in example.items())
                lines.append(f"        Reply: mycelium message propose {kv}")
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
                lines.append("        Accept/reject/end: mycelium message respond accept")
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


def _watch_room(config: MyceliumConfig, room_name: str, timeout: int) -> None:
    """Core SSE watch loop — pretty-renders coordination and memory events."""
    import time

    import httpx
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    console = Console()

    def ts() -> str:
        return f"[dim]{time.strftime('%H:%M:%S')}[/]"

    def render(msg: dict) -> str | None:
        mtype = msg.get("message_type", "") or msg.get("type", "")
        sender = msg.get("sender_handle", msg.get("updated_by", "?"))

        try:
            data = (
                json_module.loads(msg.get("content", "{}"))
                if isinstance(msg.get("content"), str)
                else msg
            )
        except (json_module.JSONDecodeError, TypeError):
            data = msg

        if mtype == "coordination_join":
            intent = data.get("intent")
            handle = data.get("handle", sender)
            suffix = f" — [dim]{intent}[/]" if intent else ""
            return f"  {ts()}  [cyan]{handle}[/] joined{suffix}"

        if mtype == "coordination_start":
            n = data.get("agent_count", "?")
            return f"\n  {ts()}  [bold cyan]session started[/] — {n} agents joined\n"

        if mtype == "coordination_tick":
            # SSTP envelope: action fields live under data["payload"]
            if "payload" in data and isinstance(data["payload"], dict):
                data = data["payload"]
            round_num = data.get("round", "?")
            kind = data.get("kind")
            if kind == "negotiate":
                action = data.get("action", "propose")
                participant = data.get("participant_id", "?")
                if action == "propose":
                    issue_options = data.get("issue_options") or _ISSUE_OPTIONS
                    header = f"\n  {ts()}  [bold magenta]CognitiveEngine[/] [dim]→[/] [cyan]{participant}[/]  [bold cyan]round {round_num}[/] — propose your offer:"
                    if round_num == 1:
                        header = f"\n  {ts()}  [bold magenta]CognitiveEngine[/] analyzed agent intents and generated negotiation issues and options.\n{header}"
                    lines = [header]
                    for k, v in issue_options.items():
                        lines.append(f"              [bold white]{k}[/]")
                        opts = v if isinstance(v, list) else [str(v)]
                        for i, opt in enumerate(opts, 1):
                            lines.append(f"                [dim]{i}.[/] {opt}")
                    return "\n".join(lines)
                if action == "respond":
                    offer = data.get("current_offer") or {}
                    proposer = data.get("proposer_id", "?")
                    lines = [
                        f"\n  {ts()}  [bold magenta]CognitiveEngine[/] [dim]→[/] [cyan]{participant}[/]  [bold cyan]round {round_num}[/] — respond to offer from {proposer}:"
                    ]
                    for k, v in offer.items():
                        lines.append(f"              [dim]{k}:[/] {v}")
                    return "\n".join(lines)
                return f"\n  {ts()}  [bold magenta]CognitiveEngine[/] [dim]→[/] [cyan]{participant}[/]  [bold cyan]round {round_num}[/] — {action}"
            return f"\n  {ts()}  [bold cyan]tick {round_num}[/]"

        if mtype == "coordination_consensus":
            plan = data.get("plan", "")
            assignments = data.get("assignments", {})
            lines = [f"\n  {ts()}  [bold green]consensus[/]"]
            if plan:
                lines.append(f"              [dim]plan:[/] {plan}")
            for handle, task in assignments.items():
                lines.append(f"              [cyan]{handle}[/]: {task}")
            return "\n".join(lines)

        if mtype == "memory_changed":
            key = data.get("key", "?")
            version = data.get("version", "?")
            by = data.get("updated_by", "?")
            return f"  {ts()}  [yellow]memory[/] [dim]{key}[/] v{version} by {by}"

        if mtype == "synthesis_complete":
            skey = data.get("synthesis_key", "?")
            return f"  {ts()}  [bold green]synthesis[/] → {skey}"

        if mtype == "delegate":
            recipient = msg.get("recipient_handle", "?")
            content = msg.get("content", "")
            return f"  {ts()}  [magenta]{sender}[/] [dim]→[/] [cyan]{recipient}[/]: {content}"

        if mtype in ("direct", "broadcast", "announce"):
            content = msg.get("content", "")
            color = "yellow" if mtype == "broadcast" else "blue"
            return f"  {ts()}  [{color}]{sender}[/]: {content}"

        return None

    # Fetch room metadata for the header
    room_meta = ""
    try:
        resp = httpx.get(f"{config.server.api_url}/rooms/{room_name}", timeout=5)
        if resp.status_code == 200:
            room = resp.json()
            state = room.get("coordination_state", "idle")
            trigger = room.get("trigger_config")
            trigger_str = ""
            if trigger:
                trigger_str = f"  trigger={trigger.get('type', '?')}"
                if trigger.get("min_contributions"):
                    trigger_str += f":{trigger['min_contributions']}"
            room_meta = f"[dim]state=[/]{state}{trigger_str}"
    except Exception:
        pass

    # Header
    header = Table.grid(padding=(0, 2))
    header.add_row(
        Text(room_name, style="bold cyan"),
        Text("Ctrl+C to stop", style="dim"),
    )
    console.print()
    console.print(
        Panel(
            f"[bold]{room_name}[/]\n{room_meta}" if room_meta else f"[bold]{room_name}[/]",
            title="[dim]watching[/]",
            border_style="dim",
            width=60,
            padding=(0, 2),
        )
    )

    url = f"{config.server.api_url}/rooms/{room_name}/messages/stream"
    start = time.time()

    with httpx.Client(timeout=None) as http, http.stream("GET", url) as response:
        for line in response.iter_lines():
            if timeout > 0 and (time.time() - start) >= timeout:
                console.print(f"\n  [dim]Timeout after {timeout}s[/]")
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
                    console.print(rendered, highlight=False)


@doc_ref(
    usage="mycelium watch [room]",
    desc="Stream live room activity via SSE. Messages appear in real time as other agents write.",
    group="other",
)
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


@doc_ref(
    usage="mycelium room post <room> --agent <handle> --response <text>",
    desc="Post a raw message to a room (triggers NOTIFY). Advanced use.",
    group="room",
)
@app.command("post")
def post(
    ctx: typer.Context,
    session_id: str = typer.Argument(..., help="Room session/name"),
    agent: str = typer.Option(..., "--agent", "-a", help="Agent handle sending the response"),
    response_text: str = typer.Option(..., "--response", "-r", help="Response message text"),
) -> None:
    """
    Post a message to a room (triggers NOTIFY).

    Examples:
        mycelium room post my-room --agent alpha#a1b2 --response "Task complete"
    """
    try:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False  # noqa: F841
        json_output = ctx.obj.get("json", False) if ctx.obj else False

        config = MyceliumConfig.load()

        from mycelium_backend_client.api.messages import (
            send_message_rooms_room_name_messages_post as send_api,
        )
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


@doc_ref(
    usage="mycelium room delegate <room> --to <handle> --task <description>",
    desc="Delegate a task to another agent in a room.",
    group="room",
)
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

        from mycelium_backend_client.api.messages import (
            send_message_rooms_room_name_messages_post as send_api,
        )
        from mycelium_backend_client.models import MessageCreate

        with _typed_client(config) as client:
            body = MessageCreate(
                sender_handle=sender, message_type="delegate", content=task, recipient_handle=to
            )
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
