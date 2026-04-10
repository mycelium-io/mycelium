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
    packages = ["opentelemetry-proto", "protobuf>=4.21.0"]

    # Prefer uv (used by uv tool installs which don't ship pip)
    import shutil
    if shutil.which("uv"):
        result = subprocess.run(
            ["uv", "pip", "install", "--python", sys.executable] + packages,
            capture_output=True, text=True,
        )
    else:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install"] + packages,
            capture_output=True, text=True,
        )

    if result.returncode != 0:
        typer.secho(f"✗ Install failed:\n{result.stderr}", fg=typer.colors.RED)
        raise typer.Exit(1)

    typer.secho("✓ Metrics dependencies installed.", fg=typer.colors.GREEN)


@app.command("status")
def status() -> None:
    """Show the health of the metrics pipeline (collector, config, data)."""
    from datetime import UTC, datetime

    all_ok = True

    # ── Collector process ────────────────────────────────────────────────
    collector_alive = False
    collector_pid: int | None = None
    collector_port = _DEFAULT_PORT
    if _PID_FILE.exists():
        try:
            lines = _PID_FILE.read_text().strip().splitlines()
            collector_pid = int(lines[0])
            if len(lines) >= 2:
                collector_port = int(lines[1])
            os.kill(collector_pid, 0)
            collector_alive = True
        except (OSError, ValueError):
            collector_alive = False
    if collector_alive:
        console.print(f"[green]✓[/green] Collector running  PID {collector_pid}  port {collector_port}")
    else:
        console.print("[red]✗[/red] Collector not running")
        if _PID_FILE.exists():
            console.print("  [dim]Stale PID file exists — run [bold]mycelium metrics stop[/bold] to clean up[/dim]")
        all_ok = False

    collector_log = _MYCELIUM_DIR / "collector.log"
    if collector_log.exists():
        try:
            log_lines = collector_log.read_text().strip().splitlines()
            recent = log_lines[-5:] if len(log_lines) > 5 else log_lines
            if recent:
                console.print(f"  [dim]Log ({collector_log}):[/dim]")
                for ln in recent:
                    console.print(f"  [dim]  {ln}[/dim]")
        except OSError:
            pass

    # ── Metrics data file ────────────────────────────────────────────────
    if _METRICS_JSON.exists():
        try:
            stat = _METRICS_JSON.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
            age = datetime.now(UTC) - mtime
            age_str = f"{int(age.total_seconds())}s ago"
            if age.total_seconds() > 3600:
                age_str = f"{age.total_seconds() / 3600:.1f}h ago"
            elif age.total_seconds() > 60:
                age_str = f"{int(age.total_seconds() / 60)}m ago"

            data = json.loads(_METRICS_JSON.read_text())
            sessions = data.get("sessions", [])
            counters = data.get("counters", {})
            msgs = counters.get("messages", {}).get("processed", 0)
            total_tok = counters.get("tokens", {}).get("total", {}).get("total", 0)

            console.print(
                f"[green]✓[/green] Data file          {_METRICS_JSON}"
            )
            console.print(
                f"  [dim]Last updated {age_str}  •  {msgs} messages  •  {len(sessions)} sessions  •  {total_tok:,} tokens[/dim]"
            )
        except Exception:
            console.print(f"[yellow]⚠[/yellow] Data file exists but unreadable: {_METRICS_JSON}")
            all_ok = False
    else:
        console.print("[yellow]⚠[/yellow] No metrics data yet (no messages received)")

    # ── OpenClaw OTEL config ─────────────────────────────────────────────
    oc_config_path = Path.home() / ".openclaw" / "openclaw.json"
    otel_endpoint: str | None = None
    otel_enabled = False
    if oc_config_path.exists():
        try:
            cfg = json.loads(oc_config_path.read_text())
            diag = cfg.get("diagnostics", {})
            otel = diag.get("otel", {})
            otel_enabled = diag.get("enabled", False) and otel.get("enabled", False)
            otel_endpoint = otel.get("endpoint", "")
        except Exception:
            pass

    if otel_enabled and otel_endpoint:
        console.print(f"[green]✓[/green] OTEL plugin        enabled → {otel_endpoint}")

        # Check endpoint matches collector port
        try:
            from urllib.parse import urlparse
            parsed = urlparse(otel_endpoint)
            ep_port = parsed.port or 80
            if collector_alive and ep_port != collector_port:
                console.print(
                    f"  [red]✗ Port mismatch:[/red] plugin sends to :{ep_port} but collector listens on :{collector_port}"
                )
                all_ok = False
            elif collector_alive:
                console.print(f"  [dim]Endpoint port :{ep_port} matches collector[/dim]")
        except Exception:
            pass
    elif oc_config_path.exists():
        console.print("[red]✗[/red] OTEL plugin        not enabled in openclaw.json")
        console.print("  [dim]Run [bold]mycelium adapter add openclaw --step=otel[/bold] to configure[/dim]")
        all_ok = False
    else:
        console.print("[yellow]⚠[/yellow] No openclaw.json found (gateway not configured)")
        all_ok = False

    # ── Summary ──────────────────────────────────────────────────────────
    console.print()
    if all_ok:
        console.print("[bold green]Pipeline healthy[/bold green]")
    else:
        console.print("[bold yellow]Pipeline has issues — see above[/bold yellow]")


