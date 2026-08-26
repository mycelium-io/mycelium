# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Memory commands: persistent namespaced memory operations.

Reads and writes resolve against the hub over HTTP; the hub owns the one store
(markdown files + the JSONL search index). A spoke needs no local replica.
"""

import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import httpx
import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from mycelium.client import hub_client, hub_error_detail, typed_client
from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref
from mycelium.filesystem import (
    get_room_dir,
    serialize_memory,
    write_memory,
)
from mycelium.protocol import MEMORY_CATEGORIES, MemoryLogEntry
from mycelium_backend_client.errors import UnexpectedStatus

app = typer.Typer(
    help="Read and write persistent memories scoped to rooms. Memories are markdown files in .mycelium/rooms/. Supports semantic vector search via a local JSONL index.",
    no_args_is_help=True,
)
console = Console()


def _get_client():
    """The shared authenticated OpenAPI client (see ``mycelium.client``)."""
    return typed_client()


def _hub_url() -> str:
    """The hub API URL this client resolves memory against."""
    return MyceliumConfig.load().server.api_url


@contextmanager
def _hub_session() -> Iterator[Any]:
    """Yield a hub client, reporting an unreachable hub instead of raising.

    Memory lives on the hub, so a hub that is down or misconfigured is an
    ordinary outcome to state plainly rather than a traceback.
    """
    with _get_client() as client:
        try:
            yield client
        except httpx.HTTPError as exc:
            console.print(f"[red]Error:[/red] can't reach the hub at {_hub_url()}: {exc}")
            console.print(
                "[dim]Check the hub is running ('mycelium status'), or point "
                "server.api_url at it.[/dim]"
            )
            raise typer.Exit(1) from exc
        except UnexpectedStatus as exc:
            detail = hub_error_detail(exc.content)
            suffix = f": {detail}" if detail else "."
            console.print(
                f"[red]Error:[/red] hub at {_hub_url()} returned HTTP {exc.status_code}{suffix}"
            )
            raise typer.Exit(1) from exc


def _unset_to_none(field: Any) -> Any:
    """Normalize a generated-client UNSET field to None."""
    from mycelium_backend_client.types import UNSET

    return None if isinstance(field, type(UNSET)) else field


def _meta_dict(field: Any) -> dict[str, Any]:
    """A memory's unmanaged frontmatter as a plain dict (empty when it has none)."""
    field = _unset_to_none(field)
    if hasattr(field, "to_dict"):
        field = field.to_dict()
    return field if isinstance(field, dict) else {}


def _value_text(value: Any) -> str:
    """Flatten a memory value to display text.

    A value is either a plain string or a structured dict (category keys carry
    ``text``/``logged_at``/``category``; a JSON memory carries its own shape).
    Structured values with no ``text`` render as pretty JSON.
    """
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    if isinstance(value, dict):
        text = value.get("text")
        return text if text is not None else json.dumps(value, indent=2, default=str)
    return "" if value is None else str(value)


def _resolve_value(value: str | None, file: str | None) -> str:
    """Resolve the memory value from the positional arg or a file.

    ``--file -`` reads stdin. The file's text is used verbatim; the two sources
    are mutually exclusive and exactly one must be given.
    """
    if value is not None and file is not None:
        console.print("[red]Error:[/red] pass either a value or --file, not both.")
        raise typer.Exit(1)

    if file is not None:
        if file == "-":
            return sys.stdin.read()
        try:
            return Path(file).read_text(encoding="utf-8")
        except OSError as exc:
            console.print(f"[red]Error:[/red] cannot read {file}: {exc.strerror or exc}")
            raise typer.Exit(1) from exc
        except UnicodeDecodeError as exc:
            console.print(f"[red]Error:[/red] {file} is not valid UTF-8 text.")
            raise typer.Exit(1) from exc

    if value is None:
        console.print("[red]Error:[/red] provide a value or --file <path> (use '-' for stdin).")
        raise typer.Exit(1)

    return value


