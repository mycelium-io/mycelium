# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cisco Systems, Inc. and its affiliates

"""
CFN observability commands — see what mycelium-backend is forwarding to
CFN's shared-memories knowledge graph, and the input-side token cost of
doing so.

Backed by the in-memory ingest log buffer on mycelium-backend. The buffer
resets on backend restart, so these numbers are process-lifetime, not
durable metrics. For the durable record, see the ``audit_events`` table.
"""

from datetime import UTC, datetime

import httpx
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref

app = typer.Typer(
    help=(
        "Inspect CFN shared-memories forwards from mycelium-backend. "
        "Token counts are cl100k_base estimates of the JSON payload sent "
        "to CFN — an input-side cost-awareness proxy, not a billing figure. "
        "CFN's actual LLM consumption (system prompts, two-stage extraction, "
        "embeddings) is typically higher."
    ),
    no_args_is_help=True,
)
console = Console()


_TOKEN_CAVEAT = (
    "[dim]~ = estimated cl100k_base tokens in the JSON payload sent to CFN. "
    "CFN's actual LLM consumption is typically higher.[/dim]"
)


def _api_url() -> str:
    return MyceliumConfig.load().server.api_url


def _relative(ts_iso: str) -> str:
    """Render a relative timestamp like '2m ago' or '37s ago'."""
    try:
        ts = datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
    except ValueError:
        return ts_iso
    now = datetime.now(UTC)
    delta = now - ts
    secs = int(delta.total_seconds())
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


_STATE_STYLES: dict[str, str] = {
    "ok": "green",
    "deduped": "dim cyan",
    "truncated": "yellow",
    "refused": "bold red",
    "disabled": "dim",
    "error": "red",
}

_VALID_STATES = tuple(_STATE_STYLES.keys())


def _fmt_tokens(n: int) -> str:
    if n < 1000:
        return f"~{n}"
    if n < 1_000_000:
        return f"~{n / 1000:.1f}k"
    return f"~{n / 1_000_000:.2f}M"


@doc_ref(
    usage="mycelium cfn log [--limit N] [--state <s>] [--json]",
    desc=(
        "Tail the mycelium-backend in-memory log of CFN shared-memories forwards. "
        "Plain columnar output, one line per event, newest first. Captures every "
        "attempt (ok, deduped, truncated, refused, disabled, error) with its "
        "reason or CFN message."
    ),
    group="cfn",
)
@app.command(name="log")
def cfn_log(
    limit: int = typer.Option(20, "--limit", "-n", min=1, max=500, help="Max events to show"),
    state: str | None = typer.Option(
        None,
        "--state",
        "-s",
        help=(
            "Filter by event state: ok, deduped, truncated, refused, disabled, error. "
            "Comma-separate to match multiple."
        ),
    ),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON response"),
) -> None:
    """Tail recent CFN shared-memories forwards from mycelium-backend.

    Newest first. Resets on backend restart.
    """
    state_filter: set[str] | None = None
    if state:
        state_filter = {s.strip() for s in state.split(",") if s.strip()}
        unknown = state_filter - set(_VALID_STATES)
        if unknown:
            console.print(
                f"[red]Unknown state(s):[/red] {', '.join(sorted(unknown))}. "
                f"Valid: {', '.join(_VALID_STATES)}",
            )
            raise typer.Exit(2)

    try:
        with httpx.Client(base_url=_api_url(), timeout=10) as client:
            resp = client.get("/api/knowledge/ingest/log", params={"limit": limit})
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        console.print(f"[red]Failed to reach mycelium-backend:[/red] {exc}")
        raise typer.Exit(1) from exc

    events = data.get("events", [])
    total = data.get("total_events", 0)

    if state_filter is not None:
        events = [e for e in events if (e.get("state") or "ok") in state_filter]

    if json_output:
        if state_filter is not None:
            data = {**data, "events": events, "filtered_by_state": sorted(state_filter)}
        console.print_json(data=data)
        return

    if not events:
        if state_filter is not None:
            wanted = ",".join(sorted(state_filter))
            console.print(f"[dim]No events matching state={wanted!r}.[/dim]")
        else:
            console.print("[dim]No CFN ingest events in the buffer yet.[/dim]")
        console.print(f"[dim]Buffer started at {data.get('buffer_started_at', '?')}.[/dim]")
        return

    # Precompute display strings so we can size columns from data.
    rows: list[dict[str, str]] = []
    for e in events:
        state_name = e.get("state") or "ok"
        rows.append(
            {
                "time": _relative(e["timestamp"]),
                "state": state_name,
                "mas": e.get("mas_id", "?"),
                "agent": e.get("agent_id") or "-",
                "recs": str(e.get("record_count", 0)),
                "tokens": _fmt_tokens(e.get("estimated_cfn_knowledge_input_tokens", 0)),
                "latency": f"{e.get('latency_ms', 0):.0f}ms",
                "reason": (e.get("reason") or e.get("cfn_message") or "").strip(),
            },
        )

    headers = {
        "time": "TIME",
        "state": "STATE",
        "mas": "MAS",
        "agent": "AGENT",
        "recs": "RECS",
        "tokens": "TOKENS",
        "latency": "LATENCY",
        "reason": "REASON / MESSAGE",
    }

    widths = {key: max(len(headers[key]), *(len(r[key]) for r in rows)) for key in headers}

    def _fmt_row(values: dict[str, str], *, header: bool = False) -> str:
        state_name = values["state"]
        if header:
            state_cell = f"{values['state']:<{widths['state']}}"
        else:
            style = _STATE_STYLES.get(state_name, "white")
            padded = f"{state_name:<{widths['state']}}"
            state_cell = f"[{style}]{padded}[/{style}]"
        recs_cell = f"{values['recs']:>{widths['recs']}}"
        tokens_cell = f"{values['tokens']:>{widths['tokens']}}"
        latency_cell = f"{values['latency']:>{widths['latency']}}"
        return (
            f"{values['time']:<{widths['time']}}  "
            f"{state_cell}  "
            f"{values['mas']:<{widths['mas']}}  "
            f"{values['agent']:<{widths['agent']}}  "
            f"{recs_cell}  "
            f"{tokens_cell}  "
            f"{latency_cell}  "
            f"{values['reason']}"
        )

    header_line = _fmt_row(headers, header=True)

    console.print(f"[bold dim]{header_line}[/bold dim]", soft_wrap=True)
    for r in rows:
        console.print(_fmt_row(r), soft_wrap=True)

    filter_note = f" (state={','.join(sorted(state_filter))})" if state_filter is not None else ""
    console.print(
        f"[dim]{len(events)} shown of {total} in buffer{filter_note} · "
        "~ tokens are cl100k_base estimates of the JSON sent to CFN, "
        "not CFN's actual LLM spend[/dim]",
        soft_wrap=True,
    )