@app.command("collect")
def collect(
    port: int | None = typer.Option(None, "--port", "-p", help=f"OTLP receiver port (default: {_DEFAULT_PORT})"),
    fg: bool = typer.Option(False, "--fg", help="Run collector in the foreground (default: background)"),
) -> None:
    """Start the OTLP HTTP receiver to collect OpenClaw telemetry."""
    resolved_port = _resolve_port(port)

    if not fg:
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

        log_file = _MYCELIUM_DIR / "collector.log"
        log_fh = open(log_file, "a")  # noqa: SIM115

        proc = subprocess.Popen(
            [
                sys.executable, "-m", "mycelium.collector_main",
                "--port", str(resolved_port),
            ],
            stdout=log_fh,
            stderr=log_fh,
            start_new_session=True,
        )

        _PID_FILE.write_text(f"{proc.pid}\n{resolved_port}\n")

        typer.secho(f"✓ Collector started (PID {proc.pid})", fg=typer.colors.GREEN)
        typer.echo(f"  OTLP receiver on port {resolved_port}")
        typer.echo(f"  Metrics file: {_METRICS_JSON}")
        typer.echo(f"  Log file: {log_file}")
    else:
        # Check if something is already listening on the port
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("127.0.0.1", resolved_port))
        except OSError:
            typer.secho(
                f"✗ Port {resolved_port} is already in use.",
                fg=typer.colors.RED,
            )
            if _PID_FILE.exists():
                try:
                    bg_pid = int(_PID_FILE.read_text().strip().splitlines()[0])
                    os.kill(bg_pid, 0)
                    typer.echo(
                        f"  A background collector is running (PID {bg_pid}).\n"
                        f"  Stop it first:  mycelium metrics stop"
                    )
                except (OSError, ValueError):
                    typer.echo("  Another process is using this port.")
            else:
                typer.echo("  Another process is using this port.")
            raise typer.Exit(1)
        finally:
            sock.close()

        import logging
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

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
            "  (runs in background by default; use --fg for foreground)\n\n"
            "  Make sure OpenClaw's diagnostics-otel plugin is configured:\n"
            "    [bold]mycelium adapter add openclaw --step=otel[/bold]"
        )
        raise typer.Exit(0)

    agents_meta = _extract_agents(oc_status)
    oc_sessions = _extract_oc_sessions(oc_status)
    oc_cost = _extract_oc_cost(oc_status)

    backend_data = (otel_data or {}).get("backend")

    if json_output:
        combined = {
            "otel": otel_data or {},
            "openclaw_status": {
                "agents": agents_meta,
                "sessions": oc_sessions,
                "cost": oc_cost,
            },
        }
        if backend_data:
            combined["backend"] = backend_data
        console.print_json(json.dumps(combined, default=str))
        return

    _render_summary_table(otel_data, oc_status, oc_cost)
    _render_cost_savings_table(otel_data, backend_data)
    _render_data_reuse_table(backend_data)
    _render_mycelium_llm_table(backend_data)
    _render_coordination_table(backend_data)
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
    """Extract the agent list from ``openclaw status --json``.

    The actual agent records live at ``oc["agents"]["agents"]``, each with
    ``id`` and ``workspaceDir`` fields.  We normalise ``id`` → ``name`` so
    downstream code can use a single key.
    """
    if not oc:
        return []
    agents_section = oc.get("agents")
    if isinstance(agents_section, dict):
        agent_list = agents_section.get("agents", [])
    elif isinstance(agents_section, list):
        agent_list = agents_section
    else:
        return []
    result = []
    for a in agent_list:
        if not isinstance(a, dict):
            continue
        entry = dict(a)
        if "name" not in entry and "id" in entry:
            entry["name"] = entry["id"]
        result.append(entry)
    return result


def _extract_oc_sessions(oc: dict | None) -> list[dict]:
    """Extract recent sessions from ``openclaw status --json``.

    Sessions live at ``oc["sessions"]["recent"]``.
    """
    if not oc:
        return []
    sessions = oc.get("sessions")
    if isinstance(sessions, dict):
        return sessions.get("recent", [])
    if isinstance(sessions, list):
        return sessions
    return []


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
    # Show integers without decimals, floats with up to 2 decimals
    if isinstance(n, float) and n == int(n):
        return f"{int(n):,}"
    if isinstance(n, float):
        return f"{n:,.2f}"
    return f"{n:,}"


def _fmt_cost(n: float | None) -> str:
    if n is None:
        return "—"
    return f"${n:,.4f}"


def _sparkline(min_v: float, avg_v: float, max_v: float, width: int = 8) -> str:
    """Generate a sparkline bar showing min/avg/max position."""
    if max_v == min_v:
        return "━" * width

    # Calculate position of avg within the range (0.0 to 1.0)
    pos = (avg_v - min_v) / (max_v - min_v)
    avg_idx = int(pos * (width - 1))

    # Build the bar: ━ for line, ● for average position
    bar = ""
    for i in range(width):
        if i == avg_idx:
            bar += "[bold cyan]●[/bold cyan]"
        else:
            bar += "[dim]━[/dim]"
    return bar


