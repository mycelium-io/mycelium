# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Metrics commands: see what the hub is doing and what it costs.

The collector polls the backend's ``/api/observability`` counters (LLM calls,
embeddings, memory, knowledge), scrapes any configured Prometheus targets,
and receives OTLP traces from anything pointed at it. ``show`` reads what it
collected; ``traces`` browses the traces.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from mycelium.collector import _ensure_shared_dir
from mycelium.commands.traces import app as traces_app

app = typer.Typer(
    help="See the hub's usage and cost, and the traces it has collected.",
    no_args_is_help=True,
)
# Trace-level views over ~/.mycelium/metrics/traces.db.
app.add_typer(traces_app, name="traces")

_DEFAULT_PORT = 4318


def _config_collector_port() -> int:
    """Read collector_port from config.toml (falls back to _DEFAULT_PORT)."""
    try:
        from mycelium.config import MyceliumConfig

        return MyceliumConfig.load().runtime.collector_port
    except Exception:
        return _DEFAULT_PORT


def _data_dir() -> Path:
    """Resolve the Mycelium data directory, respecting MYCELIUM_DATA_DIR."""
    return Path(os.environ.get("MYCELIUM_DATA_DIR") or Path.home() / ".mycelium")


def _metrics_dir() -> Path:
    """Resolve the metrics subdirectory under the data dir."""
    return _data_dir() / "metrics"


def _metrics_json() -> Path:
    return _metrics_dir() / "metrics.json"


console = Console()


def _resolve_port(cli_port: int | None) -> int:
    """Resolve the collector port: CLI flag > env var > config.toml > 4318."""
    if cli_port is not None:
        if not 1 <= cli_port <= 65535:
            typer.secho(f"✗ Invalid port {cli_port} (must be 1–65535)", fg=typer.colors.RED)
            raise typer.Exit(1)
        return cli_port
    env = os.environ.get("MYCELIUM_METRICS_PORT")
    if env:
        try:
            p = int(env)
            if 1 <= p <= 65535:
                return p
        except ValueError:
            pass
    return _config_collector_port()


def _port_in_use(port: int) -> bool:
    """Return True if *port* is already bound on localhost."""
    import socket as _sock

    s = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
    try:
        s.settimeout(1)
        s.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _check_otel_deps() -> bool:
    """Return True if opentelemetry-proto is importable, else print an error."""
    try:
        from opentelemetry.proto.collector.metrics.v1 import metrics_service_pb2  # noqa: F401

        return True
    except ImportError:
        typer.secho(
            "✗ opentelemetry-proto not found. Reinstall the CLI:\n"
            "  curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash",
            fg=typer.colors.RED,
        )
        return False


@app.command("status")
def status() -> None:
    """Show the health of the metrics pipeline (collector, config, data)."""
    from datetime import UTC, datetime

    all_ok = True

    # ── OTLP deps ────────────────────────────────────────────────────────
    if _check_otel_deps():
        console.print("[green]✓[/green] OTLP dependencies  installed")
    else:
        console.print("[red]✗[/red] OTLP dependencies  missing (opentelemetry-proto)")
        all_ok = False

    # ── Collector process ────────────────────────────────────────────────
    collector_url = _get_collector_url()
    collector_port = _resolve_port(None)
    spoke = _is_spoke_mode()

    if spoke and collector_url:
        # Spoke mode: show hub (remote) AND local collector state
        remote_data = _fetch_remote_metrics(collector_url)
        if remote_data is not None:
            console.print(f"[green]✓[/green] Hub collector      reachable ({collector_url})")
        else:
            console.print(f"[red]✗[/red] Hub collector      unreachable ({collector_url})")
            all_ok = False

        local_pid = _read_collector_pid()
        local_alive = local_pid is not None or _port_in_use(collector_port)
        if local_alive:
            pid_label = f" PID {local_pid}" if local_pid else ""
            console.print(
                f"[green]✓[/green] Local collector    running on :{collector_port}{pid_label}"
            )
        else:
            console.print(
                f"[yellow]⚠[/yellow] Local collector    not running on :{collector_port}\n"
                "  [dim]Start with [bold]mycelium metrics collect[/bold] to receive traces on this machine[/dim]"
            )
    else:
        # Hub / local mode
        collector_alive = False
        collector_label = ""
        if _docker_collector_running():
            collector_alive = True
            collector_label = "Docker container"
        elif _port_in_use(collector_port):
            collector_alive = True
            collector_label = f"port {collector_port}"

        if collector_alive:
            console.print(f"[green]✓[/green] Collector running  {collector_label}")
        else:
            console.print(
                "[red]✗[/red] Collector not running\n"
                "  [dim]Start with [bold]mycelium up --metrics[/bold][/dim]"
            )
            all_ok = False

    # ── Metrics data file ────────────────────────────────────────────────
    if _metrics_json().exists():
        try:
            stat = _metrics_json().stat()
            mtime = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
            age = datetime.now(UTC) - mtime
            age_str = f"{int(age.total_seconds())}s ago"
            if age.total_seconds() > 3600:
                age_str = f"{age.total_seconds() / 3600:.1f}h ago"
            elif age.total_seconds() > 60:
                age_str = f"{int(age.total_seconds() / 60)}m ago"

            data = json.loads(_metrics_json().read_text())
            llm_calls = (
                (data.get("backend") or {}).get("counters", {}).get("llm", {}).get("calls", 0)
            )
            hosts = len(data.get("by_host") or {})

            console.print(f"[green]✓[/green] Data file          {_metrics_json()}")
            console.print(
                f"  [dim]Last updated {age_str}  •  {llm_calls:,} backend LLM calls  •  "
                f"{hosts} host(s) sending traces[/dim]"
            )
        except Exception:
            console.print(f"[yellow]⚠[/yellow] Data file exists but unreadable: {_metrics_json()}")
            all_ok = False
    else:
        console.print("[yellow]⚠[/yellow] No metrics data yet")

    # ── Pricing data ────────────────────────────────────────────────────
    pricing = _load_pricing()
    models = pricing.get("models", [])
    gen_date = _pricing_generated_at()
    if models:
        source_label = (
            "update-pricing" if pricing.get("source") == "litellm_catalog_api" else "bundled"
        )
        console.print(
            f"[green]✓[/green] Pricing data        "
            f"{len(models)} models ({source_label}"
            f"{', ' + gen_date.split(',')[0] if gen_date else ''})"
        )
        patterns = [m.get("pattern", "?") for m in models]
        console.print(f"  [dim]{', '.join(patterns)}[/dim]")
    elif pricing:
        console.print("[yellow]⚠[/yellow] Pricing data        no models found")
        console.print(
            "  [dim]Run [bold]mycelium metrics update-pricing[/bold] to fetch pricing[/dim]"
        )
        all_ok = False
    else:
        console.print("[yellow]⚠[/yellow] Pricing data        not found")
        console.print(
            "  [dim]Run [bold]mycelium metrics update-pricing[/bold] to fetch pricing[/dim]"
        )
        all_ok = False

    # ── Summary ──────────────────────────────────────────────────────────
    console.print()
    if all_ok:
        console.print("[bold green]Pipeline healthy[/bold green]")
    else:
        console.print("[bold yellow]Pipeline has issues, see above[/bold yellow]")


def _docker_collector_running() -> bool:
    """Return True if the mycelium-collector Docker container is running."""
    try:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", "mycelium-collector"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        return result.returncode == 0 and result.stdout.strip().lower() == "true"
    except Exception:
        return False


def _is_spoke_mode() -> bool:
    """True when this node is configured as a spoke (collector_url points to a remote host)."""
    url = _get_collector_url()
    if not url:
        return False
    from urllib.parse import urlparse

    host = urlparse(url).hostname or ""
    return host not in ("localhost", "127.0.0.1", "::1", "0.0.0.0", "")


