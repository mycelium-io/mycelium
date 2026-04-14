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


def _status_cell(event: dict[str, Any]) -> str:
    if event.get("error"):
        code = event.get("cfn_status")
        label = f"err {code}" if code else "unreachable"
        return f"[red]{label}[/red]"
    code = event.get("cfn_status", 201)
    return f"[green]{code}[/green]"


def _fmt_tokens(n: int) -> str:
    if n < 1000:
        return f"~{n}"
    if n < 1_000_000:
        return f"~{n / 1000:.1f}k"
    return f"~{n / 1_000_000:.2f}M"


@doc_ref(
    usage="mycelium cfn log [--limit N] [--json] [--verbose]",
    desc=(
        "Tail the mycelium-backend in-memory log of CFN shared-memories forwards. "
        "Captures both successes and failures; token counts are cl100k_base estimates."
    ),
    group="cfn",
)
@app.command(name="log")
def cfn_log(
    limit: int = typer.Option(20, "--limit", "-n", min=1, max=500, help="Max events to show"),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON response"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show full event record including request_id and CFN message"),
) -> None:
    """Tail the recent CFN shared-memories forwards from mycelium-backend.

    Newest first. Resets on backend restart.
    """
    try:
        with httpx.Client(base_url=_api_url(), timeout=10) as client:
            resp = client.get("/api/knowledge/ingest/log", params={"limit": limit})
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        console.print(f"[red]Failed to reach mycelium-backend:[/red] {exc}")
        raise typer.Exit(1) from exc

    if json_output:
        console.print_json(data=data)
        return

    events = data.get("events", [])
    total = data.get("total_events", 0)

    if not events:
        console.print("[dim]No CFN ingest events in the buffer yet.[/dim]")
        console.print(f"[dim]Buffer started at {data.get('buffer_started_at', '?')}.[/dim]")
        return

    table = Table(
        title=f"CFN ingest log — {len(events)} shown of {total} in buffer",
        title_style="bold",
    )
    table.add_column("Time", style="dim")
    table.add_column("MAS")
    table.add_column("Agent")
    table.add_column("Records", justify="right")
    table.add_column("Tokens", justify="right")
    table.add_column("Latency", justify="right")
    table.add_column("Status")
    if verbose:
        table.add_column("Request ID", style="dim")
        table.add_column("Message", style="dim", overflow="fold")

    for e in events:
        row = [
            _relative(e["timestamp"]),
            e.get("mas_id", "?"),
            e.get("agent_id") or "-",
            str(e.get("record_count", 0)),
            _fmt_tokens(e.get("estimated_cfn_knowledge_input_tokens", 0)),
            f"{e.get('latency_ms', 0):.0f}ms",
            _status_cell(e),
        ]
        if verbose:
            rid = e.get("request_id", "")
            row.append(rid[:8] if rid else "-")
            row.append(e.get("error") or e.get("cfn_message") or "-")
        table.add_row(*row)

    console.print(table)
    console.print(_TOKEN_CAVEAT)


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
