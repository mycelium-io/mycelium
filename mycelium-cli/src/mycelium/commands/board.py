# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
The coordination board: the room's live slice, in the terminal.

``mycelium board`` is the CLI half of the same surface the GUI draws — one
projection over episodes, memory namespaces and presence, read
through whichever lens you ask for.  The default lens is "needs you", because a
board worth having is one you can ignore until it says your name.

The verbs (claim / resolve / block / promote / dismiss) are the same words the
GUI uses and the same words an agent drives over the ledger, and each one
writes.  Custody goes through a lease, because who holds a row moves under
rules a plain write cannot check; everything else is frontmatter on the row's
memory.  A row projected from somewhere other than a memory has nothing to
write onto and says so.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import typer
from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.table import Table
from rich.text import Text

from mycelium.board import LiveItem, attach_upstream, custody, infer_schema, project_items
from mycelium.board import fields as board_fields
from mycelium.board.activity import (
    DAILY_GOAL,
    by_day,
    heat_level,
    project_activity,
    streaks,
    summarize_activity,
    week_start,
    zone,
)
from mycelium.board.custody import lens_of_item
from mycelium.board.model import KINDS, PRIORITIES, STATUSES, format_age
from mycelium.board.schema import groupable_fields
from mycelium.client import hub_client
from mycelium.commands.room import _resolve_room
from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref

app = typer.Typer(
    help="The room's coordination board: what needs you, what's in flight, what resolved.",
    no_args_is_help=False,
)
console = Console()

LENS_CHOICES = {
    "needs-you": "needs_you",
    "in-flight": "in_flight",
    "resolved": "resolved",
    "all": None,
}

KIND_GLYPH = {
    "decision": ("?", "cyan"),
    "blocked": ("⊘", "red"),
    "review": ("◉", "yellow"),
    "action": ("●", "green"),
    "concern": ("△", "yellow"),
    "signal": ("◌", "dim"),
}

GROUP_LABEL = {
    "decision": "Decisions",
    "blocked": "Blocked",
    "review": "Review",
    "action": "Actions",
    "concern": "Concerns",
    "signal": "Signals",
}

CI_COLOR = {"green": "green", "running": "yellow", "red": "red"}

#: How a provider's answer reads on a row. `done` is deliberately dim: a merged
#: pull request is finished, and a board that shouts about finished work buries
#: the work that isn't.
UPSTREAM_COLOR = {
    "failed": "red",
    "blocked": "red",
    "pending": "yellow",
    "ok": "green",
    "done": "dim",
    "unknown": "dim",
}

#: Widest title a row prints before it is elided.
TITLE_WIDTH = 50

#: How a lease reads as it drains. The terminal's version of the GUI's TtlBar:
#: the same fraction, five cells wide.
TTL_CELLS = 5


# ── data ─────────────────────────────────────────────────────────────────────


@dataclass
class HubHealth:
    """How the read went, in enough detail to say something true about it.

    Reachability used to be inferred from whether one source came back, which
    reported an authenticated hub refusing a request, or a room that does not
    exist, as "hub unreachable" and sent the reader to check their network. It
    also let a board draw with two of its sources missing and look merely
    quiet. Both are worse than an error, because the reader believes them.
    """

    #: Sources that answered with data, by name.
    ok: list[str] = field(default_factory=list)
    #: Sources that failed, name to the reason.
    failed: dict[str, str] = field(default_factory=dict)
    #: Sources the hub answered at all, whatever it said. A refusal is an answer:
    #: it means the hub is running and the reader's problem is a credential, not
    #: a network.
    answered: list[str] = field(default_factory=list)

    @property
    def reachable(self) -> bool:
        """Whether there is enough to draw anything."""
        return bool(self.ok)

    @property
    def note(self) -> str | None:
        """The one line worth printing above a board, or ``None`` when all is well."""
        if not self.failed:
            return None
        if self.ok:
            missing = ", ".join(sorted(self.failed))
            total = len(self.ok) + len(self.failed)
            return f"Incomplete: {len(self.failed)} of {total} sources failed ({missing})"
        if self.answered:
            # The hub is there and said no. Sending the reader to check their
            # network here costs them the time it takes to rule it out.
            reason = next(iter(self.failed.values()))
            return f"Hub refused every request ({reason})"
        return f"Hub unreachable: {next(iter(self.failed.values()))}"


