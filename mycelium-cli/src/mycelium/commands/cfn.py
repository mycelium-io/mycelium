# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
CFN observability commands — see what mycelium-backend is forwarding to
CFN's shared-memories knowledge graph, and the input-side token cost of
doing so.

Backed by the in-memory ingest log buffer on mycelium-backend. The buffer
resets on backend restart, so these numbers are process-lifetime, not
durable metrics. For the durable record, see the ``audit_events`` table.
"""

from datetime import UTC, datetime
from typing import Any

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


def _state_cell(event: dict[str, Any]) -> str:
    state = event.get("state") or "ok"
    style = _STATE_STYLES.get(state, "white")
    return f"[{style}]{state}[/{style}]"


def _fmt_tokens(n: int) -> str:
    if n < 1000:
        return f"~{n}"
    if n < 1_000_000:
        return f"~{n / 1000:.1f}k"
    return f"~{n / 1_000_000:.2f}M"


@doc_ref(
    usage="mycelium cfn log [--limit N] [--state <s>] [--json] [--verbose]",
    desc=(
        "Tail the mycelium-backend in-memory log of CFN shared-memories forwards. "
        "Captures every attempt (ok, deduped, truncated, refused, disabled, error); "
        "token counts are cl100k_base estimates."
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
            "Repeat with comma-separated values to match multiple."
        ),
    ),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON response"),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show request_id, reason, and CFN message columns",
    ),
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
            console.print(
                f"[dim]No events matching state=[{','.join(sorted(state_filter))}].[/dim]",
            )
        else:
            console.print("[dim]No CFN ingest events in the buffer yet.[/dim]")
        console.print(f"[dim]Buffer started at {data.get('buffer_started_at', '?')}.[/dim]")
        return

    title = f"CFN ingest log — {len(events)} shown of {total} in buffer"
    if state_filter is not None:
        title += f" (state={','.join(sorted(state_filter))})"

    table = Table(title=title, title_style="bold")
    table.add_column("Time", style="dim")
    table.add_column("MAS")
    table.add_column("Agent")
    table.add_column("Records", justify="right")
    table.add_column("Tokens", justify="right")
    table.add_column("Latency", justify="right")
    table.add_column("State")
    if verbose:
        table.add_column("Request ID", style="dim")
        table.add_column("Reason / CFN message", style="dim", overflow="fold")

    for e in events:
        row = [
            _relative(e["timestamp"]),
            e.get("mas_id", "?"),
            e.get("agent_id") or "-",
            str(e.get("record_count", 0)),
            _fmt_tokens(e.get("estimated_cfn_knowledge_input_tokens", 0)),
            f"{e.get('latency_ms', 0):.0f}ms",
            _state_cell(e),
        ]
        if verbose:
            rid = e.get("request_id", "")
            row.append(rid[:8] if rid else "-")
            row.append(e.get("reason") or e.get("cfn_message") or "-")
        table.add_row(*row)

    console.print(table)
    console.print(_TOKEN_CAVEAT)
    console.print(
        "[dim]States: [green]ok[/green] forwarded · [dim cyan]deduped[/dim cyan] "
        "hash match · [yellow]truncated[/yellow] content capped · "
        "[bold red]refused[/bold red] circuit breaker · [dim]disabled[/dim] "
        "kill switch · [red]error[/red] CFN unreachable / non-2xx[/dim]",
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
