# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Room management commands for Mycelium CLI.

Commands:
- (default): Show current active room
- ls: List rooms
- create: Create a new room
- use: Switch active room context
- delete: Delete a room
- watch: Stream a room's messages live
- send: Broadcast a chat message into a room (an @handle mention summons a
  registered engine, e.g. @aligner)
- messages: Show a room's recent messages
- export: Write a room's whole history to local JSON lines
- delegate: Delegate a task to an agent in a room
- clone: Clone a room from a remote backend instance
"""

import json as json_module
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import typer
from rich.markup import escape

from mycelium import chat
from mycelium.cli_options import acts_as, confirms, emits_json, in_room, paged
from mycelium.client import answered, hub_client, hub_error_detail
from mycelium.client import typed_client as _typed_client
from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref
from mycelium.error_handler import print_error
from mycelium.exceptions import MyceliumError
from mycelium.identity import resolve_actor
from mycelium.names import who
from mycelium.slim.message_format import room_episode
from mycelium.text_input import takes_text
from mycelium_backend_client.errors import UnexpectedStatus

if TYPE_CHECKING:
    from mycelium.commands.swarm import LiveView
    from mycelium_backend_client.models import RoomMembers, RoomPresenceRead

# The "raise-up" whitelist: message types promoted onto the primary channel
# surface (here, `room watch`'s live stream) rather than staying inspector-only.
# Must mirror contracts/channel-surface.json's `raise_up_types` byte-for-byte; the
# frontend (mycelium-frontend/src/components/event-stream.tsx) carries an
# independent copy, and tests/test_channel_surface_contract.py asserts both stay in
# sync with the contract so the two surfaces can't silently drift apart.
# (`room watch` also renders CLI-native detail: ticks, session start, raw
# memory_changed; that has no frontend-inspector equivalent to hide behind;
# that detail is intentionally outside this shared list.)
RAISE_UP_TYPES = frozenset(
    {
        "coordination_join",
        "coordination_consensus",
        "l9_knowledge",
    }
)


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

        from mycelium_backend_client.api.rooms import list_rooms_api_rooms_get as list_api

        with _typed_client(config) as client:
            rooms = answered(
                list_api.sync_detailed(
                    client=client, name=active_room, limit=1, viewer=_viewer(config)
                ),
                list,
            )

        if not rooms:
            typer.secho(f"Active room '{active_room}' not found on server.", fg=typer.colors.RED)
            raise typer.Exit(1)

        room = rooms[0]
        if json_output:
            typer.echo(json_module.dumps(room.to_dict(), indent=2, default=str))
        else:
            typer.secho(f"Current Room: {room.name}", fg=typer.colors.GREEN, bold=True)
            typer.echo(f"  ID:      {room.id}")
            typer.echo(f"  Created: {room.created_at.isoformat()[:10]}")

    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


def _viewer(config: MyceliumConfig) -> str | None:
    """Who is listing, so the hub includes their private rooms."""
    return resolve_actor(config, require=False, fallback="") or None


@doc_ref(
    usage="mycelium room ls",
    desc="List the shared rooms and your private ones.",
    group="room",
)
@app.command("ls")
@paged()
@emits_json()
def list_rooms(
    ctx: typer.Context,
    limit: int = 20,
    name: str | None = typer.Option(None, "--name", help="Only rooms with this name."),
) -> None:
    """List available rooms."""
    try:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False  # noqa: F841
        json_output = ctx.obj.get("json", False) if ctx.obj else False

        config = MyceliumConfig.load()

        params: dict[str, str | int] = {"limit": limit}
        if name:
            params["name"] = name

        from mycelium_backend_client.api.rooms import list_rooms_api_rooms_get as list_api

        with _typed_client(config) as client:
            rooms = answered(
                list_api.sync_detailed(
                    client=client, name=name, limit=limit, viewer=_viewer(config)
                ),
                list,
            )

        if json_output:
            typer.echo(json_module.dumps([r.to_dict() for r in rooms], indent=2, default=str))
        else:
            if not rooms:
                typer.echo("No rooms found.")
                typer.echo("Create a room with: mycelium room create <name>")
                return

            active_room = config.get_active_room()
            typer.secho(f"Rooms ({len(rooms)})", bold=True)
            typer.echo("")

            for room in rooms:
                is_active = room.name == active_room
                created_at = room.created_at.isoformat()[:10]
                private = ", private" if room.is_public is False else ""
                if is_active:
                    typer.secho(f"  * {room.name}", fg=typer.colors.GREEN, bold=True, nl=False)
                    typer.echo(f"  (created {created_at}{private})")
                else:
                    typer.echo(f"    {room.name}  (created {created_at}{private})")

            typer.echo("")
            typer.echo("Use 'mycelium room use <name>' to set the active room")

    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


@doc_ref(
    usage="mycelium room create <name> [--private]",
    desc=(
        "Create a new persistent coordination room. <code>--private</code> lists it only"
        " for you (and members you add); anyone who knows its name can still open it."
    ),
    group="room",
)
@app.command()
@acts_as("owner", optional=True)
@emits_json()
def create(
    ctx: typer.Context,
    name: str | None = typer.Argument(None, help="Room name"),
    public: bool = typer.Option(
        True,
        "--public/--private",
        help="Private rooms are listed only for you. It hides the room; it doesn't lock it.",
    ),
    owner: str | None = None,
) -> None:
    """Create a new room."""
    try:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False  # noqa: F841
        json_output = ctx.obj.get("json", False) if ctx.obj else False

        config = MyceliumConfig.load()

        if name is None:
            name = typer.prompt("Room name")

        from mycelium_backend_client.api.rooms import create_room_api_rooms_post as create_api
        from mycelium_backend_client.models import RoomCreate, RoomRead

        with _typed_client(config) as client:
            # A private room is listed for its owner, so it needs one; the hub
            # says so plainly when nobody could be named.
            body = RoomCreate(name=name, is_public=public, owner=None if public else owner)
            created = answered(create_api.sync_detailed(client=client, body=body), RoomRead)

        # The hub owns the room dir + store; a spoke keeps no local copy. Any
        # local dir an agent needs (e.g. agents/ for a manifest) is created
        # lazily on write, so nothing to pre-create here.
        if json_output:
            typer.echo(json_module.dumps(created.to_dict(), indent=2, default=str))
        else:
            typer.secho(
                f"Created room: {created.name}",
                fg=typer.colors.GREEN,
            )
            typer.echo(f"  ID:      {created.id}")
            typer.echo(f"  Created: {created.created_at.isoformat()[:10]}")
            typer.echo("")
            typer.echo(f"  Run 'mycelium room use {name}' to make it your active room")

    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


@doc_ref(
    usage="mycelium room use <name>",
    desc="Switch active room. Subsequent <code>memory</code> and <code>message</code> commands use this room by default.",
    group="room",
)
@app.command("use")
@emits_json()
def use(
    ctx: typer.Context,
    room_name: str = typer.Argument(..., help="Room name to set as active"),
) -> None:
    """Switch active room for this project."""
    try:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False  # noqa: F841
        json_output = ctx.obj.get("json", False) if ctx.obj else False

        config = MyceliumConfig.load()

        from mycelium_backend_client.api.rooms import list_rooms_api_rooms_get as list_api

        with _typed_client(config) as client:
            rooms = answered(list_api.sync_detailed(client=client, name=room_name, limit=1), list)

            if not rooms:
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
                "Next: post a position with 'mycelium respond -H <handle> \"<position>\"', "
                "then summon the mediator with 'mycelium engine invoke aligner'"
            )

    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


@doc_ref(
    usage="mycelium room delete <name> [<name> ...] [--yes]",
    desc="Delete one or more rooms and all their data (memories, sessions, messages).",
    group="room",
)
@app.command()
@confirms("force", also_force=True)
def delete(
    ctx: typer.Context,
    room_names: list[str] = typer.Argument(..., help="Room name(s) to delete"),
    force: bool = False,
) -> None:
    """Delete one or more rooms."""
    try:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False  # noqa: F841
        config = MyceliumConfig.load()

        if not force:
            if len(room_names) == 1:
                prompt = f"Delete room '{room_names[0]}'? This cannot be undone."
            else:
                names_list = ", ".join(f"'{n}'" for n in room_names)
                prompt = f"Delete {len(room_names)} rooms ({names_list})? This cannot be undone."
            if not typer.confirm(prompt):
                typer.echo("Canceled.")
                raise typer.Exit(0)

        from mycelium_backend_client.api.rooms import (
            delete_room_api_rooms_room_name_delete as delete_api,
        )

        for room_name in room_names:
            with _typed_client(config) as client:
                resp = delete_api.sync_detailed(room_name=room_name, client=client)
            if resp.status_code >= 400:  # noqa: PLR2004
                raise UnexpectedStatus(resp.status_code, resp.content)

            typer.secho(f"Room '{room_name}' deleted.", fg=typer.colors.GREEN)

    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


@doc_ref(
    usage="mycelium room clone <room-name> [--from <api-url>]",
    desc="Clone a room from a remote backend: fetches all memories via HTTP and writes them locally.",
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
    from mycelium.filesystem import (
        ensure_room_structure,
        get_mycelium_dir,
        write_hub_memories,
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

        from mycelium_backend_client.api.memory import (
            list_memories_api_rooms_room_name_memory_get as list_api,
        )

        with _typed_client(config, base_url=api_url, timeout=60) as client:
            resp = list_api.sync_detailed(room_name, client=client, limit=1000)
        try:
            memories = answered(resp, list)
        except UnexpectedStatus:
            raise MyceliumError(
                hub_error_detail(resp.content) or f"the hub answered {resp.status_code}"
            ) from None

        ensure_room_structure(target)

        written, skipped = write_hub_memories(target, memories)
        for why in skipped:
            typer.echo(f"Skipped: {why}", err=True)

        typer.secho(f"Cloned room: {room_name} ({written} memories)", fg=typer.colors.GREEN)

        config.rooms.active = room_name
        config.save()

        # Reindex local copy against the configured backend
        typer.echo("Re-indexing...")
        try:
            from mycelium_backend_client.api.rooms import (
                reindex_room_api_rooms_room_name_reindex_post as reindex_api,
            )
            from mycelium_backend_client.models import RoomReindexRead

            with _typed_client(config, timeout=120) as client:
                stats = answered(
                    reindex_api.sync_detailed(room_name, client=client), RoomReindexRead
                )
            typer.echo(f"  Indexed {stats.indexed} memories")
        except Exception:
            typer.echo(
                "[dim]  Reindex skipped. Run 'mycelium memory reindex' when backend is available[/dim]"
            )

        typer.echo(f"\nRoom '{room_name}' is now active.")

    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


def _one_room(positional: str | None, flag: str | None) -> str | None:
    """The room a command was given, as its argument or as ``--room``.

    Both spellings are accepted because every other command takes ``--room``,
    and the prompts agents get are written that way. Two different rooms is a
    mistake, not a choice to make silently.
    """
    if positional and flag and positional != flag:
        raise typer.BadParameter(f"two rooms given: {positional} and --room {flag}")
    return positional or flag


def _resolve_room(config: MyceliumConfig, channel: str | None = None) -> str:
    """
    Resolve the coordination room name.

    The order is ``caller.room``'s: the --room flag, MYCELIUM_ROOM_ID, this
    folder's membership (``mycelium join``), then the active room ('mycelium
    room use'). With none of them it's an error.
    """
    from mycelium.cli_options import resolve_room

    return resolve_room(config, channel)


# Known stub options for NegMAS SAO issues (mirrors options_generation.py)
_ISSUE_OPTIONS: dict[str, list[str]] = {
    "budget": ["minimal", "low", "medium", "high", "uncapped"],
    "timeline": ["express", "short", "standard", "extended", "long"],
    "scope": ["core", "standard", "extended", "full"],
    "quality": ["basic", "standard", "premium"],
}


def _fmt_metric(value: object) -> str:
    """Format a metric value: 2 decimals for numbers, str() otherwise."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:.2f}"
    return str(value)