def _fetch_raw(room: str | None) -> tuple[str, dict[str, Any], HubHealth]:
    """Every source the log and the board share, read once."""
    cfg = MyceliumConfig.load()
    name = _resolve_room(cfg, room)
    health = HubHealth()

    def get(path: str, default, label: str):
        try:
            resp = client.get(path)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # The hub answered, and said no. That is a different problem from a
            # hub that is not there, and the reader fixes it differently.
            health.answered.append(label)
            health.failed[label] = f"HTTP {exc.response.status_code}"
            return default
        except Exception as exc:
            health.failed[label] = type(exc).__name__
            return default
        health.answered.append(label)
        health.ok.append(label)
        try:
            return resp.json()
        except ValueError:
            health.ok.remove(label)
            health.failed[label] = "malformed response"
            return default

    with hub_client(cfg, timeout=30) as client:
        episodes = get(f"/api/rooms/{name}/episodes", {}, "episodes")
        memories = get(f"/api/rooms/{name}/memory?limit=50", [], "memory")
        # What the tools the room points at say. A read never fetches hub-side,
        # so this costs a cache lookup, not a round trip to GitHub.
        upstream = get(f"/api/rooms/{name}/status", None, "status")
        agents = get(f"/api/rooms/{name}/agents", [], "agents")
        members = get(f"/api/rooms/{name}/sessions/members", {}, "members")
        messages = get(f"/api/rooms/{name}/messages?limit=300", {}, "messages")

    return (
        name,
        {
            "episodes": (episodes or {}).get("episodes", []) if isinstance(episodes, dict) else [],
            "memories": memories if isinstance(memories, list) else [],
            "agents": agents if isinstance(agents, list) else [],
            "members": (members or {}).get("members", []) if isinstance(members, dict) else [],
            "messages": (messages or {}).get("messages", []) if isinstance(messages, dict) else [],
            "upstream": upstream if isinstance(upstream, dict) else None,
        },
        health,
    )


def _fetch(room: str | None) -> tuple[str, list[LiveItem], HubHealth]:
    """Read every source the board projects.  A source that isn't reachable
    contributes nothing rather than failing the whole board."""
    name, sources, health = _fetch_raw(room)
    items = project_items(
        episodes=sources["episodes"],
        memories=sources["memories"],
        agents=sources["agents"],
        members=sources["members"],
        now=datetime.now(UTC),
    )
    return name, attach_upstream(items, sources["upstream"]), health


# ── rendering ────────────────────────────────────────────────────────────────


def _ttl_bar(fraction: float) -> Text:
    """A draining lease, drawn. Same fraction the GUI's TtlBar reads."""
    filled = min(TTL_CELLS, int(fraction * TTL_CELLS + 0.5))
    bar = Text()
    bar.append("▰" * filled, style="red" if fraction > 0.75 else "yellow")
    bar.append("▱" * (TTL_CELLS - filled), style="dim")
    return bar


def _custody_chip(item: LiveItem, now: datetime) -> Text:
    """Who holds this row, and how much longer their claim has to run.

    A row with no custody axis gets a plain handle and no draining bar: nobody
    has taken it for a window, so there is nothing to drain.
    """
    state = custody.custody_of(item, now)
    chip = Text()
    if state is None:
        chip.append(
            f"@{item.owner}" if item.owner else "unowned", style="cyan" if item.owner else "dim"
        )
        return chip

    if state == "held":
        chip.append(f"held @{item.owner}", style="cyan")
        fraction = custody.elapsed_fraction(custody.claimed_at(item), item.get("ttl_minutes"), now)
        if fraction is not None:
            chip.append(" ")
            chip.append_text(_ttl_bar(fraction))
            left = custody.remaining_minutes(item, now)
            if left is not None:
                chip.append(f" {left}m left", style="dim")
        return chip

    chip.append(state, style="red" if state == "expired" else "dim")
    note = custody.note_of(item, now)
    if note:
        text, author = note
        chip.append(f" — {text}", style="dim")
        # The note's author is what tells a deliberate handoff from an abandoned
        # one: they leave the same row behind, and only the byline differs.
        if author != custody.RUNTIME_AUTHOR:
            chip.append(f" (by @{author})", style="dim")
    return chip


