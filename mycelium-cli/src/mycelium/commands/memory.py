"""
Memory commands — persistent namespaced memory operations.

CRUD operations read/write markdown files in .mycelium/rooms/{room}/.
Search and subscribe use the backend API (pgvector/NOTIFY).
"""

import json
from datetime import UTC, datetime

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref
from mycelium.filesystem import (
    get_room_dir,
    list_memories,
    read_memory,
    write_memory,
)
from mycelium.sstp import MEMORY_CATEGORIES, MemoryLogEntry

app = typer.Typer(
    help="Read and write persistent memories scoped to rooms. Memories are markdown files in .mycelium/rooms/. Supports semantic vector search via pgvector.",
    no_args_is_help=True,
)
console = Console()


def _get_client():
    """Get a configured OpenAPI client."""
    from mycelium_backend_client import Client

    cfg = MyceliumConfig.load()
    return Client(base_url=cfg.server.api_url, raise_on_unexpected_status=True)


def _write_local_copy(room_name: str, mem) -> None:
    """Write a local copy of a memory file from the API response.

    This ensures the agent has a local file for reads and git sync,
    even when the backend is remote.
    """
    from mycelium_backend_client.types import UNSET

    room_dir = get_room_dir(room_name)

    # Extract content from the value field
    value = mem.value
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    if isinstance(value, dict):
        content = value.get("text", str(value))
    else:
        content = str(value)

    tags = mem.tags if not isinstance(mem.tags, type(UNSET)) else None
    updated_by = mem.updated_by if not isinstance(mem.updated_by, type(UNSET)) else None

    write_memory(
        room_dir,
        mem.key,
        content,
        created_by=mem.created_by,
        updated_by=updated_by,
        version=mem.version,
        tags=tags,
        created_at=mem.created_at,
        updated_at=mem.updated_at,
    )


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


@doc_ref(
    usage="mycelium memory set <key> <value> [--handle <handle>]",
    desc="Write a memory (upsert). Structured category keys (<code>work/</code>, <code>decisions/</code>, <code>status/</code>, <code>context/</code>) are auto-validated. Always upserts — the backend handles versioning.",
    group="memory",
)
@app.command(name="set")
def memory_set(
    key: str = typer.Argument(..., help="Memory key (e.g. 'status/deploy', 'project/config')"),
    value: str = typer.Argument(..., help="Memory value (string or JSON)"),
    room: str | None = typer.Option(
        None, "--room", "-r", help="Room name (defaults to active room)"
    ),
    handle: str = typer.Option("cli-user", "--handle", "-H", help="Agent handle"),
    no_embed: bool = typer.Option(False, "--no-embed", help="Skip vector embedding"),
    tags: str | None = typer.Option(None, "--tags", "-t", help="Comma-separated tags"),
) -> None:
    """Write a memory to a room's persistent namespace (upsert).

    Keys with a known category prefix (work/, decisions/, context/, status/) are
    validated for slug format. Other keys pass through freely.

    Always upserts — the backend handles versioning.

    Examples:
        mycelium memory set status/deploy ACTIVE
        mycelium memory set decisions/db-choice "Chose AgensGraph for graph+SQL+vector"
        mycelium memory set work/api-server "Built 12 endpoints with auth"
    """
    from mycelium_backend_client.api.memory import (
        create_memories_rooms_room_name_memory_post as create_api,
    )
    from mycelium_backend_client.models import MemoryBatchCreate, MemoryCreate

    room_name = _get_active_room(room)

    # Validate structured keys when category prefix is recognized
    entry: MemoryLogEntry | None = None
    if "/" in key:
        category = key.split("/", 1)[0]
        if category in MEMORY_CATEGORIES:
            slug = key.split("/", 1)[1]
            try:
                entry = MemoryLogEntry(category=category, slug=slug, content=value)  # type: ignore[arg-type]
            except ValidationError as exc:
                errors = exc.errors()
                if any(e["loc"] == ("slug",) for e in errors):
                    console.print(
                        f"[red]Error:[/red] invalid slug '{slug}' for {category}/ key. "
                        "Use lowercase alphanumeric with hyphens/dots/underscores."
                    )
                else:
                    console.print(f"[red]Error:[/red] {exc}")
                raise typer.Exit(1) from exc

    tag_list = [t.strip() for t in tags.split(",")] if tags else None

    if entry is not None:
        # Structured category key — auto-timestamp and structured value
        timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        item = MemoryCreate(
            key=entry.key,
            value={"text": entry.content, "logged_at": timestamp, "category": entry.category},
            created_by=handle,
            embed=not no_embed,
            content_text=f"[{timestamp}] {entry.content}",
            tags=tag_list,
        )
    else:
        # Freeform key — pass value through as-is
        try:
            parsed_value = json.loads(value)
        except json.JSONDecodeError:
            parsed_value = value

        item = MemoryCreate(
            key=key,
            value=parsed_value,
            created_by=handle,
            embed=not no_embed,
            tags=tag_list,
        )

    batch = MemoryBatchCreate(items=[item])

    # The backend API writes the file on the server and updates the search index.
    # We also write the file locally so the agent has a local copy for reads and git sync.
    with _get_client() as client:
        result = create_api.sync(room_name=room_name, client=client, body=batch)
        if result and isinstance(result, list) and len(result) > 0:
            mem = result[0]

            # Write the file locally using the response metadata
            _write_local_copy(room_name, mem)

            # Invalidate cached ETag — room has changed
            from mycelium.filesystem import get_mycelium_dir

            etag_file = get_mycelium_dir() / "rooms" / room_name / ".sync-etag"
            if etag_file.exists():
                etag_file.unlink()

            file_path = getattr(mem, "file_path", None)
            version_info = f"v{mem.version}" if hasattr(mem, "version") else ""
            path_info = f"  [{file_path}]" if file_path else ""
            console.print(
                f"[green]Memory set:[/green] {room_name}/{key} ({version_info}){path_info}"
            )
        else:
            console.print(f"[green]Memory set:[/green] {room_name}/{key}")


