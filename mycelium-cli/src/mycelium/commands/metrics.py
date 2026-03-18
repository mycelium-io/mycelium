"""
Metrics commands — collect, display, and manage OpenClaw telemetry data.

Provides an OTLP HTTP receiver that aggregates token usage, costs, durations,
and session data from OpenClaw's diagnostics-otel plugin. The `show` command
augments OTLP data with agent metadata from `openclaw status --json` and
workspace file sizes computed at display time.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    help="Collect and display OpenClaw agent metrics (OTLP receiver + display).",
    no_args_is_help=True,
)

_DEFAULT_PORT = 4318
_ENV_PORT = "MYCELIUM_METRICS_PORT"
_MYCELIUM_DIR = Path.home() / ".mycelium"
_METRICS_JSON = _MYCELIUM_DIR / "metrics.json"
_PID_FILE = _MYCELIUM_DIR / "collector.pid"

console = Console()


def _resolve_port(cli_port: int | None) -> int:
    if cli_port is not None:
        return cli_port
    env = os.environ.get(_ENV_PORT)
    if env:
        try:
            return int(env)
        except ValueError:
            pass
    return _DEFAULT_PORT


@app.command("install")
def install_metrics() -> None:
    """Install optional metrics dependencies (opentelemetry-proto, protobuf)."""
    try:
        from opentelemetry.proto.collector.metrics.v1 import metrics_service_pb2  # noqa: F401

        typer.secho("✓ Metrics dependencies already installed.", fg=typer.colors.GREEN)
        return
    except ImportError:
        pass

    typer.echo("Installing metrics dependencies...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "opentelemetry-proto", "protobuf>=4.21.0"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        typer.secho(f"✗ Install failed:\n{result.stderr}", fg=typer.colors.RED)
        raise typer.Exit(1)

    typer.secho("✓ Metrics dependencies installed.", fg=typer.colors.GREEN)


@app.command("collect")
def collect(
    port: int | None = typer.Option(None, "--port", "-p", help=f"OTLP receiver port (default: {_DEFAULT_PORT})"),
    bg: bool = typer.Option(False, "--bg", help="Run collector in the background"),
) -> None:
    """Start the OTLP HTTP receiver to collect OpenClaw telemetry."""
    resolved_port = _resolve_port(port)

    if bg:
        _MYCELIUM_DIR.mkdir(parents=True, exist_ok=True)

        if _PID_FILE.exists():
            try:
                old_pid = int(_PID_FILE.read_text().strip().splitlines()[0])
                os.kill(old_pid, 0)
                typer.secho(
                    f"Collector already running (PID {old_pid}) on port {_get_port()}",
                    fg=typer.colors.YELLOW,
                )
                return
            except (OSError, ValueError):
                _PID_FILE.unlink(missing_ok=True)

        proc = subprocess.Popen(
            [
                sys.executable, "-m", "mycelium.collector_main",
                "--port", str(resolved_port),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        _PID_FILE.write_text(f"{proc.pid}\n{resolved_port}\n")

        typer.secho(f"✓ Collector started (PID {proc.pid})", fg=typer.colors.GREEN)
        typer.echo(f"  OTLP receiver on port {resolved_port}")
        typer.echo(f"  Metrics file: {_METRICS_JSON}")
    else:
        typer.echo(f"Starting OTLP collector on port {resolved_port}...")
        typer.echo("Press Ctrl+C to stop.\n")

        from mycelium.collector import run as run_collector

        run_collector(resolved_port, _METRICS_JSON)


@app.command("stop")
def stop() -> None:
    """Stop the background OTLP collector."""
    if not _PID_FILE.exists():
        typer.secho("No collector running (PID file not found).", fg=typer.colors.YELLOW)
        raise typer.Exit(0)

    try:
        pid = int(_PID_FILE.read_text().strip().splitlines()[0])
        os.kill(pid, signal.SIGTERM)
        typer.secho(f"✓ Collector stopped (PID {pid})", fg=typer.colors.GREEN)
    except (OSError, ValueError) as exc:
        typer.secho(f"Could not stop collector: {exc}", fg=typer.colors.RED)
    finally:
        _PID_FILE.unlink(missing_ok=True)


@app.command("reset")
def reset() -> None:
    """Delete collected metrics data."""
    if _METRICS_JSON.exists():
        _METRICS_JSON.unlink()
        typer.secho("✓ Metrics data cleared.", fg=typer.colors.GREEN)
    else:
        typer.echo("No metrics data to clear.")


@app.command("show")
def show(
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
    workspace: bool = typer.Option(False, "--workspace", help="Show per-file workspace breakdown"),
) -> None:
    """
    Display collected metrics with agent metadata and workspace sizes.

    Combines OTLP data from the collector with live agent inventory from
    `openclaw status --json` and workspace file sizes from the filesystem.
    """
    otel_data = _load_metrics_json()
    oc_status = _get_openclaw_status()

    if otel_data is None and oc_status is None:
        console.print(
            "[yellow]No metrics data available.[/yellow]\n\n"
            "  Start the collector:  [bold]mycelium metrics collect[/bold]\n"
            "  Or with background:   [bold]mycelium metrics collect --bg[/bold]\n\n"
            "  Make sure OpenClaw's diagnostics-otel plugin is configured:\n"
            "    [bold]mycelium adapter add openclaw --step=otel[/bold]"
        )
        raise typer.Exit(0)

    agents_meta = _extract_agents(oc_status)
    oc_sessions = _extract_oc_sessions(oc_status)
    oc_cost = _extract_oc_cost(oc_status)

    if json_output:
        combined = {
            "otel": otel_data or {},
            "openclaw_status": {
                "agents": agents_meta,
                "sessions": oc_sessions,
                "cost": oc_cost,
            },
        }
        console.print_json(json.dumps(combined, default=str))
        return

    _render_summary_table(otel_data, oc_status, oc_cost)
    _render_agent_table(otel_data, agents_meta)

    if otel_data and otel_data.get("sessions"):
        _render_session_table(otel_data["sessions"])

    if workspace:
        _render_workspace_tables(agents_meta)

    _render_field_legend()
    console.print()


def _load_metrics_json() -> dict | None:
    if not _METRICS_JSON.exists():
        return None
    try:
        return json.loads(_METRICS_JSON.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _get_openclaw_status() -> dict | None:
    try:
        result = subprocess.run(
            ["openclaw", "status", "--json"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        pass
    return None


def _extract_agents(oc: dict | None) -> list[dict]:
    if not oc:
        return []
    agents = oc.get("agents", [])
    if isinstance(agents, dict):
        return [{"name": k, **v} for k, v in agents.items()]
    return agents


def _extract_oc_sessions(oc: dict | None) -> list[dict]:
    if not oc:
        return []
    return oc.get("sessions", [])


def _extract_oc_cost(oc: dict | None) -> dict | None:
    if not oc:
        return None
    return oc.get("cost")


def _get_port() -> int:
    """Read actual port from PID file (line 2)."""
    if _PID_FILE.exists():
        try:
            lines = _PID_FILE.read_text().strip().splitlines()
            if len(lines) >= 2:
                return int(lines[1])
        except (ValueError, OSError):
            pass
    return _DEFAULT_PORT


def _fmt_num(n: int | float | None) -> str:
    if n is None:
        return "—"
    if isinstance(n, float):
        return f"{n:,.2f}"
    return f"{n:,}"


def _fmt_cost(n: float | None) -> str:
    if n is None:
        return "—"
    return f"${n:,.4f}"


def _fmt_size(nbytes: int) -> str:
    if nbytes < 1024:
        return f"{nbytes} B"
    if nbytes < 1024 * 1024:
        return f"{nbytes / 1024:.1f} KB"
    return f"{nbytes / (1024 * 1024):.1f} MB"


def _render_summary_table(
    otel: dict | None,
    oc: dict | None,
    oc_cost: dict | None,
) -> None:
    table = Table(title="Overall", title_style="bold cyan", show_header=False, border_style="dim")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")

    counters = (otel or {}).get("counters", {})
    tokens = counters.get("tokens", {}).get("total", {})
    histograms = (otel or {}).get("histograms", {})
    messages = counters.get("messages", {})

    table.add_row("Total tokens", _fmt_num(tokens.get("total", 0)))
    table.add_row("  input", _fmt_num(tokens.get("input", 0)))
    table.add_row("  output", _fmt_num(tokens.get("output", 0)))
    table.add_row("  cache read", _fmt_num(tokens.get("cache_read", 0)))
    table.add_row("  cache write", _fmt_num(tokens.get("cache_write", 0)))

    cost = counters.get("cost_usd", {}).get("total", 0.0)
    if oc_cost and oc_cost.get("total") is not None:
        cost = oc_cost["total"]
    table.add_row("Cost (openclaw)", _fmt_cost(cost))

    table.add_row("Messages", _fmt_num(messages.get("processed", 0)))

    run_dur = histograms.get("run_duration_ms", {})
    if run_dur.get("count", 0) > 0:
        avg_ms = run_dur["sum"] / run_dur["count"]
        table.add_row("Avg run", f"{avg_ms / 1000:.1f}s")
    else:
        table.add_row("Avg run", "—")

    qdepth = histograms.get("queue_depth", {})
    if qdepth.get("count", 0) > 0:
        table.add_row("Queue depth", f"{qdepth['sum'] / qdepth['count']:.0f} (max {qdepth.get('max', '?')})")
    else:
        table.add_row("Queue depth", "—")

    otel_sessions = (otel or {}).get("sessions", [])
    table.add_row("Sessions (OTEL)", _fmt_num(len(otel_sessions)))

    gw_status = "—"
    if oc:
        gw = oc.get("gateway", {})
        if isinstance(gw, dict):
            gw_status = gw.get("status", "unknown")
        elif isinstance(gw, str):
            gw_status = gw
    table.add_row("Gateway", gw_status)

    console.print(table)
    console.print()


def _render_agent_table(otel: dict | None, agents_meta: list[dict]) -> None:
    table = Table(title="Agents", title_style="bold cyan", border_style="dim")
    table.add_column("Agent", style="bold")
    table.add_column("Input", justify="right")
    table.add_column("Output", justify="right")
    table.add_column("Total", justify="right")
    table.add_column("Cost (oc)", justify="right", style="dim")
    table.add_column("Sessions", justify="right")
    table.add_column("Workspace", justify="right")

    by_agent_tokens = (otel or {}).get("counters", {}).get("tokens", {}).get("by_agent", {})
    by_agent_cost = (otel or {}).get("counters", {}).get("cost_usd", {}).get("by_agent", {})
    otel_sessions = (otel or {}).get("sessions", [])

    agent_names: set[str] = set(by_agent_tokens.keys())
    for a in agents_meta:
        agent_names.add(a.get("name", a.get("agentName", "")))

    for name in sorted(agent_names):
        if not name:
            continue
        tok = by_agent_tokens.get(name, {})
        cost = by_agent_cost.get(name) if name in by_agent_cost else None
        sess_count = sum(1 for s in otel_sessions if s.get("agent") == name)

        ws_size = "—"
        for a in agents_meta:
            aname = a.get("name", a.get("agentName", ""))
            if aname == name:
                wdir = a.get("workspaceDir") or a.get("workspace_dir")
                if wdir:
                    ws_size = _fmt_size(_dir_size(Path(wdir)))
                break

        table.add_row(
            name,
            _fmt_num(tok.get("input", 0)),
            _fmt_num(tok.get("output", 0)),
            _fmt_num(tok.get("total", 0)),
            _fmt_cost(cost),
            str(sess_count),
            ws_size,
        )

    if not agent_names:
        table.add_row("(none)", "—", "—", "—", "—", "—", "—")

    console.print(table)
    console.print()


def _render_session_table(sessions: list[dict]) -> None:
    table = Table(title="Recent Sessions", title_style="bold cyan", border_style="dim")
    table.add_column("ID", style="dim")
    table.add_column("Agent", style="bold")
    table.add_column("Model")
    table.add_column("Turns", justify="right")
    table.add_column("Input", justify="right")
    table.add_column("Output", justify="right")
    table.add_column("Time")

    for s in sessions[:20]:
        sid = s.get("session_id", "")
        display_id = sid[:8] + ".." if len(sid) > 8 else sid
        ts = s.get("timestamp", "")
        if "T" in ts:
            ts = ts.split("T")[1][:8]

        table.add_row(
            display_id,
            s.get("agent", ""),
            s.get("model", ""),
            str(s.get("turns", "—")),
            _fmt_num(s.get("tokens", {}).get("input", 0)),
            _fmt_num(s.get("tokens", {}).get("output", 0)),
            ts,
        )

    console.print(table)
    console.print()


def _render_workspace_tables(agents_meta: list[dict]) -> None:
    for agent in agents_meta:
        name = agent.get("name", agent.get("agentName", "unknown"))
        wdir = agent.get("workspaceDir") or agent.get("workspace_dir")
        if not wdir:
            continue

        ws_path = Path(wdir)
        if not ws_path.exists():
            continue

        table = Table(
            title=f"Workspace Files ({name}: {wdir})",
            title_style="bold cyan",
            border_style="dim",
        )
        table.add_column("File", style="bold")
        table.add_column("Size", justify="right")

        total = 0
        entries: list[tuple[str, int]] = []

        for item in sorted(ws_path.iterdir()):
            if item.is_file():
                sz = item.stat().st_size
                entries.append((item.name, sz))
                total += sz
            elif item.is_dir():
                dir_sz, file_count = _dir_size_and_count(item)
                entries.append((f"{item.name}/ ({file_count} files)", dir_sz))
                total += dir_sz

        for fname, sz in entries:
            table.add_row(fname, _fmt_size(sz))

        table.add_section()
        table.add_row("Total", _fmt_size(total), style="bold")

        console.print(table)
        console.print()


def _render_field_legend() -> None:
    console.print("[dim]Field reference:[/dim]")
    console.print("[dim]  Total tokens   — cumulative LLM tokens across all agents (OTLP)[/dim]")
    console.print("[dim]    input        — tokens sent to the model (prompts + context)[/dim]")
    console.print("[dim]    output       — tokens generated by the model[/dim]")
    console.print("[dim]    cache read   — tokens served from prompt cache (reduced cost)[/dim]")
    console.print("[dim]    cache write  — tokens written to prompt cache[/dim]")
    console.print("[dim]  Cost (openclaw)— estimated cost reported by OpenClaw (unverified)[/dim]")
    console.print("[dim]  Messages      — total messages processed by the gateway (OTLP)[/dim]")
    console.print("[dim]  Avg run       — mean agent run duration in seconds (OTLP histogram)[/dim]")
    console.print("[dim]  Queue depth   — average/max pending messages in queue (OTLP)[/dim]")
    console.print("[dim]  Turns         — LLM round-trips per session (span count from OTLP traces)[/dim]")
    console.print("[dim]  Workspace     — total file size in the agent's ~/.openclaw workspace dir[/dim]")
    console.print("[dim]  Cost (oc)     — per-agent cost estimate reported by OpenClaw[/dim]")
    console.print()


def _dir_size(path: Path) -> int:
    total = 0
    try:
        for f in path.rglob("*"):
            if f.is_file():
                total += f.stat().st_size
    except OSError:
        pass
    return total


def _dir_size_and_count(path: Path) -> tuple[int, int]:
    total = 0
    count = 0
    try:
        for f in path.rglob("*"):
            if f.is_file():
                total += f.stat().st_size
                count += 1
    except OSError:
        pass
    return total, count
