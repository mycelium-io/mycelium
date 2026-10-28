# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Memory commands: persistent namespaced memory operations.

Reads and writes resolve against the hub over HTTP; the hub owns the one store
(markdown files + the JSONL search index). A spoke needs no local replica.
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import httpx
import typer
from pydantic import ValidationError
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from mycelium import identity
from mycelium.cli_options import acts_as, confirms, emits_json, in_room, paged, room_or_exit
from mycelium.client import answered, hub_error_detail, typed_client
from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref
from mycelium.filesystem import (
    get_room_dir,
    serialize_memory,
    write_hub_memories,
)
from mycelium.protocol import MEMORY_CATEGORIES, MemoryLogEntry
from mycelium.text_input import takes_text
from mycelium_backend_client.errors import UnexpectedStatus
from mycelium_backend_client.models import (
    ExpandedMemoryRead,
    LinkIntegrityRead,
    LinkRead,
    MemoryLinksRead,
    MemoryRead,
    RoomReindexRead,
    TransclusionRead,
)

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
    """The room to use, in ``caller.room``'s order."""
    return room_or_exit(MyceliumConfig.load(), room)


def _echo_json(data: Any) -> None:
    """Print ``data`` as JSON and nothing else, for ``--json``."""
    typer.echo(json.dumps(data, indent=2, default=str))


@doc_ref(
    usage="mycelium memory set <key> [<value>] [--body <markdown>] [--file <path>] [--handle <handle>]",
    desc="Write a memory (upsert). The value comes from the positional argument, <code>--body</code>, or <code>--file</code> (<code>-</code> reads stdin): exactly one of them. Structured category keys (<code>work/</code>, <code>decisions/</code>, <code>status/</code>, <code>context/</code>) are auto-validated. Always upserts; the backend handles versioning.",
    group="memory",
)
@app.command(name="set")
@takes_text("value", "The memory: markdown, plain text or JSON.", noun="value")
@in_room("room")
@acts_as("handle")
def memory_set(
    key: str = typer.Argument(..., help="Memory key (e.g. 'status/deploy', 'project/config')"),
    value: str = typer.Argument(..., help="Memory value (string or JSON)"),
    room: str | None = None,
    handle: str | None = None,
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

    The value comes from the positional argument, --body, or --file; exactly
    one of them.

    Keys with a known category prefix (work/, decisions/, context/, status/,
    procedures/) are checked: each part is lowercase letters, digits, `-`, `_`
    and `.`. Under context/ and procedures/ a key can have folders of its own
    (context/api/latency); work/, decisions/ and status/ keys are board rows and
    take one name. Other keys pass through freely.

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

    if not key.strip() or "\\" in key or key.endswith("/"):
        console.print(
            f"[red]Error:[/red] {key!r} isn't a memory key. Use `/` between its parts, like context/goal."
        )
        raise typer.Exit(1)

    room_name = _get_active_room(room)
    handle = identity.resolve_actor(MyceliumConfig.load(), override=handle)

    # Validate structured keys when category prefix is recognized
    entry: MemoryLogEntry | None = None
    if "/" in key:
        category = key.split("/", 1)[0]
        if category in MEMORY_CATEGORIES:
            slug = key.split("/", 1)[1]
            try:
                entry = MemoryLogEntry(category=category, slug=slug, content=value)  # ty: ignore[invalid-argument-type]
            except ValidationError as exc:
                slug_error = next((e for e in exc.errors() if e["loc"] == ("slug",)), None)
                if slug_error is not None:
                    why = (slug_error.get("ctx") or {}).get("error") or slug_error["msg"]
                    console.print(f"[red]Error:[/red] {escape(key)} {escape(str(why))}")
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
        resp = create_api.sync_detailed(room_name=room_name, client=client, body=batch)
        # A validation refusal is said here; any other refusal is the session's to report.
        saved: list[MemoryRead] = [] if resp.status_code == 422 else answered(resp, list)  # noqa: PLR2004
        if not saved:
            said = resp.parsed if resp.status_code == 422 else saved  # noqa: PLR2004
            console.print(f"[red]Error:[/red] the hub didn't save {room_name}/{key}: {said}")
            raise typer.Exit(1)
        console.print(f"[green]Memory set:[/green] {room_name}/{key} (v{saved[0].version})")


@doc_ref(
    usage="mycelium memory get <key>",
    desc="Read a memory by exact key from the hub.",
    group="memory",
)
@app.command(name="get")
@in_room("room")
@emits_json("as_json")
def memory_get(
    key: str = typer.Argument(..., help="Memory key"),
    room: str | None = None,
    raw: bool = typer.Option(False, "--raw", help="Show the markdown form (frontmatter + body)"),
    expand: bool = typer.Option(
        False, "--expand", help="Expand ![[key]] transclusions inline from their source"
    ),
    as_json: bool = False,
) -> None:
    """Read a memory by key (from the hub)."""
    from mycelium_backend_client.api.memory import (
        get_memory_api_rooms_room_name_memory_key_get as get_api,
    )

    room_name = _get_active_room(room)

    if expand:
        if as_json:
            _echo_json(_expanded(room_name, key).to_dict())
            return
        _print_expanded(room_name, key)
        return

    with _hub_session() as client:
        try:
            mem = answered(
                get_api.sync_detailed(room_name=room_name, key=key, client=client), MemoryRead
            )
        except UnexpectedStatus as exc:
            if exc.status_code == 404:
                console.print(f"[red]Not found:[/red] {key}")
                raise typer.Exit(1) from exc
            raise

    if as_json:
        _echo_json(mem.to_dict())
        return

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
            ),
            markup=False,
            soft_wrap=True,
        )
        return

    thread = _unset_to_none(mem.episode)
    header = f"[cyan]{mem.key}[/cyan]  [dim]v{mem.version}  {mem.created_by}"
    console.print(
        f"{header}  thread {thread.rsplit(':', 1)[-1]}[/dim]" if thread else f"{header}[/dim]"
    )
    # The body is the author's text, not Rich markup: `[[key]]` links would vanish,
    # and Rich's wrapping would add line breaks the memory doesn't have.
    console.print(content, markup=False, soft_wrap=True)
    # Every memory a person wrote carries a thread, and nothing else in the CLI
    # says so — a reader who does not know the verb has no way to find it.
    if thread:
        console.print(f'\n[dim]discuss it: mycelium board send {mem.key} "…"[/dim]')