def _row_lines(item: LiveItem, now: datetime) -> Text:
    glyph, colour = KIND_GLYPH.get(item.kind, ("●", "white"))
    lens = lens_of_item(item, now)
    head = Text()
    head.append(f" {glyph} ", style=colour)
    head.append(f"{item.id.split(':', 1)[1][:12]:<13}", style="dim")
    title = item.title if len(item.title) <= TITLE_WIDTH else item.title[: TITLE_WIDTH - 1] + "…"
    head.append(title, style="dim strike" if lens == "resolved" else "")
    if item.priority == "urgent" and lens != "resolved":
        head.append("  urgent", style="red")

    meta = Text("     ")
    meta.append(item.source.label, style="dim")
    meta.append("  ")
    meta.append_text(_custody_chip(item, now))
    if branch := item.text("branch"):
        meta.append(f"  {branch}", style="dim")
    if ci := item.text("ci"):
        meta.append(f"  CI {ci}", style=CI_COLOR.get(ci, "dim"))
    if item.get("upstream_pending") and not item.get("upstream"):
        # A row that points somewhere but has no answer yet. The terminal's
        # version of a skeleton: hold the space, say it is coming, and never
        # print a state nobody reported.
        meta.append("  checking…", style="dim")
    if upstream := item.text("upstream"):
        # The provider's own wording, not ours: "changes requested" is what the
        # reader recognises, and the state behind it is what the board sorts by.
        label = item.text("upstream_label") or upstream
        meta.append(f"  {label}", style=UPSTREAM_COLOR.get(upstream, "dim"))
        if (count := item.get("upstream_count")) and isinstance(count, int):
            meta.append(f" +{count - 1}", style="dim")
        # The answer's own age, not the row's: an agent reading "CI green" needs
        # to know how old that is, and the two surfaces must not differ on it.
        if age := item.text("upstream_age"):
            meta.append(f" {age}", style="dim")
        # A stale answer is still the truth as far as anyone knows, with a
        # refresh running behind it; saying so beats taking the value away.
        if item.text("upstream_freshness") in ("stale", "error"):
            meta.append(" (refreshing)", style="dim")
    if pr := item.text("pr"):
        meta.append(f"  {pr}", style="dim")
    if blocked_by := item.strings("blocked_by"):
        meta.append(f"  waiting on {', '.join(blocked_by)}", style="red")
    if choices := item.strings("choices"):
        meta.append(f"  [{'] ['.join(choices)}]", style="cyan")
    meta.append(f"  {format_age(item.age_minutes(now))}", style="dim")

    return Text("\n").join([head, meta])


def _grouped(items: list[LiveItem], group_by: str) -> list[tuple[str, list[LiveItem]]]:
    buckets: dict[str, list[LiveItem]] = {}
    for item in items:
        key = str(item.get(group_by) or "-")
        buckets.setdefault(key, []).append(item)

    # Kinds and statuses carry a natural order — decisions before signals, open
    # before resolved — and reading it by group size would bury the urgent ones.
    order = {"kind": KINDS, "status": STATUSES, "priority": PRIORITIES}.get(group_by)
    if order:
        return sorted(
            buckets.items(), key=lambda kv: order.index(kv[0]) if kv[0] in order else len(order)
        )
    return sorted(buckets.items(), key=lambda kv: (-len(kv[1]), kv[0]))


def _render(
    room: str,
    items: list[LiveItem],
    *,
    lens: str | None,
    group_by: str,
    view: str,
) -> Group:
    now = datetime.now(UTC)
    lenses = {i.id: lens_of_item(i, now) for i in items}
    counts = {
        "needs_you": sum(1 for i in items if lenses[i.id] == "needs_you"),
        "in_flight": sum(1 for i in items if lenses[i.id] == "in_flight"),
        "resolved": sum(1 for i in items if lenses[i.id] == "resolved"),
    }
    shown = [i for i in items if lens is None or lenses[i.id] == lens]
    shown.sort(key=lambda i: (PRIORITIES.index(i.priority), i.age_minutes(now) or 10**6))

    header = Text()
    header.append(f"{room}  ", style="bold")
    header.append(
        f"{counts['needs_you']} need you · {counts['in_flight']} in flight · "
        f"{counts['resolved']} resolved today",
        style="dim",
    )

    blocks: list[RenderableType] = [header, Text()]

    if view == "table":
        blocks.append(_table(shown, items))
    elif not shown:
        blocks.append(Text("  Nothing here. Widen the lens with --lens all.", style="dim"))
    else:
        for key, rows in _grouped(shown, group_by):
            label = GROUP_LABEL.get(key, key.replace("_", " ").capitalize())
            title = Text()
            title.append(f"{label} ", style="bold")
            title.append(str(len(rows)), style="dim")
            blocks.append(title)
            for row in rows:
                blocks.append(_row_lines(row, now))
            blocks.append(Text())

    blocks.append(Text())
    legend = Text("  ")
    legend.append("claim  release  resolve  block  promote  dismiss", style="dim")
    legend.append("     mycelium board <verb> <id>", style="dim")
    blocks.append(legend)
    return Group(*blocks)