def _fmt_val_s(v: float) -> str:
    """Format a seconds value to a fixed 6-char field like ' 1.9s ' or ' 0.0s '."""
    return f"{v:.1f}s"


def _fmt_histogram_s(h: dict) -> str:
    """Format a millisecond histogram as seconds with fixed-width aligned sparkline."""
    count = h["count"]
    if count == 0:
        return "—"
    avg = h["sum"] / count / 1000
    min_v = h.get("min")
    max_v = h.get("max")
    _W = 6  # width for each value column (e.g. " 1.9s" or " 0.0s")

    if min_v is not None and max_v is not None:
        min_s = min_v / 1000
        max_s = max_v / 1000
        if abs(max_s - min_s) > 0.05:
            bar = _sparkline(min_s, avg, max_s)
            return (
                f"{_fmt_val_s(min_s):>{_W}} {bar} {_fmt_val_s(max_s):<{_W}}  "
                f"[dim]avg {_fmt_val_s(avg):>{_W}}  n={count}[/dim]"
            )

    bar = "━" * 8
    return (
        f"{_fmt_val_s(avg):>{_W}} {bar} {'':<{_W}}  "
        f"[dim]avg {_fmt_val_s(avg):>{_W}}  n={count}[/dim]"
    )


def _fmt_histogram_raw(h: dict) -> str:
    """Format a unitless histogram with fixed-width aligned sparkline."""
    count = h["count"]
    if count == 0:
        return "—"
    avg = h["sum"] / count
    min_v = h.get("min")
    max_v = h.get("max")
    _W = 6  # match _fmt_histogram_s field width

    if min_v is not None and max_v is not None:
        if abs(max_v - min_v) > 0.5:
            bar = _sparkline(min_v, avg, max_v)
            return (
                f"{min_v:>{_W}.0f}  {bar} {max_v:<{_W}.0f}  "
                f"[dim]avg {avg:>{_W}.1f}  n={count}[/dim]"
            )

    bar = "━" * 8
    return (
        f"{avg:>{_W}.1f}  {bar} {'':<{_W}}  "
        f"[dim]avg {avg:>{_W}.1f}  n={count}[/dim]"
    )


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
    table = Table(
        title="OpenClaw Agent Activity",
        title_style="bold cyan",
        title_justify="left",
        show_header=False,
        border_style="dim",
    )
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")

    counters = (otel or {}).get("counters", {})
    histograms = (otel or {}).get("histograms", {})
    messages = counters.get("messages", {})
    otel_sessions = (otel or {}).get("sessions", [])

    tokens = counters.get("tokens", {}).get("total", {})
    table.add_row("Total tokens", _fmt_num(tokens.get("total", 0)))
    table.add_row("  input", _fmt_num(tokens.get("input", 0)))
    table.add_row("  output", _fmt_num(tokens.get("output", 0)))
    table.add_row("  cache read", _fmt_num(tokens.get("cache_read", 0)))
    table.add_row("  cache write", _fmt_num(tokens.get("cache_write", 0)))

    cost = counters.get("cost_usd", {}).get("total", 0.0)
    if oc_cost and oc_cost.get("total") is not None:
        cost = oc_cost["total"]
    table.add_row("Estimated cost", _fmt_cost(cost))

    table.add_row("Messages", _fmt_num(messages.get("processed", 0)))

    run_dur = histograms.get("run_duration_ms", {})
    if run_dur.get("count", 0) > 0:
        table.add_row("Run duration", _fmt_histogram_s(run_dur))
    else:
        table.add_row("Run duration", "—")

    msg_dur = histograms.get("message_duration_ms", {})
    if msg_dur.get("count", 0) > 0:
        table.add_row("Msg duration", _fmt_histogram_s(msg_dur))
    else:
        table.add_row("Msg duration", "—")

    qdepth = histograms.get("queue_depth", {})
    if qdepth.get("count", 0) > 0:
        table.add_row("Queue depth", _fmt_histogram_raw(qdepth))
    else:
        table.add_row("Queue depth", "—")

    qwait = histograms.get("queue_wait_ms", {})
    if qwait.get("count", 0) > 0:
        table.add_row("Queue wait", _fmt_histogram_s(qwait))
    else:
        table.add_row("Queue wait", "—")

    table.add_row("Sessions (OTEL)", _fmt_num(len(otel_sessions)))
    total_turns = sum(s.get("turns", 1) for s in otel_sessions)
    table.add_row("Total turns", _fmt_num(total_turns) if otel_sessions else "—")

    # Context utilization histogram (newly captured)
    ctx = histograms.get("context_tokens", {})
    if ctx.get("count", 0) > 0:
        table.add_row("Context window", _fmt_histogram_raw(ctx))

    # Webhook stats (newly captured)
    webhooks = counters.get("webhooks", {})
    wh_received = webhooks.get("received", 0)
    if wh_received > 0:
        wh_errors = webhooks.get("errors", 0)
        wh_str = _fmt_num(wh_received)
        if wh_errors:
            wh_str += f"  [red]({wh_errors} errors)[/red]"
        table.add_row("Webhooks", wh_str)
        wh_dur = histograms.get("webhook_duration_ms", {})
        if wh_dur.get("count", 0) > 0:
            table.add_row("Webhook latency", _fmt_histogram_s(wh_dur))

    # Session state and stuck (newly captured)
    stuck = counters.get("sessions_stuck", 0)
    if stuck:
        table.add_row("Sessions stuck", f"[red]{_fmt_num(stuck)}[/red]")
        stuck_age = histograms.get("session_stuck_age_ms", {})
        if stuck_age.get("count", 0) > 0:
            table.add_row("Stuck age", _fmt_histogram_s(stuck_age))

    # Run attempts (newly captured)
    run_attempts = counters.get("run_attempts", 0)
    if run_attempts:
        table.add_row("Run attempts", _fmt_num(run_attempts))

    # By-model cost breakdown
    cost_by_model = counters.get("cost_usd", {}).get("by_model", {})
    if cost_by_model:
        table.add_section()
        table.add_row("[dim]Cost by model[/dim]", "")
        for model_name in sorted(cost_by_model):
            table.add_row(f"  {model_name}", _fmt_cost(cost_by_model[model_name]))

    # By-model token breakdown
    tokens_by_model = counters.get("tokens", {}).get("by_model", {})
    if tokens_by_model:
        table.add_section()
        table.add_row("[dim]Tokens by model[/dim]", "")
        for model_name in sorted(tokens_by_model):
            mt = tokens_by_model[model_name]
            table.add_row(f"  {model_name}", _fmt_num(mt.get("total", 0)))

    console.print(table)
    console.print()


