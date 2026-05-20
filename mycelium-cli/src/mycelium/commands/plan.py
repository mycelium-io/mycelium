# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
Plan commands — read and edit the room's plan/ namespace.

A plan is a set of markdown files in ``.mycelium/rooms/{room}/plan/`` plus the
``- [ ]`` / ``- [x]`` checklist lines those files contain.  Plan files are
ordinary memory files with the ``plan/`` key prefix — file CRUD piggybacks on
``mycelium memory set/rm``.  This module adds the task-aware verbs on top.
"""

from __future__ import annotations

import sys

import httpx
import typer
from rich.console import Console
from rich.table import Table

from mycelium.commands.room import _resolve_room
from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref

app = typer.Typer(
    help=(
        "Manage a room's plan — markdown files + checkbox tasks in "
        ".mycelium/rooms/{room}/plan/. Visible to all agents in the room."
    ),
    no_args_is_help=True,
)
console = Console()

task_app = typer.Typer(
    help="Add, complete, or reopen tasks (markdown checklist lines).",
    no_args_is_help=True,
)
app.add_typer(task_app, name="task")


# ── helpers ──────────────────────────────────────────────────────────────────


def _fetch_plan(room: str | None = None) -> dict:
    cfg = MyceliumConfig.load()
    room_name = _resolve_room(cfg, room)
    with httpx.Client(base_url=cfg.server.api_url, timeout=30) as client:
        resp = client.get(f"/api/rooms/{room_name}/plan")
        resp.raise_for_status()
        return resp.json()


def _print_task_line(task: dict, *, show_id: bool = True) -> None:
    mark = "[green]✓[/green]" if task["done"] else "[dim]·[/dim]"
    style = "dim strike" if task["done"] else ""
    text = task["text"]
    line = f"  {mark}  [{style}]{text}[/{style}]" if style else f"  {mark}  {text}"
    if show_id:
        line += f"  [dim]({task['id']})[/dim]"
    console.print(line)


def _select_task_interactively(
    open_tasks: list[dict],
    *,
    prompt: str,
    multi: bool = False,
) -> list[str]:
    """Pick task ID(s) via questionary when stdin is a TTY.  Returns selected IDs.

    Returns an empty list if the user cancels or no terminal is available.
    """
    if not open_tasks:
        return []
    if not sys.stdin.isatty():
        return []

    try:
        import questionary
    except ImportError:
        return []

    choices = [
        questionary.Choice(
            title=f"[{t['slug']}] {t['text']}",
            value=t["id"],
        )
        for t in open_tasks
    ]
    if multi:
        ids = questionary.checkbox(prompt, choices=choices).ask()
        return ids or []
    chosen = questionary.select(prompt, choices=choices).ask()
    return [chosen] if chosen else []


# ── plan file commands ──────────────────────────────────────────────────────


@doc_ref(
    usage="mycelium plan ls",
    desc="List plan files in the active room.",
    group="plan",
)
@app.command(name="ls")
def plan_ls(
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
) -> None:
    """List plan files in the active room."""
    data = _fetch_plan(room)
    files = data.get("files", [])
    if not files:
        console.print("[dim]No plan files yet.[/dim]")
        console.print(
            "[dim]Add one with[/dim] [cyan]mycelium plan set <slug> <body>[/cyan] "
            "[dim]or a task with[/dim] [cyan]mycelium plan task add <text>[/cyan]"
        )
        return

    table = Table(title=f"{data['room']} — plan", show_lines=False)
    table.add_column("Slug", style="cyan", no_wrap=True)
    table.add_column("Title")
    table.add_column("Tasks", justify="right")
    table.add_column("Open", justify="right")
    table.add_column("Updated", style="dim")
    for f in files:
        n_tasks = len(f.get("tasks", []))
        n_open = sum(1 for t in f.get("tasks", []) if not t["done"])
        ts = str(f.get("updated_at") or "")[:16].replace("T", " ")
        table.add_row(f["slug"], f.get("title") or f["slug"], str(n_tasks), str(n_open), ts)
    console.print(table)


@doc_ref(
    usage="mycelium plan show <slug>",
    desc="Print a plan file's body.",
    group="plan",
)
@app.command(name="show")
def plan_show(
    slug: str = typer.Argument(..., help="Plan file slug (e.g. 'tasks', 'sprint')"),
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
) -> None:
    """Print a plan file's markdown body."""
    data = _fetch_plan(room)
    files = data.get("files", [])
    match = next((f for f in files if f["slug"] == slug), None)
    if not match:
        console.print(f"[red]Plan file not found:[/red] {slug}")
        raise typer.Exit(1)
    console.print(
        f"[bold cyan]{match['slug']}[/bold cyan]  [dim]{match.get('updated_at', '')}[/dim]"
    )
    console.print(match.get("content") or "")


