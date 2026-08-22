# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
The coordination board: the room's live slice, in the terminal.

``mycelium board`` is the CLI half of the same surface the GUI draws — one
projection over plan tasks, episodes, memory namespaces and presence, read
through whichever lens you ask for.  The default lens is "needs you", because a
board worth having is one you can ignore until it says your name.

The verbs (claim / resolve / block / promote / dismiss) are the same words the
GUI uses and the same words an agent drives over the ledger.  In this proof of
concept only the ones with a real write behind them act: ``resolve`` on a row
that came from a plan task toggles the task.  Everything else prints what it
would write rather than pretending.
"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime, timedelta
from typing import Any

import typer
from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.table import Table
from rich.text import Text

from mycelium.board import LiveItem, demo_items, infer_schema, project_items
from mycelium.board.activity import (
    DAILY_GOAL,
    ActivityEvent,
    by_day,
    digest,
    heat_level,
    project_activity,
    streaks,
    week_start,
    zone,
)
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

#: Widest title a row prints before it is elided.
TITLE_WIDTH = 50


# ── data ─────────────────────────────────────────────────────────────────────


def _fetch_raw(room: str | None) -> tuple[str, dict[str, Any], bool]:
    """Every source the log and the board share, read once."""
    cfg = MyceliumConfig.load()
    name = _resolve_room(cfg, room)

    def get(path: str, default):
        try:
            resp = client.get(path)
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return default

    with hub_client(cfg, timeout=30) as client:
        plan = get(f"/api/rooms/{name}/plan", None)
        episodes = get(f"/api/rooms/{name}/episodes", {})
        memories = get(f"/api/rooms/{name}/memory?limit=50", [])
        agents = get(f"/api/rooms/{name}/agents", [])
        members = get(f"/api/rooms/{name}/sessions/members", {})
        messages = get(f"/api/rooms/{name}/messages?limit=300", {})

    return (
        name,
        {
            "plan": plan,
            "episodes": (episodes or {}).get("episodes", []) if isinstance(episodes, dict) else [],
            "memories": memories if isinstance(memories, list) else [],
            "agents": agents if isinstance(agents, list) else [],
            "members": (members or {}).get("members", []) if isinstance(members, dict) else [],
            "messages": (messages or {}).get("messages", []) if isinstance(messages, dict) else [],
        },
        plan is not None,
    )


def _fetch(room: str | None) -> tuple[str, list[LiveItem], bool]:
    """Read every source the board projects.  A source that isn't reachable
    contributes nothing rather than failing the whole board."""
    name, sources, reachable = _fetch_raw(room)
    return (
        name,
        project_items(
            plan=sources["plan"],
            episodes=sources["episodes"],
            memories=sources["memories"],
            agents=sources["agents"],
            members=sources["members"],
            now=datetime.now(UTC),
        ),
        reachable,
    )


# ── rendering ────────────────────────────────────────────────────────────────


def _row_lines(item: LiveItem, now: datetime) -> Text:
    glyph, colour = KIND_GLYPH.get(item.kind, ("●", "white"))
    head = Text()
    head.append(f" {glyph} ", style=colour)
    head.append(f"{item.id.split(':', 1)[1][:12]:<13}", style="dim")
    title = item.title if len(item.title) <= TITLE_WIDTH else item.title[: TITLE_WIDTH - 1] + "…"
    head.append(title, style="dim strike" if item.lens == "resolved" else "")
    if item.priority == "urgent" and item.lens != "resolved":
        head.append("  urgent", style="red")
    if item.demo:
        head.append("  demo", style="dim")

    meta = Text("     ")
    meta.append(item.source.label, style="dim")
    meta.append("  ")
    meta.append(
        f"@{item.owner}" if item.owner else "unowned", style="cyan" if item.owner else "dim"
    )
    if branch := item.text("branch"):
        meta.append(f"  {branch}", style="dim")
    if ci := item.text("ci"):
        meta.append(f"  CI {ci}", style=CI_COLOR.get(ci, "dim"))
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
    counts = {
        "needs_you": sum(1 for i in items if i.lens == "needs_you"),
        "in_flight": sum(1 for i in items if i.lens == "in_flight"),
        "resolved": sum(1 for i in items if i.lens == "resolved"),
    }
    shown = [i for i in items if lens is None or i.lens == lens]
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
    legend.append("claim  resolve  block  promote  dismiss", style="dim")
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
    for field in columns:
        # The inferred type rides the legend under the table rather than the
        # header: at terminal widths a second word per column costs the values.
        table.add_column(field.label, no_wrap=True, overflow="ellipsis")

    for item in shown:
        values = []
        for field in columns:
            raw = item.get(field.name)
            if isinstance(raw, list):
                values.append(", ".join(str(v) for v in raw) or "-")
            elif raw in (None, ""):
                values.append("[dim]-[/dim]")
            elif field.name == "updated":
                values.append(str(raw)[:16].replace("T", " "))
            else:
                values.append(str(raw))
        table.add_row(item.title, *values)

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
    demo: bool = typer.Option(
        False, "--demo", help="Add the illustrative rows a live board would fill itself from"
    ),
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
        name, items, reachable = _fetch(room)
        if demo:
            items = items + demo_items(datetime.now(UTC))
        if not reachable and not items:
            return Group(Text(f"  Hub unreachable. No board to draw for {name}.", style="red"))
        rendered = _render(name, items, lens=LENS_CHOICES[lens], group_by=group_by, view=view)
        if not reachable:
            # The demo layer stands on its own, but never silently: a board that
            # can't read the room says so rather than looking populated.
            return Group(
                Text("  Hub unreachable. Showing the demo layer only.", style="yellow"),
                Text(),
                rendered,
            )
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
    desc="Resolve a board row. Rows projected from a plan task write through; others report what they would write.",
    group="board",
)
@app.command(name="resolve")
def board_resolve(
    row_id: str = typer.Argument(..., help="Row id as shown on the board (e.g. t3, plan:t3)"),
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
) -> None:
    """Resolve a row."""
    _verb("resolve", row_id, room)