def _table(shown: list[LiveItem], every: list[LiveItem]) -> Group:
    """The namespace as typed data.  Columns are inferred from the frontmatter
    the rows already carry, so the table is a projection, never a definition."""
    schema = infer_schema(every)
    columns = [f for f in schema if f.name != "choices"][:5]

    table = Table(show_lines=False, box=None, pad_edge=False, header_style="dim")
    table.add_column("Row", no_wrap=True, overflow="ellipsis", width=36)
    for column in columns:
        # The inferred type rides the legend under the table rather than the
        # header: at terminal widths a second word per column costs the values.
        table.add_column(column.label, no_wrap=True, overflow="ellipsis")

    for item in shown:
        # Every cell is a Text, never a str: Rich parses square brackets in a
        # plain string as markup, so a title or a field value carrying something
        # like "[/legacy]" would raise rather than render. Room content is not
        # markup, and the one styled cell here is ours to style explicitly.
        values: list[Text] = []
        for column in columns:
            raw = item.get(column.name)
            if isinstance(raw, list):
                values.append(Text(", ".join(str(v) for v in raw) or "-"))
            elif raw in (None, ""):
                values.append(Text("-", style="dim"))
            elif column.name == "updated":
                values.append(Text(str(raw)[:16].replace("T", " ")))
            else:
                values.append(Text(str(raw)))
        table.add_row(Text(item.title), *values)

    types = "  ".join(f"{f.name}·{f.type}" for f in columns)
    note = Text()
    note.append(f"  {types}\n", style="dim")
    note.append(
        f"  {len(schema)} fields inferred from {len(every)} rows · groupable: "
        f"{', '.join(f.name for f in groupable_fields(schema)[:4])}",
        style="dim",
    )
    return Group(table, Text(), note)


# ── commands ─────────────────────────────────────────────────────────────────


@doc_ref(
    usage="mycelium board [--lens needs-you|in-flight|resolved|all] [--view list|table] [--watch]",
    desc="The room's live coordination slice: what needs you, what's in flight, what resolved.",
    group="board",
)
@app.callback(invoke_without_command=True)
def board(
    ctx: typer.Context,
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
    lens: str = typer.Option(
        "needs-you", "--lens", "-l", help="needs-you | in-flight | resolved | all"
    ),
    group_by: str = typer.Option("kind", "--group", "-g", help="Field to group rows by"),
    view: str = typer.Option("list", "--view", help="list | table"),
    watch: bool = typer.Option(
        False, "--watch", "-w", help="Re-read every few seconds until interrupted"
    ),
    interval: float = typer.Option(5.0, "--interval", help="Seconds between reads under --watch"),
) -> None:
    """Show the room's coordination board."""
    if ctx.invoked_subcommand is not None:
        return
    if lens not in LENS_CHOICES:
        console.print(f"[red]Unknown lens '{lens}'.[/red] Try: {', '.join(LENS_CHOICES)}")
        raise typer.Exit(1)

    def read() -> Group:
        name, items, health = _fetch(room)
        if not health.reachable:
            return Group(Text(f"  {health.note}. No board to draw for {name}.", style="red"))
        rendered = _render(name, items, lens=LENS_CHOICES[lens], group_by=group_by, view=view)
        if health.note:
            # A board missing a source is not a quiet board, and the difference
            # matters more than the tidiness of not saying so.
            return Group(Text(f"  {health.note}", style="yellow"), Text(), rendered)
        return rendered

    if not watch:
        console.print(read())
        return

    # --watch is the honest version of a live board until the ledger pushes:
    # a re-read on a timer, not a stream pretending to be one.
    try:
        with Live(console=console, refresh_per_second=4, screen=False) as live:
            while True:
                live.update(read())
                time.sleep(max(1.0, interval))
    except KeyboardInterrupt:
        console.print("[dim]  stopped[/dim]")