def _fetch_memories(room_name: str, prefix: str | None, limit: int) -> list[MemoryRead]:
    """Fetch a room's memories from the hub, newest-first as the hub orders them.

    Exits with a clear message when the room is unknown.
    """
    from mycelium_backend_client.api.memory import (
        list_memories_api_rooms_room_name_memory_get as list_api,
    )

    with _hub_session() as client:
        try:
            return answered(
                list_api.sync_detailed(
                    room_name=room_name, client=client, prefix=prefix, limit=limit
                ),
                list,
            )
        except UnexpectedStatus as exc:
            if exc.status_code == 404:
                console.print(
                    f"[red]Not found:[/red] room '{room_name}' does not exist on the hub "
                    f"at {_hub_url()}"
                )
                raise typer.Exit(1) from exc
            raise


@doc_ref(
    usage="mycelium memory ls [prefix/]",
    desc="List memories from the hub. Optional prefix filters by namespace.",
    group="memory",
)
@app.command(name="ls")
@in_room("room")
@paged("limit")
@emits_json("as_json")
def memory_ls(
    namespace: str | None = typer.Argument(
        None, help="Key prefix to filter by (e.g. 'position/' or 'decisions/')"
    ),
    room: str | None = None,
    prefix: str | None = typer.Option(
        None, "--prefix", "-p", help="Key prefix filter (same as positional arg)"
    ),
    limit: int = 20,
    as_json: bool = False,
) -> None:
    """List memories in a room (from the hub)."""
    prefix = namespace or prefix
    room_name = _get_active_room(room)

    entries = _fetch_memories(room_name, prefix, limit)
    if as_json:
        _echo_json([m.to_dict() for m in entries])
        return
    if not entries:
        console.print("[dim]No memories found[/dim]")
        return

    console.print(f"[bold]{room_name}[/bold] ({len(entries)} memories)\n")

    for mem in entries:
        ts = mem.updated_at.isoformat()[:16].replace("T", " ")
        console.print(f"[cyan]{mem.key}[/cyan]  [dim]v{mem.version}  {mem.created_by}  {ts}[/dim]")
        content = _value_text(mem.value)
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
@in_room("room")
@paged("limit")
@emits_json("as_json")
def memory_search(
    query: str = typer.Argument(..., help="Natural language search query"),
    room: str | None = None,
    limit: int = 5,
    as_json: bool = False,
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

        result = answered(
            search_api.sync_detailed(room_name=room_name, client=client, body=body),
            MemorySearchResponse,
        )

        if as_json:
            _echo_json([r.to_dict() for r in result.results])
            return

        if not result.results:
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


def _link_label(link: LinkRead) -> str:
    """The kind of edge a link is, for the right-hand column."""
    return link.relation or link.kind or "link"


def _link_target(link: LinkRead | TransclusionRead) -> str:
    """The link's target, with its section anchor when it has one."""
    return f"{link.target}#{link.anchor}" if link.anchor else link.target


@contextmanager
def _links_session(room_name: str) -> Iterator[Any]:
    """Yield a hub client for a link read, saying plainly what went wrong.

    A 404 is the room or the key; an unreachable hub, or any other refusal, is
    said as the hub's.
    """
    with typed_client(MyceliumConfig.load(), timeout=30) as client:
        try:
            yield client
        except UnexpectedStatus as exc:
            if exc.status_code == 404:  # noqa: PLR2004
                console.print(f"[red]Not found:[/red] room '{room_name}' or key on {_hub_url()}")
                raise typer.Exit(1) from exc
            console.print(
                f"[red]Error:[/red] can't reach the hub at {_hub_url()}: "
                f"HTTP {exc.status_code}: {hub_error_detail(exc.content)}"
            )
            raise typer.Exit(1) from exc
        except httpx.HTTPError as exc:
            console.print(f"[red]Error:[/red] can't reach the hub at {_hub_url()}: {exc}")
            raise typer.Exit(1) from exc


def _expanded(room_name: str, key: str) -> ExpandedMemoryRead:
    from mycelium_backend_client.api.links import (
        get_expanded_api_rooms_room_name_links_expand_get as expand_api,
    )

    with _links_session(room_name) as client:
        return answered(
            expand_api.sync_detailed(room_name, client=client, key=key), ExpandedMemoryRead
        )


def _integrity(room_name: str) -> LinkIntegrityRead:
    from mycelium_backend_client.api.links import (
        get_integrity_api_rooms_room_name_links_integrity_get as integrity_api,
    )

    with _links_session(room_name) as client:
        return answered(integrity_api.sync_detailed(room_name, client=client), LinkIntegrityRead)


def _links(room_name: str, key: str) -> MemoryLinksRead:
    from mycelium_backend_client.api.links import (
        get_links_api_rooms_room_name_links_get as links_api,
    )

    with _links_session(room_name) as client:
        return answered(links_api.sync_detailed(room_name, client=client, key=key), MemoryLinksRead)


def _print_expanded(room_name: str, key: str) -> None:
    """Print a memory's body with its transclusions pulled in.

    A marker that couldn't be expanded is left exactly as written and called out
    below the body, so a refused embed never reads as an empty definition.
    """
    data = _expanded(room_name, key)
    console.print(f"[cyan]{key}[/cyan]  [dim]expanded[/dim]")
    console.print(data.rendered, markup=False, soft_wrap=True)

    failed = [e for e in data.expansions if not e.expanded]
    if failed:
        console.print()
        for exp in failed:
            reason = _LINK_ERRORS.get(str(exp.error), str(exp.error))
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
    report = _integrity(room_name)
    broken = report.broken
    orphans = report.orphans
    roots = report.roots
    leaves = report.leaves

    console.print(
        f"[bold]{room_name}[/bold]  [dim]{report.total_memories} memories, "
        f"{report.total_links} links[/dim]\n"
    )

    if broken:
        console.print(f"[yellow]Broken links ({len(broken)})[/yellow]")
        for link in broken:
            reason = _LINK_ERRORS.get(str(link.error), str(link.error))
            console.print(
                f"  [dim]{link.source or '?'}[/dim] → [cyan]{_link_target(link)}[/cyan]"
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
@in_room("room")
@emits_json("as_json")
def memory_links(
    key: str | None = typer.Argument(None, help="Memory key to inspect"),
    room: str | None = None,
    check: bool = typer.Option(
        False, "--check", help="Report broken links, orphans, roots, and leaves across the room"
    ),
    as_json: bool = False,
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
            _echo_json(_integrity(room_name).to_dict())
            return
        _print_integrity(room_name)
        return

    if not key:
        console.print("[red]Error:[/red] provide a memory key, or --check for the whole room.")
        raise typer.Exit(1)

    data = _links(room_name, key)
    if as_json:
        _echo_json(data.to_dict())
        return

    outbound = data.outbound
    backlinks = data.backlinks

    console.print(f"[bold cyan]{key}[/bold cyan]\n")

    if outbound:
        console.print("[dim]→ links to[/dim]")
        for link in outbound:
            ok = link.resolved
            mark = "[green]✓[/green]" if ok else "[red]✗[/red]"
            reason = "" if ok else f"  [red]{_LINK_ERRORS.get(str(link.error), '?')}[/red]"
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
            console.print(f"  [cyan]{link.source or '?'}[/cyan]  [dim]{_link_label(link)}[/dim]")
    else:
        console.print("[dim]← referenced by nothing[/dim]")


@doc_ref(
    usage="mycelium memory rm <key> [--force]",
    desc="Delete a memory: removes the markdown file and search index entry.",
    group="memory",
)
@app.command(name="rm")
@in_room("room")
@confirms("force", also_force=True)
def memory_rm(
    key: str = typer.Argument(..., help="Memory key to delete"),
    room: str | None = None,
    force: bool = False,
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
        resp = delete_api.sync_detailed(room_name=room_name, key=key, client=client)
        if resp.status_code >= 400:  # noqa: PLR2004
            raise UnexpectedStatus(resp.status_code, resp.content)
        console.print(f"[green]Deleted:[/green] {key}")


@doc_ref(
    usage="mycelium memory reindex",
    desc="Re-index the room into the local JSONL search index. Run after editing memory files outside the CLI.",
    group="memory",
)
@app.command(name="reindex")
@in_room("room")
def memory_reindex(
    room: str | None = None,
) -> None:
    """Re-index the room into the local JSONL search index.

    Run after editing memory files outside the CLI to update search.
    """
    room_name = _get_active_room(room)
    cfg = MyceliumConfig.load()

    console.print(f"[dim]Re-indexing {room_name}...[/dim]")
    stats = _reindex(cfg, room_name)
    if stats is None:
        console.print(f"[red]Error:[/red] the hub didn't reindex {room_name}")
        raise typer.Exit(1)
    console.print(f"[green]Re-indexed:[/green] {stats.indexed} memories")
    if stats.errors:
        console.print(f"[yellow]Errors:[/yellow] {stats.errors}")


def _reindex(cfg: MyceliumConfig, room_name: str) -> RoomReindexRead | None:
    """Have the hub rebuild the room's search index: what it did, or ``None``
    when it refused."""
    from mycelium_backend_client.api.rooms import (
        reindex_room_api_rooms_room_name_reindex_post as reindex_api,
    )

    with typed_client(cfg, timeout=120) as client:
        resp = reindex_api.sync_detailed(room_name, client=client)
    # A validation refusal is the ``None`` above; any other refusal raises.
    return None if resp.status_code == 422 else answered(resp, RoomReindexRead)  # noqa: PLR2004


@doc_ref(
    usage="mycelium memory subscribe <pattern> [-H <handle>]",
    desc="Subscribe to memory change notifications matching a glob pattern.",
    group="memory",
)
@app.command(name="subscribe")
@in_room("room")
@acts_as("handle")
def memory_subscribe(
    pattern: str = typer.Argument(..., help="Key glob pattern (e.g. 'project/*')"),
    room: str | None = None,
    handle: str | None = None,
) -> None:
    """Subscribe to memory change notifications."""
    from mycelium_backend_client.api.memory import (
        subscribe_api_rooms_room_name_memory_subscribe_post as sub_api,
    )
    from mycelium_backend_client.models import SubscriptionCreate, SubscriptionRead

    room_name = _get_active_room(room)
    handle = identity.resolve_actor(MyceliumConfig.load(), override=handle)

    with _get_client() as client:
        body = SubscriptionCreate(key_pattern=pattern, subscriber=handle)
        result = answered(
            sub_api.sync_detailed(room_name=room_name, client=client, body=body), SubscriptionRead
        )
        console.print(f"[green]Subscribed:[/green] {pattern} (id: {str(result.id)[:8]}...)")


# ── Structured memory commands ───────────────────────────────────────────────


def _list_by_category(category: str, room: str | None, limit: int, *, as_json: bool) -> None:
    """Shared implementation for category-filtered listing; reads from the hub."""
    room_name = _get_active_room(room)
    prefix = f"{category}/"

    entries = _fetch_memories(room_name, prefix, limit)
    if as_json:
        _echo_json([m.to_dict() for m in entries])
        return
    if not entries:
        console.print(f"[dim]No {category} memories found[/dim]")
        return

    table = Table(title=f"{room_name}: {category}", show_lines=False)
    table.add_column("Key", style="cyan", no_wrap=True)
    table.add_column("Value", max_width=80)
    table.add_column("By", style="dim")
    table.add_column("Updated", style="dim")

    for mem in entries:
        short_key = mem.key.removeprefix(prefix)
        display = _value_text(mem.value)[:80]
        ts = mem.updated_at.isoformat()[:16].replace("T", " ")
        table.add_row(short_key, display, mem.created_by, ts)

    console.print(table)


@doc_ref(
    usage="mycelium memory status",
    desc="Show current status: filters to <code>status/*</code> memories as a table.",
    group="memory",
)
@app.command(name="status")
@in_room("room")
@paged("limit")
@emits_json("as_json")
def memory_status(room: str | None = None, limit: int = 20, as_json: bool = False) -> None:
    """Show current status of everything (filters to status/* memories)."""
    _list_by_category("status", room, limit, as_json=as_json)


@doc_ref(
    usage="mycelium memory work",
    desc="Show what's been built: filters to <code>work/*</code> memories as a table.",
    group="memory",
)
@app.command(name="work")
@in_room("room")
@paged("limit")
@emits_json("as_json")
def memory_work(room: str | None = None, limit: int = 20, as_json: bool = False) -> None:
    """Show what's been built (filters to work/* memories)."""
    _list_by_category("work", room, limit, as_json=as_json)


@doc_ref(
    usage="mycelium memory decisions",
    desc="Show why choices were made: filters to <code>decisions/*</code> memories as a table.",
    group="memory",
)
@app.command(name="decisions")
@in_room("room")
@paged("limit")
@emits_json("as_json")
def memory_decisions(room: str | None = None, limit: int = 20, as_json: bool = False) -> None:
    """Show why choices were made (filters to decisions/* memories)."""
    _list_by_category("decisions", room, limit, as_json=as_json)


@doc_ref(
    usage="mycelium memory context",
    desc="Show background and preferences: filters to <code>context/*</code> memories as a table.",
    group="memory",
)
@app.command(name="context")
@in_room("room")
@paged("limit")
@emits_json("as_json")
def memory_context(room: str | None = None, limit: int = 20, as_json: bool = False) -> None:
    """Show background and preferences (filters to context/* memories)."""
    _list_by_category("context", room, limit, as_json=as_json)


@doc_ref(
    usage="mycelium memory procedures",
    desc="Show reusable how-to steps: filters to <code>procedures/*</code> memories as a table.",
    group="memory",
)
@app.command(name="procedures")
@in_room("room")
@paged("limit")
@emits_json("as_json")
def memory_procedures(room: str | None = None, limit: int = 20, as_json: bool = False) -> None:
    """Show reusable how-to procedures (filters to procedures/* memories)."""
    _list_by_category("procedures", room, limit, as_json=as_json)


# ── Sync commands ────────────────────────────────────────────────────────────


@doc_ref(
    usage="mycelium sync [--no-reindex]",
    desc="Sync the active room with the backend: fetch all memories from the API and write them locally.",
    group="other",
)
@app.command(name="sync")
@in_room("room")
def memory_sync(
    room: str | None = None,
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

    from mycelium_backend_client.api.memory import (
        list_memories_api_rooms_room_name_memory_get as list_api,
    )

    with typed_client(cfg, timeout=60, raise_on_unexpected_status=False) as client:
        resp = list_api.sync_detailed(room_name, client=client.with_headers(headers), limit=1000)

    if resp.status_code == 304:  # noqa: PLR2004
        console.print("[dim]Already up to date[/dim]")
        return

    try:
        memories = answered(resp, list)
    except UnexpectedStatus:
        detail = hub_error_detail(resp.content) or f"HTTP {resp.status_code}"
        console.print(f"[red]Error:[/red] {detail}")
        raise typer.Exit(1) from None

    # Persist ETag for next sync
    if etag := resp.headers.get("etag"):
        etag_file.parent.mkdir(parents=True, exist_ok=True)
        etag_file.write_text(etag)

    if not memories:
        console.print("[dim]No memories to sync[/dim]")
        return

    written, skipped = write_hub_memories(get_room_dir(room_name), memories)
    for why in skipped:
        console.print(f"[yellow]Skipped:[/yellow] {why}")
    console.print(f"[green]Synced:[/green] {written} memories")

    if not no_reindex:
        try:
            stats = _reindex(cfg, room_name)
        except Exception as e:
            console.print(f"[yellow]Warning:[/yellow] reindex failed: {e}")
        else:
            if stats is None:
                console.print("[yellow]Warning:[/yellow] reindex failed: the hub refused")
            else:
                console.print(f"[green]Re-indexed:[/green] {stats.indexed} memories")