def _team_prior_line(data: dict, indent: str) -> str | None:
    """Render the optional ``team_prior`` tick field as a human-readable line.

    Example: ``team prior: 0.72 (weight 0.85, 3 episodes)``
    """
    prior = data.get("team_prior")
    if not isinstance(prior, dict):
        return None
    return (
        f"{indent}team prior: {_fmt_metric(prior.get('confidence'))} "
        f"(weight {_fmt_metric(prior.get('provenance_weight'))}, "
        f"{prior.get('episode_count')} episodes)"
    )


def _consensus_quality_line(data: dict, indent: str) -> str | None:
    """Render the optional consensus ``metrics`` block as a human-readable line.

    Example: ``quality: MPC 0.82 · GAR 0.75 · SCR 0.25``
    """
    metrics = data.get("metrics")
    if not isinstance(metrics, dict):
        return None
    return (
        f"{indent}quality: MPC {_fmt_metric(metrics.get('mpc'))} "
        f"· GAR {_fmt_metric(metrics.get('gar'))} "
        f"· SCR {_fmt_metric(metrics.get('scr'))}"
    )


def _agent_owner_map(room_name: str) -> dict[str, str]:
    """Map each agent handle to its owner, for agents that declare one.

    Resolved from the room's manifests so attribution reflects current
    ownership, not a value stamped on the message.
    """
    try:
        from mycelium.commands.agent import _room_manifests

        return {m.handle: m.owner for m in _room_manifests(room_name) if m.owner}
    except Exception:  # noqa: BLE001, attribution is best-effort, never fatal
        return {}