@doc_ref(
    usage="mycelium board resolve <id>",
    desc="Resolve a board row: a work/ lease resolves, any other memory row takes status=resolved.",
    group="board",
)
@app.command(name="resolve")
def board_resolve(
    row_id: str = typer.Argument(..., help="Row id as shown on the board (e.g. t3, work/auth)"),
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
) -> None:
    """Resolve a row."""
    cfg = MyceliumConfig.load()
    name = _resolve_room(cfg, room)

    item = _row(name, row_id)
    if item is not None and custody.custody_refusal(item) is None:
        _lease(cfg, name, "resolve", key=_lease_key(item), handle=cfg.get_current_identity())
        return
    # Not leasable, but still a row with frontmatter: `status` is a stage, and a
    # stage is a field write. Custody stays out of it — that is the lease's.
    _write_fields(cfg, name, row_id, {"status": "resolved"})


@doc_ref(
    usage="mycelium board claim <id> [--to @handle] [--ttl 30]",
    desc="Take custody of a work/ row: a lease with your handle on it, which drains unless renewed.",
    group="board",
)
@app.command(name="claim")
def board_claim(
    row_id: str = typer.Argument(..., help="Row id as shown on the board (e.g. work/auth-spike)"),
    to: str | None = typer.Option(None, "--to", help="Handle to claim it for (default: you)"),
    ttl: int = typer.Option(
        custody.DEFAULT_TTL_MINUTES, "--ttl", help="Minutes the claim holds without a renewal"
    ),
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
) -> None:
    """Claim a row, as a lease rather than a fact."""
    cfg = MyceliumConfig.load()
    name = _resolve_room(cfg, room)
    item = _row(name, row_id)
    if item is None:
        console.print(f"[dim]No row '{row_id}' on this board.[/dim]")
        raise typer.Exit(1)
    if refusal := custody.custody_refusal(item):
        # Refusing with the reason is the honest answer: there is nowhere on this
        # row to write a claim, and pretending otherwise is how a board fills up
        # with holders nobody can renew.
        console.print(f"[yellow]·[/yellow] {row_id} can't be claimed — {refusal}")
        raise typer.Exit(1)
    handle = (to or cfg.get_current_identity()).lstrip("@")
    _lease(cfg, name, "claim", key=_lease_key(item), handle=handle, ttl_minutes=ttl)


@doc_ref(
    usage='mycelium board release <id> [--note "why"]',
    desc="Hand a claimed row back to the pool, leaving a note saying you did it deliberately.",
    group="board",
)
@app.command(name="release")
def board_release(
    row_id: str = typer.Argument(..., help="Row id as shown on the board"),
    note: str | None = typer.Option(None, "--note", help="Why you're handing it back"),
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
) -> None:
    """Release a row you hold."""
    cfg = MyceliumConfig.load()
    name = _resolve_room(cfg, room)
    item = _row(name, row_id)
    if item is None:
        console.print(f"[dim]No row '{row_id}' on this board.[/dim]")
        raise typer.Exit(1)
    if refusal := custody.custody_refusal(item):
        console.print(f"[yellow]·[/yellow] {row_id} holds no lease — {refusal}")
        raise typer.Exit(1)
    _lease(
        cfg,
        name,
        "release",
        key=_lease_key(item),
        handle=cfg.get_current_identity().lstrip("@"),
        note=note,
    )


@doc_ref(
    usage="mycelium board block <id> --on <ref>",
    desc="Record what a row is waiting on. The board derives 'blocked' from that, and stores it nowhere.",
    group="board",
)
@app.command(name="block")
def board_block(
    row_id: str = typer.Argument(..., help="Row id as shown on the board"),
    on: str | None = typer.Option(None, "--on", help="What it's waiting on (e.g. #502)"),
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
) -> None:
    """Say what a row is waiting on."""
    if not on:
        console.print(
            "[yellow]·[/yellow] block needs --on: a row is blocked because it names a blocker."
        )
        raise typer.Exit(1)
    cfg = MyceliumConfig.load()
    name = _resolve_room(cfg, room)
    _write_fields(cfg, name, row_id, {custody.BLOCKED_FIELD: on})


def _lease_key(item: LiveItem) -> str:
    """The memory key behind a row. Leases are written where the row lives."""
    return item.id.split(":", 1)[1]