@doc_ref(
    usage="mycelium plan set <slug> <body>",
    desc="Create or overwrite a plan file. Body is the full markdown.",
    group="plan",
)
@app.command(name="set")
def plan_set(
    slug: str = typer.Argument(..., help="Plan file slug (no extension)"),
    body: str = typer.Argument(..., help="Markdown body"),
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
    handle: str = typer.Option("cli-user", "--handle", "-H", help="Agent handle"),
) -> None:
    """Create or overwrite a plan file (writes ``plan/<slug>.md``)."""
    from mycelium.commands.memory import memory_set

    memory_set(key=f"plan/{slug}", value=body, room=room, handle=handle, no_embed=False, tags=None)


@doc_ref(
    usage="mycelium plan rm <slug>",
    desc="Delete a plan file.",
    group="plan",
)
@app.command(name="rm")
def plan_rm(
    slug: str = typer.Argument(..., help="Plan file slug"),
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
) -> None:
    """Delete a plan file (removes ``plan/<slug>.md``)."""
    from mycelium.commands.memory import memory_rm

    memory_rm(key=f"plan/{slug}", room=room, force=force)


@doc_ref(
    usage="mycelium plan title [<text>]",
    desc=(
        "Read or set the room's plan title — the italic display line shown above "
        "room activity. Pass no text to print the current title."
    ),
    group="plan",
)
@app.command(name="title")
def plan_title(
    text: str | None = typer.Argument(None, help="New plan title (omit to read)"),
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
) -> None:
    """Read or set the room's plan title."""
    cfg = MyceliumConfig.load()
    room_name = _resolve_room(cfg, room)
    with httpx.Client(base_url=cfg.server.api_url, timeout=30) as client:
        if text is None:
            data = client.get(f"/api/rooms/{room_name}/plan").json()
            title = data.get("title")
            if title:
                console.print(f"[italic]{title}[/italic]")
            else:
                console.print("[dim]No plan title set.[/dim]")
            return
        resp = client.put(
            f"/api/rooms/{room_name}/plan/title",
            json={"text": text},
        )
        resp.raise_for_status()
        console.print(f"[green]Title set:[/green] [italic]{resp.json()['title']}[/italic]")


# ── task commands ────────────────────────────────────────────────────────────


@doc_ref(
    usage="mycelium plan tasks",
    desc="List every checkbox task across plan files. Open first, done last.",
    group="plan",
)
@app.command(name="tasks")
def plan_tasks(
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
    all_: bool = typer.Option(False, "--all", "-a", help="Include completed tasks"),
) -> None:
    """List checkbox tasks across the room's plan files."""
    data = _fetch_plan(room)
    tasks = data.get("tasks", [])
    open_tasks = [t for t in tasks if not t["done"]]
    done_tasks = [t for t in tasks if t["done"]]

    if not tasks:
        console.print(
            "[dim]No tasks yet.[/dim] Add one with [cyan]mycelium plan task add <text>[/cyan]"
        )
        return

    console.print(
        f"[bold]{data['room']}[/bold]  "
        f"[green]{len(open_tasks)} open[/green]  "
        f"[dim]{len(done_tasks)} done[/dim]"
    )
    by_file: dict[str, list[dict]] = {}
    target = tasks if all_ else open_tasks
    for t in target:
        by_file.setdefault(t["slug"], []).append(t)
    for slug, ts in by_file.items():
        console.print(f"\n[cyan]{slug}[/cyan]")
        for t in ts:
            _print_task_line(t)