@doc_ref(
    usage="mycelium memory get <key>",
    desc="Read a memory by exact key.",
    group="memory",
)
@app.command(name="get")
def memory_get(
    key: str = typer.Argument(..., help="Memory key"),
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
    raw: bool = typer.Option(False, "--raw", help="Show raw markdown file content"),
) -> None:
    """Read a memory by key — reads directly from the filesystem."""
    room_name = _get_active_room(room)
    room_dir = get_room_dir(room_name)

    result = read_memory(room_dir, key)
    if result is None:
        console.print(f"[red]Not found:[/red] {key}")
        raise typer.Exit(1)

    meta, content = result

    if raw:
        # Show the raw file
        file_path = room_dir / f"{key}.md"
        if file_path.exists():
            console.print(file_path.read_text(encoding="utf-8"))
        return

    version = meta.get("version", "?")
    created_by = meta.get("created_by", "?")
    console.print(f"[cyan]{key}[/cyan]  [dim]v{version}  {created_by}[/dim]")
    console.print(content)


@doc_ref(
    usage="mycelium memory ls [prefix/]",
    desc="List memories. Optional prefix filters by namespace.",
    group="memory",
)
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
    """List memories in a room — reads directly from the filesystem."""
    prefix = namespace or prefix
    room_name = _get_active_room(room)
    room_dir = get_room_dir(room_name)

    entries = list_memories(room_dir, prefix=prefix, limit=limit)
    if not entries:
        console.print("[dim]No memories found[/dim]")
        return

    console.print(f"[bold]{room_name}[/bold] ({len(entries)} memories)\n")

    for key, meta, content in entries:
        ts = str(meta.get("updated_at", ""))[:16].replace("T", " ")
        version = meta.get("version", "?")
        created_by = meta.get("created_by", "?")
        console.print(f"[cyan]{key}[/cyan]  [dim]v{version}  {created_by}  {ts}[/dim]")
        display = content[:120] if content else ""
        if display:
            console.print(f"  {display}{'...' if len(content) > 120 else ''}")
        console.print()


@doc_ref(
    usage="mycelium memory search <query>",
    desc="Semantic search — finds memories by meaning using cosine similarity on local embeddings. Requires the backend API.",
    group="memory",
)
@app.command(name="search")
def memory_search(
    query: str = typer.Argument(..., help="Natural language search query"),
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
    limit: int = typer.Option(5, "--limit", "-n", help="Max results"),
) -> None:
    """Semantic search over memories (uses pgvector via backend API)."""
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