def _hub_suffix() -> str:
    """Return '` (from hub)`' on a spoke, else ''.

    Backend-sourced metrics on a spoke are proxied via the hub collector
    rather than counted locally; tagging the title makes that clear so
    a spoke operator doesn't think their node is doing the ingestion.
    """
    return " [dim](from hub)[/dim]" if _is_spoke_mode() else ""


_ROOM_LOOKUP_CACHE: tuple[dict[str, str], dict[str, str]] | None = None

# Per-invocation handle on the backend snapshot, so ``_resolve_room_lookup``
# can layer the ``room_identities`` registry on top of ``/api/rooms``. Set
# by ``show()`` after backend data is loaded, cleared at the end of the
# invocation. The snapshot's identity entries win; they survive room
# deletion, while /api/rooms is destructive (see Room model in
# fastapi-backend/app/models.py, no ``deleted_at`` column).
_SNAPSHOT_BACKEND_FOR_LOOKUP: dict | None = None


def _set_room_lookup_context(backend: dict | None) -> None:
    """Wire the backend snapshot into the next ``_resolve_room_lookup`` call.

    Also invalidates any cached lookup so the new context takes effect.
    Safe to call multiple times; the cache is rebuilt lazily on first
    read after the context changes.
    """
    global _SNAPSHOT_BACKEND_FOR_LOOKUP, _ROOM_LOOKUP_CACHE
    _SNAPSHOT_BACKEND_FOR_LOOKUP = backend
    _ROOM_LOOKUP_CACHE = None


def _resolve_room_lookup() -> tuple[dict[str, str], dict[str, str]]:
    """Return ``(mas_to_name, name_to_mas)`` for the per-room metric tables.

    Sources, merged in priority order (highest first):
      1. The backend snapshot's ``room_identities`` map (populated by
         ``record_room_identity`` server-side at write-time). Survives
         room deletion, so it's the authoritative join for both alive
         and tombstoned rooms.
      2. ``GET /api/rooms``: covers any room registered before the
         server started tracking identities, but rows vanish on delete.

    The result is cached for the lifetime of the CLI process; `metrics show`
    runs are short-lived, and rooms rarely churn within a single invocation.
    On any failure (no backend reachable, request error) we still return
    whatever the snapshot gave us; if both are empty, two empty dicts so
    the caller can fall back gracefully.
    """
    global _ROOM_LOOKUP_CACHE
    if _ROOM_LOOKUP_CACHE is not None:
        return _ROOM_LOOKUP_CACHE
    mas_to_name: dict[str, str] = {}
    name_to_mas: dict[str, str] = {}

    # Source 1: snapshot identities, authoritative for both directions.
    # These survive room deletion, so they override /api/rooms when both
    # are present (in practice they'll agree for alive rooms).
    snap = _SNAPSHOT_BACKEND_FOR_LOOKUP or {}
    snapshot_ids = snap.get("room_identities") if isinstance(snap, dict) else None
    if isinstance(snapshot_ids, dict):
        for mas_id, name in snapshot_ids.items():
            if mas_id and name:
                mas_to_name[str(mas_id)] = str(name)
                name_to_mas[str(name)] = str(mas_id)

    # Source 2: /api/rooms, fills in anything the snapshot missed.
    # ``setdefault`` semantics ensure snapshot wins on conflicts.
    try:
        from mycelium.config import MyceliumConfig

        api_url = MyceliumConfig.load().server.api_url
        if not api_url:
            _ROOM_LOOKUP_CACHE = (mas_to_name, name_to_mas)
            return _ROOM_LOOKUP_CACHE
        import httpx

        resp = httpx.get(
            f"{api_url.rstrip('/')}/api/rooms",
            headers={"Accept": "application/json"},
            timeout=2.0,
        )
        if resp.status_code != 200:
            _ROOM_LOOKUP_CACHE = (mas_to_name, name_to_mas)
            return _ROOM_LOOKUP_CACHE
        rooms = resp.json()
        if not isinstance(rooms, list):
            _ROOM_LOOKUP_CACHE = (mas_to_name, name_to_mas)
            return _ROOM_LOOKUP_CACHE
        for r in rooms:
            mas_id = r.get("mas_id")
            name = r.get("name")
            if mas_id and name:
                mas_to_name.setdefault(str(mas_id), str(name))
                name_to_mas.setdefault(str(name), str(mas_id))
    except Exception:
        # Caching the (possibly snapshot-only) result is intentional:
        # avoid retrying a failed lookup repeatedly within the same
        # render pass.
        pass
    _ROOM_LOOKUP_CACHE = (mas_to_name, name_to_mas)
    return _ROOM_LOOKUP_CACHE


def _resolve_room_names_by_mas() -> dict[str, str]:
    """Backwards-compatible accessor; returns just the ``mas → name`` map."""
    return _resolve_room_lookup()[0]


def _resolve_mas_by_room_name() -> dict[str, str]:
    """Return the ``room_name → mas_id`` map (companion to the above)."""
    return _resolve_room_lookup()[1]


def _format_mas(mas_id: str, *, detail: bool = False) -> str:
    """Format a mas_id for the MAS column.

    Short 8-char prefix by default (keeps the column narrow); full UUID
    under ``--detail`` so operators can copy-paste without a second
    ``/api/rooms`` lookup.
    """
    if not mas_id:
        return ""
    return str(mas_id) if detail else str(mas_id)[:8]


def _collector_pid_file() -> Path:
    """Path to the spoke collector PID file."""
    return _metrics_dir() / "collector.pid"


def _read_collector_pid() -> int | None:
    """Return the PID from the collector PID file, or None."""
    pf = _collector_pid_file()
    if not pf.exists():
        return None
    try:
        pid = int(pf.read_text().strip())
        os.kill(pid, 0)
        return pid
    except (ValueError, ProcessLookupError, PermissionError):
        pf.unlink(missing_ok=True)
        return None