@doc_ref(
    usage="mycelium cfn stats [--json]",
    desc=(
        "Aggregate CFN shared-memories forwards grouped by MAS and agent, "
        "with rolling last-hour window."
    ),
    group="cfn",
)
@app.command(name="stats")
def cfn_stats(
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON response"),
) -> None:
    """Show aggregate CFN shared-memories activity from the mycelium-backend buffer."""
    try:
        with httpx.Client(base_url=_api_url(), timeout=10) as client:
            resp = client.get("/api/knowledge/ingest/stats")
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        console.print(f"[red]Failed to reach mycelium-backend:[/red] {exc}")
        raise typer.Exit(1) from exc

    if json_output:
        console.print_json(data=data)
        return

    total = data.get("total", {})
    last_hour = data.get("last_hour", {})
    by_mas = data.get("by_mas", {}) or {}
    by_agent = data.get("by_agent", {}) or {}

    header_lines = [
        f"[bold]Buffer started:[/bold] {data.get('buffer_started_at', '?')}",
    ]
    last_event_at = data.get("last_event_at")
    if last_event_at:
        header_lines.append(
            f"[bold]Last event:[/bold] {last_event_at} ({_relative(last_event_at)})",
        )
    else:
        header_lines.append("[bold]Last event:[/bold] [dim]none yet[/dim]")

    console.print(Panel("\n".join(header_lines), title="CFN ingest buffer", expand=False))

    totals_table = Table(show_header=True, header_style="bold")
    totals_table.add_column("Window")
    totals_table.add_column("Events", justify="right")
    totals_table.add_column("Est. input tokens", justify="right")
    totals_table.add_column("Payload bytes", justify="right")
    totals_table.add_row(
        "Since buffer start",
        str(total.get("events", 0)),
        _fmt_tokens(total.get("estimated_cfn_knowledge_input_tokens", 0)),
        f"{total.get('payload_bytes', 0):,}",
    )
    totals_table.add_row(
        "Last hour",
        str(last_hour.get("events", 0)),
        _fmt_tokens(last_hour.get("estimated_cfn_knowledge_input_tokens", 0)),
        f"{last_hour.get('payload_bytes', 0):,}",
    )
    console.print(totals_table)

    if by_mas:
        mas_table = Table(title="By MAS", show_header=True, header_style="bold")
        mas_table.add_column("MAS")
        mas_table.add_column("Events", justify="right")
        mas_table.add_column("Est. input tokens", justify="right")
        ranked = sorted(
            by_mas.items(),
            key=lambda kv: kv[1].get("estimated_cfn_knowledge_input_tokens", 0),
            reverse=True,
        )
        for mas_id, agg in ranked[:10]:
            mas_table.add_row(
                mas_id,
                str(agg.get("events", 0)),
                _fmt_tokens(agg.get("estimated_cfn_knowledge_input_tokens", 0)),
            )
        console.print(mas_table)

    if by_agent:
        agent_table = Table(title="By agent", show_header=True, header_style="bold")
        agent_table.add_column("Agent")
        agent_table.add_column("Events", justify="right")
        agent_table.add_column("Est. input tokens", justify="right")
        ranked = sorted(
            by_agent.items(),
            key=lambda kv: kv[1].get("estimated_cfn_knowledge_input_tokens", 0),
            reverse=True,
        )
        for agent_id, agg in ranked[:10]:
            agent_table.add_row(
                agent_id,
                str(agg.get("events", 0)),
                _fmt_tokens(agg.get("estimated_cfn_knowledge_input_tokens", 0)),
            )
        console.print(agent_table)

    console.print(_TOKEN_CAVEAT)


