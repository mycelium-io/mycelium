# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

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


def _data_dir() -> Path:
    """Resolve the Mycelium data directory, respecting MYCELIUM_DATA_DIR."""
    return Path(os.environ.get("MYCELIUM_DATA_DIR") or Path.home() / ".mycelium")


def _metrics_dir() -> Path:
    """Resolve the metrics subdirectory under the data dir."""
    return _data_dir() / "metrics"


def _metrics_json() -> Path:
    return _metrics_dir() / "metrics.json"


def _pid_file() -> Path:
    return _metrics_dir() / "collector.pid"


console = Console()


def _resolve_port(cli_port: int | None) -> int:
    if cli_port is not None:
        if not 1 <= cli_port <= 65535:
            typer.secho(f"✗ Invalid port {cli_port} (must be 1–65535)", fg=typer.colors.RED)
            raise typer.Exit(1)
        return cli_port
    env = os.environ.get(_ENV_PORT)
    if env:
        try:
            p = int(env)
            if 1 <= p <= 65535:
                return p
        except ValueError:
            pass
    return _DEFAULT_PORT


def _read_pid_file() -> tuple[int | None, int]:
    """Read the PID and port from the collector PID file.

    Returns (pid, port).  ``pid`` is None when the file is missing or
    unparsable; ``port`` falls back to ``_DEFAULT_PORT``.
    """
    if not _pid_file().exists():
        return None, _DEFAULT_PORT
    try:
        lines = _pid_file().read_text().strip().splitlines()
        if not lines:
            return None, _DEFAULT_PORT
        pid = int(lines[0])
        port = int(lines[1]) if len(lines) >= 2 else _DEFAULT_PORT
        return pid, port
    except (OSError, ValueError, IndexError):
        return None, _DEFAULT_PORT


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
    collector_alive = False
    collector_pid, collector_port = _read_pid_file()
    if collector_pid is not None:
        try:
            os.kill(collector_pid, 0)
            collector_alive = True
        except OSError:
            collector_alive = False
    if collector_alive:
        console.print(
            f"[green]✓[/green] Collector running  PID {collector_pid}  port {collector_port}"
        )
    else:
        console.print("[red]✗[/red] Collector not running")
        if _pid_file().exists():
            console.print(
                "  [dim]Stale PID file exists — run [bold]mycelium metrics stop[/bold] to clean up[/dim]"
            )
        all_ok = False

    collector_log = _metrics_dir() / "collector.log"
    if not collector_alive and collector_log.exists():
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
            sessions = data.get("sessions", [])
            counters = data.get("counters", {})
            msgs = counters.get("messages", {}).get("processed", 0)
            total_tok = counters.get("tokens", {}).get("total", {}).get("total", 0)

            console.print(f"[green]✓[/green] Data file          {_metrics_json()}")
            console.print(
                f"  [dim]Last updated {age_str}  •  {msgs} messages  •  {len(sessions)} sessions  •  {total_tok:,} tokens[/dim]"
            )
        except Exception:
            console.print(f"[yellow]⚠[/yellow] Data file exists but unreadable: {_metrics_json()}")
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
            ep_port = parsed.port or (443 if parsed.scheme == "https" else 80)
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
        console.print(
            "  [dim]Run [bold]mycelium adapter add openclaw --step=otel[/bold] to configure[/dim]"
        )
        all_ok = False
    else:
        console.print("[yellow]⚠[/yellow] No openclaw.json found (gateway not configured)")
        all_ok = False

    # ── OpenClaw model cost / compat flags ─────────────────────────────
    if oc_config_path.exists():
        try:
            cfg = json.loads(oc_config_path.read_text())
            zero_cost_models: list[str] = []
            missing_compat: list[str] = []
            for _pname, prov in cfg.get("models", {}).get("providers", {}).items():
                for m in prov.get("models", []):
                    mid = m.get("id", "")
                    if not mid:
                        continue
                    cost = m.get("cost", {})
                    if all(cost.get(k, 0) == 0 for k in ("input", "output")):
                        zero_cost_models.append(mid)
                    if not m.get("compat", {}).get("supportsUsageInStreaming"):
                        missing_compat.append(mid)
            if zero_cost_models:
                console.print(
                    f"[yellow]⚠[/yellow] Model cost = $0     {', '.join(zero_cost_models)}"
                )
                console.print(
                    "  [dim]OpenClaw will report $0 cost via OTLP. "
                    "Run [bold]mycelium adapter add openclaw --step=otel[/bold] to patch.[/dim]"
                )
                all_ok = False
            elif otel_enabled:
                console.print("[green]✓[/green] Model cost          configured for all models")
            if missing_compat:
                console.print(f"[yellow]⚠[/yellow] Missing compat      {', '.join(missing_compat)}")
                console.print(
                    "  [dim]supportsUsageInStreaming not set — streaming token counts may be lost. "
                    "Run [bold]mycelium adapter add openclaw --step=otel[/bold] to patch.[/dim]"
                )
                all_ok = False
            elif otel_enabled:
                console.print("[green]✓[/green] Streaming compat    set for all models")
        except Exception:
            pass

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
        console.print("[bold yellow]Pipeline has issues — see above[/bold yellow]")


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


@app.command("collect")
def collect(
    port: int | None = typer.Option(
        None, "--port", "-p", help=f"OTLP receiver port (default: {_DEFAULT_PORT})"
    ),
    backend_url: str | None = typer.Option(
        None,
        "--backend-url",
        "-b",
        help="Mycelium backend URL for polling /api/observability (default: server.api_url from config)",
    ),
    fg: bool = typer.Option(
        False, "--fg", help="Run collector in the foreground (default: background)"
    ),
) -> None:
    """Start the OTLP HTTP receiver to collect OpenClaw telemetry."""
    if not _check_otel_deps():
        raise typer.Exit(1)

    if _docker_collector_running():
        typer.secho(
            "The mycelium-collector Docker container is already running on this host.\n"
            "Use 'mycelium logs mycelium-collector' to view its output, or\n"
            "'mycelium down' to stop it before starting a host-side collector.",
            fg=typer.colors.YELLOW,
        )
        return

    from mycelium.config import MyceliumConfig

    resolved_port = _resolve_port(port)
    if backend_url is None:
        backend_url = MyceliumConfig.load().server.api_url

    if not fg:
        _metrics_dir().mkdir(parents=True, exist_ok=True)

        old_pid, old_port = _read_pid_file()
        if old_pid is not None:
            try:
                os.kill(old_pid, 0)
                typer.secho(
                    f"Collector already running (PID {old_pid}) on port {old_port}",
                    fg=typer.colors.YELLOW,
                )
                return
            except OSError:
                _pid_file().unlink(missing_ok=True)

        # Guard: even without a valid PID file, check if the port is busy.
        # Use SO_REUSEADDR so lingering TIME_WAIT sockets from a just-killed
        # collector don't cause a false "already running" report.
        import socket as _sock

        _probe = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
        _probe.setsockopt(_sock.SOL_SOCKET, _sock.SO_REUSEADDR, 1)
        try:
            _probe.bind(("127.0.0.1", resolved_port))
        except OSError:
            typer.secho(
                f"Collector already running on port {resolved_port} (stale PID file)",
                fg=typer.colors.YELLOW,
            )
            return
        finally:
            _probe.close()

        log_file = _metrics_dir() / "collector.log"
        log_fh = open(log_file, "a")  # noqa: SIM115

        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "mycelium.collector_main",
                "--port",
                str(resolved_port),
                "--backend-url",
                backend_url,
            ],
            stdout=log_fh,
            stderr=log_fh,
            start_new_session=True,
        )

        _pid_file().write_text(f"{proc.pid}\n{resolved_port}\n")

        import time as _time

        _time.sleep(0.5)
        exit_code = proc.poll()
        if exit_code is not None:
            _pid_file().unlink(missing_ok=True)
            typer.secho(
                f"✗ Collector exited immediately (code {exit_code}). Check {log_file}",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)

        typer.secho(f"✓ Collector started (PID {proc.pid})", fg=typer.colors.GREEN)
        typer.echo(f"  OTLP receiver on port {resolved_port}")
        typer.echo(f"  Metrics file: {_metrics_json()}")
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
            bg_pid, _ = _read_pid_file()
            if bg_pid is not None:
                try:
                    os.kill(bg_pid, 0)
                    typer.echo(
                        f"  A background collector is running (PID {bg_pid}).\n"
                        f"  Stop it first:  mycelium metrics stop"
                    )
                except OSError:
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

        scrape_targets = MyceliumConfig.load().resolve_scrape_targets()
        run_collector(
            resolved_port,
            _metrics_json(),
            backend_api_url=backend_url,
            scrape_targets=scrape_targets,
        )


