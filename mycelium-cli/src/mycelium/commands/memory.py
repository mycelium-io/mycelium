"""
Memory commands — persistent namespaced memory operations.

mycelium memory set <key> <value>   — write a memory
mycelium memory get <key>           — read a memory
mycelium memory ls                  — list memories
mycelium memory search <query>      — semantic search
mycelium memory rm <key>            — delete a memory
mycelium memory subscribe <pattern> — watch for changes
"""

import json

import typer
from rich.console import Console
from rich.table import Table

from mycelium.config import MyceliumConfig
from mycelium.http_client import get_client

app = typer.Typer(help="Persistent memory operations")
console = Console()


def _get_active_room(room: str | None) -> str:
    """Get room name from arg or active config."""
    if room:
        return room
    cfg = MyceliumConfig.load()
    active = getattr(cfg.rooms, "active", None) if hasattr(cfg, "rooms") else None
    if active:
        return active
    typer.echo("No room specified and no active room set. Use --room or 'mycelium config set rooms.active <name>'")
    raise typer.Exit(1)


@app.command(name="set")
def memory_set(
    key: str = typer.Argument(..., help="Memory key (e.g. 'project/status')"),
    value: str = typer.Argument(..., help="Memory value (string or JSON)"),
    room: str | None = typer.Option(None, "--room", "-r", help="Room name (defaults to active room)"),
    handle: str = typer.Option("cli-user", "--handle", "-h", help="Agent handle"),
    no_embed: bool = typer.Option(False, "--no-embed", help="Skip vector embedding"),
    tags: str | None = typer.Option(None, "--tags", "-t", help="Comma-separated tags"),
) -> None:
    """Write a memory to a room's persistent namespace."""
    room_name = _get_active_room(room)

    # Try to parse value as JSON
    try:
        parsed_value = json.loads(value)
    except json.JSONDecodeError:
        parsed_value = value

    tag_list = [t.strip() for t in tags.split(",")] if tags else None

    with get_client() as client:
        resp = client.post(
            f"/rooms/{room_name}/memory",
            json={
                "items": [
                    {
                        "key": key,
                        "value": parsed_value,
                        "created_by": handle,
                        "embed": not no_embed,
                        "tags": tag_list,
                    }
                ]
            },
        )
        data = resp.json()
        console.print(f"[green]Memory set:[/green] {key} (v{data[0]['version']})")


@app.command(name="get")
def memory_get(
    key: str = typer.Argument(..., help="Memory key"),
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
) -> None:
    """Read a memory by key."""
    room_name = _get_active_room(room)

    with get_client() as client:
        try:
            resp = client.get(f"/rooms/{room_name}/memory/{key}")
            data = resp.json()
            console.print(f"[cyan]{data['key']}[/cyan] (v{data['version']}, by {data['created_by']})")
            if isinstance(data["value"], dict):
                console.print(json.dumps(data["value"], indent=2))
            else:
                console.print(str(data["value"]))
        except Exception as e:
            console.print(f"[red]Not found:[/red] {key} ({e})")
            raise typer.Exit(1) from e


@app.command(name="ls")
def memory_ls(
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
    prefix: str | None = typer.Option(None, "--prefix", "-p", help="Key prefix filter"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
) -> None:
    """List memories in a room."""
    room_name = _get_active_room(room)

    with get_client() as client:
        params = {"limit": limit}
        if prefix:
            params["prefix"] = prefix
        resp = client.get(f"/rooms/{room_name}/memory", params=params)
        memories = resp.json()

        if not memories:
            console.print("[dim]No memories found[/dim]")
            return

        console.print(f"[bold]{room_name}[/bold] ({len(memories)} memories)\n")

        for mem in memories:
            # Header line: key + version + author
            ts = mem["updated_at"][:16].replace("T", " ")
            console.print(
                f"[cyan]{mem['key']}[/cyan]  "
                f"[dim]v{mem['version']}  {mem['created_by']}  {ts}[/dim]"
            )
            # Value preview
            value = mem.get("value")
            if isinstance(value, dict):
                # Show dict keys or short JSON
                flat = json.dumps(value, default=str)
                if len(flat) <= 120:
                    console.print(f"  {flat}")
                else:
                    console.print(f"  {flat[:120]}...")
            elif isinstance(value, str):
                preview = value[:120]
                console.print(f"  {preview}")
            console.print()


@app.command(name="search")
def memory_search(
    query: str = typer.Argument(..., help="Natural language search query"),
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
    limit: int = typer.Option(5, "--limit", "-n", help="Max results"),
) -> None:
    """Semantic search over memories."""
    room_name = _get_active_room(room)

    with get_client() as client:
        resp = client.post(
            f"/rooms/{room_name}/memory/search",
            json={"query": query, "limit": limit},
        )
        data = resp.json()
        results = data.get("results", [])

        if not results:
            console.print("[dim]No matching memories found[/dim]")
            return

        for r in results:
            mem = r["memory"]
            sim = r["similarity"]
            console.print(
                f"[cyan]{mem['key']}[/cyan] "
                f"[dim](similarity: {sim:.3f}, v{mem['version']})[/dim]"
            )
            if mem.get("content_text"):
                preview = mem["content_text"][:200]
                console.print(f"  {preview}")
            console.print()


@app.command(name="rm")
def memory_rm(
    key: str = typer.Argument(..., help="Memory key to delete"),
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
) -> None:
    """Delete a memory."""
    room_name = _get_active_room(room)

    if not force:
        confirm = typer.confirm(f"Delete memory '{key}' from room '{room_name}'?")
        if not confirm:
            raise typer.Exit(0)

    with get_client() as client:
        client.delete(f"/rooms/{room_name}/memory/{key}")
        console.print(f"[green]Deleted:[/green] {key}")


@app.command(name="subscribe")
def memory_subscribe(
    pattern: str = typer.Argument(..., help="Key glob pattern (e.g. 'project/*')"),
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
    handle: str = typer.Option("cli-user", "--handle", "-h", help="Subscriber agent handle"),
) -> None:
    """Subscribe to memory change notifications."""
    room_name = _get_active_room(room)

    with get_client() as client:
        resp = client.post(
            f"/rooms/{room_name}/memory/subscribe",
            json={"key_pattern": pattern, "subscriber": handle},
        )
        data = resp.json()
        console.print(f"[green]Subscribed:[/green] {pattern} (id: {data['id'][:8]}...)")