def _row(room: str, row_id: str) -> LiveItem | None:
    """Find the row a verb names, however the reader typed its id.

    The board elides ids to fit a column, and a reader retypes what they saw, so
    ``work/auth``, ``memory:work/auth`` and the truncated form all have to land on
    the same row.
    """
    _, items, _ = _fetch(room)
    wanted = row_id.strip()
    for item in items:
        tail = item.id.split(":", 1)[1] if ":" in item.id else item.id
        if wanted in (item.id, tail, tail[:12]):
            return item
    return None


def _lease(cfg: MyceliumConfig, room: str, action: str, **body: Any) -> None:
    """Write a custody change through the hub, and say what it did."""
    payload = {k: v for k, v in body.items() if v is not None}
    try:
        with hub_client(cfg, timeout=30) as client:
            resp = client.post(f"/api/rooms/{room}/leases/{action}", json=payload)
    except httpx.HTTPError as e:
        console.print(f"[red]✗[/red] hub unreachable: {e}")
        raise typer.Exit(1) from e
    if resp.status_code == 409:
        detail = resp.json().get("detail", {})
        held_by = detail.get("owner") if isinstance(detail, dict) else None
        console.print(
            f"[yellow]·[/yellow] {payload.get('key')} is already held by @{held_by}. "
            "[dim]Its lease has to drain (or its holder release it) before anyone else takes it.[/dim]"
        )
        raise typer.Exit(1)
    if resp.status_code >= 400:
        console.print(f"[red]✗[/red] {action} failed: {resp.text}")
        raise typer.Exit(1)
    data = resp.json()
    if action == "claim":
        console.print(
            f"[green]✓[/green] held [bold]{data.get('key')}[/bold] by @{data.get('owner')} "
            f"[dim]for {data.get('ttl_minutes')}m — renewed by your loop, or it drains back to "
            "the pool.[/dim]"
        )
    elif action == "release":
        console.print(
            f"[green]✓[/green] released [bold]{data.get('key')}[/bold] "
            f"[dim]— {data.get('custody_note')}[/dim]"
        )
    else:
        console.print(f"[green]✓[/green] {action}d [bold]{data.get('key')}[/bold]")


def _write_fields(cfg: MyceliumConfig, room: str, row_id: str, patch: dict) -> None:
    """Put a verb's frontmatter on the row, and say what landed.

    The same upsert a ``memory set --meta`` goes through, so a verb typed here
    and an agent writing frontmatter leave one kind of trace. A row with no
    frontmatter behind it, or a key a lease owns, is refused in its own terms
    rather than written somewhere it would not be read back.
    """
    item = _row(room, row_id)
    if item is None:
        console.print(f"[dim]No row '{row_id}' on this board.[/dim]")
        raise typer.Exit(1)
    refusal = board_fields.field_write_refusal(item)
    if refusal:
        console.print(f"[yellow]·[/yellow] {row_id} can't take a field write — {refusal}")
        raise typer.Exit(1)
    reserved = board_fields.reserved_in(patch)
    if reserved:
        console.print(
            f"[yellow]·[/yellow] {', '.join(reserved)} moves through a lease, not a field "
            "write — use claim / release / resolve."
        )
        raise typer.Exit(1)
    key = board_fields.memory_key_of(item)
    body = {"key": key, "handle": cfg.get_current_identity(), "fields": patch}
    try:
        with hub_client(cfg, timeout=30) as client:
            resp = client.post(f"/api/rooms/{room}/fields", json=body)
    except httpx.HTTPError as e:
        console.print(f"[red]✗[/red] hub unreachable: {e}")
        raise typer.Exit(1) from e
    if resp.status_code >= 400:
        console.print(f"[red]✗[/red] write failed: {resp.text}")
        raise typer.Exit(1)
    rendered = " ".join(f"{k}={v}" for k, v in patch.items())
    console.print(f"[green]✓[/green] wrote [bold]{key}[/bold] → {rendered}")


# ── the log ──────────────────────────────────────────────────────────────────

ACTOR_MARK = {"agent": "🤖", "engine": "◈", "human": "🧑"}
HEAT_BLOCKS = ["·", "░", "▒", "▓", "█"]