@app.command("stop")
def stop() -> None:
    """Stop the background OTLP collector."""
    if not _pid_file().exists():
        typer.secho("No collector running (PID file not found).", fg=typer.colors.YELLOW)
        raise typer.Exit(0)

    pid, _ = _read_pid_file()
    if pid is None:
        typer.secho("Could not read collector PID.", fg=typer.colors.RED)
        _pid_file().unlink(missing_ok=True)
        return

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        typer.secho(f"Collector (PID {pid}) already exited.", fg=typer.colors.YELLOW)
        _pid_file().unlink(missing_ok=True)
        return
    except OSError as exc:
        typer.secho(f"Could not stop collector (PID {pid}): {exc}", fg=typer.colors.RED)
        return

    import time as _time

    stopped = False
    for _ in range(20):
        _time.sleep(0.1)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            stopped = True
            break

    if stopped:
        typer.secho(f"✓ Collector stopped (PID {pid})", fg=typer.colors.GREEN)
        _pid_file().unlink(missing_ok=True)
    else:
        typer.secho(
            f"⚠ Collector (PID {pid}) still running after SIGTERM. "
            "It may need to be killed manually.",
            fg=typer.colors.YELLOW,
        )


@app.command("reset")
def reset() -> None:
    """Delete collected metrics data."""
    if _metrics_json().exists():
        _metrics_json().unlink()
        typer.secho("✓ Metrics data cleared.", fg=typer.colors.GREEN)
    else:
        typer.echo("No metrics data to clear.")


_LITELLM_CATALOG_API = "https://api.litellm.ai/model_catalog"

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
    """Fetch a single model's pricing from the LiteLLM Model Catalog API."""
    import httpx

    url = f"{_LITELLM_CATALOG_API}/{litellm_key}"
    try:
        resp = httpx.get(url, headers={"Accept": "application/json"}, timeout=10.0)
        if resp.status_code != 200:
            return None
        return resp.json()
    except (httpx.HTTPError, ValueError):
        return None


def _build_pricing_entry(spec: dict, api_data: dict) -> dict | None:
    """Transform LiteLLM Catalog API response into a pricing.json model entry."""
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
    """Extract model names from collected metrics not covered by _TRACKED_MODELS.

    Reads metrics.json from the metrics directory and returns model strings from:
      - OTLP: ``counters.tokens.by_model`` keys
      - Backend: ``backend.counters.llm.by_model.*`` keys
    """
    try:
        data = json.loads(_metrics_json().read_text())
    except (OSError, json.JSONDecodeError):
        return []

    raw_models: set[str] = set()

    otlp_by_model = data.get("counters", {}).get("tokens", {}).get("by_model", {})
    raw_models.update(otlp_by_model.keys())

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
    """Fetch latest LLM pricing from the LiteLLM Model Catalog API.

    Writes updated pricing to ``$MYCELIUM_DATA_DIR/metrics/pricing.json``,
    which is used by ``mycelium metrics show cost`` for cost estimates.
    Falls back to the bundled pricing.json when the local cache is missing.

    Models are sourced from three places (in order):
      1. Built-in tracked models (14 common Anthropic/OpenAI models)
      2. Auto-discovered models from collected metrics (metrics/metrics.json)
      3. Manually added models via --add
    """
    from datetime import UTC, datetime

    console.print("[bold]Fetching pricing from LiteLLM Model Catalog API...[/bold]")

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

    _metrics_dir().mkdir(parents=True, exist_ok=True)
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


_VALID_SECTIONS = ("openclaw", "claude", "mycelium", "cfn", "cost", "all")
_SECTION_ALIASES: dict[str, str] = {}  # reserved for future aliases