def _parse_meta_pairs(pairs: list[str] | None) -> dict[str, Any]:
    """Parse repeated ``--meta key=value`` into frontmatter.

    Values are read as JSON when they parse (so ``true``, ``3``, and
    ``[a, b]`` land as their real types) and as plain strings otherwise, which
    is what a key like ``supersedes=decisions/db-v1`` wants.
    """
    frontmatter: dict[str, Any] = {}
    for pair in pairs or []:
        if "=" not in pair:
            console.print(f"[red]Error:[/red] --meta expects key=value, got '{pair}'.")
            raise typer.Exit(1)
        name, _, raw = pair.partition("=")
        try:
            frontmatter[name.strip()] = json.loads(raw)
        except json.JSONDecodeError:
            frontmatter[name.strip()] = raw
    return frontmatter


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
    usage="mycelium memory set <key> [<value>] [--file <path>] [--handle <handle>]",
    desc="Write a memory (upsert). The value comes from the positional argument or <code>--file</code> (<code>-</code> reads stdin): one or the other, not both. Structured category keys (<code>work/</code>, <code>decisions/</code>, <code>status/</code>, <code>context/</code>) are auto-validated. Always upserts; the backend handles versioning.",
    group="memory",
)
@app.command(name="set")
def memory_set(
    key: str = typer.Argument(..., help="Memory key (e.g. 'status/deploy', 'project/config')"),
    value: str | None = typer.Argument(None, help="Memory value (string or JSON)"),
    file: str | None = typer.Option(
        None, "--file", "-f", help="Read the value from a file ('-' for stdin)"
    ),
    room: str | None = typer.Option(
        None, "--room", "-r", help="Room name (defaults to active room)"
    ),
    handle: str = typer.Option("cli-user", "--handle", "-H", help="Agent handle"),
    no_embed: bool = typer.Option(False, "--no-embed", help="Skip vector embedding"),
    tags: str | None = typer.Option(None, "--tags", "-t", help="Comma-separated tags"),
    expandable: bool = typer.Option(
        False, "--expandable", help="Let other memories pull this one inline with ![[key]]"
    ),
    meta: list[str] | None = typer.Option(
        None,
        "--meta",
        "-m",
        help="Extra frontmatter as key=value (repeatable), e.g. -m supersedes=decisions/db-v1",
    ),
) -> None:
    """Write a memory to a room's persistent namespace (upsert).

    The value comes from the positional argument or --file; they are mutually
    exclusive and one is required.

    Keys with a known category prefix (work/, decisions/, context/, status/) are
    validated for slug format. Other keys pass through freely.

    Always upserts; the backend handles versioning.

    Examples:
        mycelium memory set status/deploy ACTIVE
        mycelium memory set decisions/db-choice "Chose AgensGraph for graph+SQL+vector"
        mycelium memory set work/api-server "Built 12 endpoints with auth"
        mycelium memory set reference/spec --file spec.md
        cat notes.md | mycelium memory set context/notes -f -
        mycelium memory set glossary/slim "SLIM is the messaging fabric." --expandable
        mycelium memory set decisions/db "Postgres" -m supersedes=decisions/db-v1
    """
    from mycelium_backend_client.api.memory import (
        create_memories_api_rooms_room_name_memory_post as create_api,
    )
    from mycelium_backend_client.models import MemoryBatchCreate, MemoryCreate

    value = _resolve_value(value, file)
    room_name = _get_active_room(room)

    # Validate structured keys when category prefix is recognized
    entry: MemoryLogEntry | None = None
    if "/" in key:
        category = key.split("/", 1)[0]
        if category in MEMORY_CATEGORIES:
            slug = key.split("/", 1)[1]
            try:
                entry = MemoryLogEntry(category=category, slug=slug, content=value)  # ty: ignore[invalid-argument-type]
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
        # Structured category key: auto-timestamp and structured value
        from mycelium_backend_client.models import MemoryCreateValueType0

        timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        structured_value = MemoryCreateValueType0()
        structured_value["text"] = entry.content
        structured_value["logged_at"] = timestamp
        structured_value["category"] = entry.category
        item = MemoryCreate(
            key=entry.key,
            value=structured_value,
            created_by=handle,
            embed=not no_embed,
            content_text=f"[{timestamp}] {entry.content}",
            tags=tag_list,
        )
    else:
        # Freeform key: pass value through as-is
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

    # Extra frontmatter rides as an additional property; the generated client
    # passes unknown fields through, so no client regen is needed.
    frontmatter = _parse_meta_pairs(meta)
    if expandable:
        frontmatter["expandable"] = True
    if frontmatter:
        item["meta"] = frontmatter

    batch = MemoryBatchCreate(items=[item])

    # Write to hub (single store; spoke has no local copy)
    with _hub_session() as client:
        result = create_api.sync(room_name=room_name, client=client, body=batch)
        if result and isinstance(result, list) and len(result) > 0:
            mem = result[0]
            version_info = f"v{mem.version}" if hasattr(mem, "version") else ""
            console.print(f"[green]Memory set:[/green] {room_name}/{key} ({version_info})")
        else:
            console.print(f"[green]Memory set:[/green] {room_name}/{key}")


