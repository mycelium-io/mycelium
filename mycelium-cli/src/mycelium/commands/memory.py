"""
Memory commands — persistent namespaced memory operations.

Uses the generated OpenAPI client for type-safe API access.
"""

import json

import typer
from rich.console import Console

from mycelium.config import MyceliumConfig

app = typer.Typer(
    help="Read and write persistent memories scoped to rooms. Memories persist across sessions and support semantic vector search.",
    no_args_is_help=True,
)
console = Console()


def _get_client():
    """Get a configured OpenAPI client."""
    from mycelium_backend_client import Client

    cfg = MyceliumConfig.load()
    return Client(base_url=cfg.server.api_url, raise_on_unexpected_status=True)


def _get_active_room(room: str | None) -> str:
    """Get room name from arg or active config."""
    if room:
        return room
    cfg = MyceliumConfig.load()
    active = getattr(cfg.rooms, "active", None) if hasattr(cfg, "rooms") else None
    if active:
        return active
    typer.echo(
        "No room specified and no active room set. Use --room or 'mycelium config set rooms.active <name>'"
    )
    raise typer.Exit(1)


@app.command(name="set")
def memory_set(
    key: str = typer.Argument(..., help="Memory key (e.g. 'project/status')"),
    value: str = typer.Argument(..., help="Memory value (string or JSON)"),
    room: str | None = typer.Option(
        None, "--room", "-r", help="Room name (defaults to active room)"
    ),
    handle: str = typer.Option("cli-user", "--handle", "-h", help="Agent handle"),
    no_embed: bool = typer.Option(False, "--no-embed", help="Skip vector embedding"),
    tags: str | None = typer.Option(None, "--tags", "-t", help="Comma-separated tags"),
    update: bool = typer.Option(
        False, "--update", "-u", help="Allow overwriting an existing memory"
    ),
) -> None:
    """Write a memory to a room's persistent namespace.

    Fails if the key already exists unless --update is passed.
    """
    from mycelium_backend_client.api.memory import (
        create_memories_rooms_room_name_memory_post as create_api,
    )
    from mycelium_backend_client.api.memory import (
        get_memory_rooms_room_name_memory_key_get as get_api,
    )
    from mycelium_backend_client.models import MemoryBatchCreate, MemoryCreate

    room_name = _get_active_room(room)

    # Check for existing key unless --update is set
    if not update:
        try:
            from mycelium_backend_client.errors import UnexpectedStatus

            with _get_client() as client:
                existing = get_api.sync(room_name=room_name, key=key, client=client)
                if existing is not None:
                    console.print(
                        f"[red]Error:[/red] {room_name}/{key} already exists (v{existing.version}). "
                        f"Use [bold]--update[/bold] to overwrite."
                    )
                    raise typer.Exit(1)
        except UnexpectedStatus as e:
            if e.status_code != 404:
                raise

    # Try to parse value as JSON
    try:
        parsed_value = json.loads(value)
    except json.JSONDecodeError:
        parsed_value = value

    tag_list = [t.strip() for t in tags.split(",")] if tags else None

    item = MemoryCreate(
        key=key,
        value=parsed_value,
        created_by=handle,
        embed=not no_embed,
        tags=tag_list,
    )
    batch = MemoryBatchCreate(items=[item])

    with _get_client() as client:
        result = create_api.sync(room_name=room_name, client=client, body=batch)
        if result and isinstance(result, list) and len(result) > 0:
            console.print(f"[green]Memory set:[/green] {room_name}/{key} (v{result[0].version})")
        else:
            console.print(f"[green]Memory set:[/green] {room_name}/{key}")


@app.command(name="get")
def memory_get(
    key: str = typer.Argument(..., help="Memory key"),
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
) -> None:
    """Read a memory by key."""
    from mycelium_backend_client.api.memory import (
        get_memory_rooms_room_name_memory_key_get as get_api,
    )

    room_name = _get_active_room(room)

    with _get_client() as client:
        result = get_api.sync(room_name=room_name, key=key, client=client)
        if result is None:
            console.print(f"[red]Not found:[/red] {key}")
            raise typer.Exit(1)
        console.print(
            f"[cyan]{result.key}[/cyan]  [dim]v{result.version}  {result.created_by}[/dim]"
        )
        value = result.value
        if hasattr(value, "to_dict"):
            value = value.to_dict()
        if isinstance(value, dict):
            console.print(json.dumps(value, indent=2, default=str))
        else:
            console.print(str(value))


@app.command(name="ls")
def memory_ls(
    namespace: str | None = typer.Argument(
        None, help="Key prefix to filter by (e.g. 'position/' or 'decisions/')"
    ),
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
    prefix: str | None = typer.Option(
        None, "--prefix", "-p", help="Key prefix filter (same as positional arg)"
    ),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
) -> None:
    """List memories in a room, optionally filtered by namespace prefix."""
    # Positional arg takes priority over --prefix flag
    prefix = namespace or prefix
    from mycelium_backend_client.api.memory import (
        list_memories_rooms_room_name_memory_get as list_api,
    )

    room_name = _get_active_room(room)

    with _get_client() as client:
        result = list_api.sync(room_name=room_name, client=client, prefix=prefix, limit=limit)
        if not result:
            console.print("[dim]No memories found[/dim]")
            return

        console.print(f"[bold]{room_name}[/bold] ({len(result)} memories)\n")

        for mem in result:
            ts = str(mem.updated_at)[:16].replace("T", " ") if mem.updated_at else ""
            console.print(
                f"[cyan]{mem.key}[/cyan]  [dim]v{mem.version}  {mem.created_by}  {ts}[/dim]"
            )
            value = mem.value
            if hasattr(value, "to_dict"):
                value = value.to_dict()
            if isinstance(value, dict):
                flat = json.dumps(value, default=str)
                console.print(f"  {flat[:120]}{'...' if len(flat) > 120 else ''}")
            elif isinstance(value, str):
                console.print(f"  {value[:120]}")
            console.print()