@app.command("show")
def show(
    section: str | None = typer.Argument(
        None,
        help="Section to show: openclaw, claude, mycelium, cfn, cost, all. Omit for overview.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
    workspace: bool = typer.Option(False, "--workspace", help="Show per-file workspace breakdown"),
    include_heartbeat: bool = typer.Option(
        False,
        "--include-heartbeat",
        help="Include OpenClaw 'heartbeat' channel tokens in totals (excluded by default).",
    ),
) -> None:
    """
    Display collected metrics with agent metadata and workspace sizes.

    With no argument, shows a compact overview. Pass a section name for
    full detail: openclaw, claude, mycelium, cfn.
    """
    if section is not None:
        section = section.lower()
        if section not in _VALID_SECTIONS:
            typer.secho(
                f"Unknown section '{section}'. Valid: openclaw, claude, mycelium, cfn, cost, all",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)
        section = _SECTION_ALIASES.get(section, section)

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

    # ── Dispatch by section ───────────────────────────────────────────
    if section is None:
        _render_overview(otel_data, oc_cost, backend_data, include_heartbeat=include_heartbeat)
        return

    show_openclaw = section in ("openclaw", "all")
    show_claude = section in ("claude", "all")
    show_mycelium = section in ("mycelium", "all")
    show_cfn = section in ("cfn", "all")
    show_cost = section in ("cost", "all")

    if show_claude:
        console.print(
            "[bold blue]Claude Code[/bold blue]\n"
            "[dim]Metrics collection for the Claude Code adapter is not yet wired.\n"
            "Once connected, token usage and session data will appear here.[/dim]\n"
        )

    if show_openclaw:
        _render_summary_table(
            otel_data,
            oc_status,
            include_background=include_heartbeat,
        )
        _render_cache_efficiency_table(otel_data, include_background=include_heartbeat)
        _render_agent_table(otel_data, agents_meta)
        if otel_data and otel_data.get("sessions"):
            _render_session_table(otel_data["sessions"])
        if workspace:
            _render_workspace_tables(agents_meta)

    if show_mycelium:
        if not backend_data:
            console.print(
                "[dim]Backend metrics not collected (spoke mode or collector not running)[/dim]"
            )
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
                _render_knowledge_table(backend_data)
                rendered = True

            if not rendered:
                table = Table(
                    title="Mycelium Backend",
                    title_style="bold magenta",
                    title_justify="left",
                    show_header=False,
                    border_style="dim",
                )
                table.add_column("Info")
                table.add_row(
                    "No activity yet — this section populates when the backend\n"
                    "processes embeddings, LLM calls, knowledge, or briefings."
                )
                console.print(table)
                console.print()

    if show_cfn:
        _render_coordination_table(backend_data)
        _render_cfn_llm_usage_table(backend_data)
        _render_cfn_transport_table(backend_data)
        _render_cfn_scrape_table((otel_data or {}).get("scrape"))
        if not backend_data and not (otel_data or {}).get("scrape"):
            console.print(
                "[dim]CFN metrics not available (spoke mode or no CFN stack running)[/dim]"
            )
            console.print()

    if show_cost:
        _render_cost_estimates(
            otel_data, oc_cost, backend_data, include_heartbeat=include_heartbeat
        )

    _render_field_legend()
    console.print()


def _render_overview(
    otel: dict | None,
    oc_cost: dict | None,
    backend: dict | None,
    *,
    include_heartbeat: bool = False,
) -> None:
    """Compact overview pulling headline numbers from all data sources."""
    table = Table(
        title="Mycelium Metrics Overview",
        title_style="bold",
        title_justify="left",
        show_header=False,
        border_style="dim",
    )
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")

    # ── OpenClaw section ──────────────────────────────────────────────
    fg_tokens, _ = _oc_token_totals(otel, include_background=include_heartbeat)
    total_tokens = fg_tokens.get("total", 0)
    otel_sessions = (otel or {}).get("sessions", [])

    cache_read = fg_tokens.get("cache_read", 0)
    cache_write = fg_tokens.get("cache_write", 0)
    input_tokens = fg_tokens.get("input", 0)
    denom = cache_read + cache_write + input_tokens
    cache_rate = (cache_read / denom * 100) if denom > 0 and cache_read > 0 else 0.0

    table.add_row("[cyan]Adapters (OpenClaw)[/cyan]", "")
    table.add_row("  Tokens", _fmt_num(total_tokens))
    table.add_row("  Sessions", _fmt_num(len(otel_sessions)))
    if cache_rate > 0:
        table.add_row("  Cache hit rate", f"{cache_rate:.0f}%")

    # ── Mycelium backend section ──────────────────────────────────────
    table.add_section()
    if backend:
        be_counters = backend.get("counters", {})
        llm = be_counters.get("llm", {})
        embeddings = be_counters.get("embeddings", {})
        memory = be_counters.get("memory", {})
        knowledge = be_counters.get("knowledge", {})
        indexer = be_counters.get("indexer", {})

        table.add_row("[magenta]Mycelium Backend[/magenta]", "")
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
        table.add_row(
            "[magenta]Mycelium Backend[/magenta]", "[dim]not collected (spoke mode)[/dim]"
        )

    # ── CFN section ───────────────────────────────────────────────────
    table.add_section()
    if backend:
        be_counters = backend.get("counters", {})
        coord = be_counters.get("coordination", {})
        cfn = be_counters.get("cfn", {})

        cfn_llm = be_counters.get("cfn_llm", {})
        has_cfn = (
            coord.get("sessions_started", 0) > 0
            or cfn.get("calls", 0) > 0
            or cfn_llm.get("calls", 0) > 0
        )

        table.add_row("[blue]CFN[/blue]", "")
        if has_cfn:
            started = coord.get("sessions_started", 0)
            completed = coord.get("sessions_completed", 0)
            success = coord.get("outcome.success", 0)
            failure = coord.get("outcome.failure", 0)
            if started > 0:
                table.add_row(
                    "  Coordination",
                    f"{_fmt_num(started)} started, {_fmt_num(completed)} completed",
                )
                if success + failure > 0:
                    table.add_row(
                        "  Outcomes",
                        f"[green]{success}[/green] consensus, [red]{failure}[/red] failed",
                    )
            rounds = coord.get("rounds", 0)
            if rounds > 0:
                table.add_row("  Rounds", _fmt_num(rounds))
            total_calls = cfn.get("calls", 0)
            if total_calls > 0:
                errors = cfn.get("errors", 0)
                err_str = f"  [red]({errors} errors)[/red]" if errors else ""
                table.add_row("  Transport calls", f"{_fmt_num(total_calls)}{err_str}")
            llm_calls = cfn_llm.get("calls", 0)
            if llm_calls > 0:
                prompt_tok = cfn_llm.get("input_tokens", 0)
                compl_tok = cfn_llm.get("output_tokens", 0)
                table.add_row("  LLM calls (engines)", _fmt_num(llm_calls))
                table.add_row(
                    "  LLM tokens",
                    f"{_fmt_num(prompt_tok)} in / {_fmt_num(compl_tok)} out",
                )
        else:
            table.add_row("  [dim]No CFN activity yet[/dim]", "")
    else:
        table.add_row("[blue]CFN[/blue]", "[dim]not collected (spoke mode)[/dim]")

    console.print(table)
    console.print()
    console.print("[dim]Detail: mycelium metrics show <openclaw|mycelium|cfn|cost>[/dim]")
    console.print()


def _load_metrics_json() -> dict | None:
    if not _metrics_json().exists():
        return None
    try:
        return json.loads(_metrics_json().read_text())
    except (json.JSONDecodeError, OSError):
        return None


_OC_STATUS_CACHE = _data_dir() / "openclaw_status_cache.json"
_OC_STATUS_MAX_AGE_S = 60


def _get_openclaw_status() -> dict | None:
    """Get openclaw status, using a short-lived cache to avoid blocking the CLI.

    ``openclaw status --json`` can take 10+ seconds.  We cache the result for
    up to 60s so repeated ``metrics show`` calls are fast.  A null result is
    also cached to avoid re-attempting a slow/failing subprocess.
    """
    import time as _t

    # Try cache first
    try:
        if _OC_STATUS_CACHE.exists():
            age = _t.time() - _OC_STATUS_CACHE.stat().st_mtime
            if age < _OC_STATUS_MAX_AGE_S:
                raw = _OC_STATUS_CACHE.read_text()
                if not raw.strip() or raw.strip() == "null":
                    return None
                return json.loads(raw)
    except (OSError, json.JSONDecodeError):
        pass

    # Cache miss or stale — fetch fresh
    data = _fetch_openclaw_status()
    try:
        _OC_STATUS_CACHE.write_text(json.dumps(data) if data else "null")
    except OSError:
        pass
    return data


def _fetch_openclaw_status() -> dict | None:
    try:
        result = subprocess.run(
            ["openclaw", "status", "--json"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=15,
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        pass
    finally:
        _restore_terminal()
    return None


def _restore_terminal() -> None:
    """Reset terminal to cooked/canonical mode if stdin is a tty.

    Node-based CLIs (like openclaw) may put the terminal into raw mode for
    interactive prompts.  If the subprocess is killed or exits uncleanly the
    terminal stays in raw mode, breaking readline (arrow keys, Ctrl-P, etc.).
    """
    if not sys.stdin.isatty():
        return
    try:
        import termios

        fd = sys.stdin.fileno()
        attrs = termios.tcgetattr(fd)
        # If ICANON or ECHO are off, the terminal is in raw/cbreak mode
        if not (attrs[3] & termios.ICANON) or not (attrs[3] & termios.ECHO):
            subprocess.run(["stty", "sane"], stdin=sys.stdin, check=False)
    except (ImportError, OSError, ValueError):
        pass


def _extract_agents(oc: dict | None) -> list[dict]:
    """Extract the agent list from ``openclaw status --json`` or config fallback.

    Tries ``oc["agents"]["agents"]`` first (legacy), then ``oc["agents"]["list"]``
    (current openclaw config layout).  If ``oc`` is None (status command failed or
    timed out), falls back to reading ``~/.openclaw/openclaw.json`` directly.
    """
    agents_section = None
    if oc:
        agents_section = oc.get("agents")
    else:
        agents_section = _read_openclaw_agents_from_config()

    if isinstance(agents_section, dict):
        agent_list = agents_section.get("agents") or agents_section.get("list") or []
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


def _read_openclaw_agents_from_config() -> dict | None:
    """Read agents section directly from ~/.openclaw/openclaw.json as fallback."""
    config_path = Path.home() / ".openclaw" / "openclaw.json"
    try:
        with open(config_path) as f:
            data = json.load(f)
        return data.get("agents")
    except (OSError, json.JSONDecodeError):
        return None


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
    _, port = _read_pid_file()
    return port


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


def _max_n_width(*hists: dict) -> int:
    """Width of the largest ``count`` (comma-formatted) across histograms.

    Pass every histogram that will share a column in the same panel; each
    panel computes this once and feeds it to ``_fmt_histogram_s`` /
    ``_fmt_prom_latency`` so their ``avg`` columns line up vertically
    regardless of count magnitude.
    """
    widths = [len(f"{h.get('count', 0):,}") for h in hists if h.get("count", 0) > 0]
    return max(widths) if widths else 0


def _fmt_histogram_s(h: dict, n_width: int) -> str:
    """Format a millisecond histogram as seconds with fixed-width aligned sparkline.

    ``n_width`` is the rendered width of the largest ``n=`` in the
    caller's group (so every row's ``avg`` column lines up vertically).
    Callers compute it once per panel — see ``_render_cfn_coord_table``
    and ``_render_cfn_transport_table``.
    """
    count = h.get("count", 0)
    if count == 0:
        return "—"
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
    # the empty-bar slot entirely — saves ~16 chars and still shows the
    # value, the avg (which equals the only datum), and the count.
    return f"{_fmt_val_s(avg):>{_W}} [dim]avg {_fmt_val_s(avg):>{_W}} {n_field}[/dim]"


def _fmt_prom_latency(lat: dict, n_width: int) -> str:
    """Format a Prometheus-bucket latency dict for the CFN scrape panel.

    Visual grammar mirrors ``_fmt_histogram_s`` (used by CFN Transport
    Health) so both CFN panels read with the same rhythm — fixed-width
    numeric columns, label-then-value, dim ``n=`` suffix:

        avg  614µs  p50   —      p99   —       n=17,968
        avg 49.0ms  p50   —      p99   —       n=2

    Differences from ``_fmt_histogram_s``: no min/max sparkline (Prometheus
    histograms can't give us those), p50/p99 columns instead, and a unit-
    aware value formatter so sub-millisecond /health latencies don't read
    as ``0.0s``.

    ``avg`` is always shown (computed from exact ``_sum / _count``, the
    only truly precise number Prometheus histograms give us). p50/p99 are
    *suppressed with ``—``* — keeping the column in place — when the
    bucket layout has insufficient resolution (no observations cross a
    bucket boundary). Today CFN's mgmt-plane uses ``[100, 500, 1000]ms``
    buckets and every observation lands in the first one; once
    cfn_component_metrics_reconciliation.md item #6 ships finer buckets,
    real p50/p99 numbers will appear with no code change.
    """
    count = lat.get("count", 0)
    if count == 0:
        return "—"

    from mycelium.prom_scrape import histogram_quantile

    buckets = lat.get("buckets") or []
    avg_ms = lat.get("sum", 0.0) / count if count else 0.0

    # "Useful" buckets = at least one cross-bucket transition exists.
    finite = [(b, c) for b, c in buckets if not (isinstance(b, float) and b == float("inf"))]
    crossings = sum(1 for i in range(1, len(finite)) if finite[i][1] > finite[i - 1][1])
    p50_ms = histogram_quantile(0.50, buckets) if crossings >= 1 else None
    p99_ms = histogram_quantile(0.99, buckets) if crossings >= 1 else None

    # Fixed value-column width chosen to fit ``999.9ms`` and ``99.99s`` —
    # the two longest realistic values from _fmt_ms. Right-aligned so the
    # decimal points stack cleanly when scanning a column of routes.
    _W = 7

    def _slot(v_ms: float) -> str:
        return f"{_fmt_ms(v_ms):>{_W}}"

    # Conditional rendering keeps the row on a single line in the common
    # CFN-today case (coarse buckets → no percentiles) and saves ~16 chars
    # per row that Rich would otherwise wrap. When buckets get finer (see
    # cfn_component_metrics_reconciliation.md item #6), the p50/p99
    # columns reappear automatically.
    parts = [f"avg {_slot(avg_ms)}"]
    if p50_ms is not None:
        parts.append(f"p50 {_slot(p50_ms)}")
    if p99_ms is not None:
        parts.append(f"p99 {_slot(p99_ms)}")
    # Pad ``n=`` to the caller-supplied width so the ``avg`` column lines
    # up across rows even when counts differ by orders of magnitude
    # (e.g. /health at n=18,001 next to /api/...register at n=2). Width
    # is the *rendered* width of the largest count's comma-formatted
    # string in this group; falls back to natural width if unspecified.
    n_field = f"n={count:,}".rjust(2 + n_width)
    parts.append(f"[dim]{n_field}[/dim]")
    return "  ".join(parts)


def _fmt_ms(ms: float | None) -> str:
    """Format a millisecond value with a sensibly chosen unit.

    Sub-millisecond → µs (so ``/health`` stops reading as ``0.0s``).
    Sub-second     → ms.
    Anything else  → seconds with two decimals.
    """
    if ms is None:
        return "—"
    if ms < 1.0:
        return f"{ms * 1000:.0f}µs"
    if ms < 1000.0:
        return f"{ms:.1f}ms"
    return f"{ms / 1000:.2f}s"


def _fmt_histogram_raw(h: dict) -> str:
    """Format a unitless histogram with fixed-width aligned sparkline."""
    count = h.get("count", 0)
    if count == 0:
        return "—"
    avg = h.get("sum", 0) / count
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
    return f"{avg:>{_W}.1f}  {bar} {'':<{_W}}  [dim]avg {avg:>{_W}.1f}  n={count}[/dim]"


def _fmt_size(nbytes: int) -> str:
    if nbytes < 1024:
        return f"{nbytes} B"
    if nbytes < 1024 * 1024:
        return f"{nbytes / 1024:.1f} KB"
    return f"{nbytes / (1024 * 1024):.1f} MB"


def _render_summary_table(
    otel: dict | None,
    oc: dict | None,
    *,
    include_background: bool = False,
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

    fg_tokens, bg_tokens = _oc_token_totals(otel, include_background=include_background)
    bg_total = bg_tokens.get("total", 0)

    title_suffix = "" if include_background else " (excl. heartbeat)"
    table.add_row(
        f"Total tokens{title_suffix}",
        _fmt_num(fg_tokens.get("total", 0)),
    )
    table.add_row("  input", _fmt_num(fg_tokens.get("input", 0)))
    table.add_row("  output", _fmt_num(fg_tokens.get("output", 0)))
    table.add_row("  cache read", _fmt_num(fg_tokens.get("cache_read", 0)))
    table.add_row("  cache write", _fmt_num(fg_tokens.get("cache_write", 0)))
    if not include_background and bg_total > 0:
        grand = bg_total + fg_tokens.get("total", 0)
        bg_pct = bg_total / grand * 100 if grand else 0
        table.add_row(
            "  [dim]heartbeat (background)[/dim]",
            f"[dim]{_fmt_num(bg_total)} ({bg_pct:.0f}%)[/dim]",
        )

    table.add_row("Messages", _fmt_num(messages.get("processed", 0)))

    run_dur = histograms.get("run_duration_ms", {})
    msg_dur = histograms.get("message_duration_ms", {})
    qwait = histograms.get("queue_wait_ms", {})
    oc_durations_n = _max_n_width(run_dur, msg_dur, qwait)

    if run_dur.get("count", 0) > 0:
        table.add_row("Run duration", _fmt_histogram_s(run_dur, oc_durations_n))
    else:
        table.add_row("Run duration", "—")

    if msg_dur.get("count", 0) > 0:
        table.add_row("Msg duration", _fmt_histogram_s(msg_dur, oc_durations_n))
    else:
        table.add_row("Msg duration", "—")

    qdepth = histograms.get("queue_depth", {})
    if qdepth.get("count", 0) > 0:
        table.add_row("Queue depth", _fmt_histogram_raw(qdepth))
    else:
        table.add_row("Queue depth", "—")

    if qwait.get("count", 0) > 0:
        table.add_row("Queue wait", _fmt_histogram_s(qwait, oc_durations_n))
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
            table.add_row("Webhook latency", _fmt_histogram_s(wh_dur, _max_n_width(wh_dur)))

    # Session state and stuck (newly captured)
    stuck = counters.get("sessions_stuck", 0)
    if stuck:
        table.add_row("Sessions stuck", f"[red]{_fmt_num(stuck)}[/red]")
        stuck_age = histograms.get("session_stuck_age_ms", {})
        if stuck_age.get("count", 0) > 0:
            table.add_row("Stuck age", _fmt_histogram_s(stuck_age, _max_n_width(stuck_age)))

    # Run attempts (newly captured)
    run_attempts = counters.get("run_attempts", 0)
    if run_attempts:
        table.add_row("Run attempts", _fmt_num(run_attempts))

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
    by_channel_histograms = (otel or {}).get("histograms", {}).get("by_agent", {})
    by_channel_tokens = counters.get("tokens", {}).get("by_agent", {})
    otel_sessions = (otel or {}).get("sessions", [])

    session_tokens_by_agent: dict[str, dict[str, int]] = {}
    for s in otel_sessions:
        a = s.get("agent", "")
        if not a:
            continue
        bucket = session_tokens_by_agent.setdefault(
            a,
            {
                "input": 0,
                "output": 0,
                "cache_read": 0,
                "cache_write": 0,
                "total": 0,
            },
        )
        st = s.get("tokens", {})
        for k in ("input", "output", "cache_read", "cache_write", "total"):
            bucket[k] += st.get(k, 0)

    known_agents = {a.get("name", "") for a in agents_meta} - {""}
    agent_names: set[str] = set()
    for name in set(by_channel_tokens.keys()) | set(session_tokens_by_agent.keys()):
        if name in known_agents:
            agent_names.add(name)
    agent_names |= known_agents

    has_hist = any(
        by_channel_histograms.get(n, {}).get("run_duration_ms", {}).get("count", 0) > 0
        for n in agent_names
    )

    table = Table(
        title="OpenClaw Agents", title_style="bold cyan", title_justify="left", border_style="dim"
    )
    table.add_column("Agent", style="bold")
    table.add_column("Input\ntokens", justify="right")
    table.add_column("Output\ntokens", justify="right")
    table.add_column("Cache R\ntokens", justify="right", style="dim")
    table.add_column("Cache W\ntokens", justify="right", style="dim")
    table.add_column("Sessions", justify="right")
    table.add_column("Turns", justify="right")
    if has_hist:
        table.add_column("Avg Run", justify="right")
    table.add_column("Workspace", justify="right")

    totals: dict[str, int | float] = {
        "input": 0,
        "output": 0,
        "cache_read": 0,
        "cache_write": 0,
        "sessions": 0,
        "turns": 0,
    }

    for name in sorted(agent_names):
        tok = by_channel_tokens.get(name, session_tokens_by_agent.get(name, {}))
        agent_sessions = [s for s in otel_sessions if s.get("agent") == name]
        sess_count = len(agent_sessions)
        total_turns = sum(s.get("turns", 1) for s in agent_sessions)

        totals["input"] += tok.get("input", 0)
        totals["output"] += tok.get("output", 0)
        totals["cache_read"] += tok.get("cache_read", 0)
        totals["cache_write"] += tok.get("cache_write", 0)
        totals["sessions"] += sess_count
        totals["turns"] += total_turns

        ws_size = "—"
        for a in agents_meta:
            if a.get("name") == name:
                wdir = a.get("workspaceDir")
                if wdir:
                    ws_size = _fmt_size(_dir_size(Path(wdir)))
                break

        avg_run = "—"
        agent_h = by_channel_histograms.get(name, {})
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
        ]
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
        ]
        total_row.append(f"[bold]{totals['sessions']}[/bold]")
        total_row.append(f"[bold]{totals['turns']}[/bold]")
        if has_hist:
            total_row.append("—")
        total_row.append("—")
        table.add_row(*total_row)

    if not agent_names:
        placeholder_cols = 7 + (1 if has_hist else 0)
        table.add_row("(none)", *["—"] * (placeholder_cols - 1))

    console.print(table)
    console.print()

    _render_channel_table(by_channel_tokens, by_channel_histograms, known_agents)


def _render_channel_table(
    by_channel_tokens: dict,
    by_channel_histograms: dict,
    known_agents: set[str],
) -> None:
    """Show token usage by openclaw.channel for non-agent channels."""
    channel_names = {c for c in by_channel_tokens if c and c not in known_agents}
    if not channel_names:
        return

    has_hist = any(
        by_channel_histograms.get(c, {}).get("run_duration_ms", {}).get("count", 0) > 0
        for c in channel_names
    )

    table = Table(
        title="Tokens by Channel",
        title_style="bold cyan",
        title_justify="left",
        border_style="dim",
    )
    table.add_column("Channel", style="bold")
    table.add_column("Input\ntokens", justify="right")
    table.add_column("Output\ntokens", justify="right")
    table.add_column("Cache R\ntokens", justify="right", style="dim")
    table.add_column("Cache W\ntokens", justify="right", style="dim")
    if has_hist:
        table.add_column("Avg Run", justify="right")

    totals: dict[str, int | float] = {
        "input": 0,
        "output": 0,
        "cache_read": 0,
        "cache_write": 0,
    }

    for name in sorted(channel_names):
        tok = by_channel_tokens.get(name, {})
        totals["input"] += tok.get("input", 0)
        totals["output"] += tok.get("output", 0)
        totals["cache_read"] += tok.get("cache_read", 0)
        totals["cache_write"] += tok.get("cache_write", 0)

        avg_run = "—"
        ch_h = by_channel_histograms.get(name, {})
        rd = ch_h.get("run_duration_ms", {})
        if rd.get("count", 0) > 0:
            avg_s = rd["sum"] / rd["count"] / 1000
            avg_run = f"{avg_s:.1f}s"

        row: list[str] = [
            name,
            _fmt_num(tok.get("input", 0)),
            _fmt_num(tok.get("output", 0)),
            _fmt_num(tok.get("cache_read", 0)),
            _fmt_num(tok.get("cache_write", 0)),
        ]
        if has_hist:
            row.append(avg_run)
        table.add_row(*row)

    if len(channel_names) > 1:
        total_row: list[str] = [
            "[bold]Total[/bold]",
            f"[bold]{_fmt_num(totals['input'])}[/bold]",
            f"[bold]{_fmt_num(totals['output'])}[/bold]",
            f"[bold]{_fmt_num(totals['cache_read'])}[/bold]",
            f"[bold]{_fmt_num(totals['cache_write'])}[/bold]",
        ]
        if has_hist:
            total_row.append("—")
        table.add_row(*total_row)

    console.print(table)
    console.print()


def _render_session_table(sessions: list[dict]) -> None:
    table = Table(
        title="OpenClaw Recent Sessions",
        title_style="bold cyan",
        title_justify="left",
        border_style="dim",
    )
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


# OpenClaw "channels" that represent background/idle traffic rather than agent work.
# These tend to dominate token counts on long-running gateways because the prompt
# prefix gets re-cached on every tick. Excluded from headline numbers by default;
# pass --include-heartbeat to fold them back in.
_BACKGROUND_CHANNELS: set[str] = {"heartbeat"}


def _oc_token_totals(
    otel: dict | None,
    *,
    include_background: bool = False,
) -> tuple[dict[str, int], dict[str, int]]:
    """Compute OpenClaw token totals split into (foreground, background) buckets.

    ``foreground`` is the sum across non-background channels (real agent work).
    ``background`` is the sum across channels in ``_BACKGROUND_CHANNELS``.

    When ``include_background`` is True, foreground includes background channels
    so callers can pass a single total back to the existing display code.

    Falls back to ``counters.tokens.total`` if no per-channel breakdown exists
    (older metrics.json files).
    """
    counters = (otel or {}).get("counters", {})
    by_channel = counters.get("tokens", {}).get("by_agent", {}) or {}
    keys = ("input", "output", "cache_read", "cache_write", "total")
    fg: dict[str, int] = dict.fromkeys(keys, 0)
    bg: dict[str, int] = dict.fromkeys(keys, 0)

    if not by_channel:
        total = counters.get("tokens", {}).get("total", {})
        for k in keys:
            fg[k] = int(total.get(k, 0) or 0)
        return fg, bg

    for channel, tok in by_channel.items():
        bucket = bg if channel in _BACKGROUND_CHANNELS else fg
        for k in keys:
            bucket[k] += int(tok.get(k, 0) or 0)

    if include_background:
        for k in keys:
            fg[k] += bg[k]
        bg = dict.fromkeys(keys, 0)

    return fg, bg


_BUNDLED_PRICING_JSON = Path(__file__).resolve().parent.parent / "data" / "pricing.json"


def _user_pricing_json() -> Path:
    return _metrics_dir() / "pricing.json"


_pricing_data: dict | None = None


def _load_pricing() -> dict:
    """Load pricing data (cached after first call).

    Resolution order:
      1. ``$MYCELIUM_DATA_DIR/metrics/pricing.json`` — written by ``mycelium metrics update-pricing``
      2. Bundled ``data/pricing.json`` — shipped with the CLI package
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


def _render_cache_efficiency_table(
    otel: dict | None,
    *,
    include_background: bool = False,
) -> None:
    """Diagnostic panel for OpenClaw's prompt cache behaviour.

    Intentionally does NOT show dollar "savings". The cache is operated by the
    LLM provider (e.g. Anthropic), not by Mycelium, so attributing the saving
    to us would be misleading. We show the operational signal instead:
    hit rate, read/write/input volumes, and reads-per-write (cache reuse).
    """
    fg_tokens, bg_tokens = _oc_token_totals(otel, include_background=include_background)
    cache_read = fg_tokens.get("cache_read", 0)
    cache_write = fg_tokens.get("cache_write", 0)
    input_tokens = fg_tokens.get("input", 0)
    bg_total = bg_tokens.get("total", 0)

    denom = cache_read + cache_write + input_tokens
    if cache_read == 0 or denom == 0:
        return

    table = Table(
        title="OpenClaw Cache Efficiency",
        title_style="bold cyan",
        title_justify="left",
        show_header=False,
        border_style="dim",
    )
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")

    scope_suffix = "" if include_background else " (excl. heartbeat)"

    cache_ratio = cache_read / denom * 100
    table.add_row(
        f"Prompt cache hit rate{scope_suffix}",
        f"[green]{cache_ratio:.1f}%[/green]",
    )
    table.add_row("  cache read tokens", _fmt_num(cache_read))
    table.add_row("  cache write tokens", _fmt_num(cache_write))
    table.add_row("  uncached input tokens", _fmt_num(input_tokens))

    if cache_write > 0:
        reuse = cache_read / cache_write
        table.add_row(
            "  reads per write",
            f"{reuse:.1f}× [dim](higher = more reuse before re-cache)[/dim]",
        )

    if not include_background and bg_total > 0:
        grand = bg_total + fg_tokens.get("total", 0)
        if grand > 0:
            bg_pct = bg_total / grand * 100
            table.add_section()
            table.add_row(
                "[dim]heartbeat tokens excluded[/dim]",
                f"[dim]{_fmt_num(bg_total)} ({bg_pct:.0f}% of OpenClaw total)[/dim]",
            )

    console.print(table)
    console.print()


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


def _render_knowledge_table(backend: dict | None) -> None:
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
        title="Knowledge Ingestion",
        title_style="bold magenta",
        title_justify="left",
        show_header=False,
        border_style="dim",
    )
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")

    if ingestions > 0:
        table.add_row("Ingestions", _fmt_num(ingestions))
    if writes > 0:
        table.add_row("Shared-memory writes", _fmt_num(writes))
    errors = knowledge.get("errors", 0)
    if errors > 0:
        table.add_row("Errors", f"[red]{_fmt_num(errors)}[/red]")
    skipped = knowledge.get("skipped", 0)
    if skipped > 0:
        table.add_row("Skipped (dedupe)", _fmt_num(skipped))

    console.print(table)
    console.print()


def _render_mycelium_llm_table(backend: dict | None) -> None:
    """Render a panel showing Mycelium backend's own LLM usage."""
    if not backend:
        return

    be_counters = backend.get("counters", {})
    cfn_llm = be_counters.get("cfn_llm", {})
    has_cfn_tokens = cfn_llm.get("calls", 0) > 0
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
        if est_tokens and not has_cfn_tokens:
            table.add_row("  est. input tokens", _fmt_num(est_tokens))
        kg_errors = knowledge.get("errors", 0)
        if kg_errors:
            table.add_row("  graph store errors", f"[red]{_fmt_num(kg_errors)}[/red]")
        kg_lat = be_histograms.get("knowledge.ingestion_duration_ms", {})
        if kg_lat.get("count", 0) > 0:
            table.add_row("  ingestion duration", _fmt_histogram_s(kg_lat, _max_n_width(kg_lat)))

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
            table.add_row(
                "  synthesis duration", _fmt_histogram_s(synth_lat, _max_n_width(synth_lat))
            )

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


def _render_data_reuse_table(backend: dict | None) -> None:
    """Render a panel showing data reuse metrics from Mycelium databases."""
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
            table.add_row(
                "  returned results", f"[green]{_fmt_num(hits)}[/green] ({hit_rate:.0f}%)"
            )
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
        query_errors = knowledge.get("query_errors", 0)
        results = knowledge.get("results_returned", 0)

        table.add_row("Knowledge graph queries", _fmt_num(queries))
        if queries > 0:
            hit_rate = query_hits / queries * 100
            table.add_row(
                "  returned results",
                f"[green]{_fmt_num(query_hits)}[/green] ({hit_rate:.0f}%)",
            )
            table.add_row("  no results", _fmt_num(query_misses))
            if query_errors:
                table.add_row("  errors", f"[red]{_fmt_num(query_errors)}[/red]")
            table.add_row("  total results returned", _fmt_num(results))

        # Query type breakdown
        neighbor = knowledge.get("queries.neighbour", 0)
        path = knowledge.get("queries.path", 0)
        concept = knowledge.get("queries.concept", 0)
        semantic = knowledge.get("queries.semantic", 0)
        if neighbor + path + concept + semantic > 0:
            table.add_section()
            table.add_row("[dim]By query type:[/dim]", "")
            if neighbor:
                table.add_row("  neighbour", _fmt_num(neighbor))
            if path:
                table.add_row("  path", _fmt_num(path))
            if concept:
                table.add_row("  concept", _fmt_num(concept))
            if semantic:
                table.add_row("  semantic", _fmt_num(semantic))

        query_lat = be_histograms.get("knowledge.query_latency_ms", {})
        if query_lat.get("count", 0) > 0:
            table.add_row("Query latency", _fmt_histogram_s(query_lat, _max_n_width(query_lat)))

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
        title="CFN Coordination",
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

    # Pad ``n=`` across the histogram rows so the ``avg`` column lines up
    # vertically even when counts span orders of magnitude
    # (e.g. n=14 sessions vs n=334 rounds).
    time_to_consensus = be_histograms.get("coordination.time_to_consensus_ms", {})
    round_duration = be_histograms.get("coordination.round_duration_ms", {})
    coord_n_width = max(
        (
            len(f"{h.get('count', 0):,}")
            for h in (time_to_consensus, round_duration)
            if h.get("count", 0) > 0
        ),
        default=0,
    )
    if time_to_consensus.get("count", 0) > 0:
        table.add_row(
            "Time to consensus",
            _fmt_histogram_s(time_to_consensus, n_width=coord_n_width),
        )
    if round_duration.get("count", 0) > 0:
        table.add_row(
            "Round duration",
            _fmt_histogram_s(round_duration, n_width=coord_n_width),
        )

    participants = be_histograms.get("coordination.session_participants", {})
    if participants.get("count", 0) > 0:
        avg = participants["sum"] / participants["count"]
        table.add_row("Avg participants/session", f"{avg:.1f}")

    by_room_keys = sorted(k for k in coord if k.startswith("by_room."))
    if by_room_keys:
        table.add_section()
        table.add_row("[dim]Rounds by room:[/dim]", "")
        for key in by_room_keys[:5]:
            label = key.replace("by_room.", "")
            # Strip ``:session:<uuid>`` suffix — the session id is high-
            # cardinality noise that bloats the column on 80-col
            # terminals and forces every histogram row to wrap. The room
            # name (e.g. ``dist-e2e-18e8b583``) is the meaningful key.
            if ":session:" in label:
                label = label.split(":session:", 1)[0]
            table.add_row(f"  {label}", _fmt_num(coord[key]))
        if len(by_room_keys) > 5:
            table.add_row(f"  [dim]...and {len(by_room_keys) - 5} more[/dim]", "")

    console.print(table)
    console.print()


def _render_cfn_llm_usage_table(backend: dict | None) -> None:
    """Render actual LLM token usage reported by the cognition engines via _usage."""
    if not backend:
        return

    be_counters = backend.get("counters", {})
    cfn_llm = be_counters.get("cfn_llm", {})

    total_calls = cfn_llm.get("calls", 0)
    if total_calls == 0:
        return

    table = Table(
        title="CFN LLM Token Usage",
        title_style="bold blue",
        title_justify="left",
        show_header=False,
        border_style="dim",
    )
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")

    table.add_row("Total LLM calls (engines)", _fmt_num(total_calls))
    table.add_row("  input tokens", _fmt_num(cfn_llm.get("input_tokens", 0)))
    table.add_row("  output tokens", _fmt_num(cfn_llm.get("output_tokens", 0)))
    total_tokens = cfn_llm.get("total_tokens", 0)
    if total_tokens > 0:
        table.add_row("  total tokens", _fmt_num(total_tokens))
    cached = cfn_llm.get("cached_tokens", 0)
    if cached > 0:
        table.add_row("  cached tokens", _fmt_num(cached))

    be_histograms = backend.get("histograms", {})
    lat = be_histograms.get("cfn_llm.latency_ms", {})
    if lat.get("count", 0) > 0:
        table.add_row("LLM latency (total)", _fmt_histogram_s(lat, _max_n_width(lat)))

    # By pipeline rollup
    pipeline_keys = sorted(k for k in cfn_llm if k.startswith("by_pipeline."))
    if pipeline_keys:
        table.add_section()
        table.add_row("[dim]By pipeline:[/dim]", "")
        pipelines: dict[str, dict[str, int]] = {}
        for key in pipeline_keys:
            parts = key.split(".")
            if len(parts) >= 3:
                pip = parts[1]
                metric = parts[2]
                pipelines.setdefault(pip, {})[metric] = cfn_llm[key]
        for pip, data in sorted(pipelines.items()):
            calls = data.get("calls", 0)
            inp = data.get("input_tokens", 0)
            out = data.get("output_tokens", 0)
            table.add_row(
                f"  {pip}",
                f"{_fmt_num(calls)} calls, {_fmt_num(inp)} in / {_fmt_num(out)} out",
            )

    # By LLM operation detail
    op_keys = sorted(k for k in cfn_llm if k.startswith("by_llm_operation."))
    if op_keys:
        table.add_section()
        table.add_row("[dim]By operation:[/dim]", "")
        operations: dict[str, dict[str, int]] = {}
        for key in op_keys:
            parts = key.split(".")
            if len(parts) >= 3:
                op = ".".join(parts[1:-1])
                metric = parts[-1]
                operations.setdefault(op, {})[metric] = cfn_llm[key]
        for op, data in sorted(operations.items()):
            calls = data.get("calls", 0)
            inp = data.get("input_tokens", 0)
            out = data.get("output_tokens", 0)
            table.add_row(
                f"  {op}",
                f"{_fmt_num(calls)} calls, {_fmt_num(inp)} in / {_fmt_num(out)} out",
            )

    # By room
    room_keys = sorted(k for k in cfn_llm if k.startswith("by_room."))
    if room_keys:
        table.add_section()
        table.add_row("[dim]By room:[/dim]", "")
        rooms: dict[str, dict[str, int]] = {}
        for key in room_keys:
            parts = key.split(".")
            if len(parts) >= 3:
                room = parts[1]
                metric = parts[2]
                rooms.setdefault(room, {})[metric] = cfn_llm[key]
        for room, data in sorted(rooms.items()):
            calls = data.get("calls", 0)
            inp = data.get("input_tokens", 0)
            out = data.get("output_tokens", 0)
            label = room
            if ":session:" in label:
                label = label.split(":session:", 1)[0]
            table.add_row(
                f"  {label}",
                f"{_fmt_num(calls)} calls, {_fmt_num(inp)} in / {_fmt_num(out)} out",
            )

    console.print(table)
    console.print()


def _render_cfn_transport_table(backend: dict | None) -> None:
    """Render a panel showing outbound CFN HTTP call health."""
    if not backend:
        return

    be_counters = backend.get("counters", {})
    cfn = be_counters.get("cfn", {})

    total = cfn.get("calls", 0)
    if total == 0:
        return

    table = Table(
        title="CFN Transport Health",
        title_style="bold blue",
        title_justify="left",
        show_header=False,
        border_style="dim",
    )
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")

    table.add_row("Total outbound calls", _fmt_num(total))

    node_calls = cfn.get("calls.node", 0)
    mgmt_calls = cfn.get("calls.mgmt", 0)
    if node_calls or mgmt_calls:
        if node_calls:
            table.add_row("  CFN node", _fmt_num(node_calls))
        if mgmt_calls:
            table.add_row("  CFN mgmt", _fmt_num(mgmt_calls))

    errors = cfn.get("errors", 0)
    if errors:
        rate = (errors / total * 100) if total else 0
        table.add_row("Errors", f"[red]{_fmt_num(errors)}[/red] ({rate:.1f}%)")
        node_err = cfn.get("errors.node", 0)
        mgmt_err = cfn.get("errors.mgmt", 0)
        if node_err:
            table.add_row("  node errors", f"[red]{_fmt_num(node_err)}[/red]")
        if mgmt_err:
            table.add_row("  mgmt errors", f"[red]{_fmt_num(mgmt_err)}[/red]")

    be_histograms = backend.get("histograms", {})

    cfn_lat = be_histograms.get("cfn.latency_ms", {})
    node_lat = be_histograms.get("cfn.latency_ms.node", {})
    mgmt_lat = be_histograms.get("cfn.latency_ms.mgmt", {})
    # Same n-width trick as the Coordination panel — keeps avg columns
    # aligned across all/node/mgmt rows when call volumes differ.
    transport_n_width = max(
        (
            len(f"{h.get('count', 0):,}")
            for h in (cfn_lat, node_lat, mgmt_lat)
            if h.get("count", 0) > 0
        ),
        default=0,
    )
    if cfn_lat.get("count", 0) > 0:
        table.add_section()
        table.add_row(
            "Latency (all)",
            _fmt_histogram_s(cfn_lat, n_width=transport_n_width),
        )
    if node_lat.get("count", 0) > 0:
        table.add_row("  node", _fmt_histogram_s(node_lat, n_width=transport_n_width))
    if mgmt_lat.get("count", 0) > 0:
        table.add_row("  mgmt", _fmt_histogram_s(mgmt_lat, n_width=transport_n_width))

    # Per-operation breakdown
    op_keys = sorted(k for k in cfn if k.startswith("calls.node.") or k.startswith("calls.mgmt."))
    if op_keys:
        table.add_section()
        table.add_row("[dim]By operation:[/dim]", "")
        for key in op_keys:
            label = key.replace("calls.", "")
            table.add_row(f"  {label}", _fmt_num(cfn[key]))

    # Status code breakdown: aggregate 2xx, suppress 409 (expected for
    # idempotent re-registrations), show remaining codes individually.
    # status.0 means no HTTP response (timeout, connection refused, DNS).
    status_keys = sorted(k for k in cfn if k.startswith("status."))
    if status_keys:
        ok_total = 0
        other_rows: list[tuple[str, int]] = []
        for key in status_keys:
            code = int(key.replace("status.", ""))
            count = cfn[key]
            if 200 <= code < 300 or code == 409:
                ok_total += count
            elif code == 0:
                other_rows.append(("no response", count))
            else:
                other_rows.append((str(code), count))
        table.add_section()
        table.add_row("[dim]By status code:[/dim]", "")
        if ok_total:
            table.add_row("  OK (2xx)", _fmt_num(ok_total))
        for label, count in other_rows:
            if label == "no response":
                table.add_row("  no response (transport error)", f"[red]{_fmt_num(count)}[/red]")
            else:
                style = "red" if int(label) >= 500 else "yellow"
                table.add_row(f"  HTTP {label}", f"[{style}]{_fmt_num(count)}[/{style}]")

    console.print(table)
    console.print()


def _render_cfn_scrape_table(scrape: dict | None) -> None:
    """Render Prometheus scrape data from configured CFN/IoC targets.

    ``scrape`` is the top-level ``"scrape"`` dict in metrics.json — keyed by
    target name, each value is ``{"data": <rolled-up dict | None>,
    "scraped_at": <iso8601>}``. Targets unreachable on the last poll are
    shown with a "[degraded]" marker rather than dropped, so users can
    distinguish "I forgot to start the service" from "I never configured
    the scrape target".

    Scope: this is the *outbound* measurement of CFN's HTTP surface, which
    is independent of (and complementary to) the inbound Mycelium-backend
    counters surfaced by `_render_cfn_transport_table`. We expect CFN to
    grow domain-specific Prometheus series (`cfn_llm_tokens_total`,
    `cfn_llm_latency_seconds`, …); when they do, the panel below will
    automatically pick them up only after the rollup function in
    ``mycelium.prom_scrape`` learns to recognise them. Until then, all we
    can show is HTTP-level RED.
    """
    if not scrape:
        return

    # Filter out targets that have never produced data (i.e. data is None
    # *and* always has been). If even one scrape succeeded we render the
    # row so the user sees the degraded state.
    visible = {
        name: payload
        for name, payload in scrape.items()
        if payload and (payload.get("data") is not None or payload.get("scraped_at"))
    }
    if not visible:
        return

    table = Table(
        title="CFN /metrics Scrape",
        title_style="bold blue",
        title_justify="left",
        show_header=False,
        border_style="dim",
    )
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")

    first = True
    for name, payload in sorted(visible.items()):
        if not first:
            table.add_section()
        first = False

        scraped_at = payload.get("scraped_at", "")
        data = payload.get("data")

        if data is None:
            table.add_row(
                f"[blue]{name}[/blue]",
                f"[yellow][degraded — last attempt {scraped_at}][/yellow]",
            )
            continue

        total_calls = data.get("calls", 0)
        total_errors = data.get("errors", 0)
        by_route = data.get("by_route", {})
        if total_calls == 0 and not by_route:
            # Endpoint reachable but produced no http_requests_total — likely
            # a stock instrumentator that hasn't seen any traffic yet, OR a
            # non-fastapi-instrumentator surface (raw prometheus_client).
            table.add_row(
                f"[blue]{name}[/blue]",
                f"[dim](no HTTP RED samples yet — last poll {scraped_at})[/dim]",
            )
            continue

        table.add_row(f"[blue]{name}[/blue]", "")
        table.add_row("  Total requests", _fmt_num(total_calls))
        if total_errors:
            rate = (total_errors / total_calls * 100) if total_calls else 0
            table.add_row(
                "  Errors (4xx≠404 + 5xx)",
                f"[red]{_fmt_num(total_errors)}[/red] ({rate:.1f}%)",
            )

        # Top routes by request volume — keep it short, the panel is
        # already three steps removed from the user's primary concern.
        top_routes = sorted(
            by_route.items(),
            key=lambda kv: kv[1].get("calls", 0),
            reverse=True,
        )[:6]
        if top_routes:
            table.add_row("  [dim]Top routes:[/dim]", "")
            # Width of the largest n= field in this group, so every row's
            # avg/p50/p99 columns align vertically regardless of traffic skew.
            max_n_width = max(
                len(f"{r.get('latency_ms', {}).get('count', 0):,}") for _, r in top_routes
            )
            for route_name, route_data in top_routes:
                lat = route_data.get("latency_ms", {})
                table.add_row(
                    f"    {route_name}",
                    _fmt_prom_latency(lat, n_width=max_n_width),
                )

    console.print(table)
    console.print()


def _estimate_cost(
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_write_tokens: int,
    model: str,
) -> float:
    """Estimate cost in USD from token counts and model pricing."""
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


def _render_cost_estimates(
    otel: dict | None,
    oc_cost: dict | None,
    backend: dict | None,
    *,
    include_heartbeat: bool = False,
) -> None:
    """Unified cost section compiling token usage from all sources."""
    from mycelium.config import MyceliumConfig

    try:
        config = MyceliumConfig.load()
        cfn_model = config.llm.model or ""
    except Exception:
        cfn_model = ""

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

    # ── OpenClaw (provider-reported cost) ──────────────────────────────
    oc_reported_cost = 0.0
    if oc_cost and oc_cost.get("total") is not None:
        oc_reported_cost = oc_cost["total"]
    elif otel:
        oc_reported_cost = otel.get("counters", {}).get("cost_usd", {}).get("total", 0.0)

    fg_tokens, _ = _oc_token_totals(otel, include_background=include_heartbeat)
    oc_total_tokens = (
        fg_tokens.get("input", 0)
        + fg_tokens.get("output", 0)
        + fg_tokens.get("cache_read", 0)
        + fg_tokens.get("cache_write", 0)
    )

    if oc_total_tokens > 0 or oc_reported_cost > 0:
        if oc_reported_cost > 0:
            oc_pricing_label = "otel (provider-reported)"
        else:
            oc_pricing_label = "[yellow]otel — $0 (check model cost config)[/yellow]"
        table.add_row(
            "[cyan]OpenClaw Agents[/cyan]",
            _fmt_num(oc_total_tokens) if oc_total_tokens else "—",
            _fmt_cost(oc_reported_cost) if oc_reported_cost > 0 else "[dim]$0.00[/dim]",
            oc_pricing_label,
        )
        total_cost += oc_reported_cost

    # ── CFN Engines (estimated from tokens + pricing.json) ─────────────
    be_counters = (backend or {}).get("counters", {})
    cfn_llm = be_counters.get("cfn_llm", {})
    cfn_calls = cfn_llm.get("calls", 0)

    if cfn_calls > 0:
        cfn_prompt = cfn_llm.get("input_tokens", 0)
        cfn_compl = cfn_llm.get("output_tokens", 0)
        cfn_cached = cfn_llm.get("cached_tokens", 0)
        cfn_total = cfn_prompt + cfn_compl

        cfn_est_cost = _estimate_cost(
            input_tokens=cfn_prompt,
            output_tokens=cfn_compl,
            cache_read_tokens=cfn_cached,
            cache_write_tokens=0,
            model=cfn_model,
        )
        _, model_label = _get_model_pricing(cfn_model)
        table.add_row(
            "[blue]CFN Engines[/blue]",
            _fmt_num(cfn_total),
            _fmt_cost(cfn_est_cost),
            f"est. ({model_label})",
        )
        total_cost += cfn_est_cost

        # Per-pipeline breakdown under CFN
        pipeline_keys = sorted(k for k in cfn_llm if k.startswith("by_pipeline."))
        if pipeline_keys:
            pipelines: dict[str, dict[str, int]] = {}
            for key in pipeline_keys:
                parts = key.split(".")
                if len(parts) >= 3:
                    pip = parts[1]
                    metric = parts[2]
                    pipelines.setdefault(pip, {})[metric] = cfn_llm[key]
            for pip, data in sorted(pipelines.items()):
                p_prompt = data.get("input_tokens", 0)
                p_compl = data.get("output_tokens", 0)
                p_total = p_prompt + p_compl
                p_cost = _estimate_cost(
                    input_tokens=p_prompt,
                    output_tokens=p_compl,
                    cache_read_tokens=0,
                    cache_write_tokens=0,
                    model=cfn_model,
                )
                label = pip.replace("_", " ").title()
                table.add_row(
                    f"  [dim]{label}[/dim]",
                    f"[dim]{_fmt_num(p_total)}[/dim]",
                    f"[dim]{_fmt_cost(p_cost)}[/dim]",
                    "",
                )

    # ── Mycelium Backend LLM (estimated) ───────────────────────────────
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
                "litellm (provider-reported)",
            )
            total_cost += myc_reported
        else:
            myc_est = _estimate_cost(
                input_tokens=myc_prompt,
                output_tokens=myc_compl,
                cache_read_tokens=0,
                cache_write_tokens=0,
                model=cfn_model,
            )
            _, model_label = _get_model_pricing(cfn_model)
            table.add_row(
                "[magenta]Mycelium LLM[/magenta]",
                _fmt_num(myc_total),
                _fmt_cost(myc_est),
                f"est. ({model_label})",
            )
            total_cost += myc_est

    # ── Claude Code (placeholder) ──────────────────────────────────────
    # Not yet wired — omit row entirely until data available

    # ── Totals ─────────────────────────────────────────────────────────
    if total_cost > 0:
        table.add_section()
        table.add_row("[bold]Total[/bold]", "", f"[bold]{_fmt_cost(total_cost)}[/bold]", "")

    if total_cost == 0 and oc_total_tokens == 0 and cfn_calls == 0:
        table.add_row("[dim]No cost data yet[/dim]", "", "", "")

    console.print(table)

    # Pricing source note
    gen_date = _pricing_generated_at()
    if gen_date:
        console.print(f"[dim]  Estimates use litellm pricing data (updated {gen_date})[/dim]")
    console.print()


def _render_field_legend() -> None:
    console.print("[dim]Data sources:[/dim]")
    console.print(
        "[dim]  [cyan]OpenClaw[/cyan]  — Agent activity via OTLP telemetry (tokens, sessions)[/dim]"
    )
    console.print(
        "[dim]  [magenta]Mycelium[/magenta]  — Backend API metrics (embeddings, memory, LLM calls)[/dim]"
    )
    console.print(
        "[dim]  [blue]CFN[/blue]   — Cognition Fabric Node (coordination, negotiation)[/dim]"
    )
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