@doc_ref(
    usage="mycelium memory get <key>",
    desc="Read a memory by exact key from the hub.",
    group="memory",
)
@app.command(name="get")
def memory_get(
    key: str = typer.Argument(..., help="Memory key"),
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
    raw: bool = typer.Option(False, "--raw", help="Show the markdown form (frontmatter + body)"),
    expand: bool = typer.Option(
        False, "--expand", help="Expand ![[key]] transclusions inline from their source"
    ),
) -> None:
    """Read a memory by key (from the hub)."""
    from mycelium_backend_client.api.memory import (
        get_memory_api_rooms_room_name_memory_key_get as get_api,
    )
    from mycelium_backend_client.models import MemoryRead

    room_name = _get_active_room(room)

    if expand:
        _print_expanded(room_name, key)
        return

    with _hub_session() as client:
        try:
            mem = get_api.sync(room_name=room_name, key=key, client=client)
        except UnexpectedStatus as exc:
            if exc.status_code == 404:
                console.print(f"[red]Not found:[/red] {key}")
                raise typer.Exit(1) from exc
            raise

    if not isinstance(mem, MemoryRead):
        console.print(f"[red]Not found:[/red] {key}")
        raise typer.Exit(1)

    content = _value_text(mem.value)

    if raw:
        console.print(
            serialize_memory(
                content,
                key=mem.key,
                created_by=mem.created_by,
                updated_by=_unset_to_none(mem.updated_by),
                version=mem.version,
                tags=_unset_to_none(mem.tags),
                created_at=mem.created_at,
                updated_at=mem.updated_at,
                extra_meta=_meta_dict(mem.meta) or None,
            )
        )
        return

    thread = _unset_to_none(mem.episode)
    header = f"[cyan]{mem.key}[/cyan]  [dim]v{mem.version}  {mem.created_by}"
    console.print(
        f"{header}  thread {thread.rsplit(':', 1)[-1]}[/dim]" if thread else f"{header}[/dim]"
    )
    console.print(content)
    # Every memory a person wrote carries a thread, and nothing else in the CLI
    # says so — a reader who does not know the verb has no way to find it.
    if thread:
        console.print(f'\n[dim]discuss it: mycelium board send {mem.key} "…"[/dim]')


def _fetch_memories(room_name: str, prefix: str | None, limit: int) -> list[dict[str, Any]]:
    """Fetch a room's memories from the hub, newest-first as the hub orders them.

    Returns the raw JSON records (the list endpoint is untyped in the generated
    client), or exits with a clear message when the room is unknown.
    """
    from mycelium_backend_client.api.memory import (
        list_memories_api_rooms_room_name_memory_get as list_api,
    )

    with _hub_session() as client:
        try:
            entries = list_api.sync(room_name=room_name, client=client, prefix=prefix, limit=limit)
        except UnexpectedStatus as exc:
            if exc.status_code == 404:
                console.print(
                    f"[red]Not found:[/red] room '{room_name}' does not exist on the hub "
                    f"at {_hub_url()}"
                )
                raise typer.Exit(1) from exc
            raise

    if not isinstance(entries, list):
        return []
    return cast("list[dict[str, Any]]", [r for r in entries if isinstance(r, dict)])