@doc_ref(
    usage="mycelium board log [--since 7d|--day YYYY-MM-DD|--week|--last-week] [--tz <zone>]",
    desc="What the room worked on, by day and by who, in whichever timezone you read it in.",
    group="board",
)
@app.command(name="log")
def board_log(
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
    since: str = typer.Option("7d", "--since", "-s", help="Window: 7d, 30d, today"),
    day: str | None = typer.Option(None, "--day", help="One day, as YYYY-MM-DD"),
    week: bool = typer.Option(False, "--week", help="This week, Monday to Sunday"),
    last_week: bool = typer.Option(False, "--last-week", help="The week before this one"),
    tz_name: str | None = typer.Option(
        None, "--tz", help="Timezone the days are read in (default: $TZ, else UTC)", envvar="TZ"
    ),
    by: str | None = typer.Option(None, "--by", help="Only this actor's lines"),
) -> None:
    """What the room worked on, by day.

    The board says what needs you now; the log says what got done, which is the
    half an agent needs when it comes back to a room after a week away.
    """
    tz = zone(tz_name)
    name, sources, health = _fetch_raw(room)
    today_local = datetime.now(tz).date()

    events = project_activity(
        messages=sources["messages"],
        memories=sources["memories"],
        episodes=sources["episodes"],
        agent_handles=[a.get("handle", "") for a in sources["agents"]],
    )
    if by:
        wanted = by.lstrip("@").lower()
        events = [e for e in events if e.actor.lower() == wanted]

    if not events and not health.reachable:
        console.print(Text(f"  {health.note}. No log to draw for {name}.", style="red"))
        return

    if day:
        try:
            frm = to = date.fromisoformat(day)
        except ValueError:
            console.print(f"[red]Not a date:[/red] {day}")
            raise typer.Exit(1) from None
    elif week:
        frm = week_start(today_local)
        to = frm + timedelta(days=6)
    elif last_week:
        frm = week_start(today_local) - timedelta(days=7)
        to = frm + timedelta(days=6)
    elif since == "today":
        frm = to = today_local
    else:
        days_back = int(since.rstrip("d")) if since.rstrip("d").isdigit() else 7
        frm, to = today_local - timedelta(days=days_back - 1), today_local

    days = by_day(events, tz)
    current, longest = streaks(days, today_local)
    summary = summarize_activity(days, frm, to)
    logged_today = len(days.get(today_local, []))

    console.print()
    header = Text()
    header.append(f"{name}  ", style="bold")
    header.append(f"{frm} to {to}" if frm != to else str(frm), style="")
    header.append(f"  ·  {tz.key}", style="dim")
    console.print(header)

    stats = Text("  ")
    stats.append(
        f"{logged_today}/{DAILY_GOAL} today",
        style="green" if logged_today >= DAILY_GOAL else "cyan",
    )
    stats.append(
        f"  ·  {current}-day streak (longest {longest})"
        f"  ·  {len(summary.events)} logged over {summary.active_days} active "
        f"{'day' if summary.active_days == 1 else 'days'}",
        style="dim",
    )
    console.print(stats)
    console.print()

    # A fortnight of heat, so a glance shows the rhythm before any of the lines.
    spark = Text("  ")
    cursor = to - timedelta(days=13)
    while cursor <= to:
        spark.append(HEAT_BLOCKS[heat_level(len(days.get(cursor, [])))], style="cyan")
        cursor += timedelta(days=1)
    spark.append(f"   {to - timedelta(days=13)} → {to}", style="dim")
    console.print(spark)
    console.print()

    if not summary.events:
        console.print("[dim]  Nothing logged in this window.[/dim]\n")
        return

    for actor, kind, actor_events in summary.by_actor:
        lane = Text("  ")
        lane.append(
            f"{ACTOR_MARK.get(kind, '·')} @{actor}", style="cyan" if kind != "human" else "white"
        )
        lane.append(f"  {kind}  {len(actor_events)} logged", style="dim")
        console.print(lane)
        for event in actor_events[:12]:
            line = Text("      ")
            line.append(event.at.astimezone(tz).strftime("%m-%d %H:%M  "), style="dim")
            line.append(f"{event.verb} ", style="")
            line.append(event.title, style="dim")
            console.print(line)
        if len(actor_events) > 12:
            console.print(Text(f"      +{len(actor_events) - 12} more", style="dim"))
        console.print()