def frame_episode(mtype: str, msg: dict, data: dict) -> str | None:
    """The episode a tail frame belongs to, however it reached the tail.

    Chat arrives two ways — the history replay's folded row, which carries the
    episode as a plain field, and the live stream's raw message, which
    carries it in the header — so the question "which conversation is this?" has
    to be asked of both shapes to be worth asking at all.
    """
    if mtype == "l9_exchange":
        episode = ((data.get("l9", {}).get("header", {})).get("message", {})).get("episode")
    else:
        episode = msg.get("episode") or data.get("episode")
    return episode if isinstance(episode, str) and episode else None


def in_a_thread(room: str, mtype: str, msg: dict, data: dict) -> bool:
    """Whether this frame's prose belongs to a thread rather than to the room.

    The room's account of a thread is the **ping** — that a task moved, not what
    was said in it. So the prose itself does not also draw here: printing both
    would be the argument plus a line saying an argument happened, which is
    worse than either. It is not lost, it is placed; ``board messages`` reads it.

    A frame with no episode at all predates threading and is the room's.
    """
    episode = frame_episode(mtype, msg, data)
    return episode is not None and episode != room_episode(room)


def _ping_line(data: dict, stamp: str) -> str | None:
    """Render a thread's activity as the one line it is meant to be.

    A ping says a task moved and deliberately not what was said in it — that is
    how the room stays readable while agents argue inside a row. So the tail
    gets the thread's short id, who wrote, and the way to read it, rather than
    an echo of the prose.

    One line per ping, not a coalesced counter: a tail is a tail, and rewriting
    a line that has already scrolled past is what this surface declines to do
    for an amendment too.
    """
    from mycelium.slim.message_format import ping_of

    ping = ping_of(data)
    if ping is None:
        return None
    thread = str(ping.get("episode", "")).rsplit(":", 1)[-1] or "?"
    who = ping.get("sender")
    by = f" [dim]· @{who}[/]" if who else ""
    return (
        f"  {stamp}  [dim]·[/] activity in [cyan]{thread}[/]{by} [dim]· board messages {thread}[/]"
    )


def chat_line(mtype: str, msg: dict, data: dict, sender: str, stamp: str, own: str) -> str | None:
    """Render one chat message for the live tail, or None if it carries no prose.

    Chat reaches the tail two ways: the history replay hands back a plain
    ``broadcast`` the backend has already folded (so a revised message arrives as
    its newest text, stamped ``edited_at``), while the live stream carries the raw
    message — including an amendment, which arrives as the message it is. A
    tail is a tail: it shows the amendment as it lands rather than rewriting a line
    that already scrolled past, but marks it an edit and names what it revises.
    """
    if mtype == "l9_exchange":
        if ping := _ping_line(data, stamp):
            return ping
        content = data.get("content", "")
        if not content:
            return None  # presence/control payloads carry no prose
        header = data.get("l9", {}).get("header", {})
        if header.get("subkind") == "amend":
            parents = header.get("message", {}).get("parents") or []
            revises = f" [dim]{parents[0][:8]}[/]" if parents else ""
            return f"  {stamp}  [yellow]{sender}[/]{own} [dim]✎ edits[/]{revises}: {content}"
        return f"  {stamp}  [yellow]{sender}[/]{own}: {content}"

    content = msg.get("content", "")
    color = "yellow" if mtype == "broadcast" else "blue"
    edited = " [dim](edited)[/]" if msg.get("edited_at") else ""
    return f"  {stamp}  [{color}]{sender}[/]{own}: {content}{edited}"


def _thread_view(config: MyceliumConfig, room_name: str) -> "LiveView":
    """``swarm``'s live view over the whole room: every thread's messages, each
    labeled with its task, and the board's notices. Each thread's task is
    known up front from the board, and kept current by the notices."""
    from mycelium.chat import thread_tasks
    from mycelium.commands.swarm import LiveView

    view = LiveView()
    for episode, (key, title) in thread_tasks(config, room_name).items():
        view.titles[episode] = title
        view.keys[episode] = key
    return view


def _thread_line(view: "LiveView", msg: dict, data: dict) -> str | None:
    """A thread's message or a board notice, as ``view`` draws it. A message
    read back from history carries its text bare, where the stream carries the
    whole envelope, so it's handed over the way the stream would."""
    streamed = data is not msg and msg.get("message_type") == "l9_exchange"
    frame = (
        msg
        if streamed
        else {
            **msg,
            "message_type": "l9_exchange",
            "content": json_module.dumps({"content": str(msg.get("content") or "")}),
        }
    )
    return view.render(frame)