@doc_ref(
    usage="mycelium memory ls [prefix/]",
    desc="List memories from the hub. Optional prefix filters by namespace.",
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
    """List memories in a room (from the hub)."""
    prefix = namespace or prefix
    room_name = _get_active_room(room)

    entries = _fetch_memories(room_name, prefix, limit)
    if not entries:
        console.print("[dim]No memories found[/dim]")
        return

    console.print(f"[bold]{room_name}[/bold] ({len(entries)} memories)\n")

    for mem in entries:
        ts = str(mem.get("updated_at", ""))[:16].replace("T", " ")
        version = mem.get("version", "?")
        created_by = mem.get("created_by", "?")
        console.print(
            f"[cyan]{mem.get('key', '?')}[/cyan]  [dim]v{version}  {created_by}  {ts}[/dim]"
        )
        content = _value_text(mem.get("value"))
        display = content[:120]
        if display:
            console.print(f"  {display}{'...' if len(content) > 120 else ''}")
        console.print()


@doc_ref(
    usage="mycelium memory search <query>",
    desc="Semantic search: finds memories by meaning using cosine similarity on local embeddings. Requires the backend API.",
    group="memory",
)
@app.command(name="search")
def memory_search(
    query: str = typer.Argument(..., help="Natural language search query"),
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
    limit: int = typer.Option(5, "--limit", "-n", help="Max results"),
) -> None:
    """Semantic search over memories (via the backend API)."""
    from mycelium_backend_client.api.memory import (
        search_memories_api_rooms_room_name_memory_search_post as search_api,
    )
    from mycelium_backend_client.models import MemorySearchRequest

    room_name = _get_active_room(room)

    with _hub_session() as client:
        body = MemorySearchRequest(query=query, limit=limit)
        from mycelium_backend_client.models import MemorySearchResponse

        result = search_api.sync(room_name=room_name, client=client, body=body)

        if not isinstance(result, MemorySearchResponse) or not result.results:
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


# How a link failed to resolve, in words. The backend reports codes; only the
# CLI has to phrase them.
_LINK_ERRORS = {
    "not_found": "no such memory",
    "no_anchor": "no such section",
    "not_expandable": "target is not expandable",
    "cross_room": "cross-room links are not supported",
}


def _link_label(link: dict[str, Any]) -> str:
    """The kind of edge a link is, for the right-hand column."""
    return link.get("relation") or link.get("kind") or "link"


def _link_target(link: dict[str, Any]) -> str:
    """The link's target, with its section anchor when it has one."""
    target = str(link.get("target", "?"))
    anchor = link.get("anchor")
    return f"{target}#{anchor}" if anchor else target


def _fetch_links(room_name: str, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
    """GET a link endpoint on the hub, reporting an unreachable hub plainly."""
    cfg = MyceliumConfig.load()
    try:
        with hub_client(cfg, timeout=30) as client:
            resp = client.get(f"/api/rooms/{room_name}/links{path}", params=params)
            if resp.status_code == 404:
                console.print(f"[red]Not found:[/red] room '{room_name}' or key on {_hub_url()}")
                raise typer.Exit(1)
            resp.raise_for_status()
            return cast("dict[str, Any]", resp.json())
    except httpx.HTTPError as exc:
        console.print(f"[red]Error:[/red] can't reach the hub at {_hub_url()}: {exc}")
        raise typer.Exit(1) from exc


def _print_expanded(room_name: str, key: str) -> None:
    """Print a memory's body with its transclusions pulled in.

    A marker that couldn't be expanded is left exactly as written and called out
    below the body, so a refused embed never reads as an empty definition.
    """
    data = _fetch_links(room_name, "/expand", {"key": key})
    console.print(f"[cyan]{key}[/cyan]  [dim]expanded[/dim]")
    console.print(data.get("rendered", ""))

    failed = [e for e in (data.get("expansions") or []) if not e.get("expanded")]
    if failed:
        console.print()
        for exp in failed:
            reason = _LINK_ERRORS.get(str(exp.get("error")), str(exp.get("error")))
            console.print(
                f"[yellow]Not expanded:[/yellow] [cyan]{_link_target(exp)}[/cyan]: {reason}"
            )


def _print_integrity(room_name: str) -> None:
    """Room-wide link health: broken links, orphans, roots, and leaves.

    Terminology:
    - orphan: no inbound links AND no outbound links — fully isolated.
    - root:   no inbound links but has outbound links — an entry point.
    - leaf:   has inbound links but no outbound links — a dead end.
    """
    report = _fetch_links(room_name, "/integrity")
    broken = report.get("broken") or []
    orphans = report.get("orphans") or []
    roots = report.get("roots") or []
    leaves = report.get("leaves") or []

    console.print(
        f"[bold]{room_name}[/bold]  [dim]{report.get('total_memories', 0)} memories, "
        f"{report.get('total_links', 0)} links[/dim]\n"
    )

    if broken:
        console.print(f"[yellow]Broken links ({len(broken)})[/yellow]")
        for link in broken:
            reason = _LINK_ERRORS.get(str(link.get("error")), str(link.get("error")))
            console.print(
                f"  [dim]{link.get('source', '?')}[/dim] → [cyan]{_link_target(link)}[/cyan]"
                f"  [red]{reason}[/red]"
            )
        console.print()
    else:
        console.print("[green]No broken links[/green]\n")

    if orphans:
        console.print(f"[yellow]Orphans ({len(orphans)})[/yellow]: no links in or out")
        for key in orphans:
            console.print(f"  [cyan]{key}[/cyan]")
        console.print()

    if roots:
        console.print(f"[dim]Roots ({len(roots)}): nothing links here yet[/dim]")
        for key in roots:
            console.print(f"  [cyan]{key}[/cyan]")
        console.print()

    if leaves:
        console.print(f"[dim]Leaves ({len(leaves)}): links arrive but go no further[/dim]")
        for key in leaves:
            console.print(f"  [cyan]{key}[/cyan]")


@doc_ref(
    usage="mycelium memory links <key> [--check]",
    desc="Show a memory's links: what it points at and what points back at it. Links are <code>myc://key</code> or <code>[[key]]</code> in the body, plus typed frontmatter relations (<code>supersedes</code>, <code>depends-on</code>, <code>part-of</code>, <code>relates-to</code>). <code>--check</code> reports broken links, orphans (no connections), roots (no inbound), and leaves (no outbound) across the whole room.",
    group="memory",
)
@app.command(name="links")
def memory_links(
    key: str | None = typer.Argument(None, help="Memory key to inspect"),
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
    check: bool = typer.Option(
        False, "--check", help="Report broken links, orphans, roots, and leaves across the room"
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit raw JSON"),
) -> None:
    """Show what a memory links to, and what links back to it.

    Backlinks are the point: before you change a memory, they tell you exactly
    which other memories depend on what it says.

    Examples:
        mycelium memory links decisions/db
        mycelium memory links --check
    """
    room_name = _get_active_room(room)

    if check:
        if as_json:
            console.print_json(data=_fetch_links(room_name, "/integrity"))
            return
        _print_integrity(room_name)
        return

    if not key:
        console.print("[red]Error:[/red] provide a memory key, or --check for the whole room.")
        raise typer.Exit(1)

    data = _fetch_links(room_name, "", {"key": key})
    if as_json:
        console.print_json(data=data)
        return

    outbound = data.get("outbound") or []
    backlinks = data.get("backlinks") or []

    console.print(f"[bold cyan]{key}[/bold cyan]\n")

    if outbound:
        console.print("[dim]→ links to[/dim]")
        for link in outbound:
            ok = link.get("resolved")
            mark = "[green]✓[/green]" if ok else "[red]✗[/red]"
            reason = "" if ok else f"  [red]{_LINK_ERRORS.get(str(link.get('error')), '?')}[/red]"
            console.print(
                f"  {mark} [cyan]{_link_target(link)}[/cyan]"
                f"  [dim]{_link_label(link)}[/dim]{reason}"
            )
        console.print()
    else:
        console.print("[dim]→ links to nothing[/dim]\n")

    if backlinks:
        console.print(f"[dim]← referenced by ({len(backlinks)})[/dim]")
        for link in backlinks:
            console.print(
                f"  [cyan]{link.get('source', '?')}[/cyan]  [dim]{_link_label(link)}[/dim]"
            )
    else:
        console.print("[dim]← referenced by nothing[/dim]")


@doc_ref(
    usage="mycelium memory rm <key> [--force]",
    desc="Delete a memory: removes the markdown file and search index entry.",
    group="memory",
)
@app.command(name="rm")
def memory_rm(
    key: str = typer.Argument(..., help="Memory key to delete"),
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
) -> None:
    """Delete a memory (removes both the file and search index)."""
    from mycelium_backend_client.api.memory import (
        delete_memory_api_rooms_room_name_memory_key_delete as delete_api,
    )

    room_name = _get_active_room(room)

    if not force:
        confirm = typer.confirm(f"Delete memory '{key}' from room '{room_name}'?")
        if not confirm:
            raise typer.Exit(0)

    # Delete on the hub, which owns the store (file + index). No local copy exists.
    with _hub_session() as client:
        delete_api.sync_detailed(room_name=room_name, key=key, client=client)
        console.print(f"[green]Deleted:[/green] {key}")


@doc_ref(
    usage="mycelium memory reindex",
    desc="Re-index the room into the local JSONL search index. Run after editing memory files outside the CLI.",
    group="memory",
)
@app.command(name="reindex")
def memory_reindex(
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
) -> None:
    """Re-index the room into the local JSONL search index.

    Run after editing memory files outside the CLI to update search.
    """
    room_name = _get_active_room(room)
    cfg = MyceliumConfig.load()

    console.print(f"[dim]Re-indexing {room_name}...[/dim]")
    with hub_client(cfg, timeout=120) as client:
        resp = client.post(f"/api/rooms/{room_name}/reindex")
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
        subscribe_api_rooms_room_name_memory_subscribe_post as sub_api,
    )
    from mycelium_backend_client.models import SubscriptionCreate, SubscriptionRead

    room_name = _get_active_room(room)

    with _get_client() as client:
        body = SubscriptionCreate(key_pattern=pattern, subscriber=handle)
        result = sub_api.sync(room_name=room_name, client=client, body=body)
        if isinstance(result, SubscriptionRead):
            sub_id = str(result.id)[:8] if result.id else "?"
            console.print(f"[green]Subscribed:[/green] {pattern} (id: {sub_id}...)")


# ── Structured memory commands ───────────────────────────────────────────────


def _list_by_category(category: str, room: str | None, limit: int) -> None:
    """Shared implementation for category-filtered listing; reads from the hub."""
    room_name = _get_active_room(room)
    prefix = f"{category}/"

    entries = _fetch_memories(room_name, prefix, limit)
    if not entries:
        console.print(f"[dim]No {category} memories found[/dim]")
        return

    table = Table(title=f"{room_name}: {category}", show_lines=False)
    table.add_column("Key", style="cyan", no_wrap=True)
    table.add_column("Value", max_width=80)
    table.add_column("By", style="dim")
    table.add_column("Updated", style="dim")

    for mem in entries:
        short_key = str(mem.get("key", "?")).removeprefix(prefix)
        display = _value_text(mem.get("value"))[:80]
        ts = str(mem.get("updated_at", ""))[:16].replace("T", " ")
        created_by = mem.get("created_by", "?")
        table.add_row(short_key, display, created_by, ts)

    console.print(table)


@doc_ref(
    usage="mycelium memory status",
    desc="Show current status: filters to <code>status/*</code> memories as a table.",
    group="memory",
)
@app.command(name="status")
def memory_status(
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
) -> None:
    """Show current status of everything (filters to status/* memories)."""
    _list_by_category("status", room, limit)


@doc_ref(
    usage="mycelium memory work",
    desc="Show what's been built: filters to <code>work/*</code> memories as a table.",
    group="memory",
)
@app.command(name="work")
def memory_work(
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
) -> None:
    """Show what's been built (filters to work/* memories)."""
    _list_by_category("work", room, limit)


@doc_ref(
    usage="mycelium memory decisions",
    desc="Show why choices were made: filters to <code>decisions/*</code> memories as a table.",
    group="memory",
)
@app.command(name="decisions")
def memory_decisions(
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
) -> None:
    """Show why choices were made (filters to decisions/* memories)."""
    _list_by_category("decisions", room, limit)


@doc_ref(
    usage="mycelium memory context",
    desc="Show background and preferences: filters to <code>context/*</code> memories as a table.",
    group="memory",
)
@app.command(name="context")
def memory_context(
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
) -> None:
    """Show background and preferences (filters to context/* memories)."""
    _list_by_category("context", room, limit)


@doc_ref(
    usage="mycelium memory procedures",
    desc="Show reusable how-to steps: filters to <code>procedures/*</code> memories as a table.",
    group="memory",
)
@app.command(name="procedures")
def memory_procedures(
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
) -> None:
    """Show reusable how-to procedures (filters to procedures/* memories)."""
    _list_by_category("procedures", room, limit)


# ── Sync commands ────────────────────────────────────────────────────────────


@doc_ref(
    usage="mycelium sync [--no-reindex]",
    desc="Sync the active room with the backend: fetch all memories from the API and write them locally.",
    group="other",
)
@app.command(name="sync")
def memory_sync(
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
    no_reindex: bool = typer.Option(False, "--no-reindex", help="Skip re-indexing after sync"),
) -> None:
    """Sync room files from the backend API, fetching all memories and writing local copies.

    Use this to pull the latest room state from a remote backend instance.
    Hooks call this on session start/end to keep local files current.

    Examples:
        mycelium sync           # fetch all memories + reindex
        mycelium sync --no-reindex
    """
    room_name = _get_active_room(room)
    cfg = MyceliumConfig.load()

    from mycelium.filesystem import get_mycelium_dir

    etag_file = get_mycelium_dir() / "rooms" / room_name / ".sync-etag"
    headers = {}
    if etag_file.exists():
        headers["If-None-Match"] = etag_file.read_text().strip()

    console.print(f"[dim]Syncing {room_name} from {cfg.server.api_url}...[/dim]")

    with hub_client(cfg, timeout=60, headers=headers) as client:
        resp = client.get(f"/api/rooms/{room_name}/memory", params={"limit": 1000})

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

    from datetime import datetime

    def _parse_dt(val: str | None):
        if not val:
            return None
        if isinstance(val, datetime):
            return val
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None

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
            created_at=_parse_dt(mem.get("created_at")),
            updated_at=_parse_dt(mem.get("updated_at")),
        )
        written += 1

    console.print(f"[green]Synced:[/green] {written} memories")

    if not no_reindex:
        try:
            with hub_client(cfg, timeout=120) as client:
                resp = client.post(f"/api/rooms/{room_name}/reindex")
                resp.raise_for_status()
                data = resp.json()
            console.print(f"[green]Re-indexed:[/green] {data.get('indexed', 0)} memories")
        except Exception as e:
            console.print(f"[yellow]Warning:[/yellow] reindex failed: {e}")