@doc_ref(
    usage="mycelium memory rm <key> [--force]",
    desc="Delete a memory — removes the markdown file and search index entry.",
    group="memory",
)
@app.command(name="rm")
def memory_rm(
    key: str = typer.Argument(..., help="Memory key to delete"),
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
) -> None:
    """Delete a memory — removes both the file and search index."""
    from mycelium_backend_client.api.memory import (
        delete_memory_rooms_room_name_memory_key_delete as delete_api,
    )

    room_name = _get_active_room(room)

    if not force:
        confirm = typer.confirm(f"Delete memory '{key}' from room '{room_name}'?")
        if not confirm:
            raise typer.Exit(0)

    # Delete via backend (handles both file + DB)
    with _get_client() as client:
        delete_api.sync_detailed(room_name=room_name, key=key, client=client)
        console.print(f"[green]Deleted:[/green] {key}")


@doc_ref(
    usage="mycelium memory reindex",
    desc="Re-index the room into the pgvector search index. Run after editing memory files outside the CLI.",
    group="memory",
)
@app.command(name="reindex")
def memory_reindex(
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
) -> None:
    """Re-index the room into the pgvector search index.

    Run after editing memory files outside the CLI to update search.
    """
    import httpx

    room_name = _get_active_room(room)
    cfg = MyceliumConfig.load()

    console.print(f"[dim]Re-indexing {room_name}...[/dim]")
    with httpx.Client(base_url=cfg.server.api_url, timeout=120) as client:
        resp = client.post(f"/rooms/{room_name}/reindex")
        resp.raise_for_status()
        data = resp.json()

    indexed = data.get("indexed", 0)
    errors = data.get("errors", 0)
    console.print(f"[green]Re-indexed:[/green] {indexed} memories")
    if errors:
        console.print(f"[yellow]Errors:[/yellow] {errors}")


@doc_ref(
    usage="mycelium memory subscribe <pattern> [-H <handle>]",
    desc="Subscribe to memory change notifications matching a glob pattern.",
    group="memory",
)
@app.command(name="subscribe")
def memory_subscribe(
    pattern: str = typer.Argument(..., help="Key glob pattern (e.g. 'project/*')"),
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
    handle: str = typer.Option("cli-user", "--handle", "-H", help="Subscriber agent handle"),
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


@doc_ref(
    usage="mycelium catchup",
    desc="Get a full briefing on everything in the room — reads from <code>.mycelium/rooms/</code> and the latest synthesis.",
    group="other",
)
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
        console.print(f"[dim]{synth['key']}  {str(synth['created_at'])[:16]}[/dim]\n")
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
                f"  [cyan]{mem['key']}[/cyan]  [dim]{mem['created_by']}  {str(mem['created_at'])[:16]}[/dim]"
            )
            if mem.get("content_text"):
                console.print(f"    {mem['content_text'][:150]}")
        if len(recent) > 10:
            console.print(f"\n  [dim]... and {len(recent) - 10} more[/dim]")
    else:
        console.print("[dim]No new activity since last synthesis.[/dim]")
    console.print()


# ── Structured memory commands ───────────────────────────────────────────────


def _list_by_category(category: str, room: str | None, limit: int) -> None:
    """Shared implementation for category-filtered listing — reads from filesystem."""
    room_name = _get_active_room(room)
    room_dir = get_room_dir(room_name)
    prefix = f"{category}/"

    entries = list_memories(room_dir, prefix=prefix, limit=limit)
    if not entries:
        console.print(f"[dim]No {category} memories found[/dim]")
        return

    table = Table(title=f"{room_name} — {category}", show_lines=False)
    table.add_column("Key", style="cyan", no_wrap=True)
    table.add_column("Value", max_width=80)
    table.add_column("By", style="dim")
    table.add_column("Updated", style="dim")

    for key, meta, content in entries:
        short_key = key.removeprefix(prefix)
        display = content[:80] if content else ""
        ts = str(meta.get("updated_at", ""))[:16].replace("T", " ")
        created_by = meta.get("created_by", "?")
        table.add_row(short_key, display, created_by, ts)

    console.print(table)


