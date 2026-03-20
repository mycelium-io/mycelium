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
    from mycelium_backend_client.api.memory import (
        create_memories_rooms_room_name_memory_post as create_api,
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

    with _get_client() as client:
        result = create_api.sync(room_name="_notebooks", client=client, body=batch)
        if result:
            mem = result[0]
            console.print(f"[green]Notebook set:[/green] {mem.key} (v{mem.version})")


@doc_ref(
    usage="mycelium notebook get <key> [-H <handle>]",
    desc="Read a private notebook memory by key.",
    group="notebook",
)
@app.command(name="get")
def notebook_get(
    key: str = typer.Argument(..., help="Memory key"),
    handle: str | None = typer.Option(None, "--handle", "-H", help="Agent handle"),
) -> None:
    """Read a notebook memory by key."""
    from mycelium_backend_client.api.memory import (
        get_memory_rooms_room_name_memory_key_get as get_api,
    )

    agent_handle = _resolve_handle(handle)

    with _get_client() as client:
        try:
            result = get_api.sync(
                room_name="_notebooks",
                key=key,
                client=client,
                scope="notebook",
                handle=agent_handle,
            )
            if result:
                val = result.value
                if hasattr(val, "to_dict"):
                    val = val.to_dict()
                console.print(f"[cyan]{result.key}[/cyan] (v{result.version})")
                console.print(json.dumps(val, indent=2, default=str) if isinstance(val, dict) else str(val))
        except Exception as e:
            if hasattr(e, "status_code") and e.status_code == 404:
                console.print(f"[dim]Not found: {key}[/dim]")
            else:
                raise


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
    """List notebook memories."""
    from mycelium_backend_client.api.memory import (
        list_memories_rooms_room_name_memory_get as list_api,
    )

    agent_handle = _resolve_handle(handle)

    with _get_client() as client:
        result = list_api.sync(
            room_name="_notebooks",
            client=client,
            scope="notebook",
            handle=agent_handle,
            prefix=prefix,
            limit=limit,
        )
        if not result:
            console.print("[dim]No notebook memories found[/dim]")
            return

        console.print(f"[bold]Notebook ({agent_handle})[/bold] — {len(result)} memories\n")
        for mem in result:
            val = mem.value
            if hasattr(val, "to_dict"):
                val = val.to_dict()
            display = str(val.get("text", val)) if isinstance(val, dict) else str(val)
            display = display[:80]
            console.print(f"  [cyan]{mem.key}[/cyan]  v{mem.version}  {display}")


@doc_ref(
    usage="mycelium notebook search <query> [-H <handle>]",
    desc="Semantic search within your private notebook.",
    group="notebook",
)
@app.command(name="search")
def notebook_search(
    query: str = typer.Argument(..., help="Natural language search query"),
    handle: str | None = typer.Option(None, "--handle", "-H", help="Agent handle"),
    limit: int = typer.Option(5, "--limit", "-n", help="Max results"),
) -> None:
    """Semantic search in your notebook."""
    from mycelium_backend_client.api.memory import (
        search_memories_rooms_room_name_memory_search_post as search_api,
    )
    from mycelium_backend_client.models import MemorySearchRequest

    _resolve_handle(handle)  # validate handle exists

    body = MemorySearchRequest(query=query, limit=limit)

    with _get_client() as client:
        # The search endpoint needs scope/handle params — use notebook room
        result = search_api.sync(room_name="_notebooks", client=client, body=body)
        if not result or not result.results:
            console.print("[dim]No matches found[/dim]")
            return

        for sr in result.results:
            mem = sr.memory
            sim = sr.similarity
            console.print(f"  [cyan]{mem.key}[/cyan]  ({sim:.2f})  {mem.content_text[:60] if mem.content_text else ''}")