def _watch_room(
    config: MyceliumConfig, room_name: str, timeout: int, *, everything: bool = False
) -> None:
    """Core SSE watch loop: pretty-renders coordination and memory events.

    ``everything`` also follows every thread's messages and the board's
    notices, which the room's own view leaves to ``board messages``."""
    import time

    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    from mycelium.slim.message_format import payload_type_of

    console = Console()
    owners = _agent_owner_map(room_name)
    view = _thread_view(config, room_name) if everything else None

    def ts() -> str:
        return f"[dim]{time.strftime('%H:%M:%S')}[/]"

    def own_tag(handle: str) -> str:
        """Owner attribution for an owned agent, else empty."""
        owner = owners.get(handle)
        return f" [dim]owned by @{owner}[/]" if owner else ""

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
            suffix = f": [dim]{intent}[/]" if intent else ""
            return f"  {ts()}  [cyan]{handle}[/] joined{suffix}"

        if mtype == "coordination_start":
            n = data.get("agent_count", "?")
            return f"\n  {ts()}  [bold cyan]session started[/] ({n} agents joined)\n"

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
                    header = f"\n  {ts()}  [bold magenta]aligner[/] [dim]→[/] [cyan]{participant}[/]  [bold cyan]round {round_num}[/]: propose your offer:"
                    if round_num == 1:
                        header = f"\n  {ts()}  [bold magenta]aligner[/] analyzed agent intents and generated negotiation issues and options.\n{header}"
                    lines = [header]
                    prior_line = _team_prior_line(data, "              ")
                    if prior_line:
                        lines.append(f"[dim]{prior_line}[/]")
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
                        f"\n  {ts()}  [bold magenta]aligner[/] [dim]→[/] [cyan]{participant}[/]  [bold cyan]round {round_num}[/]: respond to offer from {proposer}:"
                    ]
                    prior_line = _team_prior_line(data, "              ")
                    if prior_line:
                        lines.append(f"[dim]{prior_line}[/]")
                    for k, v in offer.items():
                        lines.append(f"              [dim]{k}:[/] {v}")
                    return "\n".join(lines)
                return f"\n  {ts()}  [bold magenta]aligner[/] [dim]→[/] [cyan]{participant}[/]  [bold cyan]round {round_num}[/]: {action}"
            return f"\n  {ts()}  [bold cyan]tick {round_num}[/]"

        if mtype == "coordination_consensus":
            assignments = data.get("assignments", {})
            lines = [f"\n  {ts()}  [bold green]consensus[/]"]
            tasks = data.get("tasks") or []
            if tasks:
                lines.append(f"              [dim]work:[/] {', '.join(tasks)}")
            for handle, task in assignments.items():
                lines.append(f"              [cyan]{handle}[/]: {task}")
            quality_line = _consensus_quality_line(data, "              ")
            if quality_line:
                lines.append(f"[dim]{quality_line}[/]")
            return "\n".join(lines)

        if mtype == "l9_knowledge":
            message_payload = data.get("l9", {}).get("payload", {}).get("data", {})
            key = message_payload.get("key", "memory")
            by = message_payload.get("updated_by")
            text = data.get("content") or f"{key} updated"
            suffix = f" [dim]by {by}[/]" if by else ""
            return f"  {ts()}  [yellow]knowledge[/] {text}{suffix}"

        if mtype == "memory_changed":
            key = data.get("key", "?")
            version = data.get("version", "?")
            by = data.get("updated_by", "?")
            return f"  {ts()}  [yellow]memory[/] [dim]{key}[/] v{version} by {by}"

        if mtype == "delegate":
            recipient = msg.get("recipient_handle", "?")
            content = msg.get("content", "")
            return f"  {ts()}  [magenta]{escape(who(sender))}[/]{own_tag(sender)} [dim]→[/] [cyan]{recipient}[/]: {content}"

        if mtype in ("l9_exchange", "direct", "broadcast", "announce"):
            if view is not None:
                kind = payload_type_of(data) if isinstance(data, dict) else None
                if kind == "notice":
                    return view.render(msg)
                if kind == "ping":
                    return None  # the thread's own message draws instead
                if in_a_thread(room_name, mtype, msg, data):
                    return _thread_line(view, msg, data)
            if in_a_thread(room_name, mtype, msg, data):
                return None
            # The person's name beside their handle; escaped, since a name is
            # free text and Rich would read brackets in it as markup.
            return chat_line(mtype, msg, data, escape(who(sender)), ts(), own_tag(sender))

        return None

    room_meta = ""

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

    # Replay recent history so events that fired before SSE connected are visible.
    # coordination_join events are NOTIFY-only (not persisted), so we synthesize
    # them from the sessions list to ensure all participants are shown.
    from mycelium_backend_client.api.messages import (
        list_messages_api_rooms_room_name_messages_get as messages_api,
    )
    from mycelium_backend_client.api.sessions import (
        list_sessions_api_rooms_room_name_sessions_get as sessions_api,
    )
    from mycelium_backend_client.models import MessageListResponse, ParticipantListResponse

    try:
        with _typed_client(config, timeout=10, raise_on_unexpected_status=False) as client:
            joined = sessions_api.sync_detailed(room_name, client=client).parsed
        if isinstance(joined, ParticipantListResponse):
            for p in joined.participants:
                rendered = render(
                    {
                        "message_type": "coordination_join",
                        "sender_handle": p.agent_handle,
                        "content": json_module.dumps(
                            {"handle": p.agent_handle, "intent": p.intent or None}
                        ),
                    }
                )
                if rendered:
                    console.print(rendered, highlight=False)
    except Exception:
        pass

    try:
        with _typed_client(config, timeout=10, raise_on_unexpected_status=False) as client:
            # Unfiltered: filtering by ``?episode=<live>`` would drop messages
            # from before threading was added, hiding history silently.
            # ``render`` applies the same rule to the replay as to the live
            # stream, where an untagged row is the room's.
            history = messages_api.sync_detailed(room_name, client=client, limit=50).parsed
        if isinstance(history, MessageListResponse):
            # ``render`` draws the live stream's frames too, so each message is
            # handed to it as the record the stream would carry.
            for msg in reversed(history.messages):
                rendered = render(msg.to_dict())
                if rendered:
                    console.print(rendered, highlight=False)
    except Exception:
        pass

    stream_path = f"/api/rooms/{room_name}/messages/stream"
    start = time.time()

    with (
        hub_client(config, timeout=None) as http,
        http.stream("GET", stream_path) as response,
    ):
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
    usage="mycelium watch [<room> | --room <room>] [--all]",
    desc=(
        "Stream live room activity via SSE. Messages appear in real time as other agents "
        "write. <code>--all</code> follows every thread and board change too."
    ),
    group="other",
)
@app.command()
@in_room("room_opt", resolve=False)
def watch(
    ctx: typer.Context,
    room_name: str | None = typer.Argument(None, help="Room to watch (default: active room)"),
    room_opt: str | None = None,
    timeout: int = typer.Option(0, "--timeout", "-t", help="Timeout in seconds (0=no timeout)"),
    everything: bool = typer.Option(
        False,
        "--all",
        help="Also follow every thread's messages, labeled with their task, and board changes.",
    ),
) -> None:
    """
    Stream live messages from a room.

    Auto-resolves the active room (no argument needed).
    Renders coordination events, agent joins, ticks, and consensus.

    The room's own view shows a line when a thread moves, not what was said
    in it. With --all you follow everything as it happens: each thread's
    messages, labeled with their task and cut to a few lines, and each
    board change (filed, taken, resolved) as a line of its own.

    Examples:
        mycelium room watch
        mycelium room watch my-room
        mycelium room watch --all
        mycelium room watch --timeout 120
    """
    try:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False  # noqa: F841
        config = MyceliumConfig.load()
        name = _one_room(room_name, room_opt) or _resolve_room(config)
        _watch_room(config, name, timeout, everything=everything)
    except KeyboardInterrupt:
        typer.echo("\n  [Stopped]")
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