# ── status-provider credentials ───────────────────────────────────────────────
#
# A status provider keeps a board row's external pointer live (a pull request's
# review state, a ticket's status). To reach the tool it needs a credential, and
# the provider only *names* it: the hub resolves the name and renders it onto the
# wire. These verbs write the value the hub resolves, into a 0600 file outside
# config.toml (which `config apply` would otherwise clobber). See
# `mycelium.status_credentials` and `app/services/status/credentials.py`.
#
# Providers run hub-side, so these are hub-operator commands: run them where the
# backend runs. Nothing here can print a value.

credential_app = typer.Typer(
    help=(
        "Give the hub the credentials its status providers need to keep board "
        "rows live (a GitHub token, a Jira email + token). Stored 0600 outside "
        "config.toml; the value is never printed."
    ),
    no_args_is_help=True,
)
app.add_typer(credential_app, name="credential")


@doc_ref(
    usage="mycelium board credential set <name> [--stdin]",
    desc=(
        "Store a status-provider credential value under the name a provider "
        "declares (e.g. <code>GITHUB_TOKEN</code>). Read from a prompt or stdin, "
        "never argv; saved 0600 outside <code>config.toml</code>."
    ),
    group="board",
)
@credential_app.command("set")
def credential_set(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Credential name a provider declares, e.g. GITHUB_TOKEN"),
    stdin: bool = typer.Option(
        False, "--stdin", help="Read the value from stdin instead of a prompt."
    ),
) -> None:
    """Store the value for a credential a status provider names.

    The name is the provider's, not yours: GitHub's provider declares
    ``GITHUB_TOKEN``, Jira's declares ``JIRA_EMAIL`` and ``JIRA_TOKEN``. The value
    is read from stdin (``--stdin``) or a hidden prompt, never from the command
    line, so it never lands in shell history or ``ps`` output.

    Examples:
        mycelium board credential set GITHUB_TOKEN --stdin < token.txt
        mycelium board credential set GITHUB_TOKEN   # prompts, hidden
    """
    from mycelium import status_credentials

    try:
        json_output = ctx.obj.get("json", False) if ctx.obj else False

        if stdin:
            value = sys.stdin.read().strip()
        elif sys.stdin.isatty():
            value = typer.prompt(f"Value for {name}", hide_input=True)
        else:
            console.print(
                "[red]No value given.[/red] Pass --stdin to read one, or run it "
                "interactively for a hidden prompt."
            )
            raise typer.Exit(1)

        path = status_credentials.set_credential(name, value)

        if json_output:
            typer.echo(json.dumps({"name": name, "stored": str(path), "empty": not value}))
            return

        console.print(f"[green]Stored[/green] [cyan]{name}[/cyan] [dim](value not shown)[/dim].")
        console.print(f"[dim]Saved to {path} (mode 0600).[/dim]")
        if not value:
            console.print(
                "[yellow]The value is empty[/yellow]; the hub will report it as set-but-empty "
                "and still refuse the provider until it has a real value."
            )
    except typer.Exit:
        raise
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None


@doc_ref(
    usage="mycelium board credential ls",
    desc="List the status-provider credential names the hub has, and whether each is set. Never the values.",
    group="board",
)
@credential_app.command("ls")
def credential_ls(ctx: typer.Context) -> None:
    """List stored status-provider credential names, never their values."""
    from mycelium import status_credentials

    try:
        names = status_credentials.list_names()
        json_output = ctx.obj.get("json", False) if ctx.obj else False

        if json_output:
            typer.echo(json.dumps(names, indent=2, sort_keys=True))
            return

        if not names:
            console.print("[dim]No status-provider credentials on this hub.[/dim]")
            return

        table = Table(title="Status-provider credentials")
        table.add_column("name", style="cyan")
        table.add_column("value")
        for name, is_set in names.items():
            table.add_row(name, "set" if is_set else "[yellow]empty[/yellow]")
        console.print(table)
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None


@doc_ref(
    usage="mycelium board credential rm <name>",
    desc="Forget a status-provider credential on this hub.",
    group="board",
)
@credential_app.command("rm")
def credential_rm(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Credential name to forget"),
) -> None:
    """Drop a stored status-provider credential."""
    from mycelium import status_credentials

    try:
        existed = status_credentials.remove_credential(name)
        json_output = ctx.obj.get("json", False) if ctx.obj else False
        if json_output:
            typer.echo(json.dumps({"removed": existed}))
            return
        if existed:
            console.print(f"[green]Removed[/green] [cyan]{name}[/cyan].")
        else:
            console.print(f"[dim]No credential named {name} on this hub; nothing to do.[/dim]")
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None