# ── CFN shared-memories read surface ──────────────────────────────────────────
#
# These four subcommands hit the cfn_read_router backend routes from C5,
# which proxy to CFN's shared-memories/query and graph/{concepts,neighbors,paths}.
# The graph routes are flagged include_in_schema=False upstream, so their
# response shapes may drift — print raw dict fields when rendering.


def _default_workspace() -> str | None:
    cfg = MyceliumConfig.load()
    return cfg.server.workspace_id or cfg.runtime.workspace_id or None


def _default_mas() -> str | None:
    cfg = MyceliumConfig.load()
    return cfg.server.mas_id or None


def _cfn_request(method: str, path: str, **kwargs) -> dict:
    """Hit a mycelium-backend route, exit(1) with a clear error on failure."""
    try:
        with httpx.Client(base_url=_api_url(), timeout=300) as client:
            resp = client.request(method, path, **kwargs)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as exc:
        detail = ""
        try:
            detail = exc.response.json().get("detail", "")
        except Exception:  # noqa: BLE001
            detail = exc.response.text[:300]
        console.print(f"[red]backend returned {exc.response.status_code}:[/red] {detail}")
        raise typer.Exit(1) from exc
    except httpx.HTTPError as exc:
        console.print(f"[red]Failed to reach mycelium-backend:[/red] {exc}")
        raise typer.Exit(1) from exc