def _render_agent_table(otel: dict | None, agents_meta: list[dict]) -> None:
    counters = (otel or {}).get("counters", {})
    by_agent_cost = counters.get("cost_usd", {}).get("by_agent", {})
    by_agent_histograms = (otel or {}).get("histograms", {}).get("by_agent", {})
    by_agent_tokens = counters.get("tokens", {}).get("by_agent", {})
    otel_sessions = (otel or {}).get("sessions", [])

    session_tokens_by_agent: dict[str, dict[str, int]] = {}
    for s in otel_sessions:
        a = s.get("agent", "")
        if not a:
            continue
        bucket = session_tokens_by_agent.setdefault(a, {
            "input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "total": 0,
        })
        st = s.get("tokens", {})
        for k in ("input", "output", "cache_read", "cache_write", "total"):
            bucket[k] += st.get(k, 0)

    agent_names: set[str] = set(by_agent_tokens.keys()) | set(session_tokens_by_agent.keys())
    for a in agents_meta:
        agent_names.add(a.get("name", ""))
    _FILTERED_CHANNELS = {"matrix", "slack", "discord", "cli", ""}
    agent_names -= _FILTERED_CHANNELS

    has_cost = any(by_agent_cost.get(n) for n in agent_names)
    has_hist = any(
        by_agent_histograms.get(n, {}).get("run_duration_ms", {}).get("count", 0) > 0
        for n in agent_names
    )

    table = Table(title="OpenClaw Agents", title_style="bold cyan", title_justify="left", border_style="dim")
    table.add_column("Agent", style="bold")
    table.add_column("Input", justify="right")
    table.add_column("Output", justify="right")
    table.add_column("Cache R", justify="right", style="dim")
    table.add_column("Cache W", justify="right", style="dim")
    table.add_column("Total", justify="right")
    if has_cost:
        table.add_column("Cost", justify="right")
    table.add_column("Sessions", justify="right")
    table.add_column("Turns", justify="right")
    if has_hist:
        table.add_column("Avg Run", justify="right")
    table.add_column("Workspace", justify="right")

    totals: dict[str, int | float] = {
        "input": 0, "output": 0, "cache_read": 0, "cache_write": 0,
        "total": 0, "sessions": 0, "turns": 0, "cost": 0.0,
    }

    for name in sorted(agent_names):
        if not name:
            continue
        tok = by_agent_tokens.get(name, session_tokens_by_agent.get(name, {}))
        agent_sessions = [s for s in otel_sessions if s.get("agent") == name]
        sess_count = len(agent_sessions)
        total_turns = sum(s.get("turns", 1) for s in agent_sessions)

        totals["input"] += tok.get("input", 0)
        totals["output"] += tok.get("output", 0)
        totals["cache_read"] += tok.get("cache_read", 0)
        totals["cache_write"] += tok.get("cache_write", 0)
        totals["total"] += tok.get("total", 0)
        totals["sessions"] += sess_count
        totals["turns"] += total_turns

        agent_cost = by_agent_cost.get(name, 0.0)
        totals["cost"] += agent_cost

        ws_size = "—"
        for a in agents_meta:
            if a.get("name") == name:
                wdir = a.get("workspaceDir")
                if wdir:
                    ws_size = _fmt_size(_dir_size(Path(wdir)))
                break

        avg_run = "—"
        agent_h = by_agent_histograms.get(name, {})
        rd = agent_h.get("run_duration_ms", {})
        if rd.get("count", 0) > 0:
            avg_s = rd["sum"] / rd["count"] / 1000
            avg_run = f"{avg_s:.1f}s"

        row: list[str] = [
            name,
            _fmt_num(tok.get("input", 0)),
            _fmt_num(tok.get("output", 0)),
            _fmt_num(tok.get("cache_read", 0)),
            _fmt_num(tok.get("cache_write", 0)),
            _fmt_num(tok.get("total", 0)),
        ]
        if has_cost:
            row.append(_fmt_cost(agent_cost) if agent_cost else "—")
        row.append(str(sess_count))
        row.append(str(total_turns) if total_turns else "—")
        if has_hist:
            row.append(avg_run)
        row.append(ws_size)
        table.add_row(*row)

    if len(agent_names) > 1:
        total_row: list[str] = [
            "[bold]Total[/bold]",
            f"[bold]{_fmt_num(totals['input'])}[/bold]",
            f"[bold]{_fmt_num(totals['output'])}[/bold]",
            f"[bold]{_fmt_num(totals['cache_read'])}[/bold]",
            f"[bold]{_fmt_num(totals['cache_write'])}[/bold]",
            f"[bold]{_fmt_num(totals['total'])}[/bold]",
        ]
        if has_cost:
            total_row.append(f"[bold]{_fmt_cost(totals['cost'])}[/bold]")
        total_row.append(f"[bold]{totals['sessions']}[/bold]")
        total_row.append(f"[bold]{totals['turns']}[/bold]")
        if has_hist:
            total_row.append("—")
        total_row.append("—")
        table.add_row(*total_row)

    if not agent_names:
        placeholder_cols = 8 + (1 if has_cost else 0) + (1 if has_hist else 0)
        table.add_row("(none)", *["—"] * placeholder_cols)

    console.print(table)
    console.print()


