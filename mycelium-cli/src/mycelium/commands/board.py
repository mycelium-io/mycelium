# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Board commands — the "Needs you" coordination cockpit (issue #493).

``mycelium board`` renders a live projection over the room's event ledger, the
compiled plan, and any negotiation in flight. Triage verbs (claim / resolve /
block / promote / dismiss) and ``capture`` are the *same* vocabulary agents drive
over the ledger, so human and agent coordination share one surface.

The board is served by the backend (``GET /rooms/{room}/board``); this module is
a thin Rich client over it, mirroring ``commands/plan.py`` (raw httpx until the
generated client picks the routes up).
"""

from __future__ import annotations

import time

import httpx
import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from mycelium.commands.room import _resolve_room
from mycelium.config import MyceliumConfig

app = typer.Typer(
    help="The 'Needs you' coordination board: live triage over the room's event ledger.",
    no_args_is_help=False,
    invoke_without_command=True,
)
console = Console()

# Lens grouping mirrors ``board._lens`` on the backend.
_LENS_ORDER = ["needs", "flight", "resolved"]
_LENS_TITLE = {"needs": "⚠ NEEDS YOU", "flight": "◐ IN FLIGHT", "resolved": "✓ RESOLVED"}
_KIND_STYLE = {
    "decision": "yellow",
    "blocked": "red",
    "review": "cyan",
    "concern": "cyan",
    "action": "dim",
}
_VERBS = ("claim", "resolve", "block", "promote", "dismiss")


# ── helpers ──────────────────────────────────────────────────────────────────


def _base(room: str | None) -> tuple[str, str]:
    """Resolve (api_url, room_name) from config + the optional --room override."""
    cfg = MyceliumConfig.load()
    return cfg.server.api_url, _resolve_room(cfg, room)


def _fetch_board(api_url: str, room_name: str) -> dict:
    with httpx.Client(base_url=api_url, timeout=30) as client:
        resp = client.get(f"/api/rooms/{room_name}/board")
        resp.raise_for_status()
        return resp.json()


def _lens_of(item: dict) -> str:
    if item.get("state") == "resolved":
        return "resolved"
    return "needs" if item.get("needs_you") else "flight"


def _short(item_id: str) -> str:
    """A stable, human-quotable id — UUIDs shrink to 8 chars; short ids stay."""
    return item_id if ":" in item_id or len(item_id) <= 8 else item_id[:8]


def _resolve_item(items: list[dict], partial: str) -> dict:
    """Find the one item whose id (or its short form) matches ``partial``.

    Lets a caller type a short prefix instead of a full UUID. Ambiguity or a
    miss raises, so a verb never lands on the wrong row.
    """
    exact = [i for i in items if i["id"] == partial]
    if exact:
        return exact[0]
    hits = [i for i in items if i["id"].startswith(partial) or _short(i["id"]) == partial]
    if not hits:
        raise typer.BadParameter(f"no board item matches {partial!r}")
    if len(hits) > 1:
        ids = ", ".join(_short(i["id"]) for i in hits[:5])
        raise typer.BadParameter(f"{partial!r} is ambiguous — matches {ids}")
    return hits[0]


def _meta_bits(item: dict) -> Text:
    """The dim trailing metadata: owner · work-links · deps · provenance · age."""
    bits = Text()
    owner = item.get("owner")
    if owner:
        glyph = "🤖" if owner.get("kind") == "agent" else "🧑"
        dot = " ●" if owner.get("present") else ""
        bits.append(
            f"{glyph} {owner['handle']}{dot}  ",
            style="cyan" if owner.get("kind") == "agent" else "white",
        )
    work = item.get("work") or {}
    if work.get("branch"):
        bits.append(f"{work['branch']} ", style="dim")
    if work.get("ci"):
        ci = work["ci"]
        ci_style = {"green": "green", "running": "yellow", "failed": "red"}.get(ci, "dim")
        bits.append(f"CI●{ci} ", style=ci_style)
    if work.get("pr"):
        pr = work["pr"]
        bits.append(f"PR#{pr['number']} {pr.get('state', '')} ", style="cyan")
    if item.get("waiting_on"):
        bits.append(f"waiting on {item['waiting_on']}  ", style="yellow")
    if (gh := item.get("github")) and gh.get("issue"):
        bits.append(f"#{gh['issue']} ", style="dim")
    if item.get("provenance"):
        bits.append(f"{item['provenance']}  ", style="dim")
    if item.get("age"):
        bits.append(str(item["age"]), style="dim")
    return bits


def _render(data: dict, *, show_all: bool) -> None:
    room = data.get("room", "")
    counts = data.get("counts", {})
    header = Text(f"{room}", style="bold")
    header.append(
        f"   {counts.get('needs', 0)} need you · "
        f"{counts.get('flight', 0)} in flight · "
        f"{counts.get('resolved', 0)} resolved",
        style="dim",
    )
    console.print(header)

    items = data.get("items", [])
    lenses = _LENS_ORDER if show_all else ["needs", "flight"]
    any_shown = False
    for lens in lenses:
        rows = [i for i in items if _lens_of(i) == lens]
        if not rows:
            continue
        any_shown = True
        console.print()
        console.print(Text(_LENS_TITLE[lens], style="bold dim"))
        grid = Table.grid(padding=(0, 2))
        grid.add_column(no_wrap=True)  # id
        grid.add_column(no_wrap=True)  # kind
        grid.add_column()  # title
        grid.add_column()  # meta
        for i in rows:
            kind = i.get("state") if i.get("state") == "blocked" else i.get("kind", "action")
            style = _KIND_STYLE.get(kind, "white")
            title = Text(i.get("title", ""), style="dim strike" if lens == "resolved" else "")
            if i.get("choices"):
                title.append("   " + "  ".join(f"[{c}]" for c in i["choices"]), style="cyan")
            grid.add_row(
                Text(_short(i["id"]), style="dim"),
                Text(str(kind), style=style),
                title,
                _meta_bits(i),
            )
        console.print(grid)

    if not any_shown:
        console.print()
        console.print(
            Text("Nothing needs you. The board self-heals — items land as events do.", style="dim"),
        )
    console.print()
    console.print(
        Text("verbs: ", style="dim").append(
            "claim · resolve · block · promote · dismiss · capture", style="dim italic"
        ),
    )


def _run_verb(api_url: str, room_name: str, item_id: str, verb: str, body: dict) -> None:
    with httpx.Client(base_url=api_url, timeout=30) as client:
        resp = client.post(f"/api/rooms/{room_name}/board/items/{item_id}/{verb}", json=body)
        if resp.status_code == 409:
            raise typer.BadParameter(resp.json().get("detail", "verb not allowed for this item"))
        resp.raise_for_status()


def _verb_command(verb: str, item: str, room: str | None, **body: object) -> None:
    """Shared body for the five verb subcommands: resolve id, POST, confirm."""
    api_url, room_name = _base(room)
    data = _fetch_board(api_url, room_name)
    target = _resolve_item(data.get("items", []), item)
    clean = {k: v for k, v in body.items() if v is not None}
    _run_verb(api_url, room_name, target["id"], verb, clean)
    console.print(
        f"[green]✓[/green] {verb} [dim]{_short(target['id'])}[/dim]  {target.get('title', '')}"
    )


# ── commands ─────────────────────────────────────────────────────────────────


@app.callback(invoke_without_command=True)
def board(
    ctx: typer.Context,
    room: str | None = typer.Option(
        None, "--room", "-r", help="Room name (defaults to the active room)."
    ),
    show_all: bool = typer.Option(
        False, "--all", "-a", help="Show every lens, not just what needs you."
    ),
    watch: bool = typer.Option(False, "--watch", "-w", help="Live view; re-render as events land."),
) -> None:
    """Show the board (default lens = what needs you). A subcommand overrides this."""
    if ctx.invoked_subcommand is not None:
        return
    api_url, room_name = _base(room)
    if not watch:
        _render(_fetch_board(api_url, room_name), show_all=show_all)
        return
    try:
        while True:
            console.clear()
            _render(_fetch_board(api_url, room_name), show_all=show_all)
            console.print(Text("watching · Ctrl+C to stop", style="dim"))
            time.sleep(2)
    except KeyboardInterrupt:
        console.print("[dim]stopped[/dim]")


@app.command()
def capture(
    text: str = typer.Argument(
        ..., help="Natural-language concern; recorded as a structured board item."
    ),
    room: str | None = typer.Option(None, "--room", "-r"),
    sender: str = typer.Option("cli", "--as", help="Who is capturing this."),
) -> None:
    """Capture a concern in one gesture — natural language in, structured row out."""
    api_url, room_name = _base(room)
    with httpx.Client(base_url=api_url, timeout=30) as client:
        resp = client.post(
            f"/api/rooms/{room_name}/board/capture", json={"text": text, "sender": sender}
        )
        resp.raise_for_status()
        item = resp.json()
    console.print(f"[green]✓[/green] captured [dim]{_short(item['id'])}[/dim]  {item['title']}")


@app.command()
def claim(
    item: str = typer.Argument(..., help="Board item id (a short prefix is fine)."),
    to: str | None = typer.Option(None, "--to", help="Assign to this handle (defaults to you)."),
    room: str | None = typer.Option(None, "--room", "-r"),
) -> None:
    """Claim an item — assign an owner and move it into flight."""
    _verb_command("claim", item, room, owner=to)


@app.command()
def resolve(
    item: str = typer.Argument(..., help="Board item id (a short prefix is fine)."),
    room: str | None = typer.Option(None, "--room", "-r"),
) -> None:
    """Resolve an item — it drops off the active lenses."""
    _verb_command("resolve", item, room)


@app.command()
def block(
    item: str = typer.Argument(..., help="Board item id (a short prefix is fine)."),
    on: str | None = typer.Option(None, "--on", help="What it's waiting on, e.g. '#502'."),
    room: str | None = typer.Option(None, "--room", "-r"),
) -> None:
    """Block an item — it stays in 'needs you' until unblocked."""
    _verb_command("block", item, room, waiting_on=on)


@app.command()
def promote(
    item: str = typer.Argument(..., help="Board item id (a short prefix is fine)."),
    issue: int | None = typer.Option(
        None, "--issue", help="Back-link to this GitHub issue number."
    ),
    room: str | None = typer.Option(None, "--room", "-r"),
) -> None:
    """Promote a durable item to GitHub by reference; it leaves the live board."""
    _verb_command("promote", item, room, issue=issue)


@app.command()
def dismiss(
    item: str = typer.Argument(..., help="Board item id (a short prefix is fine)."),
    room: str | None = typer.Option(None, "--room", "-r"),
) -> None:
    """Dismiss an item — drop it from the board."""
    _verb_command("dismiss", item, room)