@doc_ref(
    usage="mycelium plan task add <text> [--file <slug>]",
    desc="Append a new <code>- [ ]</code> line to a plan file (defaults to <code>tasks</code>).",
    group="plan",
)
@task_app.command(name="add")
def task_add(
    text: str = typer.Argument(..., help="Task description"),
    file: str = typer.Option("tasks", "--file", "-f", help="Plan file slug to append to"),
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
) -> None:
    """Append a new ``- [ ]`` line to a plan file."""
    cfg = MyceliumConfig.load()
    room_name = _resolve_room(cfg, room)
    with httpx.Client(base_url=cfg.server.api_url, timeout=30) as client:
        resp = client.post(
            f"/api/rooms/{room_name}/plan/tasks",
            json={"text": text, "slug": file},
        )
        resp.raise_for_status()
        task = resp.json()
    console.print(
        f"[green]Added:[/green] [{task['slug']}] {task['text']}  [dim]({task['id']})[/dim]"
    )


def _toggle(task_id: str, *, done: bool, room: str | None) -> dict:
    cfg = MyceliumConfig.load()
    room_name = _resolve_room(cfg, room)
    with httpx.Client(base_url=cfg.server.api_url, timeout=30) as client:
        resp = client.post(
            f"/api/rooms/{room_name}/plan/tasks/{task_id}/toggle",
            json={"done": done},
        )
        if resp.status_code == 404:
            console.print(f"[red]Task not found:[/red] {task_id}")
            raise typer.Exit(1)
        resp.raise_for_status()
        return resp.json()


@doc_ref(
    usage="mycelium plan task done [<id>...]",
    desc="Mark task(s) complete. Run without IDs to pick from open tasks interactively.",
    group="plan",
)
@task_app.command(name="done")
def task_done(
    task_ids: list[str] | None = typer.Argument(None, help="One or more task IDs"),
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
) -> None:
    """Mark a task complete.  Without IDs, prompts to pick from open tasks."""
    ids = list(task_ids or [])
    if not ids:
        data = _fetch_plan(room)
        open_tasks = [t for t in data.get("tasks", []) if not t["done"]]
        if not open_tasks:
            console.print("[dim]No open tasks.[/dim]")
            return
        ids = _select_task_interactively(
            open_tasks,
            prompt="Mark tasks as done",
            multi=True,
        )
        if not ids:
            console.print("[dim]Nothing selected.[/dim]")
            return
    for tid in ids:
        t = _toggle(tid, done=True, room=room)
        console.print(f"[green]✓[/green] [{t['slug']}] {t['text']}")


@doc_ref(
    usage="mycelium plan task undo [<id>...]",
    desc="Reopen completed task(s). Run without IDs to pick interactively.",
    group="plan",
)
@task_app.command(name="undo")
def task_undo(
    task_ids: list[str] | None = typer.Argument(None, help="One or more task IDs"),
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
) -> None:
    """Reopen a completed task."""
    ids = list(task_ids or [])
    if not ids:
        data = _fetch_plan(room)
        done_tasks = [t for t in data.get("tasks", []) if t["done"]]
        if not done_tasks:
            console.print("[dim]No completed tasks.[/dim]")
            return
        ids = _select_task_interactively(
            done_tasks,
            prompt="Reopen tasks",
            multi=True,
        )
        if not ids:
            console.print("[dim]Nothing selected.[/dim]")
            return
    for tid in ids:
        t = _toggle(tid, done=False, room=room)
        console.print(f"[yellow]↺[/yellow] [{t['slug']}] {t['text']}")
