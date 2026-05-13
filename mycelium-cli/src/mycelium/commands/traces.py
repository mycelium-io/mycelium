# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
Trace viewer — query and pivot the spans collected in ``~/.mycelium/metrics/traces.db``.

The OTLP receiver in ``mycelium.collector`` writes every span it receives
from OpenClaw's ``diagnostics-otel`` and ``openclaw-deep-observability``
plugins into a SQLite table::

    spans(trace_id, span_id, parent_span_id, name, kind, service, host,
          start_time, duration_ms, status, status_message, attributes,
          created_at)

``attributes`` is a JSON blob containing rich identity / behavior info:

  Identity
    - openclaw.agent / gen_ai.agent.id / ioa_observe.entity.name
    - gen_ai.conversation.id           (e.g. agent:claire-agent:matrix:channel:!xyz:local)
    - openclaw.session.key             (same shape as conversation.id)
    - session.id                       (UUID for one logical conversation)
    - openclaw.channel                 (matrix | mycelium-room | …)

  Behavior
    - gen_ai.request.model / response.model
    - gen_ai.usage.input_tokens / output_tokens / total_tokens
    - openclaw.toolName / gen_ai.tool.name
    - openclaw.outcome                 (completed | failed | …)
    - openclaw.exec.exit_code
    - status / status_message          (span-level OK/ERROR)

This module exposes a ``traces`` Typer subapp mounted under ``mycelium
metrics traces …`` with pivots for the dimensions above.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from collections import Counter
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    help="View distributed traces collected from OpenClaw deep-observability.",
    no_args_is_help=True,
)

console = Console()

# ── Path helpers ──────────────────────────────────────────────────────────

_DEFAULT_DATA_DIR = Path.home() / ".mycelium"


def _data_dir() -> Path:
    return Path(os.environ.get("MYCELIUM_DATA_DIR") or _DEFAULT_DATA_DIR)


def _traces_db_path() -> Path:
    return _data_dir() / "metrics" / "traces.db"


def _open_db() -> sqlite3.Connection:
    """Open the traces DB read-only and fail fast with a friendly message."""
    db_path = _traces_db_path()
    if not db_path.exists():
        typer.secho(
            f"✗ traces.db not found at {db_path}",
            fg=typer.colors.RED,
        )
        typer.echo(
            "  The OTLP receiver writes this file. Make sure `mycelium metrics collect`"
            " is running on the hub (or the docker collector is up)."
        )
        raise typer.Exit(1)
    # Read-only via URI so we don't accidentally lock the writer.
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# ── Time-window parsing ───────────────────────────────────────────────────

_SINCE_RE = re.compile(r"^(\d+)\s*([smhd])?$")


def _since_to_sql(since: str | None) -> str:
    """Translate a ``since`` shorthand into a SQLite ``datetime(...)`` modifier.

    Accepts: ``5m``, ``2h``, ``1d``, ``600s``, raw seconds. Bare numbers are
    treated as minutes for ergonomics. Default window is 1 hour.
    """
    if since is None:
        since = "1h"
    since = since.strip().lower()
    m = _SINCE_RE.match(since)
    if not m:
        typer.secho(f"✗ Could not parse --since={since!r}", fg=typer.colors.RED)
        typer.echo("  Use forms like 30s, 15m, 2h, 1d.")
        raise typer.Exit(2)
    n = int(m.group(1))
    unit = m.group(2) or "m"
    suffix = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}[unit]
    return f"-{n} {suffix}"


def _where_since(since: str | None) -> tuple[str, list]:
    """Build a WHERE fragment + params for ``created_at > now-since``."""
    return ("created_at > datetime('now', ?)", [_since_to_sql(since)])


# ── Attribute JSON access ────────────────────────────────────────────────