def _render_session_table(sessions: list[dict]) -> None:
    table = Table(title="OpenClaw Recent Sessions", title_style="bold cyan", title_justify="left", border_style="dim")
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
        name = agent.get("name", "unknown")
        wdir = agent.get("workspaceDir")
        if not wdir:
            continue

        ws_path = Path(wdir)
        if not ws_path.exists():
            continue

        table = Table(
            title=f"Workspace Files ({name}: {wdir})",
            title_style="bold cyan",
            title_justify="left",
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


def _detect_model(otel: dict | None) -> str:
    """Return the primary model name from OTLP token data (most tokens wins)."""
    by_model = (otel or {}).get("counters", {}).get("tokens", {}).get("by_model", {})
    if not by_model:
        return ""
    return max(by_model, key=lambda m: by_model[m].get("total", 0))


_PRICING_JSON = Path(__file__).resolve().parent.parent / "data" / "pricing.json"
_pricing_data: dict | None = None


def _load_pricing() -> dict:
    """Load pricing.json (cached after first call).

    Generated by ``scripts/update-pricing.py`` from litellm's model_cost map.
    Run ``npm run update:pricing`` in mycelium-cli or fastapi-backend to refresh.
    """
    global _pricing_data
    if _pricing_data is not None:
        return _pricing_data
    try:
        _pricing_data = json.loads(_PRICING_JSON.read_text())
    except (OSError, json.JSONDecodeError):
        _pricing_data = {}
    return _pricing_data


def _get_model_pricing(model_name: str) -> tuple[dict, str]:
    """Match a model string (e.g. 'bedrock/global.anthropic.claude-haiku-4-5-…')
    against known pricing.  Returns (pricing_dict, short_label)."""
    data = _load_pricing()
    default = data.get("default", {})
    default_pricing = {
        "input": default.get("input_per_token", 8e-07),
        "cache_discount": default.get("cache_discount", 0.90),
    }

    lower = model_name.lower()
    for entry in data.get("models", []):
        if entry["pattern"] in lower:
            return {
                "input": entry["input_per_token"],
                "cache_discount": entry["cache_discount"],
            }, entry["pattern"]

    return default_pricing, default.get("label", "unknown model")


def _pricing_generated_at() -> str:
    """Return the generation timestamp from pricing.json, or empty string."""
    data = _load_pricing()
    ts = data.get("generated_at", "")
    if "T" in ts:
        return ts.split("T")[0]
    return ts


def _render_cost_savings_table(otel: dict | None, backend: dict | None) -> None:
    """Render a Cost Savings panel showing local embedding savings and cache efficiency."""
    counters = (otel or {}).get("counters", {})
    tokens = counters.get("tokens", {}).get("total", {})
    cache_read = tokens.get("cache_read", 0)
    input_tokens = tokens.get("input", 0)

    be_counters = (backend or {}).get("counters", {}) if backend else {}
    embeddings = be_counters.get("embeddings", {})
    indexer = be_counters.get("indexer", {})

    embed_count = embeddings.get("computed", 0)
    cost_avoided = embeddings.get("estimated_cost_avoided_usd", 0.0)
    files_indexed = indexer.get("files_indexed", 0)
    files_skipped = indexer.get("files_skipped", 0)

    has_data = embed_count > 0 or cache_read > 0 or files_indexed > 0

    if not has_data:
        return

    table = Table(
        title="Cost Savings (OpenClaw + Mycelium)",
        title_style="bold green",
        title_justify="left",
        show_header=False,
        border_style="dim",
    )
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")

    if embed_count > 0:
        table.add_row("[dim]Mycelium:[/dim] Local embeddings", _fmt_num(embed_count))
        table.add_row(
            "  estimated API cost avoided",
            f"[green]{_fmt_cost(cost_avoided)}[/green]",
        )
        est_tokens = embeddings.get("estimated_tokens", 0)
        if est_tokens:
            table.add_row("  estimated tokens (local)", _fmt_num(est_tokens))

        by_source_keys = [k for k in embeddings if k.startswith("by_source.")]
        for key in sorted(by_source_keys):
            label = key.replace("by_source.", "  ")
            table.add_row(label, _fmt_num(embeddings[key]))

    be_histograms = (backend or {}).get("histograms", {}) if backend else {}
    embed_lat = be_histograms.get("embeddings.latency_ms", {})
    if embed_lat.get("count", 0) > 0:
        table.add_row("Embedding latency (local)", _fmt_histogram_s(embed_lat))

    total_index_files = files_indexed + files_skipped
    if total_index_files > 0:
        skip_pct = files_skipped / total_index_files * 100
        table.add_row("Indexer files processed", _fmt_num(total_index_files))
        table.add_row(
            "  skipped (unchanged)",
            f"[green]{_fmt_num(files_skipped)} ({skip_pct:.0f}%)[/green]",
        )
        table.add_row("  indexed (re-embedded)", _fmt_num(files_indexed))
        pruned = indexer.get("files_pruned", 0)
        if pruned:
            table.add_row("  pruned (deleted)", _fmt_num(pruned))

    idx_lat = be_histograms.get("indexer.duration_ms", {})
    if idx_lat.get("count", 0) > 0:
        table.add_row("Index run duration", _fmt_histogram_s(idx_lat))

    if cache_read > 0 and (input_tokens + cache_read) > 0:
        cache_ratio = cache_read / (input_tokens + cache_read) * 100
        model_name = _detect_model(otel)
        pricing, pricing_label = _get_model_pricing(model_name)
        input_price = pricing["input"]
        cache_discount = pricing["cache_discount"]

        if embed_count > 0 or files_indexed > 0:
            table.add_section()
        table.add_row("[dim]OpenClaw:[/dim] Prompt cache hit", f"[green]{cache_ratio:.1f}%[/green]")
        table.add_row("  cache read tokens", _fmt_num(cache_read))

        estimated_saving = cache_read * input_price * cache_discount
        if estimated_saving > 0.0001:
            table.add_row(
                "  estimated cache savings",
                f"[green]~{_fmt_cost(estimated_saving)}[/green]",
            )
            gen_date = _pricing_generated_at()
            date_suffix = f", updated {gen_date}" if gen_date else ""
            table.add_row(
                "  pricing basis",
                f"[dim]{pricing_label} @ ${input_price * 1e6:.2f}/MTok, "
                f"{cache_discount:.0%} cache discount{date_suffix}[/dim]",
            )

    console.print(table)
    console.print()


def _render_mycelium_llm_table(backend: dict | None) -> None:
    """Render a panel showing Mycelium backend's own LLM usage."""
    if not backend:
        return

    be_counters = backend.get("counters", {})
    llm = be_counters.get("llm", {})

    if llm.get("calls", 0) == 0:
        return

    table = Table(
        title="Mycelium Backend LLM Usage",
        title_style="bold magenta",
        title_justify="left",
        show_header=False,
        border_style="dim",
    )
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")

    table.add_row("Total LLM calls", _fmt_num(llm.get("calls", 0)))
    table.add_row("  input tokens", _fmt_num(llm.get("input_tokens", 0)))
    table.add_row("  output tokens", _fmt_num(llm.get("output_tokens", 0)))
    cost = llm.get("cost_usd", 0.0)
    if cost > 0:
        table.add_row("  total cost", _fmt_cost(cost))
    errors = llm.get("errors", 0)
    if errors > 0:
        table.add_row("  errors", f"[red]{_fmt_num(errors)}[/red]")

    by_op_keys = sorted(k for k in llm if k.startswith("by_operation."))
    if by_op_keys:
        table.add_section()
        for key in by_op_keys:
            label = key.replace("by_operation.", "")
            table.add_row(f"  {label}", _fmt_num(llm[key]))

    by_model_keys = sorted(k for k in llm if k.startswith("by_model."))
    if by_model_keys:
        table.add_section()
        for key in by_model_keys:
            label = key.replace("by_model.", "")
            table.add_row(f"  model: {label}", _fmt_num(llm[key]))

    be_histograms = backend.get("histograms", {})
    llm_lat = be_histograms.get("llm.latency_ms", {})
    if llm_lat.get("count", 0) > 0:
        table.add_section()
        table.add_row("LLM latency (all)", _fmt_histogram_s(llm_lat))

    for key in sorted(be_histograms):
        if key.startswith("llm.latency_ms.") and key != "llm.latency_ms":
            h = be_histograms[key]
            if h.get("count", 0) > 0:
                label = key.replace("llm.latency_ms.", "  ")
                table.add_row(label, _fmt_histogram_s(h))

    # Knowledge graph stats
    knowledge = be_counters.get("knowledge", {})
    if knowledge.get("ingestions", 0) > 0:
        table.add_section()
        table.add_row("Knowledge ingestions", _fmt_num(knowledge["ingestions"]))
        table.add_row("  concepts extracted", _fmt_num(knowledge.get("concepts_extracted", 0)))
        table.add_row("  relations extracted", _fmt_num(knowledge.get("relations_extracted", 0)))
        kg_errors = knowledge.get("errors", 0)
        if kg_errors:
            table.add_row("  graph store errors", f"[red]{_fmt_num(kg_errors)}[/red]")
        kg_lat = be_histograms.get("knowledge.ingestion_duration_ms", {})
        if kg_lat.get("count", 0) > 0:
            table.add_row("  ingestion duration", _fmt_histogram_s(kg_lat))

    # Synthesis stats
    synthesis = be_counters.get("synthesis", {})
    if synthesis.get("runs", 0) > 0:
        table.add_section()
        table.add_row("Synthesis runs", _fmt_num(synthesis["runs"]))
        synth_errors = synthesis.get("errors", 0)
        if synth_errors:
            table.add_row("  errors", f"[red]{_fmt_num(synth_errors)}[/red]")
        synth_lat = be_histograms.get("synthesis.duration_ms", {})
        if synth_lat.get("count", 0) > 0:
            table.add_row("  synthesis duration", _fmt_histogram_s(synth_lat))

    # Memory stats
    memory = be_counters.get("memory", {})
    if memory.get("writes", 0) > 0 or memory.get("searches", 0) > 0:
        table.add_section()
        if memory.get("writes", 0) > 0:
            table.add_row("Memory writes", _fmt_num(memory["writes"]))
            embedded = memory.get("writes_embedded", 0)
            if embedded:
                table.add_row("  with embedding", _fmt_num(embedded))
        if memory.get("searches", 0) > 0:
            table.add_row("Semantic searches", _fmt_num(memory["searches"]))
            search_lat = be_histograms.get("memory.search_latency_ms", {})
            if search_lat.get("count", 0) > 0:
                table.add_row("  search latency", _fmt_histogram_s(search_lat))

    console.print(table)
    console.print()


def _render_data_reuse_table(backend: dict | None) -> None:
    """Render a panel showing data reuse metrics from IOC/Mycelium databases."""
    if not backend:
        return

    be_counters = backend.get("counters", {})
    be_histograms = backend.get("histograms", {})
    memory = be_counters.get("memory", {})
    synthesis = be_counters.get("synthesis", {})
    knowledge = be_counters.get("knowledge", {})

    # Check if we have any data reuse metrics
    has_memory_reuse = memory.get("search_hits", 0) > 0 or memory.get("search_misses", 0) > 0
    has_synthesis_reuse = synthesis.get("briefings", 0) > 0
    has_knowledge_reuse = knowledge.get("queries", 0) > 0

    if not (has_memory_reuse or has_synthesis_reuse or has_knowledge_reuse):
        return

    table = Table(
        title="Mycelium Data Reuse",
        title_style="bold magenta",
        title_justify="left",
        show_header=False,
        border_style="dim",
    )
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")

    # Memory search reuse
    if has_memory_reuse:
        searches = memory.get("searches", 0)
        hits = memory.get("search_hits", 0)
        misses = memory.get("search_misses", 0)
        results = memory.get("results_returned", 0)

        table.add_row("Memory searches", _fmt_num(searches))
        if searches > 0:
            hit_rate = hits / searches * 100
            table.add_row("  returned results", f"[green]{_fmt_num(hits)}[/green] ({hit_rate:.0f}%)")
            table.add_row("  no results", _fmt_num(misses))
            table.add_row("  total results returned", _fmt_num(results))

    # Synthesis reuse
    if has_synthesis_reuse:
        if has_memory_reuse:
            table.add_section()
        briefings = synthesis.get("briefings", 0)
        cache_hits = synthesis.get("cache_hits", 0)
        cache_misses = synthesis.get("cache_misses", 0)

        table.add_row("Briefing requests", _fmt_num(briefings))
        if briefings > 0:
            hit_rate = cache_hits / briefings * 100
            table.add_row(
                "  used cached synthesis",
                f"[green]{_fmt_num(cache_hits)}[/green] ({hit_rate:.0f}%)",
            )
            table.add_row("  no cached synthesis", _fmt_num(cache_misses))

        mem_since = be_histograms.get("synthesis.memories_since_last", {})
        if mem_since.get("count", 0) > 0:
            avg = mem_since["sum"] / mem_since["count"]
            table.add_row("  avg memories since synthesis", f"{avg:.1f}")

    # Knowledge graph reuse
    if has_knowledge_reuse:
        if has_memory_reuse or has_synthesis_reuse:
            table.add_section()
        queries = knowledge.get("queries", 0)
        query_hits = knowledge.get("query_hits", 0)
        query_misses = knowledge.get("query_misses", 0)
        results = knowledge.get("results_returned", 0)

        table.add_row("Knowledge graph queries", _fmt_num(queries))
        if queries > 0:
            hit_rate = query_hits / queries * 100
            table.add_row(
                "  returned results",
                f"[green]{_fmt_num(query_hits)}[/green] ({hit_rate:.0f}%)",
            )
            table.add_row("  no results", _fmt_num(query_misses))
            table.add_row("  total results returned", _fmt_num(results))

        # Query type breakdown
        neighbor = knowledge.get("queries.neighbor", 0)
        path = knowledge.get("queries.path", 0)
        concept = knowledge.get("queries.concept", 0)
        if neighbor + path + concept > 0:
            table.add_section()
            table.add_row("[dim]By query type:[/dim]", "")
            if neighbor:
                table.add_row("  neighbor", _fmt_num(neighbor))
            if path:
                table.add_row("  path", _fmt_num(path))
            if concept:
                table.add_row("  concept", _fmt_num(concept))

        query_lat = be_histograms.get("knowledge.query_latency_ms", {})
        if query_lat.get("count", 0) > 0:
            table.add_row("Query latency", _fmt_histogram_s(query_lat))

    console.print(table)
    console.print()


def _render_coordination_table(backend: dict | None) -> None:
    """Render a panel showing Mycelium coordination/negotiation metrics."""
    if not backend:
        return

    be_counters = backend.get("counters", {})
    coord = be_counters.get("coordination", {})

    if coord.get("sessions_started", 0) == 0 and coord.get("rounds", 0) == 0:
        return

    table = Table(
        title="IOC/CFN Coordination",
        title_style="bold blue",
        title_justify="left",
        show_header=False,
        border_style="dim",
    )
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")

    table.add_row("Sessions started", _fmt_num(coord.get("sessions_started", 0)))
    table.add_row("Sessions completed", _fmt_num(coord.get("sessions_completed", 0)))

    success = coord.get("outcome.success", 0)
    failure = coord.get("outcome.failure", 0)

    if success + failure > 0:
        table.add_section()
        if success > 0:
            table.add_row("  consensus reached", f"[green]{_fmt_num(success)}[/green]")
        if failure > 0:
            table.add_row("  failed", f"[red]{_fmt_num(failure)}[/red]")

    table.add_section()
    table.add_row("Total rounds", _fmt_num(coord.get("rounds", 0)))

    be_histograms = backend.get("histograms", {})

    rounds_to_consensus = be_histograms.get("coordination.rounds_to_consensus", {})
    if rounds_to_consensus.get("count", 0) > 0:
        avg = rounds_to_consensus["sum"] / rounds_to_consensus["count"]
        min_r = rounds_to_consensus.get("min", avg)
        max_r = rounds_to_consensus.get("max", avg)
        table.add_row("Rounds to consensus", f"{avg:.1f} (min {min_r:.0f}, max {max_r:.0f})")

    time_to_consensus = be_histograms.get("coordination.time_to_consensus_ms", {})
    if time_to_consensus.get("count", 0) > 0:
        table.add_row("Time to consensus", _fmt_histogram_s(time_to_consensus))

    round_duration = be_histograms.get("coordination.round_duration_ms", {})
    if round_duration.get("count", 0) > 0:
        table.add_row("Round duration", _fmt_histogram_s(round_duration))

    participants = be_histograms.get("coordination.session_participants", {})
    if participants.get("count", 0) > 0:
        avg = participants["sum"] / participants["count"]
        table.add_row("Avg participants/session", f"{avg:.1f}")

    by_room_keys = sorted(k for k in coord if k.startswith("by_room."))
    if by_room_keys:
        table.add_section()
        table.add_row("[dim]By room:[/dim]", "")
        for key in by_room_keys[:5]:
            label = key.replace("by_room.", "")
            table.add_row(f"  {label}", _fmt_num(coord[key]))
        if len(by_room_keys) > 5:
            table.add_row(f"  [dim]...and {len(by_room_keys) - 5} more[/dim]", "")

    console.print(table)
    console.print()


def _render_field_legend() -> None:
    console.print("[dim]Data sources:[/dim]")
    console.print("[dim]  [cyan]OpenClaw[/cyan]  — Agent activity via OTLP telemetry (tokens, costs, sessions)[/dim]")
    console.print("[dim]  [magenta]Mycelium[/magenta]  — Backend API metrics (embeddings, memory, LLM calls)[/dim]")
    console.print("[dim]  [cyan]IOC/CFN[/cyan]   — Cognition Fabric Node (coordination, negotiation)[/dim]")
    data = _load_pricing()
    gen_date = _pricing_generated_at()
    litellm_ver = data.get("litellm_version", "")
    if gen_date or litellm_ver:
        source_parts = ["Pricing: litellm"]
        if litellm_ver and litellm_ver != "unknown":
            source_parts[0] += f" {litellm_ver}"
        if gen_date:
            source_parts.append(f"updated {gen_date}")
        console.print(f"[dim]  {' · '.join(source_parts)}[/dim]")
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