@doc_ref(
    usage="mycelium memory status",
    desc="Show current status — filters to <code>status/*</code> memories as a table.",
    group="memory",
)
@app.command(name="status")
def memory_status(
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
) -> None:
    """Show current status of everything — filters to status/* memories."""
    _list_by_category("status", room, limit)


@doc_ref(
    usage="mycelium memory work",
    desc="Show what's been built — filters to <code>work/*</code> memories as a table.",
    group="memory",
)
@app.command(name="work")
def memory_work(
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
) -> None:
    """Show what's been built — filters to work/* memories."""
    _list_by_category("work", room, limit)


@doc_ref(
    usage="mycelium memory decisions",
    desc="Show why choices were made — filters to <code>decisions/*</code> memories as a table.",
    group="memory",
)
@app.command(name="decisions")
def memory_decisions(
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
) -> None:
    """Show why choices were made — filters to decisions/* memories."""
    _list_by_category("decisions", room, limit)


@doc_ref(
    usage="mycelium memory context",
    desc="Show background and preferences — filters to <code>context/*</code> memories as a table.",
    group="memory",
)
@app.command(name="context")
def memory_context(
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
) -> None:
    """Show background and preferences — filters to context/* memories."""
    _list_by_category("context", room, limit)


@doc_ref(
    usage="mycelium memory procedures",
    desc="Show reusable how-to steps — filters to <code>procedures/*</code> memories as a table.",
    group="memory",
)
@app.command(name="procedures")
def memory_procedures(
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
) -> None:
    """Show reusable how-to procedures — filters to procedures/* memories."""
    _list_by_category("procedures", room, limit)


# ── Sync commands ────────────────────────────────────────────────────────────


@doc_ref(
    usage="mycelium sync [--no-reindex]",
    desc="Sync the active room with the backend — fetch all memories from the API and write them locally.",
    group="other",
)
@app.command(name="sync")
def memory_sync(
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
    no_reindex: bool = typer.Option(False, "--no-reindex", help="Skip re-indexing after sync"),
) -> None:
    """Sync room files from the backend API — fetches all memories and writes local copies.

    Use this to pull the latest room state from a remote backend instance.
    Hooks call this on session start/end to keep local files current.

    Examples:
        mycelium sync           # fetch all memories + reindex
        mycelium sync --no-reindex
    """
    import httpx

    room_name = _get_active_room(room)
    cfg = MyceliumConfig.load()

    from mycelium.filesystem import get_mycelium_dir

    etag_file = get_mycelium_dir() / "rooms" / room_name / ".sync-etag"
    headers = {}
    if etag_file.exists():
        headers["If-None-Match"] = etag_file.read_text().strip()

    console.print(f"[dim]Syncing {room_name} from {cfg.server.api_url}...[/dim]")

    with httpx.Client(base_url=cfg.server.api_url, timeout=60) as client:
        resp = client.get(f"/rooms/{room_name}/memory", params={"limit": 1000}, headers=headers)

    if resp.status_code == 304:
        console.print("[dim]Already up to date[/dim]")
        return

    resp.raise_for_status()
    memories = resp.json()

    # Persist ETag for next sync
    if etag := resp.headers.get("etag"):
        etag_file.parent.mkdir(parents=True, exist_ok=True)
        etag_file.write_text(etag)

    if not memories:
        console.print("[dim]No memories to sync[/dim]")
        return

    room_dir = get_room_dir(room_name)
    written = 0
    for mem in memories:
        value = mem.get("value", "")
        if isinstance(value, dict):
            content = value.get("text", json.dumps(value))
        else:
            content = str(value)
        write_memory(
            room_dir,
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

    console.print(f"[green]Synced:[/green] {written} memories")

    if not no_reindex:
        try:
            with httpx.Client(base_url=cfg.server.api_url, timeout=120) as client:
                resp = client.post(f"/rooms/{room_name}/reindex")
                resp.raise_for_status()
                data = resp.json()
            console.print(f"[green]Re-indexed:[/green] {data.get('indexed', 0)} memories")
        except Exception as e:
            console.print(f"[yellow]Warning:[/yellow] reindex failed: {e}")