@doc_ref(
    usage='mycelium room send "<content>" | --body "<markdown>" | --file <path> [--room <room>] [--handle <handle>]',
    desc="Send an addressed chat message into a room, in markdown. Use <code>@handle</code> mentions to direct it to specific agents.",
    group="room",
)
@app.command("send")
@takes_text("content", "The message, in markdown. @handle mentions address agents.", noun="message")
@in_room()
@acts_as()
@emits_json()
def send(
    ctx: typer.Context,
    content: str = typer.Argument(
        ...,
        help='Message content. Use @handle mentions to address specific agents, e.g. "@avery-agent ping".',
    ),
    room: str | None = None,
    handle: str | None = None,
) -> None:
    """
    Send an addressed chat message into a room (cross-agent DM).

    Drops a broadcast message into the room's message stream. Agents in the
    room will receive it if the content @-mentions them.

    Use this for:
      - Addressed DMs between agents in the same room
      - Seeding a scenario for a group of agents (facilitator posts, agents respond)
      - One-way notifications without expecting a reply loop

    To participate in a room's coordination as a member (receive an addressed
    turn and reply as a position), use `mycelium await` / `mycelium respond`
    instead.

    Examples:
        mycelium room send "@avery-agent please review the cache config"
        mycelium room send --room design-review --handle arnold "@rowan-agent thoughts on the API proposal?"
        mycelium room send "@avery-agent @rowan-agent sync at 3pm re: sprint priorities"
    """
    try:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False  # noqa: F841
        json_output = ctx.obj.get("json", False) if ctx.obj else False

        config = MyceliumConfig.load()
        room_name = _resolve_room(config, room)
        sender_handle = handle or config.get_current_identity()
        chat.post(
            config,
            room_name,
            sender_handle=sender_handle,
            content=content,
            json_output=json_output,
        )

    except (typer.Exit, typer.Abort):
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


@doc_ref(
    usage='mycelium room amend <message-id> "<new content>" | --body "<markdown>" | --file <path> [--room <room>] [--handle <handle>]',
    desc="Revise a message you sent. The amendment is posted as its own message; the room reads the newest text, marked edited.",
    group="room",
)
@app.command("amend")
@takes_text("content", "The revised message, in markdown.", noun="message")
@in_room()
@acts_as()
@emits_json()
def amend(
    ctx: typer.Context,
    message_id: str = typer.Argument(
        ..., help="Id of the message to revise (the short id `room messages` prints is enough)"
    ),
    content: str = typer.Argument(..., help="The revised message text"),
    room: str | None = None,
    handle: str | None = None,
) -> None:
    """
    Revise a message you already sent.

    Editing here is additive, not destructive: the revision is posted as its own
    message pointing at the one it revises, so the room's transcript keeps every
    version and nothing is rewritten. What readers see is the folded result — the
    newest text, marked edited.

    Only the message's own sender can amend it. Get the id from
    `mycelium room messages` (the short id after the message type).

    Examples:
        mycelium room amend a1b2c3d4 "the cache TTL is 300s, not 30s"
        mycelium room amend a1b2c3d4 "corrected numbers" --room design-review
    """
    try:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False  # noqa: F841
        json_output = ctx.obj.get("json", False) if ctx.obj else False

        config = MyceliumConfig.load()
        room_name = _resolve_room(config, room)
        sender_handle = handle or config.get_current_identity()

        from mycelium_backend_client.api.messages import (
            amend_message_api_rooms_room_name_messages_message_id_amend_post as amend_api,
        )
        from mycelium_backend_client.models import MessageAmend, MessageAmended

        with _typed_client(config) as client:
            body = MessageAmend(content=content, sender_handle=sender_handle)
            resp = amend_api.sync_detailed(
                room_name=room_name, message_id=message_id, client=client, body=body
            )
        # No such message, someone else's, or a body the hub won't take is said
        # here; any other refusal goes to print_error.
        said_here = resp.status_code in (403, 404, 422)
        result = resp.parsed if said_here else answered(resp, MessageAmended)

        if not isinstance(result, MessageAmended):
            typer.secho(
                f"  Could not amend {message_id} in {room_name} "
                "(no such message, or it isn't yours).",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)

        if json_output:
            typer.echo(json_module.dumps(result.to_dict(), indent=2, default=str))
            return

        where = f"the thread of “{result.task}”" if isinstance(result.task, str) else room_name
        # Not `%-d`: Windows' strftime refuses it.
        at = result.created_at.astimezone()
        posted = f"{at:%b} {at.day}, {at:%H:%M}"
        typer.echo(f"  ✎  {sender_handle} edited {message_id} in {where} (first posted {posted})")
        for line in amend_report(result.replaced, content):
            typer.secho(line.text, fg=typer.colors.YELLOW if line.warn else None)

    except (typer.Exit, typer.Abort):
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


@dataclass(frozen=True)
class ReportLine:
    text: str
    warn: bool = False


#: How much of each text an amend shows: a short message whole, a long one's first lines.
_AMEND_LINES = 3
_AMEND_WIDTH = 100


def _shown(text: str, *, whole: bool = False) -> list[str]:
    if whole:
        # Exactly as written, blank lines included, so it can be copied back.
        return text.strip().splitlines() or [""]
    lines = [ln.rstrip() for ln in text.strip().splitlines() if ln.strip()]
    shown = [
        ln if len(ln) <= _AMEND_WIDTH else ln[: _AMEND_WIDTH - 1] + "…"
        for ln in lines[:_AMEND_LINES]
    ]
    if len(lines) > _AMEND_LINES:
        shown.append(f"… and {len(lines) - _AMEND_LINES} more lines")
    return shown or [""]


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9']+", text.lower()) if len(w) > 3}


def little_in_common(old: str, new: str) -> bool:
    """Whether two versions of a message share almost none of their words:
    what an amend of the wrong message looks like, rather than a correction."""
    before, after = _words(old), _words(new)
    if not before or not after:
        return False
    return len(before & after) / len(before | after) < 0.2


def amend_report(old: str, new: str) -> list[ReportLine]:
    """What an amend replaced, above what it wrote, and a warning when the two
    have little in common, so a wrong edit shows on the spot. With the warning,
    the replaced text is shown whole: it's what puts the message back."""
    wrong = little_in_common(old, new)
    lines = [
        ReportLine(f"     Replaced: {ln}" if i == 0 else f"               {ln}")
        for i, ln in enumerate(_shown(old, whole=wrong))
    ]
    lines += [
        ReportLine(f"     With:     {ln}" if i == 0 else f"               {ln}")
        for i, ln in enumerate(_shown(new))
    ]
    if wrong:
        lines.append(
            ReportLine(
                "     These have little in common. If it's not the message you meant, "
                "amend it again with the replaced text above, in full.",
                warn=True,
            )
        )
    return lines