@doc_ref(
    usage="mycelium board claim <id> [--to @handle]",
    desc="Claim a board row for yourself or an agent.",
    group="board",
)
@app.command(name="claim")
def board_claim(
    row_id: str = typer.Argument(..., help="Row id as shown on the board"),
    to: str | None = typer.Option(None, "--to", help="Handle to claim it for"),
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
) -> None:
    """Claim a row."""
    _verb("claim", row_id, room, owner=to)


def _verb(verb: str, row_id: str, room: str | None, *, owner: str | None = None) -> None:
    """Apply a verb where a real write exists, and say so plainly where it
    doesn't — the live ledger these rows belong to isn't built yet."""
    cfg = MyceliumConfig.load()
    name = _resolve_room(cfg, room)
    task_id = row_id.split(":", 1)[1] if row_id.startswith("plan:") else row_id

    if verb == "resolve":
        with hub_client(cfg, timeout=30) as client:
            resp = client.post(
                f"/api/rooms/{name}/plan/tasks/{task_id}/toggle",
                json={"done": True},
            )
        if resp.status_code < 400:
            console.print(
                f"[green]✓[/green] resolved [bold]{task_id}[/bold] (plan task marked done)"
            )
            return
        console.print(f"[dim]No plan task '{task_id}'.[/dim]")

    patch = {"status": {"claim": "in_progress", "resolve": "resolved"}.get(verb, verb)}
    if owner:
        patch["owner"] = owner if owner.startswith("@") else f"@{owner}"
    rendered = " ".join(f"{k}={v}" for k, v in patch.items())
    console.print(
        f"[yellow]·[/yellow] {verb} [bold]{row_id}[/bold] → {rendered}\n"
        "[dim]  Not written. Rows from episodes, memory and presence can't be "
        "changed from here yet; plan-sourced rows write through today.[/dim]"
    )


# ── the log ──────────────────────────────────────────────────────────────────

ACTOR_MARK = {"agent": "🤖", "engine": "◈", "human": "🧑"}
HEAT_BLOCKS = ["·", "░", "▒", "▓", "█"]


def _demo_activity(end: date) -> list[ActivityEvent]:
    """A short illustrative history, so `--demo` shows the shape of a log that
    has been kept. Every event says it is demo."""
    actors = [("agent-y", "agent"), ("agent-z", "agent"), ("julia", "human"), ("aligner", "engine")]
    work = [
        ("resolved", "flip reads behind a flag"),
        ("posted", "48h soak looks clean"),
        ("wrote", "decisions/cutover"),
        ("completed", "rotate the signing key"),
        ("converged", "cutover window · @growth @risk"),
    ]
    events: list[ActivityEvent] = []
    for back in range(70):
        day = end - timedelta(days=back)
        seed = day.toordinal()
        count = 0 if seed % 8 == 3 else (1 + seed % 3 if day.weekday() >= 5 else 2 + seed % 7)
        for i in range(count):
            actor, kind = actors[(seed + i) % len(actors)]
            verb, title = work[(seed + i * 3) % len(work)]
            events.append(
                ActivityEvent(
                    id=f"demo:{day}:{i}",
                    at=datetime(
                        day.year,
                        day.month,
                        day.day,
                        8 + (seed + i) % 11,
                        (seed * i) % 60,
                        tzinfo=UTC,
                    ),
                    actor=actor,
                    actor_kind=kind,
                    verb=verb,
                    title=title,
                    source="demo layer",
                    demo=True,
                )
            )
    return events


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
    demo: bool = typer.Option(False, "--demo", help="Add an illustrative history, always marked"),
) -> None:
    """What the room worked on, by day.

    The board says what needs you now; the log says what got done, which is the
    half an agent needs when it comes back to a room after a week away.
    """
    tz = zone(tz_name)
    name, sources, reachable = _fetch_raw(room)
    today_local = datetime.now(tz).date()

    events = project_activity(
        messages=sources["messages"],
        memories=sources["memories"],
        episodes=sources["episodes"],
        plan=sources["plan"],
        agent_handles=[a.get("handle", "") for a in sources["agents"]],
    )
    if demo:
        events += _demo_activity(today_local)
    if by:
        wanted = by.lstrip("@").lower()
        events = [e for e in events if e.actor.lower() == wanted]

    if not events and not reachable:
        console.print(f"[red]  Hub unreachable. No log to draw for {name}.[/red]")
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
    summary = digest(days, frm, to)
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
            if event.demo:
                line.append("  demo", style="dim")
            console.print(line)
        if len(actor_events) > 12:
            console.print(Text(f"      +{len(actor_events) - 12} more", style="dim"))
        console.print()