def _parse_attrs(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        d = json.loads(raw)
        return d if isinstance(d, dict) else {}
    except (ValueError, TypeError):
        return {}


def _attr_first(attrs: dict, *keys: str, default: str = "") -> str:
    """Return the first present (truthy) attribute value coerced to string."""
    for k in keys:
        v = attrs.get(k)
        if v is not None and v != "":
            return str(v)
    return default


def _agent_of(attrs: dict) -> str:
    return _attr_first(
        attrs,
        "openclaw.agent",
        "gen_ai.agent.id",
        "gen_ai.agent.name",
        "ioa_observe.entity.name",
        default="-",
    )


def _conversation_of(attrs: dict) -> str:
    return _attr_first(
        attrs,
        "gen_ai.conversation.id",
        "openclaw.session.key",
        default="-",
    )


def _model_of(attrs: dict) -> str:
    return _attr_first(
        attrs,
        "gen_ai.response.model",
        "gen_ai.request.model",
        "openclaw.model",
        default="-",
    )


# ``agent:<agent>:<channel-kind>:<channel-type>:<room-id>``
_CONV_RE = re.compile(
    r"^agent:(?P<agent>[^:]+):(?P<chan_kind>[^:]+):(?P<chan_type>[^:]+):(?P<room>.+)$"
)


def _split_conversation(conv: str) -> tuple[str, str, str]:
    """Return (agent, channel_kind, room_id) from a conversation key.

    ``channel_kind`` is e.g. ``matrix`` or ``mycelium-room``; ``room_id`` is
    everything after it (so a Matrix ``!abc:server`` stays intact).
    """
    if not conv or conv == "-":
        return ("-", "-", "-")
    m = _CONV_RE.match(conv)
    if not m:
        return ("-", "-", conv)
    return (m.group("agent"), m.group("chan_kind"), m.group("room"))


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def _fmt_time(ts: str | None) -> str:
    """Format a stored ISO-8601 timestamp as ``HH:MM:SS`` for table display."""
    if not ts:
        return "-"
    # ts looks like 2026-05-12T19:26:36.516700+00:00
    t = ts.split("T", 1)[-1]
    return t.split(".", 1)[0].split("+", 1)[0][:8]


# ── Filter construction shared across subcommands ─────────────────────────


def _build_filters(
    since: str | None,
    host: str | None,
    agent: str | None,
    room: str | None,
    name_like: str | None,
    status: str | None,
) -> tuple[str, list]:
    where = []
    params: list = []

    sql, p = _where_since(since)
    where.append(sql)
    params.extend(p)

    if host:
        where.append("host = ?")
        params.append(host)

    if name_like:
        where.append("name LIKE ?")
        params.append(name_like.replace("*", "%"))

    if status:
        where.append("status = ?")
        params.append(status.lower())

    # agent / room are inside the JSON blob, so they get filtered in Python.
    # We still hand them back so the loader knows to apply them.
    return (" AND ".join(where), params)


def _row_matches_attr_filter(row: sqlite3.Row, agent: str | None, room: str | None) -> bool:
    if not agent and not room:
        return True
    attrs = _parse_attrs(row["attributes"])
    if agent:
        if _agent_of(attrs).lower() != agent.lower():
            return False
    if room:
        _, _, rid = _split_conversation(_conversation_of(attrs))
        if rid != room and room.lower() not in rid.lower():
            return False
    return True


# ── Subcommands ───────────────────────────────────────────────────────────


SinceOpt = typer.Option("1h", "--since", help="Time window: 30s, 15m, 2h, 1d.")
HostOpt = typer.Option(None, "--host", help="Filter to a single host (e.g. oclw3, oclw4).")
AgentOpt = typer.Option(None, "--agent", help="Filter to a single agent (matched against openclaw.agent / gen_ai.agent.id).")
RoomOpt = typer.Option(None, "--room", help="Filter to a room id (Matrix room id or mycelium room name; substring match).")
NameOpt = typer.Option(None, "--name", help="Filter span name (LIKE pattern, * wildcard).")
StatusOpt = typer.Option(None, "--status", help="Filter by span status: ok, error, unset.")
LimitOpt = typer.Option(20, "--limit", "-n", help="Max rows to display.")


@app.command("summary")
def summary(
    since: str = SinceOpt,
    host: str | None = HostOpt,
    agent: str | None = AgentOpt,
    room: str | None = RoomOpt,
) -> None:
    """High-level rollup: total spans, errors, hosts, agents, rooms, models."""
    where_sql, params = _build_filters(since, host, None, None, None, None)
    with _open_db() as conn:
        rows = conn.execute(
            f"SELECT host, status, duration_ms, attributes FROM spans WHERE {where_sql};",
            params,
        ).fetchall()

    rows = [r for r in rows if _row_matches_attr_filter(r, agent, room)]

    if not rows:
        typer.secho(f"No spans in window (since={since}).", fg=typer.colors.YELLOW)
        return

    total = len(rows)
    errors = sum(1 for r in rows if (r["status"] or "").lower() == "error")
    hosts = Counter(r["host"] or "-" for r in rows)
    agents: Counter = Counter()
    rooms: Counter = Counter()
    chan_kinds: Counter = Counter()
    models: Counter = Counter()
    tokens_in = tokens_out = 0
    tool_calls = 0
    durations = []

    for r in rows:
        a = _parse_attrs(r["attributes"])
        agents[_agent_of(a)] += 1
        _, ck, rid = _split_conversation(_conversation_of(a))
        chan_kinds[ck] += 1
        if rid != "-":
            rooms[rid] += 1
        m = _model_of(a)
        if m != "-":
            models[m] += 1
        tokens_in += int(a.get("gen_ai.usage.input_tokens") or 0)
        tokens_out += int(a.get("gen_ai.usage.output_tokens") or 0)
        if a.get("openclaw.toolName") or a.get("gen_ai.tool.name"):
            tool_calls += 1
        if r["duration_ms"]:
            durations.append(float(r["duration_ms"]))

    durations.sort()

    def pct(p: float) -> float:
        if not durations:
            return 0.0
        idx = min(len(durations) - 1, int(len(durations) * p))
        return durations[idx]

    table = Table(title=f"Trace summary (since {since})", show_header=False, box=None)
    table.add_column("Metric", style="bold")
    table.add_column("Value")
    table.add_row("Spans", str(total))
    table.add_row(
        "Errors",
        f"{errors}  [{(errors / total * 100):.1f}%]" if errors else "0",
    )
    table.add_row("Hosts", str(len(hosts)))
    table.add_row("Agents", str(sum(1 for k in agents if k != "-")))
    table.add_row("Rooms", str(len(rooms)))
    table.add_row("Channel kinds", ", ".join(f"{k}({n})" for k, n in chan_kinds.most_common() if k != "-") or "-")
    table.add_row("Distinct models", str(len(models)))
    table.add_row("Tool-call spans", str(tool_calls))
    table.add_row("Tokens in/out", f"{tokens_in:,} / {tokens_out:,}")
    table.add_row(
        "Span duration p50/p95/p99 (ms)",
        f"{pct(0.5):.1f} / {pct(0.95):.1f} / {pct(0.99):.1f}",
    )
    console.print(table)


def _print_groupby(
    title: str,
    rows: list[sqlite3.Row],
    key_fn,
    limit: int,
) -> None:
    counts: Counter = Counter()
    err_counts: Counter = Counter()
    durations: dict[str, list[float]] = {}
    tokens_in: Counter = Counter()
    tokens_out: Counter = Counter()
    for r in rows:
        a = _parse_attrs(r["attributes"])
        k = key_fn(r, a)
        counts[k] += 1
        if (r["status"] or "").lower() == "error":
            err_counts[k] += 1
        if r["duration_ms"]:
            durations.setdefault(k, []).append(float(r["duration_ms"]))
        tokens_in[k] += int(a.get("gen_ai.usage.input_tokens") or 0)
        tokens_out[k] += int(a.get("gen_ai.usage.output_tokens") or 0)

    if not counts:
        typer.secho("No spans in window.", fg=typer.colors.YELLOW)
        return

    table = Table(title=title)
    table.add_column("Key", overflow="fold")
    table.add_column("Spans", justify="right")
    table.add_column("Errors", justify="right")
    table.add_column("Avg ms", justify="right")
    table.add_column("p95 ms", justify="right")
    table.add_column("Tokens in", justify="right")
    table.add_column("Tokens out", justify="right")

    for k, n in counts.most_common(limit):
        ds = sorted(durations.get(k, []))
        avg = sum(ds) / len(ds) if ds else 0
        p95 = ds[int(len(ds) * 0.95)] if len(ds) > 1 else (ds[0] if ds else 0)
        err = err_counts.get(k, 0)
        table.add_row(
            _truncate(str(k), 70),
            str(n),
            (f"[red]{err}[/red]" if err else "0"),
            f"{avg:.1f}",
            f"{p95:.1f}",
            f"{tokens_in[k]:,}" if tokens_in[k] else "-",
            f"{tokens_out[k]:,}" if tokens_out[k] else "-",
        )
    console.print(table)


def _load_filtered_rows(
    since: str | None,
    host: str | None,
    agent: str | None,
    room: str | None,
    name: str | None = None,
    status: str | None = None,
) -> list[sqlite3.Row]:
    where_sql, params = _build_filters(since, host, agent, room, name, status)
    with _open_db() as conn:
        rows = conn.execute(
            f"SELECT * FROM spans WHERE {where_sql} ORDER BY start_time DESC;",
            params,
        ).fetchall()
    return [r for r in rows if _row_matches_attr_filter(r, agent, room)]


@app.command("by-host")
def by_host(
    since: str = SinceOpt,
    agent: str | None = AgentOpt,
    room: str | None = RoomOpt,
    limit: int = LimitOpt,
) -> None:
    """Group spans by source host."""
    rows = _load_filtered_rows(since, None, agent, room)
    _print_groupby(f"Spans by host (since {since})", rows, lambda r, _a: r["host"] or "-", limit)


@app.command("by-agent")
def by_agent(
    since: str = SinceOpt,
    host: str | None = HostOpt,
    room: str | None = RoomOpt,
    limit: int = LimitOpt,
) -> None:
    """Group spans by agent (openclaw.agent / gen_ai.agent.id)."""
    rows = _load_filtered_rows(since, host, None, room)
    _print_groupby(f"Spans by agent (since {since})", rows, lambda _r, a: _agent_of(a), limit)


@app.command("by-room")
def by_room(
    since: str = SinceOpt,
    host: str | None = HostOpt,
    agent: str | None = AgentOpt,
    limit: int = LimitOpt,
) -> None:
    """Group spans by room (matrix room id or mycelium room name)."""
    rows = _load_filtered_rows(since, host, agent, None)

    def key(_r, attrs: dict) -> str:
        agent_id, chan_kind, rid = _split_conversation(_conversation_of(attrs))
        if rid == "-":
            return "-"
        return f"[{chan_kind}] {rid}  ({agent_id})"

    _print_groupby(f"Spans by room (since {since})", rows, key, limit)


@app.command("by-channel")
def by_channel(
    since: str = SinceOpt,
    host: str | None = HostOpt,
    agent: str | None = AgentOpt,
    limit: int = LimitOpt,
) -> None:
    """Group spans by channel kind (matrix vs mycelium-room vs …)."""
    rows = _load_filtered_rows(since, host, agent, None)

    def key(_r, attrs: dict) -> str:
        _, ck, _ = _split_conversation(_conversation_of(attrs))
        if ck == "-":
            ck = _attr_first(attrs, "openclaw.channel", default="-")
        return ck

    _print_groupby(f"Spans by channel kind (since {since})", rows, key, limit)


@app.command("by-model")
def by_model(
    since: str = SinceOpt,
    host: str | None = HostOpt,
    agent: str | None = AgentOpt,
    room: str | None = RoomOpt,
    limit: int = LimitOpt,
) -> None:
    """Group spans by LLM model (gen_ai.response.model / request.model)."""
    rows = _load_filtered_rows(since, host, agent, room)
    _print_groupby(f"Spans by model (since {since})", rows, lambda _r, a: _model_of(a), limit)


@app.command("by-name")
def by_name(
    since: str = SinceOpt,
    host: str | None = HostOpt,
    agent: str | None = AgentOpt,
    room: str | None = RoomOpt,
    limit: int = LimitOpt,
) -> None:
    """Group spans by span name (e.g. openclaw.agent.turn, openclaw.tool.execution)."""
    rows = _load_filtered_rows(since, host, agent, room)
    _print_groupby(f"Spans by name (since {since})", rows, lambda r, _a: r["name"], limit)


@app.command("by-tool")
def by_tool(
    since: str = SinceOpt,
    host: str | None = HostOpt,
    agent: str | None = AgentOpt,
    room: str | None = RoomOpt,
    limit: int = LimitOpt,
) -> None:
    """Group tool-call spans by tool name."""
    rows = _load_filtered_rows(since, host, agent, room)
    rows = [
        r
        for r in rows
        if (a := _parse_attrs(r["attributes"]))
        and (a.get("openclaw.toolName") or a.get("gen_ai.tool.name"))
    ]

    def key(_r, attrs: dict) -> str:
        return _attr_first(attrs, "openclaw.toolName", "gen_ai.tool.name", default="-")

    _print_groupby(f"Tool-call spans (since {since})", rows, key, limit)


# These spans come from OpenClaw's built-in CPU/event-loop watchdogs. They
# fire on a fixed schedule from the gateway itself (not from any agent
# turn) and dominate "errors" / "slow" listings if not excluded. Pass
# --all to include them.
_INFRA_SPAN_NAMES: set[str] = {
    "openclaw.diagnostic.phase",
    "openclaw.liveness.warning",
}


def _drop_infra_spans(rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
    return [r for r in rows if r["name"] not in _INFRA_SPAN_NAMES]


AllOpt = typer.Option(
    False,
    "--all",
    help=(
        "Include infrastructure spans (openclaw.diagnostic.phase /"
        " openclaw.liveness.warning) that fire on a timer from the gateway."
    ),
)


@app.command("errors")
def errors(
    since: str = SinceOpt,
    host: str | None = HostOpt,
    agent: str | None = AgentOpt,
    room: str | None = RoomOpt,
    limit: int = LimitOpt,
    include_all: bool = AllOpt,
) -> None:
    """Show spans with status=error in the window."""
    rows = _load_filtered_rows(since, host, agent, room, status="error")
    if not include_all:
        rows = _drop_infra_spans(rows)
    if not rows:
        typer.secho(f"No error spans (since {since}).", fg=typer.colors.GREEN)
        return
    table = Table(title=f"Error spans (since {since})")
    table.add_column("Time")
    table.add_column("Host")
    table.add_column("Agent")
    table.add_column("Name")
    table.add_column("Dur ms", justify="right")
    table.add_column("Message", overflow="fold")
    for r in rows[:limit]:
        a = _parse_attrs(r["attributes"])
        table.add_row(
            _fmt_time(r["start_time"]),
            r["host"] or "-",
            _truncate(_agent_of(a), 18),
            _truncate(r["name"], 32),
            f"{(r['duration_ms'] or 0):.0f}",
            _truncate(r["status_message"] or "-", 80),
        )
    console.print(table)


@app.command("slow")
def slow(
    since: str = SinceOpt,
    host: str | None = HostOpt,
    agent: str | None = AgentOpt,
    room: str | None = RoomOpt,
    name: str | None = NameOpt,
    limit: int = LimitOpt,
    include_all: bool = AllOpt,
) -> None:
    """Show the slowest spans in the window."""
    rows = _load_filtered_rows(since, host, agent, room, name=name)
    if not include_all:
        rows = _drop_infra_spans(rows)
    rows.sort(key=lambda r: float(r["duration_ms"] or 0), reverse=True)
    table = Table(title=f"Slowest spans (since {since})")
    table.add_column("Dur ms", justify="right")
    table.add_column("Time")
    table.add_column("Host")
    table.add_column("Agent")
    table.add_column("Name")
    table.add_column("Model")
    table.add_column("Room", overflow="fold")
    for r in rows[:limit]:
        a = _parse_attrs(r["attributes"])
        _, _, rid = _split_conversation(_conversation_of(a))
        table.add_row(
            f"{(r['duration_ms'] or 0):.0f}",
            _fmt_time(r["start_time"]),
            r["host"] or "-",
            _truncate(_agent_of(a), 18),
            _truncate(r["name"], 28),
            _truncate(_model_of(a), 30),
            _truncate(rid, 36),
        )
    console.print(table)


@app.command("list")
def list_spans(
    since: str = SinceOpt,
    host: str | None = HostOpt,
    agent: str | None = AgentOpt,
    room: str | None = RoomOpt,
    name: str | None = NameOpt,
    status: str | None = StatusOpt,
    limit: int = LimitOpt,
) -> None:
    """List recent spans (newest first), with the most useful columns inline."""
    rows = _load_filtered_rows(since, host, agent, room, name=name, status=status)
    table = Table(title=f"Recent spans (since {since})")
    table.add_column("Time")
    table.add_column("Host")
    table.add_column("Agent")
    table.add_column("Name")
    table.add_column("Dur ms", justify="right")
    table.add_column("Status")
    table.add_column("Tokens", justify="right")
    table.add_column("Room", overflow="fold")
    for r in rows[:limit]:
        a = _parse_attrs(r["attributes"])
        toks_in = int(a.get("gen_ai.usage.input_tokens") or 0)
        toks_out = int(a.get("gen_ai.usage.output_tokens") or 0)
        toks = f"{toks_in:,}/{toks_out:,}" if toks_in or toks_out else "-"
        st = r["status"] or "unset"
        if st == "error":
            st = f"[red]{st}[/red]"
        _, _, rid = _split_conversation(_conversation_of(a))
        table.add_row(
            _fmt_time(r["start_time"]),
            r["host"] or "-",
            _truncate(_agent_of(a), 18),
            _truncate(r["name"], 30),
            f"{(r['duration_ms'] or 0):.0f}",
            st,
            toks,
            _truncate(rid, 36),
        )
    console.print(table)


def _walk_trace(
    spans_by_id: dict[str, sqlite3.Row],
    children: dict[str, list[str]],
    span_id: str,
    depth: int,
    out: list[tuple[int, sqlite3.Row]],
) -> None:
    row = spans_by_id.get(span_id)
    if row is None:
        return
    out.append((depth, row))
    for child in sorted(
        children.get(span_id, []),
        key=lambda sid: spans_by_id[sid]["start_time"],
    ):
        _walk_trace(spans_by_id, children, child, depth + 1, out)


@app.command("show")
def show_trace(
    trace_or_span: str = typer.Argument(
        ..., help="Trace id or span id (any span in the trace works)."
    ),
) -> None:
    """Render a single trace as a tree, parent → children, ordered by time."""
    with _open_db() as conn:
        # Resolve to a trace_id whether the user gave a trace_id or a span_id.
        row = conn.execute(
            "SELECT trace_id FROM spans WHERE trace_id = ? OR span_id = ? LIMIT 1;",
            (trace_or_span, trace_or_span),
        ).fetchone()
        if row is None:
            typer.secho(f"✗ No spans found for {trace_or_span!r}.", fg=typer.colors.RED)
            raise typer.Exit(1)
        trace_id = row["trace_id"]
        spans = conn.execute(
            "SELECT * FROM spans WHERE trace_id = ? ORDER BY start_time;",
            (trace_id,),
        ).fetchall()

    spans_by_id = {s["span_id"]: s for s in spans}
    children: dict[str, list[str]] = {}
    roots: list[str] = []
    for s in spans:
        parent = s["parent_span_id"] or ""
        if parent and parent in spans_by_id:
            children.setdefault(parent, []).append(s["span_id"])
        else:
            roots.append(s["span_id"])

    ordered: list[tuple[int, sqlite3.Row]] = []
    for root in sorted(roots, key=lambda sid: spans_by_id[sid]["start_time"]):
        _walk_trace(spans_by_id, children, root, 0, ordered)

    table = Table(title=f"Trace {trace_id}  ({len(spans)} spans)")
    table.add_column("Span")
    table.add_column("Host")
    table.add_column("Agent")
    table.add_column("Dur ms", justify="right")
    table.add_column("Status")
    table.add_column("Notes", overflow="fold")
    for depth, s in ordered:
        a = _parse_attrs(s["attributes"])
        notes = []
        if (m := _model_of(a)) != "-":
            notes.append(f"model={_truncate(m, 40)}")
        toks_in = int(a.get("gen_ai.usage.input_tokens") or 0)
        toks_out = int(a.get("gen_ai.usage.output_tokens") or 0)
        if toks_in or toks_out:
            notes.append(f"tok={toks_in}/{toks_out}")
        if (tn := _attr_first(a, "openclaw.toolName", "gen_ai.tool.name")):
            notes.append(f"tool={tn}")
        if (oc := _attr_first(a, "openclaw.outcome")):
            notes.append(f"outcome={oc}")
        if (xc := a.get("openclaw.exec.exit_code")) is not None:
            notes.append(f"exit={xc}")
        st = s["status"] or "unset"
        if st == "error":
            st = f"[red]{st}[/red]"
            if s["status_message"]:
                notes.append(f"err={_truncate(s['status_message'], 80)}")
        prefix = ("  " * depth) + ("└─ " if depth else "")
        table.add_row(
            prefix + _truncate(s["name"], 40),
            s["host"] or "-",
            _truncate(_agent_of(a), 18),
            f"{(s['duration_ms'] or 0):.0f}",
            st,
            ", ".join(notes) or "-",
        )
    console.print(table)


@app.command("show-attrs")
def show_attrs(
    span_id: str = typer.Argument(..., help="Exact span id."),
) -> None:
    """Dump the full attribute JSON for a single span."""
    with _open_db() as conn:
        row = conn.execute(
            "SELECT * FROM spans WHERE span_id = ?;", (span_id,)
        ).fetchone()
    if row is None:
        typer.secho(f"✗ No span with id {span_id!r}.", fg=typer.colors.RED)
        raise typer.Exit(1)
    out = {
        "trace_id": row["trace_id"],
        "span_id": row["span_id"],
        "parent_span_id": row["parent_span_id"],
        "name": row["name"],
        "kind": row["kind"],
        "service": row["service"],
        "host": row["host"],
        "start_time": row["start_time"],
        "duration_ms": row["duration_ms"],
        "status": row["status"],
        "status_message": row["status_message"],
        "attributes": _parse_attrs(row["attributes"]),
    }
    typer.echo(json.dumps(out, indent=2))


@app.command("rooms")
def rooms_overview(
    since: str = SinceOpt,
    host: str | None = HostOpt,
) -> None:
    """List active rooms with span counts and participating agents."""
    rows = _load_filtered_rows(since, host, None, None)
    by_room: dict[str, dict] = {}
    for r in rows:
        a = _parse_attrs(r["attributes"])
        agent_id, chan_kind, rid = _split_conversation(_conversation_of(a))
        if rid == "-":
            continue
        e = by_room.setdefault(
            rid, {"channel": chan_kind, "spans": 0, "agents": set(), "hosts": set()}
        )
        e["spans"] += 1
        if agent_id != "-":
            e["agents"].add(agent_id)
        if r["host"]:
            e["hosts"].add(r["host"])

    if not by_room:
        typer.secho(f"No rooms in window (since {since}).", fg=typer.colors.YELLOW)
        return
    table = Table(title=f"Rooms (since {since})")
    table.add_column("Channel")
    table.add_column("Room", overflow="fold")
    table.add_column("Spans", justify="right")
    table.add_column("Agents")
    table.add_column("Hosts")
    for rid, info in sorted(by_room.items(), key=lambda kv: -kv[1]["spans"]):
        table.add_row(
            info["channel"],
            _truncate(rid, 50),
            str(info["spans"]),
            ", ".join(sorted(info["agents"])) or "-",
            ", ".join(sorted(info["hosts"])) or "-",
        )
    console.print(table)


@app.command("agents")
def agents_overview(
    since: str = SinceOpt,
    host: str | None = HostOpt,
) -> None:
    """List active agents with span counts, hosts, and rooms."""
    rows = _load_filtered_rows(since, host, None, None)
    by_agent: dict[str, dict] = {}
    for r in rows:
        a = _parse_attrs(r["attributes"])
        agent_id = _agent_of(a)
        if agent_id == "-":
            continue
        e = by_agent.setdefault(
            agent_id,
            {
                "spans": 0,
                "errors": 0,
                "hosts": set(),
                "rooms": set(),
                "models": set(),
                "tokens_in": 0,
                "tokens_out": 0,
            },
        )
        e["spans"] += 1
        if (r["status"] or "").lower() == "error":
            e["errors"] += 1
        if r["host"]:
            e["hosts"].add(r["host"])
        _, _, rid = _split_conversation(_conversation_of(a))
        if rid != "-":
            e["rooms"].add(rid)
        m = _model_of(a)
        if m != "-":
            e["models"].add(m)
        e["tokens_in"] += int(a.get("gen_ai.usage.input_tokens") or 0)
        e["tokens_out"] += int(a.get("gen_ai.usage.output_tokens") or 0)

    if not by_agent:
        typer.secho(f"No agents in window (since {since}).", fg=typer.colors.YELLOW)
        return
    table = Table(title=f"Agents (since {since})")
    table.add_column("Agent")
    table.add_column("Spans", justify="right")
    table.add_column("Errors", justify="right")
    table.add_column("Hosts")
    table.add_column("Rooms", justify="right")
    table.add_column("Models", overflow="fold")
    table.add_column("Tokens in/out", justify="right")
    for agent_id, info in sorted(by_agent.items(), key=lambda kv: -kv[1]["spans"]):
        err_cell = (
            f"[red]{info['errors']}[/red]" if info["errors"] else "0"
        )
        table.add_row(
            agent_id,
            str(info["spans"]),
            err_cell,
            ", ".join(sorted(info["hosts"])) or "-",
            str(len(info["rooms"])),
            _truncate(", ".join(sorted(info["models"])), 50) or "-",
            f"{info['tokens_in']:,}/{info['tokens_out']:,}",
        )
    console.print(table)


@app.command("schema")
def schema() -> None:
    """Print the spans table schema and the most common attribute keys.

    Useful when you want to write your own ad-hoc SQL or pivot.
    """
    db_path = _traces_db_path()
    typer.secho(f"DB: {db_path}", bold=True)
    with _open_db() as conn:
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='spans';"
        ).fetchone()
        if sql:
            typer.echo("")
            typer.echo(sql[0])
        rows = conn.execute(
            "SELECT attributes FROM spans WHERE created_at > datetime('now','-1 hour') LIMIT 5000;"
        ).fetchall()
    counts: Counter = Counter()
    for r in rows:
        for k in _parse_attrs(r["attributes"]):
            counts[k] += 1
    typer.echo("")
    typer.secho(
        f"Top attribute keys (last hour, sample of {len(rows)} spans):", bold=True
    )
    for k, n in counts.most_common(40):
        typer.echo(f"  {n:5d}  {k}")