@doc_ref(
    usage="mycelium room messages [<room> | --room <room>] [--limit N] [--sender <handle>] [--type <type>] [--id <id>] [--before <stamp|age>] [--since <stamp|age>]",
    desc="Read recent messages in a room (point-in-time, newest first), each whole in its own box. Filter with <code>--sender</code> / <code>--type</code>, read one message with <code>--id</code>, and walk back through history with <code>--before</code>.",
    group="room",
)
@app.command("messages")
@in_room("room_opt", resolve=False)
@paged()
@emits_json()
def messages(
    ctx: typer.Context,
    room: str | None = typer.Argument(None, help="Room to read (defaults to active room)"),
    room_opt: str | None = None,
    limit: int = 20,
    sender: str | None = typer.Option(
        None, "--sender", "-s", help="Only messages from this handle"
    ),
    message_type: str | None = typer.Option(
        None, "--type", "-t", help="Only this message type (e.g. direct, broadcast, announce)"
    ),
    message_id: str | None = typer.Option(
        None,
        "--id",
        help="Only the message whose id starts with this (the eight characters a wake names it by)",
    ),
    before: str | None = typer.Option(
        None,
        "--before",
        "-b",
        help="Only messages before this ISO stamp or age (2h, 30m, 1d): the cursor to walk back",
    ),
    since: str | None = typer.Option(
        None, "--since", help="Only messages at/after this ISO stamp or age (2h, 30m, 1d)"
    ),
) -> None:
    """
    Read recent messages in a room: a point-in-time snapshot, newest first.

    Unlike `mycelium room watch` (which streams live), this returns immediately
    with the most recent messages and exits. Handy for scripts and for checking
    whether an agent's reply has landed.

    Each message is printed whole, in a box with its text behind a `│`, so
    where one ends is never in doubt. A wake names a message by the first
    eight characters of its id; `--id` reads that one message.

    History is paged by content, not position: when older messages exist the
    footer names the `--before` cursor that reads the next page back, so a
    walk through a busy room does not shift under messages arriving live.

    Examples:
        mycelium room messages
        mycelium room messages design-review --limit 5
        mycelium room messages cc-e2e --sender cc-x
        mycelium room messages my-room --type broadcast
        mycelium room messages my-room --id 930ecf2c
        mycelium room messages my-room --before 2h
        mycelium room messages my-room --since 2026-09-03T09:00:00Z --before 2026-09-03T12:00:00Z
    """
    try:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False  # noqa: F841
        json_output = ctx.obj.get("json", False) if ctx.obj else False

        config = MyceliumConfig.load()
        room_name = _resolve_room(config, _one_room(room, room_opt))
        stem = f"mycelium room messages {room_name} --limit {limit}"
        if sender:
            stem += f" --sender {sender}"
        if message_type:
            stem += f" --type {message_type}"
        chat.read(
            config,
            room_name,
            limit=limit,
            sender=sender,
            message_type=message_type,
            message_id=message_id,
            since=chat.parse_stamp(since) if since else None,
            before=chat.parse_stamp(before) if before else None,
            older_with=stem,
            empty_note=f"no message with an id starting {message_id}" if message_id else None,
            json_output=json_output,
        )

    except (typer.Exit, typer.Abort):
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


#: How each wake outcome reads, and its color.
WAKE_OUTCOME = {
    "delivered": ("delivered", "green"),
    "dropped": ("dropped", "red"),
    "unreached": ("unreached, reads it on its next await", "yellow"),
    "handed": ("handed over, no word from its runner", "yellow"),
    "skipped": ("skipped, nothing unread asked for it by then", "dim"),
}


@doc_ref(
    usage="mycelium room wakes [<room> | --room <room>] [--agent <handle>] [--limit N]",
    desc="What each wake the hub raised in a room delivered, newest first: who it was for, why, the messages it covered, and whether it reached the agent.",
    group="room",
)
@app.command("wakes")
@in_room("room_opt", resolve=False)
@paged()
@emits_json()
def wakes(
    ctx: typer.Context,
    room: str | None = typer.Argument(None, help="Room to read (defaults to active room)"),
    room_opt: str | None = None,
    agent: str | None = typer.Option(None, "--agent", help="Only wakes for this handle"),
    limit: int = 20,
) -> None:
    """
    What each wake in a room delivered, newest first.

    When an agent misses something, this tells "it was woken with it and didn't
    act" from "it was never woken with it". Each wake names the messages that
    asked for the agent by id (read them with `mycelium room messages`), and
    says whether it was delivered, or dropped and why (no pane bound to the
    agent, or held too long while it worked). A mention of an agent nothing
    runs is unreached: it reads the message on its next await. A wake that,
    by the time it was due, had nothing unread behind it (the agent had read
    or answered it already) is skipped rather than rung for nothing.

    Examples:
        mycelium room wakes
        mycelium room wakes --agent builder --limit 5
        mycelium room wakes design-review --json
    """
    try:
        json_output = ctx.obj.get("json", False) if ctx.obj else False
        config = MyceliumConfig.load()
        room_name = _resolve_room(config, _one_room(room, room_opt))
        from mycelium_backend_client.api.sessions import (
            list_wakes_api_rooms_room_name_sessions_wakes_get as wakes_api,
        )
        from mycelium_backend_client.types import UNSET

        with _typed_client(config, timeout=30, raise_on_unexpected_status=False) as client:
            resp = wakes_api.sync_detailed(
                room_name, client=client, limit=limit, agent=agent.lstrip("@") if agent else UNSET
            )
        try:
            records = answered(resp, list)
        except UnexpectedStatus:
            raise MyceliumError(
                hub_error_detail(resp.content) or f"the hub answered {resp.status_code}"
            ) from None
        if json_output:
            typer.echo(json_module.dumps([r.to_dict() for r in records], indent=2))
            return
        from rich.console import Console

        console = Console()
        if not records:
            console.print(f"[dim]No wakes recorded in {room_name} yet.[/dim]")
            return
        for r in records:
            said, color = WAKE_OUTCOME.get(r.outcome, (r.outcome, "dim"))
            when = (r.at or "")[:19].replace("T", " ")
            sender = f" from @{r.from_}" if r.from_ else ""
            line = f"{when}  @{r.agent}  {r.reason}{sender}  [{color}]{said}[/{color}]"
            if r.why:
                line += f" [dim]({escape(str(r.why))})[/dim]"
            console.print(line)
            if r.messages:
                console.print(f"[dim]    asked in: {', '.join(r.messages)}[/dim]")
    except (typer.Exit, typer.Abort):
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


def _unset(value: object) -> object:
    """A generated model's field, with an unset one as ``None``."""
    from mycelium_backend_client.types import Unset

    return None if isinstance(value, Unset) else value