@app.command("collect")
def collect(
    port: int | None = typer.Option(None, "--port", "-p", help="OTLP listen port"),
    foreground: bool = typer.Option(
        False, "--foreground", "-f", help="Run in the foreground instead of daemonizing"
    ),
) -> None:
    """Start a collector on this machine (in the background by default).

    It receives OTLP traces sent to this machine, keeps them locally and
    forwards them to the hub's collector. It doesn't poll the backend; a
    spoke reads the hub's numbers through ``collector_url``.

    Stop with ``mycelium metrics stop``.
    """
    if not _is_spoke_mode():
        typer.secho(
            "✗ 'collect' is for spoke nodes only.\n"
            "  Set metrics.collector_url in config.toml (or MYCELIUM_COLLECTOR_URL)\n"
            "  to point at the hub collector, then re-run.\n"
            "  On hub/local nodes use: mycelium up --metrics",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    if not _check_otel_deps():
        raise typer.Exit(1)

    resolved_port = _resolve_port(port)

    existing_pid = _read_collector_pid()
    if existing_pid:
        typer.secho(
            f"✗ Spoke collector already running (PID {existing_pid}).\n"
            "  Stop it first with: mycelium metrics stop",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    if _port_in_use(resolved_port):
        typer.secho(
            f"✗ Port {resolved_port} is already in use. "
            "Stop the existing process or choose a different port with --port.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    output = _metrics_json()
    _ensure_shared_dir(output.parent)

    hub_url = _get_collector_url()

    if foreground:
        typer.echo(f"Starting spoke collector on :{resolved_port} (foreground)")
        typer.echo(f"  Data: {output}")
        if hub_url:
            typer.echo(f"  Forwarding OTLP to hub: {hub_url}")
        typer.echo("  Press Ctrl+C to stop\n")

        from mycelium.collector import run as collector_run

        collector_run(resolved_port, output, no_backend=True, hub_url=hub_url)
        return

    _daemonize_collector(resolved_port, output, hub_url)


def _daemonize_collector(port: int, output: Path, hub_url: str | None) -> None:
    """Fork the collector into the background and write a PID file."""
    import signal

    if not hasattr(os, "fork"):
        typer.secho(
            "✗ Background daemonization requires os.fork() (macOS/Linux).",
            fg=typer.colors.RED,
        )
        typer.echo("  On Windows, run the collector in the foreground with --foreground.")
        raise typer.Exit(1)

    log_file = _metrics_dir() / "collector.log"
    pid_file = _collector_pid_file()

    # Pipe for the grandchild daemon to report its PID to the original parent
    read_fd, write_fd = os.pipe()

    child_pid = os.fork()
    if child_pid != 0:
        os.close(write_fd)
        # Wait for the intermediate child to exit
        os.waitpid(child_pid, 0)
        # Read the daemon (grandchild) PID from the pipe
        with os.fdopen(read_fd) as f:
            daemon_pid = f.read().strip()
        typer.secho(f"✓ Spoke collector started (PID {daemon_pid})", fg=typer.colors.GREEN)
        typer.echo(f"  Port: {port}")
        typer.echo(f"  Data: {output}")
        if hub_url:
            typer.echo(f"  Forwarding OTLP to hub: {hub_url}")
        typer.echo(f"  Log:  {log_file}")
        typer.echo("  Stop: mycelium metrics stop")
        return

    # ── Child process (intermediate) ──
    os.close(read_fd)
    os.setsid()

    # Second fork to fully detach
    if os.fork() != 0:
        os.close(write_fd)
        os._exit(0)

    # ── Grandchild (actual daemon) ──
    daemon_pid_str = str(os.getpid())
    os.write(write_fd, daemon_pid_str.encode())
    os.close(write_fd)

    pid_file.write_text(daemon_pid_str)

    # Redirect stdio to log file
    sys.stdin.close()
    fd = os.open(str(log_file), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    os.dup2(fd, 1)
    os.dup2(fd, 2)
    os.close(fd)

    def _cleanup(signum: int, _frame: object) -> None:
        pid_file.unlink(missing_ok=True)
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _cleanup)
    signal.signal(signal.SIGINT, _cleanup)

    try:
        import logging

        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        from mycelium.collector import run as collector_run

        collector_run(port, output, no_backend=True, hub_url=hub_url)
    finally:
        pid_file.unlink(missing_ok=True)


@app.command("stop")
def stop_collector() -> None:
    """Stop the metrics collector.

    On spoke nodes, stops the background spoke collector process.
    On hub/local nodes, stops the Dockerized collector container.
    """
    import signal

    spoke = _is_spoke_mode()

    if spoke:
        pid = _read_collector_pid()
        if pid is None:
            port = _resolve_port(None)
            if _port_in_use(port):
                typer.secho(
                    f"⚠ Collector appears to be running on :{port} but no PID file found.\n"
                    "  It may have been started in foreground mode; Ctrl+C it directly.",
                    fg=typer.colors.YELLOW,
                )
                raise typer.Exit(1)
            typer.echo("Spoke collector is not running.")
            return

        try:
            os.kill(pid, signal.SIGTERM)
            typer.secho(f"✓ Spoke collector stopped (PID {pid})", fg=typer.colors.GREEN)
        except ProcessLookupError:
            typer.echo("Spoke collector is not running (stale PID file cleaned up).")
        _collector_pid_file().unlink(missing_ok=True)
    else:
        if not _docker_collector_running():
            typer.echo("Collector container is not running.")
            return
        typer.echo("Stopping collector container...")
        result = subprocess.run(
            ["docker", "stop", "mycelium-collector"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if result.returncode == 0:
            typer.secho("✓ Collector container stopped", fg=typer.colors.GREEN)
        else:
            typer.secho(
                f"✗ Failed to stop collector: {result.stderr.strip()}",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)


@app.command("reset")
def reset() -> None:
    """Delete collected metrics data."""
    if _metrics_json().exists():
        _metrics_json().unlink()
        typer.secho("✓ Metrics data cleared.", fg=typer.colors.GREEN)
    else:
        typer.echo("No metrics data to clear.")


# litellm's public model-catalog endpoint (data-only; litellm is not a dependency).
_PRICING_CATALOG_API = "https://api.litellm.ai/model_catalog"

_TRACKED_MODELS: list[dict] = [
    {"pattern": "claude-sonnet-4", "provider": "anthropic", "litellm_key": "claude-sonnet-4-5"},
    {
        "pattern": "claude-3-7-sonnet",
        "provider": "anthropic",
        "litellm_key": "claude-3-7-sonnet-20250219",
    },
    {
        "pattern": "claude-3-5-sonnet",
        "provider": "anthropic",
        "litellm_key": "anthropic.claude-3-5-sonnet-20240620-v1:0",
    },
    {
        "pattern": "claude-3-5-haiku",
        "provider": "anthropic",
        "litellm_key": "anthropic.claude-3-5-haiku-20241022-v1:0",
    },
    {"pattern": "claude-haiku-4", "provider": "anthropic", "litellm_key": "claude-haiku-4-5"},
    {
        "pattern": "claude-3-haiku",
        "provider": "anthropic",
        "litellm_key": "claude-3-haiku-20240307",
    },
    {"pattern": "claude-3-opus", "provider": "anthropic", "litellm_key": "claude-3-opus-20240229"},
    {"pattern": "claude-opus-4", "provider": "anthropic", "litellm_key": "claude-opus-4-1"},
    {"pattern": "gpt-4o-mini", "provider": "openai", "litellm_key": "gpt-4o-mini"},
    {"pattern": "gpt-4o", "provider": "openai", "litellm_key": "gpt-4o"},
    {"pattern": "gpt-4-turbo", "provider": "openai", "litellm_key": "gpt-4-turbo"},
    {"pattern": "o3-mini", "provider": "openai", "litellm_key": "o3-mini"},
    {"pattern": "o3", "provider": "openai", "litellm_key": "o3"},
    {"pattern": "o4-mini", "provider": "openai", "litellm_key": "o4-mini"},
]

_DEFAULT_CACHE_DISCOUNT = 0.90

_EMBEDDING_MODEL = "text-embedding-3-small"


def _fetch_model_pricing_from_api(litellm_key: str) -> dict | None:
    """Fetch a single model's pricing from the model pricing catalog."""
    import httpx

    url = f"{_PRICING_CATALOG_API}/{litellm_key}"
    try:
        resp = httpx.get(url, headers={"Accept": "application/json"}, timeout=10.0)
        if resp.status_code != 200:
            return None
        return resp.json()
    except (httpx.HTTPError, ValueError):
        return None


def _build_pricing_entry(spec: dict, api_data: dict) -> dict | None:
    """Transform a model pricing catalog response into a pricing.json model entry."""
    input_price = api_data.get("input_cost_per_token", 0)
    output_price = api_data.get("output_cost_per_token", 0)
    cache_read = api_data.get("cache_read_input_token_cost")
    cache_write = api_data.get("cache_creation_input_token_cost")

    if not input_price:
        return None

    if not output_price:
        output_price = input_price * 4

    if cache_read is not None and cache_read >= 0 and input_price > 0:
        cache_discount = round(max(0.0, min(1.0, 1.0 - (cache_read / input_price))), 2)
    else:
        cache_discount = _DEFAULT_CACHE_DISCOUNT

    if cache_write is not None and cache_write > 0 and input_price > 0:
        cache_write_premium = round(max(0.0, (cache_write / input_price) - 1.0), 4)
    else:
        provider = spec.get("provider", "").lower()
        cache_write_premium = 0.25 if provider == "anthropic" else 0.0

    return {
        "pattern": spec["pattern"],
        "input_per_token": input_price,
        "output_per_token": output_price,
        "cache_discount": cache_discount,
        "cache_write_premium": cache_write_premium,
        "litellm_key": spec["litellm_key"],
    }


_PROVIDER_PREFIXES = [
    "bedrock/global.",
    "bedrock/",
    "anthropic/",
    "anthropic.",
    "openai/",
    "azure/",
    "vertex_ai/",
    "google/",
]


def _resolve_litellm_key(model_string: str) -> str:
    """Strip provider/routing prefixes to derive a plausible LiteLLM catalog key.

    Applies iteratively so stacked prefixes like
    ``"bedrock/global.anthropic.claude-haiku-4-5-20251001-v1:0"``
    are fully stripped to ``"claude-haiku-4-5-20251001-v1:0"``.
    """
    key = model_string
    changed = True
    while changed:
        changed = False
        for prefix in _PROVIDER_PREFIXES:
            if key.startswith(prefix):
                key = key[len(prefix) :]
                changed = True
                break
    return key


def _discover_models_from_metrics() -> list[str]:
    """Model names the backend has used that ``_TRACKED_MODELS`` doesn't cover.

    Read from ``backend.counters.llm.by_model.*`` in metrics.json.
    """
    try:
        data = json.loads(_metrics_json().read_text())
    except (OSError, json.JSONDecodeError):
        return []

    raw_models: set[str] = set()

    be_llm = data.get("backend", {}).get("counters", {}).get("llm", {})
    for key in be_llm:
        if key.startswith("by_model."):
            raw_models.add(key.removeprefix("by_model."))

    tracked_patterns = [spec["pattern"] for spec in _TRACKED_MODELS]

    untracked: list[str] = []
    for model in sorted(raw_models):
        lower = model.lower()
        if not any(pat in lower for pat in tracked_patterns):
            untracked.append(model)

    return untracked


def _parse_add_spec(spec: str) -> dict:
    """Parse a ``pattern:litellm_key`` or bare ``litellm_key`` into a model spec."""
    if ":" in spec:
        pattern, litellm_key = spec.split(":", 1)
    else:
        pattern = spec
        litellm_key = spec
    return {"pattern": pattern, "provider": "", "litellm_key": litellm_key}


@app.command("update-pricing")
def update_pricing(
    add: list[str] | None = typer.Option(
        None,
        "--add",
        help=(
            "Manually add a model. Format: 'pattern:litellm_key' or just 'litellm_key'. "
            "Repeatable. Example: --add deepseek-v3:deepseek-chat"
        ),
    ),
) -> None:
    """Fetch latest LLM pricing from the public model pricing catalog.

    Writes updated pricing to ``$MYCELIUM_DATA_DIR/metrics/pricing.json``,
    which is used by ``mycelium metrics show cost`` for cost estimates.
    Falls back to the bundled pricing.json when the local cache is missing.

    Models are sourced from three places (in order):
      1. Built-in tracked models (14 common Anthropic/OpenAI models)
      2. Auto-discovered models from collected metrics (metrics/metrics.json)
      3. Manually added models via --add
    """
    from datetime import UTC, datetime

    console.print("[bold]Fetching model pricing from the pricing catalog...[/bold]")

    models: list[dict] = []
    warnings: list[str] = []

    # 1. Built-in tracked models
    for spec in _TRACKED_MODELS:
        api_data = _fetch_model_pricing_from_api(spec["litellm_key"])
        if api_data is None:
            warnings.append(
                f"  [yellow]WARNING[/yellow]: no API data for '{spec['pattern']}' ({spec['litellm_key']})"
            )
            continue

        entry = _build_pricing_entry(spec, api_data)
        if entry is None:
            warnings.append(f"  [yellow]WARNING[/yellow]: '{spec['pattern']}' has no input pricing")
            continue

        models.append(entry)

    tracked_count = len(models)
    console.print(f"  {tracked_count}/{len(_TRACKED_MODELS)} tracked models updated")

    # 2. Auto-discover from collected metrics
    discovered = _discover_models_from_metrics()
    known_patterns = {m["pattern"] for m in models}
    discovered_count = 0

    for model_string in discovered:
        litellm_key = _resolve_litellm_key(model_string)
        if litellm_key in known_patterns:
            continue

        api_data = _fetch_model_pricing_from_api(litellm_key)
        if api_data is None:
            warnings.append(
                f"  [yellow]WARNING[/yellow]: no API data for discovered model '{model_string}' (tried key '{litellm_key}')"
            )
            continue

        spec = {"pattern": litellm_key, "provider": "", "litellm_key": litellm_key}
        entry = _build_pricing_entry(spec, api_data)
        if entry is None:
            continue

        entry["discovered_from"] = model_string
        models.append(entry)
        known_patterns.add(litellm_key)
        discovered_count += 1

    if discovered_count > 0:
        console.print(f"  {discovered_count} model(s) discovered from collected metrics")

    # 3. Manually added models via --add
    manual_count = 0
    for raw_spec in add or []:
        spec = _parse_add_spec(raw_spec)
        if spec["pattern"] in known_patterns:
            console.print(f"  [dim]Skipping '{spec['pattern']}' (already tracked)[/dim]")
            continue

        api_data = _fetch_model_pricing_from_api(spec["litellm_key"])
        if api_data is None:
            warnings.append(
                f"  [yellow]WARNING[/yellow]: no API data for --add '{raw_spec}' (tried key '{spec['litellm_key']}')"
            )
            continue

        entry = _build_pricing_entry(spec, api_data)
        if entry is None:
            warnings.append(f"  [yellow]WARNING[/yellow]: --add '{raw_spec}' has no input pricing")
            continue

        models.append(entry)
        known_patterns.add(spec["pattern"])
        manual_count += 1

    if manual_count > 0:
        console.print(f"  {manual_count} model(s) added via --add")

    embed_data = _fetch_model_pricing_from_api(_EMBEDDING_MODEL)
    embed_price = (embed_data or {}).get("input_cost_per_token", 2e-08)

    output = {
        "generated_at": datetime.now(UTC).isoformat(),
        "source": "litellm_catalog_api",
        "models": models,
        "default": {
            "input_per_token": 8e-07,
            "output_per_token": 3.2e-06,
            "cache_discount": _DEFAULT_CACHE_DISCOUNT,
            "cache_write_premium": 0.25,
            "label": "unknown model",
        },
        "embedding_baseline": {
            "model": _EMBEDDING_MODEL,
            "input_per_token": embed_price,
        },
    }

    _ensure_shared_dir(_metrics_dir())
    _user_pricing_json().write_text(json.dumps(output, indent=2) + "\n")

    global _pricing_data
    _pricing_data = None

    console.print(f"[green]Wrote {_user_pricing_json()}[/green]")

    if warnings:
        for w in warnings:
            console.print(w)

    # Show diff against bundled defaults
    old_bundled: dict | None = None
    try:
        old_bundled = json.loads(_BUNDLED_PRICING_JSON.read_text())
    except (OSError, json.JSONDecodeError):
        pass

    if old_bundled:
        old_models = {m["pattern"]: m for m in old_bundled.get("models", [])}
        changes = 0
        for m in models:
            old = old_models.get(m["pattern"])
            if not old:
                console.print(
                    f"  [green]+[/green] {m['pattern']:25s}  "
                    f"in ${m['input_per_token'] * 1e6:.2f}  "
                    f"out ${m['output_per_token'] * 1e6:.2f}/MTok  "
                    f"{m['cache_discount']:.0%} discount"
                )
                changes += 1
            else:
                old_input = old.get("input_per_token", 0)
                old_output = old.get("output_per_token", 0)
                old_discount = old.get("cache_discount", 0)
                if (
                    abs(old_input - m["input_per_token"]) > 1e-12
                    or abs(old_output - m["output_per_token"]) > 1e-12
                    or abs(old_discount - m["cache_discount"]) > 0.001
                ):
                    console.print(
                        f"  [yellow]~[/yellow] {m['pattern']:25s}  "
                        f"in ${old_input * 1e6:.2f} -> ${m['input_per_token'] * 1e6:.2f}  "
                        f"out ${old_output * 1e6:.2f} -> ${m['output_per_token'] * 1e6:.2f}/MTok  "
                        f"{old_discount:.0%} -> {m['cache_discount']:.0%} discount"
                    )
                    changes += 1
        if changes == 0:
            console.print("  No pricing changes vs bundled defaults.")


_VALID_SECTIONS = ("mycelium", "cost", "all")


@app.command("show")
def show(
    section: str | None = typer.Argument(
        None,
        help="Section to show: mycelium, cost, all. Omit for an overview.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
    detail: bool = typer.Option(
        False,
        "--detail",
        help=("Show every room in the per-room tables, not just the top 5, and show ids in full."),
    ),
) -> None:
    """
    Show the hub's LLM calls, search indexing, knowledge writes and estimated cost.

    With no argument, shows a short overview. Pass a section for the detail:
    mycelium (the backend's activity), cost, or all.
    """
    if section is not None:
        section = section.lower()
        if section not in _VALID_SECTIONS:
            typer.secho(
                f"Unknown section '{section}'. Valid: {', '.join(_VALID_SECTIONS)}",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)

    otel_data = _load_metrics_json()

    if otel_data is None:
        spoke = _is_spoke_mode()
        hub_url = _get_collector_url()
        collector_up = (
            _docker_collector_running()
            or _port_in_use(_resolve_port(None))
            or (spoke and hub_url is not None and _fetch_remote_metrics(hub_url) is not None)
        )
        if collector_up:
            console.print(
                "[yellow]No metrics data yet.[/yellow]\n\n"
                "  The collector is running but hasn't written anything yet.\n"
                "  It polls the backend every 30 seconds; try again shortly."
            )
        else:
            hint = (
                "  Start the local collector:  [bold]mycelium metrics collect[/bold]"
                if spoke
                else "  Start the collector:  [bold]mycelium up --metrics[/bold]"
            )
            console.print(f"[yellow]No metrics data available.[/yellow]\n\n{hint}")
        raise typer.Exit(0)

    backend_data = otel_data.get("backend")
    _set_room_lookup_context(backend_data)

    if json_output:
        console.print_json(json.dumps(otel_data, default=str))
        return

    if section is None:
        _render_overview(otel_data, backend_data)
        return

    show_mycelium = section in ("mycelium", "all")
    show_cost = section in ("cost", "all")

    if show_mycelium:
        if not backend_data:
            if _is_spoke_mode():
                console.print(
                    "[dim]Backend metrics not yet available from hub. "
                    "Ensure the hub collector is running.[/dim]"
                )
            else:
                console.print("[dim]Backend metrics not collected (collector not running)[/dim]")
            console.print()
        else:
            rendered = False
            be_counters = backend_data.get("counters", {})
            has_embeddings = be_counters.get("embeddings", {}).get("computed", 0) > 0
            has_indexer = be_counters.get("indexer", {}).get("runs", 0) > 0
            has_llm = be_counters.get("llm", {}).get("calls", 0) > 0
            has_knowledge = (be_counters.get("knowledge") or {}).get("writes", 0) > 0 or (
                be_counters.get("knowledge") or {}
            ).get("ingestions", 0) > 0

            if has_embeddings or has_indexer:
                _render_cost_avoidance_table(backend_data)
                rendered = True
            if has_llm:
                _render_mycelium_llm_table(backend_data)
                rendered = True
            if has_knowledge:
                _render_knowledge_table(backend_data, detail=detail)
                rendered = True

            if not rendered:
                table = Table(
                    title=f"Mycelium Backend{_hub_suffix()}",
                    title_style="bold magenta",
                    title_justify="left",
                    show_header=False,
                    border_style="dim",
                )
                table.add_column("Info")
                table.add_row(
                    "No activity yet. This section populates when the backend\n"
                    "processes embeddings, LLM calls, knowledge, or briefings."
                )
                console.print(table)
                console.print()

    if show_cost:
        _render_cost_estimates(backend_data)

    console.print()


def _render_overview(otel: dict | None, backend: dict | None) -> None:
    """Short overview: the backend's headline numbers, and the hosts sending traces."""
    table = Table(
        title="Mycelium Metrics Overview",
        title_style="bold",
        title_justify="left",
        show_header=False,
        border_style="dim",
    )
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")

    if backend:
        be_counters = backend.get("counters", {})
        llm = be_counters.get("llm", {})
        embeddings = be_counters.get("embeddings", {})
        memory = be_counters.get("memory", {})
        knowledge = be_counters.get("knowledge", {})
        indexer = be_counters.get("indexer", {})

        be_label = "[magenta]Mycelium Backend[/magenta]"
        if _is_spoke_mode():
            be_label += " [dim](from hub)[/dim]"
        table.add_row(be_label, "")
        has_be_row = False
        if llm.get("calls", 0) > 0:
            table.add_row("  LLM calls", _fmt_num(llm["calls"]))
            has_be_row = True
        embed_count = embeddings.get("computed", 0)
        if embed_count > 0:
            table.add_row("  Embeddings (local)", _fmt_num(embed_count))
            has_be_row = True
        writes = memory.get("writes", 0)
        searches = memory.get("searches", 0)
        if writes > 0 or searches > 0:
            table.add_row(
                "  Memory writes / searches", f"{_fmt_num(writes)} / {_fmt_num(searches)}"
            )
            has_be_row = True
        knowledge_writes = knowledge.get("writes", 0)
        ingestions = knowledge.get("ingestions", 0)
        if knowledge_writes > 0 or ingestions > 0:
            parts = []
            if ingestions > 0:
                parts.append(f"{_fmt_num(ingestions)} ingested")
            if knowledge_writes > 0:
                parts.append(f"{_fmt_num(knowledge_writes)} written")
            table.add_row("  Knowledge", ", ".join(parts))
            has_be_row = True
        indexed = indexer.get("files_indexed", 0)
        skipped = indexer.get("files_skipped", 0)
        runs = indexer.get("runs", 0)
        if runs > 0:
            table.add_row("  Indexer", f"{_fmt_num(indexed)} indexed, {_fmt_num(skipped)} skipped")
            has_be_row = True
        if not has_be_row:
            table.add_row("  [dim]No activity yet[/dim]", "")
    else:
        label = "[dim]via hub[/dim]" if _is_spoke_mode() else ""
        table.add_row("[magenta]Mycelium Backend[/magenta]", f"[dim]No activity yet[/dim] {label}")

    console.print(table)
    console.print()

    by_host = (otel or {}).get("by_host", {})
    is_spoke = _is_spoke_mode()
    if by_host and not is_spoke:
        host_table = Table(
            title="Hosts sending traces",
            title_style="bold cyan",
            title_justify="left",
            show_header=True,
            border_style="dim",
        )
        host_table.add_column("Host", style="bold")
        host_table.add_column("Agents")
        host_table.add_column("Spans", justify="right")
        host_table.add_column("Last Seen")
        for hk in sorted(by_host, key=lambda h: by_host[h].get("last_seen", ""), reverse=True):
            hd = by_host[hk]
            agents = ", ".join(hd.get("agents", [])) or "-"
            spans = str(hd.get("spans", 0))
            last = hd.get("last_seen", "-")
            if last and last != "-":
                try:
                    from datetime import datetime

                    dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                    last = dt.strftime("%H:%M:%S")
                except Exception:
                    pass
            host_table.add_row(hk, agents, spans, last)
        console.print(host_table)
        console.print()

    console.print("[dim]Detail: mycelium metrics show <mycelium|cost>[/dim]")
    if by_host and not is_spoke:
        console.print("[dim]Traces: mycelium metrics traces[/dim]")
    console.print()


def _get_collector_url() -> str | None:
    """Return the configured remote collector URL, or None for local mode."""
    try:
        from mycelium.config import MyceliumConfig

        return MyceliumConfig.load().metrics.collector_url or None
    except Exception:
        return None


def _fetch_remote_metrics(collector_url: str) -> dict | None:
    """GET /collector/metrics from a remote collector (best-effort)."""
    import urllib.request

    url = f"{collector_url.rstrip('/')}/collector/metrics"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
            return json.loads(resp.read())
    except Exception:
        return None


def _load_local_metrics() -> dict | None:
    """Load metrics from the local metrics.json file (if it exists)."""
    if not _metrics_json().exists():
        return None
    try:
        return json.loads(_metrics_json().read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _load_metrics_json() -> dict | None:
    """Load metrics data, merging local and remote sources in spoke mode.

    Hub / local mode (no ``collector_url`` or it points to localhost):
      Read only the local ``metrics.json``; the Docker collector already
      has everything.

    Spoke mode (``collector_url`` points to a remote hub):
      1. Fetch backend data from the hub's ``/collector/metrics``.
      2. Read the local ``metrics.json`` written by this machine's collector.
      3. Merge: local data wins, with the hub's ``backend`` section overlaid.
    """
    if not _is_spoke_mode():
        return _load_local_metrics()

    hub_url = _get_collector_url()
    hub_data = _fetch_remote_metrics(hub_url) if hub_url else None
    local_data = _load_local_metrics()

    if hub_data is None and local_data is None:
        return None
    if hub_data is None:
        return local_data
    if local_data is None:
        return hub_data

    merged = dict(local_data)
    if "backend" in hub_data:
        merged["backend"] = hub_data["backend"]
    merged.setdefault("updated_at", hub_data.get("updated_at", ""))
    return merged


def _fmt_num(n: int | float | None) -> str:
    if n is None:
        return "-"
    # Show integers without decimals, floats with up to 2 decimals
    if isinstance(n, float) and n == int(n):
        return f"{int(n):,}"
    if isinstance(n, float):
        return f"{n:,.2f}"
    return f"{n:,}"


def _fmt_cost(n: float | None) -> str:
    if n is None:
        return "-"
    return f"${n:,.4f}"


def _parent_room(label: str) -> str:
    """Strip ``:session:<uuid>`` suffix so per-session counters roll up to the
    user-visible parent room. Centralizes bucketing logic so each renderer
    strips consistently (before keying, not just while labeling).
    """
    return label.split(":session:", 1)[0] if ":session:" in label else label


def _aggregate_by_room(
    counters: dict[str, int | float], *, prefix: str = "by_room."
) -> dict[str, dict[str, int | float]]:
    """Group ``<prefix><room>.<metric>`` counters by parent room.

    Returns ``{room: {metric: total}}`` with sessions of the same parent
    folded together via :func:`_parent_room`. Centralizes the
    ``:session:`` rollup rule so it is applied exactly once and the same way
    everywhere.
    """
    out: dict[str, dict[str, int | float]] = {}
    for key, val in counters.items():
        if not key.startswith(prefix):
            continue
        rest = key[len(prefix) :]
        if "." not in rest:
            continue
        room_part, metric = rest.rsplit(".", 1)
        room = _parent_room(room_part)
        bucket = out.setdefault(room, {})
        bucket[metric] = bucket.get(metric, 0) + (val or 0)
    return out


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


def _max_n_width(*hists: dict) -> int:
    """Width of the largest ``count`` (comma-formatted) across histograms.

    Pass every histogram that will share a column in the same panel; each
    panel computes this once and feeds it to ``_fmt_histogram_s`` so its
    ``avg`` columns line up vertically regardless of count magnitude.
    """
    widths = [len(f"{h.get('count', 0):,}") for h in hists if h.get("count", 0) > 0]
    return max(widths) if widths else 0


def _fmt_histogram_s(h: dict, n_width: int) -> str:
    """Format a millisecond histogram as seconds with fixed-width aligned sparkline.

    ``n_width`` is the rendered width of the largest ``n=`` in the
    caller's group (so every row's ``avg`` column lines up vertically).
    Callers compute it once per panel.
    """
    count = h.get("count", 0)
    if count == 0:
        return "-"
    avg = h.get("sum", 0) / count / 1000
    min_v = h.get("min")
    max_v = h.get("max")
    _W = 6  # width for each value column (e.g. " 1.9s" or " 0.0s")

    n_field = f"n={count:,}".rjust(2 + n_width)

    if min_v is not None and max_v is not None:
        min_s = min_v / 1000
        max_s = max_v / 1000
        if abs(max_s - min_s) > 0.05:
            bar = _sparkline(min_s, avg, max_s)
            return (
                f"{_fmt_val_s(min_s):>{_W}} {bar} {_fmt_val_s(max_s):<{_W}} "
                f"[dim]avg {_fmt_val_s(avg):>{_W}} {n_field}[/dim]"
            )

    # Degenerate case: no min/max info or essentially zero spread. Drop
    # the empty-bar slot entirely; saves ~16 chars and still shows the
    # value, the avg (which equals the only datum), and the count.
    return f"{_fmt_val_s(avg):>{_W}} [dim]avg {_fmt_val_s(avg):>{_W}} {n_field}[/dim]"


_BUNDLED_PRICING_JSON = Path(__file__).resolve().parent.parent / "data" / "pricing.json"


def _user_pricing_json() -> Path:
    return _metrics_dir() / "pricing.json"


_pricing_data: dict | None = None


def _load_pricing() -> dict:
    """Load pricing data (cached after first call).

    Resolution order:
      1. ``$MYCELIUM_DATA_DIR/metrics/pricing.json``: written by ``mycelium metrics update-pricing``
      2. Bundled ``data/pricing.json``: shipped with the CLI package
    """
    global _pricing_data
    if _pricing_data is not None:
        return _pricing_data

    for path in (_user_pricing_json(), _BUNDLED_PRICING_JSON):
        try:
            data = json.loads(path.read_text())
            if data.get("models"):
                _pricing_data = data
                return _pricing_data
        except (OSError, json.JSONDecodeError):
            continue

    _pricing_data = {}
    return _pricing_data


def _get_model_pricing(model_name: str) -> tuple[dict, str]:
    """Match a model string (e.g. 'bedrock/global.anthropic.claude-haiku-4-5-…')
    against known pricing.  Returns (pricing_dict, short_label).

    The pricing dict contains:
      - input:                $/token for raw input
      - output:               $/token for output (defaults to 4x input)
      - cache_discount:       fraction off input price for cache reads (e.g. 0.90)
      - cache_write_premium:  fraction MORE than input price for cache writes
                              (e.g. 0.25 means writes cost 1.25x input)
    """
    data = _load_pricing()
    default = data.get("default", {})
    default_input = default.get("input_per_token", 8e-07)
    default_pricing = {
        "input": default_input,
        "output": default.get("output_per_token", default_input * 4),
        "cache_discount": default.get("cache_discount", 0.90),
        "cache_write_premium": default.get("cache_write_premium", 0.25),
    }

    lower = model_name.lower()
    for entry in data.get("models", []):
        if entry["pattern"] in lower:
            inp = entry["input_per_token"]
            return {
                "input": inp,
                "output": entry.get("output_per_token", inp * 4),
                "cache_discount": entry["cache_discount"],
                "cache_write_premium": entry.get("cache_write_premium", 0.25),
            }, entry["pattern"]

    return default_pricing, default.get("label", "unknown model")


def _pricing_generated_at() -> str:
    """Return the generation timestamp and source label from pricing data."""
    data = _load_pricing()
    ts = data.get("generated_at", "")
    date_part = ts.split("T")[0] if "T" in ts else ts
    source = data.get("source", "bundled")
    if source == "litellm_catalog_api":
        return f"{date_part}, via update-pricing" if date_part else ""
    return date_part


def _render_cost_avoidance_table(backend: dict | None) -> None:
    """Local embeddings and indexer operational metrics."""
    if not backend:
        return

    be_counters = backend.get("counters", {})
    be_histograms = backend.get("histograms", {})
    embeddings = be_counters.get("embeddings", {})
    indexer = be_counters.get("indexer", {})

    embed_count = embeddings.get("computed", 0)
    files_indexed = indexer.get("files_indexed", 0)
    files_skipped = indexer.get("files_skipped", 0)
    indexer_runs = indexer.get("runs", 0)

    if embed_count == 0 and files_indexed == 0 and files_skipped == 0 and indexer_runs == 0:
        return

    table = Table(
        title="Local Embeddings & Indexer",
        title_style="bold green",
        title_justify="left",
        show_header=False,
        border_style="dim",
    )
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")

    if embed_count > 0:
        table.add_row("Local embeddings computed", _fmt_num(embed_count))

        by_source_keys = [k for k in embeddings if k.startswith("by_source.")]
        for key in sorted(by_source_keys):
            label = key.replace("by_source.", "  ")
            table.add_row(label, _fmt_num(embeddings[key]))

    embed_lat = be_histograms.get("embeddings.latency_ms", {})
    idx_lat = be_histograms.get("indexer.duration_ms", {})
    embed_idx_n = _max_n_width(embed_lat, idx_lat)
    if embed_lat.get("count", 0) > 0:
        table.add_row("Embedding latency (local)", _fmt_histogram_s(embed_lat, embed_idx_n))

    total_index_files = files_indexed + files_skipped
    if total_index_files > 0 or indexer_runs > 0:
        if embed_count > 0:
            table.add_section()
        if total_index_files > 0:
            skip_pct = files_skipped / total_index_files * 100
            table.add_row("Indexer files processed", _fmt_num(total_index_files))
            table.add_row(
                "  skipped (unchanged)",
                f"[green]{_fmt_num(files_skipped)} ({skip_pct:.0f}%)[/green]",
            )
            table.add_row("  indexed (re-embedded)", _fmt_num(files_indexed))
        else:
            table.add_row("Indexer runs", _fmt_num(indexer_runs))
            table.add_row("  files processed", "0")
        pruned = indexer.get("files_pruned", 0)
        if pruned:
            table.add_row("  pruned (deleted)", _fmt_num(pruned))

    if idx_lat.get("count", 0) > 0:
        table.add_row("Index run duration", _fmt_histogram_s(idx_lat, embed_idx_n))

    console.print(table)
    console.print()


def _render_knowledge_table(backend: dict | None, *, detail: bool = False) -> None:
    """Render a panel showing knowledge ingestion activity."""
    if not backend:
        return
    be_counters = backend.get("counters", {})
    knowledge = be_counters.get("knowledge", {})
    writes = knowledge.get("writes", 0)
    ingestions = knowledge.get("ingestions", 0)
    if writes == 0 and ingestions == 0:
        return

    table = Table(
        title=f"Knowledge Ingestion{_hub_suffix()}",
        title_style="bold magenta",
        title_justify="left",
        show_header=False,
        border_style="dim",
    )
    table.add_column("Metric", style="bold")
    # MAS column makes the by-room sub-section unambiguous: the counter is
    # stored by ``mas_id``, so when the room is no longer in the registry
    # (e.g., transient e2e rooms) the room cell is blank but the mas_id
    # still anchors the row. For aggregate rows above, this cell is empty.
    table.add_column("MAS", style="dim", no_wrap=True)
    table.add_column("Value", justify="right")

    if ingestions > 0:
        table.add_row("Ingestions", "", _fmt_num(ingestions))
    if writes > 0:
        table.add_row("Shared-memory writes", "", _fmt_num(writes))
    errors = knowledge.get("errors", 0)
    if errors > 0:
        table.add_row("Errors", "", f"[red]{_fmt_num(errors)}[/red]")
    skipped = knowledge.get("skipped", 0)
    if skipped > 0:
        table.add_row("Skipped (dedupe)", "", _fmt_num(skipped))

    # Per-MAS / per-room breakdown when the backend has tagged ingestions.
    # We aggregate into ``{mas_id: {ingestions, errors, tokens}}`` then
    # resolve mas_id → room name for display where possible. Unresolved
    # mas_ids (room deleted from /api/rooms) leave the room cell blank
    # but still appear in the MAS column.
    by_mas: dict[str, dict[str, int]] = {}
    for key, val in knowledge.items():
        if not key.startswith("by_mas."):
            continue
        rest = key.removeprefix("by_mas.")
        mas_id, _, metric = rest.partition(".")
        if not mas_id or not metric:
            continue
        by_mas.setdefault(mas_id, {"ingestions": 0, "errors": 0, "estimated_input_tokens": 0})
        if metric in by_mas[mas_id]:
            by_mas[mas_id][metric] += int(val or 0)

    if by_mas:
        room_map = _resolve_room_names_by_mas()
        table.add_section()
        table.add_row("[dim]By room:[/dim]", "[dim]MAS id[/dim]", "")
        ranked = sorted(by_mas.items(), key=lambda kv: kv[1].get("ingestions", 0), reverse=True)
        cap = len(ranked) if detail else 5
        for mas_id, stats in ranked[:cap]:
            room_label = room_map.get(mas_id, "")
            n_ing = stats.get("ingestions", 0)
            n_err = stats.get("errors", 0)
            n_tok = stats.get("estimated_input_tokens", 0)
            parts = [f"{_fmt_num(n_ing)} ingest"]
            if n_tok > 0:
                parts.append(f"~{_fmt_num(n_tok)} tok")
            if n_err > 0:
                parts.append(f"[red]{n_err} err[/red]")
            # Blank room cell when unresolved; the mas_id alone identifies
            # the row, matching the CLI's normal "tombstone" semantics.
            room_cell = f"  {room_label}" if room_label else "  [dim](deleted)[/dim]"
            table.add_row(room_cell, _format_mas(mas_id, detail=detail), "  ·  ".join(parts))
        if len(ranked) > cap:
            table.add_row(
                f"  [dim]...and {len(ranked) - cap} more (use --detail to expand)[/dim]",
                "",
                "",
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
        title=f"Mycelium Backend LLM Usage{_hub_suffix()}",
        title_style="bold magenta",
        title_justify="left",
        show_header=False,
        border_style="dim",
    )
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")

    # Break out each backend LLM operation by its call count. We deliberately
    # do NOT show per-operation tokens here because these sites (health_probe
    # today; future heartbeats) are by design ~zero-token; surfacing the call
    # count is enough to confirm they're firing without cluttering the table.
    # The ``count(".") == 1`` filter keeps only base operation counters,
    # excluding any per-operation token/error sub-keys.
    by_op_keys = sorted(k for k in llm if k.startswith("by_operation.") and k.count(".") == 1)
    if by_op_keys:
        table.add_section()
        table.add_row("Backend LLM calls", "")
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
    llm_sub = [
        be_histograms[k]
        for k in be_histograms
        if k.startswith("llm.latency_ms.") and k != "llm.latency_ms"
    ]
    llm_n = _max_n_width(llm_lat, *llm_sub)
    if llm_lat.get("count", 0) > 0:
        table.add_section()
        table.add_row("LLM latency (all)", _fmt_histogram_s(llm_lat, llm_n))

    for key in sorted(be_histograms):
        if key.startswith("llm.latency_ms.") and key != "llm.latency_ms":
            h = be_histograms[key]
            if h.get("count", 0) > 0:
                label = key.replace("llm.latency_ms.", "  ")
                table.add_row(label, _fmt_histogram_s(h, llm_n))

    # Knowledge graph stats
    knowledge = be_counters.get("knowledge", {})
    if knowledge.get("ingestions", 0) > 0:
        table.add_section()
        table.add_row("Knowledge ingestions", _fmt_num(knowledge["ingestions"]))
        table.add_row("  concepts extracted", _fmt_num(knowledge.get("concepts_extracted", 0)))
        table.add_row("  relations extracted", _fmt_num(knowledge.get("relations_extracted", 0)))
        est_tokens = knowledge.get("estimated_input_tokens", 0)
        if est_tokens:
            table.add_row("  est. input tokens", _fmt_num(est_tokens))
        kg_errors = knowledge.get("errors", 0)
        if kg_errors:
            table.add_row("  graph store errors", f"[red]{_fmt_num(kg_errors)}[/red]")
        kg_lat = be_histograms.get("knowledge.ingestion_duration_ms", {})
        if kg_lat.get("count", 0) > 0:
            table.add_row("  ingestion duration", _fmt_histogram_s(kg_lat, _max_n_width(kg_lat)))

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
                table.add_row(
                    "  search latency", _fmt_histogram_s(search_lat, _max_n_width(search_lat))
                )

    console.print(table)
    console.print()


def _estimate_cost(
    input_tokens: float,
    output_tokens: float,
    cache_read_tokens: float,
    cache_write_tokens: float,
    model: str,
) -> float:
    """Estimate cost in USD from token counts and model pricing.

    Token counts are typed as ``float`` rather than ``int`` because the
    upstream metrics snapshots (``be_counters``/``myc_llm``) are typed as
    ``dict[str, Any]`` and ``dict.get(..., 0)`` widens to ``int | float``
    even when the runtime values are whole-number token counts. The
    arithmetic below is rate * count, which is identical under either
    type, so widening is a no-op at runtime and avoids forcing every
    caller to ``int(...)``-cast the dict value.
    """
    pricing, _ = _get_model_pricing(model)
    input_rate = pricing["input"]
    output_rate = pricing["output"]
    cache_read_rate = input_rate * (1 - pricing["cache_discount"])
    cache_write_rate = input_rate * (1 + pricing["cache_write_premium"])

    non_cached_input = max(input_tokens - cache_read_tokens, 0)
    return (
        non_cached_input * input_rate
        + cache_read_tokens * cache_read_rate
        + output_tokens * output_rate
        + cache_write_tokens * cache_write_rate
    )


def _render_cost_estimates(backend: dict | None) -> None:
    """What the backend's own LLM calls cost, reported or estimated, by room."""
    from mycelium.config import MyceliumConfig

    try:
        config = MyceliumConfig.load()
        est_model = config.llm.model or ""
    except Exception:
        est_model = ""

    table = Table(
        title="Cost Estimates",
        title_style="bold yellow",
        title_justify="left",
        show_header=True,
        header_style="dim",
        border_style="dim",
    )
    table.add_column("Source", style="bold")
    table.add_column("Tokens", justify="right")
    table.add_column("Cost", justify="right")
    table.add_column("Pricing", style="dim")

    total_cost = 0.0

    # ── Mycelium Backend LLM (estimated) ───────────────────────────────
    be_counters = (backend or {}).get("counters", {})
    myc_llm = be_counters.get("llm", {})
    myc_calls = myc_llm.get("calls", 0)

    if myc_calls > 0:
        myc_prompt = myc_llm.get("input_tokens", 0)
        myc_compl = myc_llm.get("output_tokens", 0)
        myc_total = myc_prompt + myc_compl
        myc_reported = myc_llm.get("cost_usd", 0.0)

        if myc_reported > 0:
            table.add_row(
                "[magenta]Mycelium LLM[/magenta]",
                _fmt_num(myc_total),
                _fmt_cost(myc_reported),
                "catalog (provider-reported)",
            )
            total_cost += myc_reported
        else:
            myc_est = _estimate_cost(
                input_tokens=myc_prompt,
                output_tokens=myc_compl,
                cache_read_tokens=0,
                cache_write_tokens=0,
                model=est_model,
            )
            _, model_label = _get_model_pricing(est_model)
            table.add_row(
                "[magenta]Mycelium LLM[/magenta]",
                _fmt_num(myc_total),
                _fmt_cost(myc_est),
                f"est. ({model_label})",
            )
            total_cost += myc_est

        # Per-room breakdown under Mycelium LLM. Aggregates by_room.* keys
        # when present; skips quietly if unavailable. Prefers provider-reported
        # cost when available, falling back to estimate. All rooms shown.
        myc_by_room = _aggregate_by_room(myc_llm, prefix="by_room.")
        if myc_by_room:
            ranked = sorted(
                myc_by_room.items(),
                key=lambda kv: kv[1].get("input_tokens", 0) + kv[1].get("output_tokens", 0),
                reverse=True,
            )
            shown = [
                (r, d)
                for r, d in ranked
                if (d.get("input_tokens", 0) + d.get("output_tokens", 0) > 0)
                or d.get("cost_usd", 0.0) > 0
            ]
            if shown:
                table.add_row("  [dim italic]By room:[/dim italic]", "", "", "")
                for room, data in shown:
                    r_prompt = data.get("input_tokens", 0)
                    r_compl = data.get("output_tokens", 0)
                    r_total = r_prompt + r_compl
                    r_reported = data.get("cost_usd", 0.0)
                    if r_reported > 0:
                        table.add_row(
                            f"    [dim]{room}[/dim]",
                            f"[dim]{_fmt_num(r_total)}[/dim]",
                            f"[dim]{_fmt_cost(r_reported)}[/dim]",
                            "[dim]catalog (provider-reported)[/dim]",
                        )
                    else:
                        r_cost = _estimate_cost(
                            input_tokens=r_prompt,
                            output_tokens=r_compl,
                            cache_read_tokens=0,
                            cache_write_tokens=0,
                            model=est_model,
                        )
                        table.add_row(
                            f"    [dim]{room}[/dim]",
                            f"[dim]{_fmt_num(r_total)}[/dim]",
                            f"[dim]{_fmt_cost(r_cost)}[/dim]",
                            "[dim]est.[/dim]",
                        )

    # ── Totals ─────────────────────────────────────────────────────────
    if total_cost > 0:
        table.add_section()
        table.add_row("[bold]Total[/bold]", "", f"[bold]{_fmt_cost(total_cost)}[/bold]", "")
    elif myc_calls == 0:
        table.add_row("[dim]No cost data yet[/dim]", "", "", "")

    console.print(table)

    # Pricing source note
    gen_date = _pricing_generated_at()
    if gen_date:
        console.print(f"[dim]  Estimates use catalog pricing data (updated {gen_date})[/dim]")
    console.print()
