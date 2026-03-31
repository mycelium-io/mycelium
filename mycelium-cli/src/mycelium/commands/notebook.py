# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
Notebook commands — agent-private persistent memory.

Notebooks are scoped to a handle. They store identity, preferences,
session history, and context that belongs to a specific agent — not
shared with the room by default.
"""

import json

import typer
from rich.console import Console

from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref
from mycelium.filesystem import (
    get_notebook_dir,
    list_memories,
    read_memory,
)

app = typer.Typer(
    help="Agent-private memory. Persists identity, preferences, and context across sessions.",
    invoke_without_command=True,
)

console = Console()


def _get_client():
    from mycelium_backend_client import Client

    config = MyceliumConfig.load()
    return Client(base_url=config.server.api_url, raise_on_unexpected_status=True)


def _resolve_handle(handle: str | None) -> str:
    if handle:
        return handle
    try:
        config = MyceliumConfig.load()
        return config.get_current_identity() or "cli-user"
    except Exception:
        return "cli-user"


@doc_ref(
    usage="mycelium notebook set <key> <value> [-H <handle>]",
    desc="Write a private notebook memory. Persists across sessions, visible only to this agent.",
    group="notebook",
)
@app.command(name="set")
def notebook_set(
    key: str = typer.Argument(..., help="Memory key"),
    value: str = typer.Argument(..., help="Memory value (string or JSON)"),
    handle: str | None = typer.Option(None, "--handle", "-H", help="Agent handle"),
    no_embed: bool = typer.Option(False, "--no-embed", help="Skip vector embedding"),
) -> None:
    """Write a memory to your private notebook."""
    from mycelium_backend_client.api.notebook import (
        write_notebook_notebook_handle_memory_post as write_api,
    )
    from mycelium_backend_client.models import MemoryBatchCreate, MemoryCreate

    agent_handle = _resolve_handle(handle)

    try:
        parsed_value = json.loads(value)
    except json.JSONDecodeError:
        parsed_value = value

    item = MemoryCreate(
        key=key,
        value=parsed_value,
        created_by=agent_handle,
        embed=not no_embed,
        scope="notebook",
        owner_handle=agent_handle,
    )
    batch = MemoryBatchCreate(items=[item])

    # Backend writes the file + updates search index
    with _get_client() as client:
        result = write_api.sync(handle=agent_handle, client=client, body=batch)
        if result and isinstance(result, list):
            mem = result[0]
            file_path = getattr(mem, "file_path", None)
            path_info = f"  [{file_path}]" if file_path else ""
            console.print(f"[green]Notebook set:[/green] {mem.key} (v{mem.version}){path_info}")


@doc_ref(
    usage="mycelium notebook get <key> [-H <handle>]",
    desc="Read a private notebook memory by key.",
    group="notebook",
)
@app.command(name="get")
def notebook_get(
    key: str = typer.Argument(..., help="Memory key"),
    handle: str | None = typer.Option(None, "--handle", "-H", help="Agent handle"),
    raw: bool = typer.Option(False, "--raw", help="Show raw markdown file content"),
) -> None:
    """Read a notebook memory by key — reads from filesystem."""
    agent_handle = _resolve_handle(handle)
    notebook_dir = get_notebook_dir(agent_handle)

    result = read_memory(notebook_dir, key)
    if result is None:
        console.print(f"[dim]Not found: {key}[/dim]")
        raise typer.Exit(1)

    meta, content = result

    if raw:
        file_path = notebook_dir / f"{key}.md"
        if file_path.exists():
            console.print(file_path.read_text(encoding="utf-8"))
        return

    version = meta.get("version", "?")
    console.print(f"[cyan]{key}[/cyan] (v{version})")
    console.print(content)


@doc_ref(
    usage="mycelium notebook ls [-H <handle>] [--prefix prefix/]",
    desc="List your private notebook memories.",
    group="notebook",
)
@app.command(name="ls")
def notebook_ls(
    handle: str | None = typer.Option(None, "--handle", "-H", help="Agent handle"),
    prefix: str | None = typer.Option(None, "--prefix", "-p", help="Key prefix filter"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
) -> None:
    """List notebook memories — reads from filesystem."""
    agent_handle = _resolve_handle(handle)
    notebook_dir = get_notebook_dir(agent_handle)

    entries = list_memories(notebook_dir, prefix=prefix, limit=limit)
    if not entries:
        console.print("[dim]No notebook memories found[/dim]")
        return

    console.print(f"[bold]Notebook ({agent_handle})[/bold] — {len(entries)} memories\n")
    for key, meta, content in entries:
        display = content[:80] if content else ""
        version = meta.get("version", "?")
        console.print(f"  [cyan]{key}[/cyan]  v{version}  {display}")


@doc_ref(
    usage="mycelium notebook search <query> [-H <handle>]",
    desc="Semantic search within your private notebook (uses pgvector).",
    group="notebook",
)
@app.command(name="search")
def notebook_search(
    query: str = typer.Argument(..., help="Natural language search query"),
    handle: str | None = typer.Option(None, "--handle", "-H", help="Agent handle"),
    limit: int = typer.Option(5, "--limit", "-n", help="Max results"),
) -> None:
    """Semantic search in your notebook (uses pgvector via backend API)."""
    from mycelium_backend_client.api.notebook import (
        search_notebook_notebook_handle_memory_search_post as search_api,
    )
    from mycelium_backend_client.models import MemorySearchRequest

    agent_handle = _resolve_handle(handle)

    body = MemorySearchRequest(query=query, limit=limit)

    with _get_client() as client:
        result = search_api.sync(handle=agent_handle, client=client, body=body)
        if not result or not result.results:
            console.print("[dim]No matches found[/dim]")
            return

        for sr in result.results:
            mem = sr.memory
            sim = sr.similarity
            console.print(
                f"  [cyan]{mem.key}[/cyan]  ({sim:.2f})  {mem.content_text[:60] if mem.content_text else ''}"
            )