@app.command(name="search")
def memory_search(
    query: str = typer.Argument(..., help="Natural language search query"),
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
    limit: int = typer.Option(5, "--limit", "-n", help="Max results"),
) -> None:
    """Semantic search over memories."""
    from mycelium_backend_client.api.memory import (
        search_memories_rooms_room_name_memory_search_post as search_api,
    )
    from mycelium_backend_client.models import MemorySearchRequest

    room_name = _get_active_room(room)

    with _get_client() as client:
        body = MemorySearchRequest(query=query, limit=limit)
        result = search_api.sync(room_name=room_name, client=client, body=body)

        if not result or not result.results:
            console.print("[dim]No matching memories found[/dim]")
            return

        for r in result.results:
            mem = r.memory
            sim = r.similarity
            console.print(
                f"[cyan]{mem.key}[/cyan] [dim](similarity: {sim:.3f}, v{mem.version})[/dim]"
            )
            if mem.content_text:
                console.print(f"  {mem.content_text[:200]}")
            console.print()


@app.command(name="rm")
def memory_rm(
    key: str = typer.Argument(..., help="Memory key to delete"),
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
) -> None:
    """Delete a memory."""
    from mycelium_backend_client.api.memory import (
        delete_memory_rooms_room_name_memory_key_delete as delete_api,
    )

    room_name = _get_active_room(room)

    if not force:
        confirm = typer.confirm(f"Delete memory '{key}' from room '{room_name}'?")
        if not confirm:
            raise typer.Exit(0)

    with _get_client() as client:
        delete_api.sync_detailed(room_name=room_name, key=key, client=client)
        console.print(f"[green]Deleted:[/green] {key}")


@app.command(name="subscribe")
def memory_subscribe(
    pattern: str = typer.Argument(..., help="Key glob pattern (e.g. 'project/*')"),
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
    handle: str = typer.Option("cli-user", "--handle", "-h", help="Subscriber agent handle"),
) -> None:
    """Subscribe to memory change notifications."""
    from mycelium_backend_client.api.memory import (
        subscribe_rooms_room_name_memory_subscribe_post as sub_api,
    )
    from mycelium_backend_client.models import SubscriptionCreate

    room_name = _get_active_room(room)

    with _get_client() as client:
        body = SubscriptionCreate(key_pattern=pattern, subscriber=handle)
        result = sub_api.sync(room_name=room_name, client=client, body=body)
        if result:
            sub_id = str(result.id)[:8] if result.id else "?"
            console.print(f"[green]Subscribed:[/green] {pattern} (id: {sub_id}...)")


@app.command(name="catchup")
def memory_catchup(
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
) -> None:
    """Get briefed on a room's current state — latest synthesis + recent activity."""
    import httpx

    room_name = _get_active_room(room)
    cfg = MyceliumConfig.load()

    with httpx.Client(base_url=cfg.server.api_url, timeout=30) as client:
        resp = client.get(f"/rooms/{room_name}/catchup")
        resp.raise_for_status()
        data = resp.json()

    console.print(
        f"\n[bold]{data['room']}[/bold]  [dim]{data['mode']} room  {data['total_memories']} memories  {len(data['contributors'])} contributors[/dim]\n"
    )

    # Contributors
    if data["contributors"]:
        console.print(f"[dim]Contributors:[/dim] {', '.join(data['contributors'])}\n")

    # Latest synthesis
    synth = data.get("latest_synthesis")
    if synth:
        console.print("[bold green]Latest Synthesis[/bold green]")
        console.print(f"[dim]{synth['key']}  {synth['created_at'][:16]}[/dim]\n")
        content = synth["content"]
        if isinstance(content, dict):
            content = content.get("synthesis", json.dumps(content, default=str))
        console.print(content)
        console.print()
    else:
        console.print(
            "[dim]No synthesis yet. Run 'mycelium room synthesize' to generate one.[/dim]\n"
        )

    # Recent activity since synthesis
    recent = data.get("recent_activity", [])
    if recent:
        n = data.get("memories_since_synthesis", len(recent))
        console.print(
            f"[bold yellow]Recent Activity[/bold yellow] ({n} memories since last synthesis)\n"
        )
        for mem in recent[:10]:
            console.print(
                f"  [cyan]{mem['key']}[/cyan]  [dim]{mem['created_by']}  {mem['created_at'][:16]}[/dim]"
            )
            if mem.get("content_text"):
                console.print(f"    {mem['content_text'][:150]}")
        if len(recent) > 10:
            console.print(f"\n  [dim]... and {len(recent) - 10} more[/dim]")
    else:
        console.print("[dim]No new activity since last synthesis.[/dim]")
    console.print()