def member_rows(members: "RoomMembers", presence: "RoomPresenceRead") -> list[dict]:
    """Everyone in the room, from its members (``/rooms/{room}/members``) and its
    live presence (``/rooms/{room}/sessions/members``), as ``room members`` says
    them. State only: nothing of what's on anyone's screen."""
    here = {m.handle.lstrip("@").lower(): m for m in presence.members}

    def row(handle: str, kind: str, owner: object = None) -> dict:
        live = here.get(handle.lstrip("@").lower())
        if kind == "engine":
            # No presence of its own: it answers whenever it's summoned.
            status = "on call"
        elif live is None:
            status = "away"
        elif kind == "person":
            status = "here"
        else:
            # herdr's state as it reports it. Present with none (awaiting, or
            # on a socket) is idle.
            status = _unset(live.status) or "idle"
        return {
            "handle": handle,
            "kind": kind,
            "owner": _unset(owner),
            "status": status,
            "last_seen": _unset(live.last_seen) if live else None,
            "wake_pending": bool(_unset(live.wake_pending)) if live else False,
            "can_reply": _unset(live.can_reply) if live else None,
            "cant_reply_why": _unset(live.cant_reply_why) if live else None,
        }

    return [
        *(row(p.handle, "person") for p in members.people),
        *(row(a.handle, "agent", a.owner) for a in members.agents),
        *(row(e.handle, "engine", e.owner) for e in members.engines),
        # Present, or holding a task, with no person or agent record: an agent
        # that runs `await` but was never registered, say.
        *(row(o.handle, "other") for o in members.others),
    ]


@doc_ref(
    usage="mycelium room members [<room> | --room <room>]",
    desc="Who is in a room and what each one is doing right now: people, agents and engines.",
    group="room",
)
@app.command("members")
@in_room("room_opt", resolve=False)
@emits_json()
def members(
    ctx: typer.Context,
    room: str | None = typer.Argument(None, help="Room to read (defaults to active room)"),
    room_opt: str | None = None,
) -> None:
    """
    Who is in a room, and what each one is doing right now.

    Every member the room knows: its people, agents and engines, and anyone
    else who is present or holds a task. An agent is working, idle, done or
    blocked while present, and away when it isn't. A person is here or away.
    An engine is on call: it answers whenever it's summoned. An agent the hub
    knows can't post says so, and --json says why.

    Examples:
        mycelium room members
        mycelium room members design-review --json
    """
    try:
        json_output = ctx.obj.get("json", False) if ctx.obj else False
        config = MyceliumConfig.load()
        room_name = _resolve_room(config, _one_room(room, room_opt))
        from mycelium_backend_client.api.members import (
            list_members_api_rooms_room_name_members_get as members_api,
        )
        from mycelium_backend_client.api.sessions import (
            list_members_api_rooms_room_name_sessions_members_get as presence_api,
        )
        from mycelium_backend_client.models import RoomMembers, RoomPresenceRead

        with _typed_client(config) as client:
            known = answered(members_api.sync_detailed(room_name, client=client), RoomMembers)
            live = answered(presence_api.sync_detailed(room_name, client=client), RoomPresenceRead)
        rows = member_rows(known, live)
        if json_output:
            typer.echo(json_module.dumps(rows, indent=2, default=str))
            return
        from rich.console import Console
        from rich.table import Table

        console = Console()
        if not rows:
            console.print(f"[dim]No members in {room_name} yet.[/dim]")
            return
        table = Table(title=f"{room_name} members", show_lines=False)
        table.add_column("Handle", style="cyan", no_wrap=True)
        table.add_column("Kind")
        table.add_column("Status", no_wrap=True)
        table.add_column("Owner", style="green")
        for r in rows:
            status = r["status"] if r["status"] != "away" else "[dim]away[/dim]"
            if r["can_reply"] is False:
                status += " · [yellow]can't reply[/yellow]"
            table.add_row(
                f"@{r['handle']}",
                r["kind"],
                status,
                f"@{r['owner']}" if r["owner"] else "[dim]-[/dim]",
            )
        console.print(table)
    except (typer.Exit, typer.Abort):
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