@doc_ref(
    usage="mycelium cfn query <intent> [--mas <mas-id>] [--workspace <ws>]",
    desc=(
        "Ask CFN's evidence agent a natural-language question about the "
        "shared knowledge graph. Returns a synthesized answer, not a record list."
    ),
    group="cfn",
)
@app.command(name="query")
def cfn_query(
    intent: str = typer.Argument(..., help="Natural-language question to ask CFN"),
    mas_id: str | None = typer.Option(None, "--mas", "-m", help="MAS ID (defaults to config)"),
    workspace: str | None = typer.Option(
        None,
        "--workspace",
        "-w",
        help="Workspace ID (defaults to config)",
    ),
    agent_id: str | None = typer.Option(
        None,
        "--agent",
        "-a",
        help="Optional agent handle for request attribution",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON response"),
) -> None:
    """Semantic-graph query against CFN's shared memory.

    Note: CFN's evidence agent returns HTTP 404 when it can't synthesize an
    answer from the graph (their convention for "insufficient evidence", not
    "graph missing"). This command renders that as a "no evidence" message,
    not a hard error.
    """
    resolved_mas = mas_id or _default_mas()
    body: dict = {"intent": intent}
    if resolved_mas:
        body["mas_id"] = resolved_mas
    if workspace or _default_workspace():
        body["workspace_id"] = workspace or _default_workspace()
    if agent_id:
        body["agent_id"] = agent_id

    # Catch 404 directly so we can render "insufficient evidence" as an
    # empty-but-OK outcome rather than an error. Any other non-2xx still
    # goes through _cfn_request's error handler.
    try:
        with httpx.Client(base_url=_api_url(), timeout=300) as client:
            resp = client.post("/api/cfn/knowledge/query", json=body)
    except httpx.HTTPError as exc:
        console.print(f"[red]Failed to reach mycelium-backend:[/red] {exc}")
        raise typer.Exit(1) from exc

    if resp.status_code == 404:
        detail = ""
        try:
            detail = resp.json().get("detail", "")
        except Exception:  # noqa: BLE001
            detail = resp.text[:300]
        if json_output:
            console.print_json(
                data={
                    "response_id": None,
                    "message": None,
                    "status": "no_evidence",
                    "detail": detail,
                }
            )
            return
        console.print(
            "[yellow]no evidence[/yellow] [dim]— CFN couldn't synthesize an "
            "answer from the graph for this intent[/dim]",
        )
        if detail:
            console.print(f"[dim]{detail}[/dim]")
        return

    if resp.status_code >= 400:
        detail = ""
        try:
            detail = resp.json().get("detail", "")
        except Exception:  # noqa: BLE001
            detail = resp.text[:300]
        console.print(f"[red]backend returned {resp.status_code}:[/red] {detail}")
        raise typer.Exit(1)

    data = resp.json()
    if json_output:
        console.print_json(data=data)
        return

    message = data.get("message") or "(no message)"
    rid = data.get("response_id", "")
    console.print(f"[bold]CFN:[/bold] {message}")
    if rid:
        console.print(f"[dim]response_id: {rid}[/dim]")


@doc_ref(
    usage="mycelium cfn concepts <id>[,<id>,...] [--mas <mas-id>]",
    desc="Fetch specific CFN concept records by ID.",
    group="cfn",
)
@app.command(name="concepts")
def cfn_concepts(
    ids: str = typer.Argument(..., help="Comma-separated concept IDs"),
    mas_id: str | None = typer.Option(None, "--mas", "-m", help="MAS ID (defaults to config)"),
    workspace: str | None = typer.Option(
        None,
        "--workspace",
        "-w",
        help="Workspace ID (defaults to config)",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON response"),
) -> None:
    """Fetch CFN concept records by ID."""
    id_list = [s.strip() for s in ids.split(",") if s.strip()]
    if not id_list:
        console.print("[red]no concept IDs provided[/red]")
        raise typer.Exit(2)

    resolved_mas = mas_id or _default_mas()
    body: dict = {"ids": id_list}
    if resolved_mas:
        body["mas_id"] = resolved_mas
    if workspace or _default_workspace():
        body["workspace_id"] = workspace or _default_workspace()

    data = _cfn_request("POST", "/api/cfn/knowledge/concepts", json=body)

    if json_output:
        console.print_json(data=data)
        return

    records = data.get("records", []) or []
    if not records:
        console.print("[dim]no matching concepts[/dim]")
        return

    for i, rec in enumerate(records):
        concepts = rec.get("concepts", []) or []
        rels = rec.get("relationships", []) or []
        console.print(f"[bold]record {i}[/bold]: {len(concepts)} concepts, {len(rels)} relations")
        for c in concepts:
            cid = c.get("id", "?")
            name = c.get("name", "")
            console.print(f"  • [cyan]{cid[:12]}[/cyan]  {name}")


@doc_ref(
    usage="mycelium cfn neighbors <concept-id> [--mas <mas-id>]",
    desc="Show CFN graph neighbors for a concept.",
    group="cfn",
)
@app.command(name="neighbors")
def cfn_neighbors(
    concept_id: str = typer.Argument(..., help="Concept ID to look up neighbors for"),
    mas_id: str | None = typer.Option(None, "--mas", "-m", help="MAS ID (defaults to config)"),
    workspace: str | None = typer.Option(
        None,
        "--workspace",
        "-w",
        help="Workspace ID (defaults to config)",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON response"),
) -> None:
    """Show CFN graph neighbors for a concept."""
    resolved_mas = mas_id or _default_mas()
    params: dict = {}
    if resolved_mas:
        params["mas_id"] = resolved_mas
    if workspace or _default_workspace():
        params["workspace_id"] = workspace or _default_workspace()

    data = _cfn_request(
        "GET",
        f"/api/cfn/knowledge/concepts/{concept_id}/neighbors",
        params=params,
    )

    if json_output:
        console.print_json(data=data)
        return

    records = data.get("records", []) or []
    console.print(f"[bold]{len(records)} neighbor record(s) for {concept_id[:12]}[/bold]")
    for i, rec in enumerate(records):
        concepts = rec.get("concepts", []) or []
        rels = rec.get("relationships", []) or []
        for c in concepts:
            cid = c.get("id", "?")
            name = c.get("name", "")
            console.print(f"  {i:>3}  [cyan]{cid[:12]}[/cyan]  {name}")
        for r in rels:
            rel = r.get("relation") or r.get("type", "?")
            nodes = r.get("node_ids", [])
            console.print(f"       [dim]↳ {rel}: {' → '.join(nodes)}[/dim]")


@doc_ref(
    usage="mycelium cfn ls [--mas <mas-id>] [--limit N] [--json]",
    desc=(
        "Enumerate nodes in CFN's knowledge graph by reading AgensGraph "
        "directly. NOT a CFN-supported API — couples to CFN's internal "
        "graph-naming convention (graph_<mas_id>)."
    ),
    group="cfn",
)
@app.command(name="ls")
def cfn_ls(
    mas_id: str | None = typer.Option(None, "--mas", "-m", help="MAS ID (defaults to config)"),
    limit: int = typer.Option(
        50,
        "--limit",
        "-l",
        min=1,
        max=500,
        help="Max nodes to return",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON response"),
) -> None:
    """List nodes in CFN's knowledge graph for a MAS.

    Goes around CFN's HTTP API and queries AgensGraph directly because CFN
    does not expose an enumeration endpoint. Returns empty or 404 if the
    graph doesn't exist (nothing has been ingested yet for that MAS).
    """
    resolved_mas = mas_id or _default_mas()
    params: dict = {"limit": limit}
    if resolved_mas:
        params["mas_id"] = resolved_mas
    data = _cfn_request(
        "GET",
        "/api/cfn/knowledge/list",
        params=params,
    )

    if json_output:
        console.print_json(data=data)
        return

    nodes = data.get("nodes", []) or []
    count = data.get("count", len(nodes))

    display_mas = resolved_mas or data.get("mas_id", "?")
    if not nodes:
        console.print(f"[dim]no nodes in graph for mas={display_mas}[/dim]")
        return

    console.print(f"[bold]{count} node(s) in graph for mas={display_mas}[/bold]")
    for n in nodes:
        label = n.get("label") or "node"
        nid = n.get("id") or ""
        name = n.get("name") or ""
        props = n.get("properties") or {}
        # Extract a short description from common property keys
        desc = props.get("description") or props.get("text") or ""
        short_id = nid[:12] if nid else "?"
        line = f"  [cyan]{short_id}[/cyan]  [magenta]{label:<12}[/magenta]  {name}"
        if desc:
            line += f"  [dim]— {desc[:80]}[/dim]"
        console.print(line, soft_wrap=True)


@doc_ref(
    usage="mycelium cfn paths <source-id> <target-id> [--mas <mas-id>] [--max-depth N] [--limit N]",
    desc="Show CFN graph paths between two concepts.",
    group="cfn",
)
@app.command(name="paths")
def cfn_paths(
    source_id: str = typer.Argument(..., help="Source concept ID"),
    target_id: str = typer.Argument(..., help="Target concept ID"),
    mas_id: str | None = typer.Option(None, "--mas", "-m", help="MAS ID (defaults to config)"),
    workspace: str | None = typer.Option(
        None,
        "--workspace",
        "-w",
        help="Workspace ID (defaults to config)",
    ),
    max_depth: int | None = typer.Option(
        None,
        "--max-depth",
        "-d",
        help="Max path depth to explore",
    ),
    limit: int | None = typer.Option(
        None,
        "--limit",
        "-l",
        help="Max number of paths to return",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON response"),
) -> None:
    """Show CFN graph paths between two concepts."""
    resolved_mas = mas_id or _default_mas()
    body: dict = {"source_id": source_id, "target_id": target_id}
    if resolved_mas:
        body["mas_id"] = resolved_mas
    if workspace or _default_workspace():
        body["workspace_id"] = workspace or _default_workspace()
    if max_depth is not None:
        body["max_depth"] = max_depth
    if limit is not None:
        body["limit"] = limit

    data = _cfn_request("POST", "/api/cfn/knowledge/paths", json=body)

    if json_output:
        console.print_json(data=data)
        return

    paths = data.get("paths", []) or []
    if not paths:
        console.print("[dim]no paths found[/dim]")
        return

    console.print(f"[bold]{len(paths)} path(s)[/bold]")
    for i, p in enumerate(paths):
        console.print(f"  {i:>3}  {p}")