@doc_ref(
    usage="mycelium room export [<room> | --room <room>] [--out <dir>] [--since <stamp|age>] [--redact]",
    desc=(
        "Write a room's whole history to local files: every message, channel and task threads "
        "alike, as JSON lines, plus the board. Run it again with the same <code>--out</code> "
        "to add only what is new. <code>--redact</code> replaces emails, tokens and non-GitHub URLs."
    ),
    group="room",
)
@app.command("export")
@in_room("room_opt", resolve=False)
@emits_json()
def export(
    ctx: typer.Context,
    room: str | None = typer.Argument(None, help="Room to export (defaults to active room)"),
    room_opt: str | None = None,
    out: str | None = typer.Option(
        None,
        "--out",
        "-o",
        help="Directory to write into (default: ~/mycelium-exports/<room>). It keeps its own cursor.",
    ),
    since: str | None = typer.Option(
        None,
        "--since",
        help="On a first export, only messages at/after this ISO stamp or age (2h, 30m, 1d)",
    ),
    redact: bool = typer.Option(
        False,
        "--redact",
        help="Replace emails, tokens, non-GitHub URLs and home-folder names with placeholders",
    ),
) -> None:
    """
    Write a room's whole history to local files, for backups, analysis or a bug report.

    The directory gets three files:

    - messages.jsonl: one line per message, channel and task threads alike,
      notices and pings included. Each line has the sender and whether they are
      a person, an agent, an engine or the system; the thread and the task it
      belongs to; the type; the mentions in it; and the text.
    - board.json: every task row, with its status, who it is for and who holds it.
    - cursor.json: where this export stopped.

    Running it again with the same --out reads only what is new and appends it,
    so a scheduled export stays cheap. The default folder is outside the one you
    run it in, and a folder inside a git checkout gets a warning, so a room's
    transcript doesn't end up in a commit.

    Examples:
        mycelium room export
        mycelium room export design-review --out ~/backup/design-review
        mycelium room export my-room --since 7d --redact
    """
    from pathlib import Path

    from mycelium import room_export

    try:
        json_output = ctx.obj.get("json", False) if ctx.obj else False
        config = MyceliumConfig.load()
        room_name = _resolve_room(config, _one_room(room, room_opt))
        target = Path(out).expanduser() if out else room_export.default_out(room_name)
        if room_export.in_git_work_tree(target):
            typer.secho(
                f"Warning: {target} is inside a git checkout. Keep it out of commits, "
                "or pick another --out.",
                fg=typer.colors.YELLOW,
                err=True,
            )
        with _typed_client(config, timeout=120, raise_on_unexpected_status=False) as client:
            result = room_export.export_room(
                client,
                room_name,
                target,
                since=chat.parse_stamp(since) if since else None,
                redacted=redact,
            )
        if json_output:
            typer.echo(json_module.dumps(result.as_dict(), indent=2))
            return
        verb = "Exported" if result.from_start else "Added"
        typer.echo(
            f"{verb} {result.new} message{'' if result.new == 1 else 's'} from {room_name} "
            f"({result.total} in the export) and {result.board_rows} board rows to {target}"
        )
    except room_export.ExportError as e:
        typer.secho(str(e), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from e
    except (typer.Exit, typer.Abort):
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


@doc_ref(
    usage='mycelium room search ["<query>"] [--from <handle>] [--task <row>] [--since <when>] [--before <when>] [--in channel|thread] [--sort newest|oldest|relevance] [--facets] [--context N]',
    desc=(
        'Search every message in a room by any field: words, <code>"phrases"</code>, '
        "<code>from:</code> <code>to:</code> <code>mentions:</code> <code>task:</code> "
        "<code>in:</code> <code>stance:</code> <code>has:</code> <code>is:</code> "
        "<code>type:</code> <code>kind:</code> <code>step:</code> <code>day:</code>, time bounds "
        "(<code>after:2h</code>, <code>on:2026-09-03</code>) and <code>-</code> to exclude. "
        "Prints counts per field to narrow by; <code>--facets</code> prints only those."
    ),
    group="room",
)
@app.command("search")
@in_room("room")
@paged()
@emits_json()
def search(  # noqa: PLR0913 — one flag per field an agent narrows by
    ctx: typer.Context,
    words: list[str] | None = typer.Argument(
        None, help='The query: words, "phrases" and field:value clauses (see below)'
    ),
    room: str | None = None,
    limit: int = 20,
    sender: list[str] | None = typer.Option(None, "--from", "-s", help="Said by this handle"),
    to: list[str] | None = typer.Option(None, "--to", help="Addressed to this handle"),
    mentions: list[str] | None = typer.Option(None, "--mentions", help="@-mentions this handle"),
    task: list[str] | None = typer.Option(
        None, "--task", help="Said in this task's thread (its key, or words from its title)"
    ),
    where: str | None = typer.Option(None, "--in", help="channel (the room) or thread (a task's)"),
    message_type: list[str] | None = typer.Option(None, "--type", "-t", help="Message type"),
    stance: str | None = typer.Option(None, "--stance", help="accept or reject"),
    has: list[str] | None = typer.Option(
        None, "--has", help="mention, link, memory, code or scores"
    ),
    since: str | None = typer.Option(
        None, "--since", "--after", help="At/after this ISO stamp, date or age (2h, 3d)"
    ),
    before: str | None = typer.Option(
        None, "--before", "-b", help="Before this ISO stamp, date or age (2h, 3d)"
    ),
    on: str | None = typer.Option(None, "--on", help="On this UTC day (2026-09-03, today)"),
    sort: str | None = typer.Option(None, "--sort", help="newest (default), oldest or relevance"),
    context: int = typer.Option(
        0, "--context", "-C", min=0, max=5, help="Messages either side of each hit, same thread"
    ),
    cursor: str | None = typer.Option(
        None, "--cursor", help="Read the next page: the cursor the last page printed"
    ),
    facets_only: bool = typer.Option(
        False, "--facets", help="Only the counts per field: how big each narrowing would be"
    ),
) -> None:
    """
    Search every message in a room, by any field, with counts to narrow by.

    The whole history, not the latest page. The query is one line: words must
    all appear, "quoted phrases" must appear as written, -word must not, and
    field:value clauses narrow (the same field twice is either; different
    fields are both; -field:value excludes):

      from:<handle>  to:<handle>  mentions:<handle>  task:<key or title words>
      in:channel|thread  stance:accept|reject  has:mention|link|memory|code|scores
      is:edited|conductor  type:<type>  kind:<kind>  status:<status>
      step:<conductor step>  day:<date>  thread:<episode>
      after:<when>  before:<when>  on:<day>  sort:newest|oldest|relevance

    @handle is from:handle. A time is an ISO date or stamp, an age (30m, 2h,
    3d, 1w), today or yesterday. Every flag below is the same clause spelled
    as a flag, so both forms mix.

    Under the hits, "narrow by" counts each field's values among the matches
    (a field's own choice left out, so the alternatives stay visible). Use
    --facets to see only those: the cheap first look before reading messages.

    Examples:
        mycelium room search "apple pay"
        mycelium room search "from:avery after:2d" --sort oldest
        mycelium room search refund --task checkout --stance reject
        mycelium room search "@builder -in:thread has:link"
        mycelium room search --facets --since 1w
        mycelium room search '"ready for review"' --context 2 --json
    """
    from mycelium import message_search

    try:
        json_output = ctx.obj.get("json", False) if ctx.obj else False
        config = MyceliumConfig.load()
        flags: dict[str, list[str]] = {
            "from": [h.lstrip("@") for h in sender or []],
            "to": [h.lstrip("@") for h in to or []],
            "mentions": [h.lstrip("@") for h in mentions or []],
            "task": list(task or []),
            "in": [where] if where else [],
            "type": list(message_type or []),
            "stance": [stance] if stance else [],
            "has": list(has or []),
            "after": [since] if since else [],
            "before": [before] if before else [],
            "on": [on] if on else [],
            "sort": [sort] if sort else [],
        }
        if sort and sort not in ("newest", "oldest", "relevance"):
            raise typer.BadParameter(f"--sort is newest, oldest or relevance, not {sort!r}")
        query = message_search.build_query(list(words or []), flags)
        message_search.run(
            config,
            str(room),
            query,
            limit=limit,
            cursor=cursor,
            context=context,
            facets_only=facets_only,
            json_output=json_output,
        )
    except (typer.Exit, typer.Abort, typer.BadParameter):
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


@doc_ref(
    usage="mycelium room delegate <room> --to <handle> --task <description>",
    desc="Delegate a task to another agent in a room.",
    group="room",
)
@app.command()
@acts_as("sender", fallback="unknown")
@emits_json()
def delegate(
    ctx: typer.Context,
    session_id: str = typer.Argument(..., help="Room session/name"),
    to: str = typer.Option(..., "--to", help="Target agent handle"),
    task: str = typer.Option(..., "--task", "-t", help="Task description to delegate"),
    sender: str = "",
) -> None:
    """
    Delegate a task to an agent in a room.

    Posts a 'delegate' type message to the room.

    Examples:
        mycelium room delegate my-room --to security-agent --task "Scan CVE-2024-1234"
    """
    try:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False  # noqa: F841
        json_output = ctx.obj.get("json", False) if ctx.obj else False

        config = MyceliumConfig.load()

        from mycelium_backend_client.api.messages import (
            send_message_api_rooms_room_name_messages_post as send_api,
        )
        from mycelium_backend_client.models import (
            MessageCreate,
            MessageCreateMessageType,
            MessageRead,
        )

        with _typed_client(config) as client:
            body = MessageCreate(
                sender_handle=sender,
                message_type=MessageCreateMessageType.DELEGATE,
                content=task,
                recipient_handle=to,
            )
            result = answered(
                send_api.sync_detailed(room_name=session_id, client=client, body=body), MessageRead
            )

        if json_output:
            typer.echo(json_module.dumps(result.to_dict(), indent=2, default=str))
        else:
            typer.secho("Task delegated", fg=typer.colors.GREEN)
            typer.echo(f"  {sender} -> {to}: {task[:80]}")

    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
