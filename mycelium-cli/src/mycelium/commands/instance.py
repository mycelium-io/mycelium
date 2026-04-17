# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
Instance management commands for Mycelium CLI.

Commands for managing local Mycelium instances:
- init: Initialize configuration
- install: Pull and start all services via docker compose
- start: Start core Mycelium services (db + backend)
- stop: Stop services
- status: Show service health
- logs: View service logs
"""

import shutil
import subprocess
from pathlib import Path

import httpx
import typer

from mycelium.config import MyceliumConfig, ServerConfig
from mycelium.doc_ref import doc_ref
from mycelium.error_handler import print_error
from mycelium.exceptions import ConfigNotFoundError
from mycelium.http_client import MyceliumHTTPClient  # kept for health check
from mycelium.ui_status import (
    CheckResult,
    print_check,
    print_kv,
    print_section,
    print_title,
    print_verdict,
)

app = typer.Typer(
    help="Docker lifecycle for the Mycelium stack (database, backend, graph viewer).",
    no_args_is_help=True,
)

_COMPOSE_PROJECT = "mycelium"

_MANAGED_CONTAINERS = [
    "mycelium-db",
    "mycelium-backend",
    "mycelium-graph-viewer",
    "ioc-cfn-mgmt-plane-svc",
    "ioc-cfn-svc",
]


def _get_compose_path() -> Path:
    """
    Resolve docker-compose file path.

    Priority:
      1. MYCELIUM_COMPOSE_FILE env var
      2. Walk up from package location to find repo's services/docker-compose.yml
         (editable installs — keeps relative build contexts correct)
      3. ~/.mycelium/docker/compose.yml  (extracted by mycelium install)
      4. Bundled in CLI package          (extracted on demand; build contexts broken)
    """
    import importlib.resources
    import os

    if env_path := os.getenv("MYCELIUM_COMPOSE_FILE"):
        return Path(env_path)

    # Walk up from package source to find repo's services/docker-compose.yml
    try:
        pkg_path = Path(str(importlib.resources.files("mycelium")))
        for depth in range(2, 7):
            candidate = pkg_path.parents[depth] / "services" / "docker-compose.yml"
            if candidate.exists():
                return candidate
    except Exception:
        pass

    installed = Path.home() / ".mycelium" / "docker" / "compose.yml"
    if installed.exists():
        return installed

    # Extract bundled compose to stable location (fallback; build contexts will be wrong)
    try:
        compose_ref = importlib.resources.files("mycelium.docker") / "compose.yml"
        installed.parent.mkdir(parents=True, exist_ok=True)
        installed.write_bytes(compose_ref.read_bytes())
        return installed
    except Exception:
        pass

    return Path.cwd() / "services" / "docker-compose.yml"


def _get_env_path() -> Path | None:
    env_path = Path.home() / ".mycelium" / ".env"
    return env_path if env_path.exists() else None


def _compose_base_cmd(compose_path: Path | None = None, env_path: Path | None = None) -> list[str]:
    """Build the docker compose prefix with consistent project name."""
    if compose_path is None:
        compose_path = _get_compose_path()
    if env_path is None:
        env_path = _get_env_path()
    cmd = ["docker", "compose", "-p", _COMPOSE_PROJECT, "-f", str(compose_path)]
    if env_path:
        cmd += ["--env-file", str(env_path)]
    return cmd


def _cfn_enabled() -> bool:
    """Return True if CFN_MGMT_URL is set in ~/.mycelium/.env."""
    env_path = _get_env_path()
    if not env_path or not env_path.exists():
        return False
    try:
        from dotenv import dotenv_values

        val = dotenv_values(env_path).get("CFN_MGMT_URL", "")
        return bool(val and val.strip())
    except Exception:
        return False


def _ensure_cfn_databases(db_container: str = "mycelium-db") -> None:
    """Create cfn_mgmt and cfn_cp databases if they don't exist.

    Mirrors install._ensure_cfn_databases — called here so that ``mycelium up``
    also provisions them, not just ``mycelium install``.
    """
    for db in ("cfn_mgmt", "cfn_cp"):
        sql = (
            f"SELECT 'CREATE DATABASE {db}' "
            f"WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '{db}')\\gexec"
        )
        subprocess.run(
            ["docker", "exec", db_container, "psql", "-U", "postgres", "-c", sql],
            capture_output=True,
        )


def _wait_for_db_container(
    compose_path: Path, db_service: str = "mycelium-db", timeout: int = 60
) -> bool:
    """Poll until the DB container shows 'healthy' in docker compose ps output."""
    import time

    env_path = _get_env_path()
    args = ["docker", "compose", "-p", _COMPOSE_PROJECT, "-f", str(compose_path)]
    if env_path:
        args += ["--env-file", str(env_path)]
    args += ["ps", "--format", "json", db_service]

    deadline = time.time() + timeout
    while time.time() < deadline:
        result = subprocess.run(args, capture_output=True, text=True)
        if result.returncode == 0 and "healthy" in result.stdout:
            return True
        time.sleep(2)
    return False


def _find_managed_containers(include_stopped: bool = False) -> list[str]:
    """Return names of managed containers that are still present."""
    try:
        cmd = ["docker", "ps", "--format", "{{.Names}}"]
        if include_stopped:
            cmd.insert(2, "-a")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if result.returncode != 0:
            return []
        managed = set(_MANAGED_CONTAINERS)
        return [
            name.strip() for name in result.stdout.strip().split("\n") if name.strip() in managed
        ]
    except Exception:
        return []


def _remove_managed_containers() -> list[str]:
    """Force-remove all managed containers (running or stopped).

    Returns names of containers that were removed.
    """
    containers = _find_managed_containers(include_stopped=True)
    if not containers:
        return []
    subprocess.run(
        ["docker", "rm", "-f", *containers],
        capture_output=True,
        check=False,
        timeout=30,
    )
    return containers


@doc_ref(
    usage="mycelium init [--api-url <url>] [--force]",
    desc="Initialize CLI configuration. Creates <code>~/.mycelium/config.toml</code>.",
    group="setup",
)
def init(
    ctx: typer.Context,
    api_url: str | None = typer.Option(
        None,
        "--api-url",
        help="Backend API URL (default: http://localhost:8000)",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Overwrite existing configuration",
    ),
) -> None:
    """
    Initialize Mycelium configuration.

    Creates ~/.mycelium/config.toml with default settings.
    """
    try:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False  # noqa: F841
        config_path = MyceliumConfig.get_config_path()

        if config_path.exists() and not force:
            typer.secho(
                f"Configuration already exists at {config_path}",
                fg=typer.colors.GREEN,
            )
            typer.echo("")
            typer.echo("Use --force to overwrite existing configuration")
            return

        if api_url is None:
            api_url = typer.prompt(
                "Backend API URL",
                default="http://localhost:8000",
                show_default=True,
            )

        assert api_url is not None

        config = MyceliumConfig(
            server=ServerConfig(
                api_url=api_url,
            )
        )
        config.save(config_path)

        typer.secho(f"Created configuration at {config_path}", fg=typer.colors.GREEN)
        typer.echo("")
        typer.echo("Configuration:")
        typer.echo(f"  API URL: {api_url}")
        typer.echo("")
        typer.echo("Next steps:")
        typer.echo("  - Run 'mycelium install' to pull and start all services")
        typer.echo("  - Run 'mycelium status' to check service health")

    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


@doc_ref(
    usage="mycelium up [--build]",
    desc="Start the Mycelium stack via <code>docker compose up</code>.",
    group="setup",
)
def start(
    ctx: typer.Context,
    build: bool = typer.Option(False, "--build", help="Rebuild images before starting"),
) -> None:
    """
    Start Mycelium services.

    Runs docker compose up -d using the bundled compose file and
    ~/.mycelium/.env for configuration.

    Examples:
        mycelium up          # start all services
        mycelium up --build  # rebuild images first
    """
    try:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False  # noqa: F841
        compose_path = _get_compose_path()

        if not compose_path.exists():
            typer.secho(f"Compose file not found at {compose_path}", fg=typer.colors.RED)
            typer.echo("Run 'mycelium install' first.")
            raise typer.Exit(1)

        cfn = _cfn_enabled()
        base = _compose_base_cmd(compose_path)
        if cfn:
            base = base + ["--profile", "cfn"]
        up_args = ["up", "-d", "--remove-orphans"]
        if build:
            up_args.append("--build")

        typer.echo("Starting Mycelium...")

        if cfn:
            # Phase 1: start DB first, then provision CFN databases before the
            # CFN services come up and try to connect.
            db_only_cmd = base[:2] + ["--progress=plain"] + base[2:] + ["up", "-d", "mycelium-db"]
            r = subprocess.run(db_only_cmd, capture_output=True, text=True)
            if r.returncode != 0:
                if r.stdout:
                    typer.echo(r.stdout)
                if r.stderr:
                    typer.echo(r.stderr, err=True)
                raise typer.Exit(r.returncode)
            _wait_for_db_container(compose_path)
            _ensure_cfn_databases()
            typer.secho("  ✓ CFN databases provisioned", fg=typer.colors.GREEN)

        # Phase 2 (or only phase): bring everything up
        quiet_cmd = base[:2] + ["--progress=plain"] + base[2:] + up_args
        result = subprocess.run(quiet_cmd, capture_output=True, text=True)

        if result.returncode != 0:
            output = (result.stdout or "") + (result.stderr or "")
            if "is already in use by container" in output:
                # Containers exist from a previous run (possibly a different
                # compose project). Remove them and retry.
                typer.secho(
                    "Existing containers detected from a previous run, recreating...",
                    fg=typer.colors.YELLOW,
                )
                _remove_managed_containers()
                result = subprocess.run(base + up_args, check=False)
                if result.returncode != 0:
                    raise typer.Exit(result.returncode)
            else:
                # Show captured output on failure
                if result.stdout:
                    typer.echo(result.stdout)
                if result.stderr:
                    typer.echo(result.stderr, err=True)
                raise typer.Exit(result.returncode)
        else:
            # Show captured output on success too (warnings, pull info, etc.)
            if result.stdout:
                typer.echo(result.stdout)
            if result.stderr:
                typer.echo(result.stderr, err=True)

        typer.secho("Services started.", fg=typer.colors.GREEN)
        typer.echo("  mycelium-backend  → http://localhost:8000")

    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


@doc_ref(
    usage="mycelium down [--volumes]",
    desc="Stop the Mycelium stack. Pass <code>--volumes</code> to also delete data.",
    group="setup",
)
def stop(
    ctx: typer.Context,
    volumes: bool = typer.Option(
        False, "--volumes", "-v", help="Also remove volumes (destructive)"
    ),
) -> None:
    """
    Stop Mycelium services.

    Examples:
        mycelium down             # stop containers, keep volumes
        mycelium down --volumes   # stop and delete all data
    """
    try:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False  # noqa: F841
        compose_path = _get_compose_path()

        if not compose_path.exists():
            typer.secho(f"Compose file not found at {compose_path}", fg=typer.colors.RED)
            raise typer.Exit(1)

        base = _compose_base_cmd(compose_path)
        down_args = ["down", "--remove-orphans"]
        if volumes:
            down_args.append("-v")

        typer.echo("Stopping Mycelium services...")
        result = subprocess.run(base + down_args, check=False)

        if result.returncode != 0:
            raise typer.Exit(result.returncode)

        # Clean up containers that compose didn't catch (e.g., started with a
        # different project name or outside compose entirely).
        remaining = _find_managed_containers()
        if remaining:
            typer.secho(
                f"Cleaning up orphaned containers: {', '.join(remaining)}",
                fg=typer.colors.YELLOW,
            )
            subprocess.run(
                ["docker", "rm", "-f", *remaining],
                capture_output=True,
                check=False,
                timeout=30,
            )

        typer.secho("Services stopped.", fg=typer.colors.GREEN)

    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


@doc_ref(
    usage="mycelium status",
    desc="Show running service health (backend connectivity, room count).",
    group="setup",
)
def status(ctx: typer.Context) -> None:
    """
    Show service health.

    Checks backend, database, LLM, embedding model, Docker containers,
    disk space, and data directory status.
    """
    try:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False  # noqa: F841
        json_output = ctx.obj.get("json", False) if ctx.obj else False

        config_path = MyceliumConfig.get_config_path()
        if not config_path.exists():
            raise ConfigNotFoundError(str(config_path))

        config = MyceliumConfig.load()

        from mycelium import __version__ as cli_version

        # -- Backend health (includes DB, LLM, embedding, version) -----------
        backend_running = False
        backend_room_count = 0
        health_data: dict = {}

        backend_error: str | None = None
        with MyceliumHTTPClient(config=config) as client:
            try:
                health_resp = client.get("/health", params={"check_llm": "true"})
                health_data = health_resp.json()
                backend_running = health_data.get("status") in ("ok", "degraded")
            except Exception as exc:
                backend_running = False
                if isinstance(exc, httpx.ConnectError):
                    backend_error = f"Cannot connect to {config.server.api_url}"
                elif isinstance(exc, httpx.TimeoutException):
                    backend_error = f"Timeout connecting to {config.server.api_url}"
                elif isinstance(exc, httpx.HTTPStatusError):
                    backend_error = f"Backend returned HTTP {exc.response.status_code}"
                else:
                    backend_error = str(exc)

            if backend_running:
                try:
                    response = client.get("/rooms")
                    rooms = response.json()
                    backend_room_count = len(rooms) if isinstance(rooms, list) else 0
                except Exception:
                    pass

        # -- Client-side checks (no backend needed) --------------------------
        docker_info = _check_docker_containers()
        disk_info = _check_disk_space()
        data_dir_info = _check_data_dir()

        if json_output:
            import json

            output: dict = {
                "versions": {
                    "cli": cli_version,
                    "backend": health_data.get("version"),
                },
                "services": {
                    "backend": {
                        "url": config.server.api_url,
                        "status": health_data.get("status", "down"),
                        "running": backend_running,
                        "room_count": backend_room_count,
                    },
                    "database": health_data.get("database"),
                    "llm": health_data.get("llm"),
                    "embedding": health_data.get("embedding"),
                    "docker": docker_info,
                },
                "system": {
                    "disk": disk_info,
                    "data_dir": data_dir_info,
                },
                "config": {
                    "path": str(config_path),
                    "api_url": config.server.api_url,
                    "active_room": config.get_active_room(),
                },
            }
            typer.echo(json.dumps(output, indent=2))
        else:
            backend_version = health_data.get("version")
            version_line = f"CLI {cli_version}"
            if backend_version:
                version_line += f"  /  Backend {backend_version}"
            print_title("Mycelium Status", subtitle=version_line)

            # ── Services ──────────────────────────────────────────────
            services: list[CheckResult] = []

            if backend_running:
                msg = f"Running at {config.server.api_url}"
                if backend_room_count > 0:
                    msg += f" ({backend_room_count} rooms)"
                services.append(CheckResult(name="Backend", status="ok", message=msg))
            else:
                services.append(
                    CheckResult(
                        name="Backend",
                        status="error",
                        message="Not running",
                        details=[backend_error] if backend_error else [config.server.api_url],
                    )
                )

            db_info = health_data.get("database") or {}
            if db_info:
                services.append(
                    CheckResult(
                        name="Database",
                        status=db_info.get("status", "unknown"),
                        message=db_info.get("message", "Unknown"),
                    )
                )

            llm_info = health_data.get("llm") or {}
            if llm_info:
                llm_status = llm_info.get("status", "unknown")
                model = llm_info.get("model", "") or "<unset>"
                key_hint = llm_info.get("key_hint") or ""
                if llm_status == "ok":
                    msg = f"{model}" + (f" ({key_hint})" if key_hint else "")
                else:
                    label = llm_status.replace("_", " ").title()
                    msg = f"{label} — {model}" + (f" ({key_hint})" if key_hint else "")
                llm_details = []
                if llm_info.get("message") and llm_status != "ok":
                    llm_details.append(llm_info["message"])
                services.append(
                    CheckResult(name="LLM", status=llm_status, message=msg, details=llm_details)
                )

            embed_info = health_data.get("embedding") or {}
            if embed_info:
                model = embed_info.get("model", "") or "<unset>"
                msg_text = embed_info.get("message", "")
                msg = f"{model}" + (
                    f" ({msg_text})" if msg_text and msg_text != "Model loaded" else " (loaded)"
                )
                services.append(
                    CheckResult(
                        name="Embedding", status=embed_info.get("status", "unknown"), message=msg
                    )
                )

            print_section("Services")
            for r in services:
                print_check(r)

            # ── Docker ────────────────────────────────────────────────
            print_section("Docker")
            if docker_info.get("available"):
                containers = docker_info.get("containers") or []
                if not containers:
                    print_check(
                        CheckResult(
                            name="(none)",
                            status="warning",
                            message="No Mycelium containers found",
                        )
                    )
                for ctr in containers:
                    ctr_status = ctr.get("status", "unknown")
                    health = ctr.get("health", "") or ""
                    label = ctr_status
                    if health and health != "N/A":
                        label += f" ({health})"
                    is_ok = "running" in ctr_status.lower() and health.lower() != "unhealthy"
                    print_check(
                        CheckResult(
                            name=ctr["name"],
                            status="ok" if is_ok else "warning",
                            message=label,
                        )
                    )
            else:
                print_check(
                    CheckResult(
                        name="docker",
                        status="warning",
                        message=docker_info.get("message", "Docker not available"),
                    )
                )

            # ── System ────────────────────────────────────────────────
            print_section("System")
            print_check(
                CheckResult(name="Disk", status=disk_info["status"], message=disk_info["message"])
            )
            print_check(
                CheckResult(
                    name="Data Dir",
                    status=data_dir_info["status"],
                    message=data_dir_info["message"],
                )
            )

            # ── Configuration ─────────────────────────────────────────
            # Informational block (no checks) — path + active room.
            print_section("Configuration")
            print_kv("Path", str(config_path))
            active_room = config.get_active_room()
            if active_room:
                print_kv("Active Room", active_room)

            # ── Verdict ───────────────────────────────────────────────
            overall_status = health_data.get("status", "down")
            if not backend_running:
                fail_msg = (
                    f"Backend unreachable: {backend_error}"
                    if backend_error
                    else "Backend is down — run: mycelium up"
                )
                print_verdict("error", fail_msg)
                if backend_error and ("HTTP 401" in backend_error or "HTTP 403" in backend_error):
                    typer.echo(
                        "  Check the backend URL (MYCELIUM_API_URL env var or server.api_url in ~/.mycelium/config.toml)"
                    )
                elif backend_error and "Cannot connect" in backend_error:
                    typer.echo("  To start services: mycelium up")
            elif overall_status == "degraded":
                print_verdict("warning", "Backend running (degraded)")
            else:
                print_verdict("ok", "All systems operational")

    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


# -- End of status helpers — see mycelium.ui_status for shared presentation -----


# -- Client-side health checks -----------------------------------------------


def _check_docker_containers() -> dict:
    """Query Docker for Mycelium container status."""
    try:
        result = subprocess.run(
            [
                "docker",
                "ps",
                "-a",
                "--filter",
                "name=mycelium",
                "--format",
                "{{.Names}}\t{{.Status}}\t{{.State}}",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if result.returncode != 0:
            return {"available": False, "message": "Docker command failed"}

        containers = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("\t")
            name = parts[0] if len(parts) > 0 else "unknown"
            status_text = parts[1] if len(parts) > 1 else "unknown"
            state = parts[2] if len(parts) > 2 else "unknown"
            health = "N/A"
            if "(healthy)" in status_text.lower():
                health = "healthy"
            elif "(unhealthy)" in status_text.lower():
                health = "unhealthy"
            elif "(health: starting)" in status_text.lower():
                health = "starting"
            containers.append({"name": name, "status": state, "health": health})

        return {"available": True, "containers": containers}
    except FileNotFoundError:
        return {"available": False, "message": "Docker not installed"}
    except subprocess.TimeoutExpired:
        return {"available": False, "message": "Docker command timed out"}
    except Exception:
        return {"available": False, "message": "Docker check failed"}


def _check_disk_space(min_mb: int = 500) -> dict:
    """Check available disk space on the home partition."""
    try:
        usage = shutil.disk_usage(Path.home())
        free_mb = usage.free // (1024 * 1024)
        total_gb = usage.total / (1024 * 1024 * 1024)
        free_gb = usage.free / (1024 * 1024 * 1024)
        if free_mb >= min_mb:
            return {
                "status": "ok",
                "message": f"{free_gb:.1f} GB free of {total_gb:.1f} GB",
                "free_mb": free_mb,
            }
        return {
            "status": "warning",
            "message": f"Low disk: {free_mb:,} MB free (< {min_mb} MB threshold)",
            "free_mb": free_mb,
        }
    except Exception:
        return {"status": "warning", "message": "Could not check disk space"}


def _check_data_dir() -> dict:
    """Check ~/.mycelium/ directory health."""
    data_dir = Path.home() / ".mycelium"
    issues = []

    if not data_dir.exists():
        return {
            "status": "error",
            "message": "~/.mycelium/ does not exist. Run: mycelium install",
            "path": str(data_dir),
        }

    if not data_dir.is_dir():
        return {
            "status": "error",
            "message": "~/.mycelium exists but is not a directory",
            "path": str(data_dir),
        }

    env_file = data_dir / ".env"
    config_file = data_dir / "config.toml"

    if not env_file.exists():
        issues.append("missing .env")
    if not config_file.exists():
        issues.append("missing config.toml")

    try:
        test_file = data_dir / ".write_test"
        test_file.touch()
        test_file.unlink(missing_ok=True)
    except OSError:
        issues.append("not writable")

    if issues:
        return {
            "status": "warning",
            "message": f"~/.mycelium/ ({', '.join(issues)})",
            "path": str(data_dir),
        }

    return {"status": "ok", "message": "~/.mycelium/ OK", "path": str(data_dir)}


@doc_ref(
    usage="mycelium logs [service] [--follow] [--tail N]",
    desc="Tail container logs via <code>docker compose logs</code>.",
    group="setup",
)
def logs(
    ctx: typer.Context,
    service: str | None = typer.Argument(
        None, help="Service name (e.g. mycelium-backend, ioc-cfn-mgmt-plane-svc)"
    ),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output"),
    tail: int | None = typer.Option(None, "--tail", help="Number of lines to show from the end"),
) -> None:
    """View service logs via docker compose."""
    try:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False  # noqa: F841

        cmd = _compose_base_cmd()
        cmd += ["logs"]
        if follow:
            cmd.append("-f")
        if tail is not None:
            cmd.extend(["--tail", str(tail)])
        if service:
            cmd.append(service)

        subprocess.run(cmd, check=False)

    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


def _get_backend_dir() -> Path:
    """Find the fastapi-backend directory (for running alembic)."""
    import importlib.resources

    try:
        pkg_path = Path(str(importlib.resources.files("mycelium")))
        for depth in range(2, 7):
            candidate = pkg_path.parents[depth] / "fastapi-backend"
            if (candidate / "alembic.ini").exists():
                return candidate
    except Exception:
        pass

    if (Path.cwd() / "alembic.ini").exists():
        return Path.cwd()

    candidate = Path.cwd() / "fastapi-backend"
    if (candidate / "alembic.ini").exists():
        return candidate

    return Path.cwd()


@doc_ref(
    usage="mycelium migrate [--revision <target>]",
    desc="Run database migrations (alembic upgrade). Defaults to latest.",
    group="setup",
)
def migrate(
    ctx: typer.Context,
    revision: str = typer.Option(
        "head", "--revision", "-r", help="Target revision (default: head)"
    ),
) -> None:
    """
    Run database migrations.

    Applies pending alembic migrations against the configured database.
    Defaults to upgrading to the latest revision.

    Examples:
        mycelium migrate              # upgrade to latest
        mycelium migrate -r head      # same as above
        mycelium migrate -r 0008      # upgrade to specific revision
    """
    try:
        backend_dir = _get_backend_dir()
        if not (backend_dir / "alembic.ini").exists():
            typer.secho(f"alembic.ini not found in {backend_dir}", fg=typer.colors.RED)
            typer.echo("Run this from the repo root or set MYCELIUM_COMPOSE_FILE.")
            raise typer.Exit(1)

        env_path = _get_env_path()

        import os

        env = {**os.environ}
        if env_path and env_path.exists():
            from dotenv import dotenv_values

            env.update({k: v for k, v in dotenv_values(env_path).items() if v is not None})

        backend_env = backend_dir / ".env"
        if backend_env.exists():
            from dotenv import dotenv_values

            env.update({k: v for k, v in dotenv_values(backend_env).items() if v is not None})

        if "DATABASE_URL" not in env:
            typer.secho("DATABASE_URL not set.", fg=typer.colors.RED)
            typer.echo("Set it in ~/.mycelium/.env or fastapi-backend/.env")
            raise typer.Exit(1)

        typer.echo(f"Running migrations (target: {revision})...")
        cmd = ["uv", "run", "alembic", "upgrade", revision]
        result = subprocess.run(
            cmd, cwd=str(backend_dir), env=env, check=False, capture_output=True, text=True
        )

        if result.stdout:
            typer.echo(result.stdout.rstrip())
        if result.stderr:
            for line in result.stderr.strip().split("\n"):
                if "Running upgrade" in line:
                    typer.secho(f"  {line.split('] ')[-1]}", fg=typer.colors.GREEN)
                elif "ERROR" in line:
                    typer.secho(f"  {line}", fg=typer.colors.RED)

        if result.returncode == 0:
            typer.secho("Migrations complete.", fg=typer.colors.GREEN)
        else:
            typer.secho("Migration failed.", fg=typer.colors.RED)
            if result.stderr and "ERROR" not in result.stderr:
                typer.echo(result.stderr)
            raise typer.Exit(result.returncode)

    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


# ── Pull command ─────────────────────────────────────────────────────────────


@doc_ref(
    usage="mycelium pull [--no-restart]",
    desc="Pull latest Docker images and restart services.",
    group="setup",
)
def pull(
    ctx: typer.Context,
    no_restart: bool = typer.Option(
        False, "--no-restart", help="Pull images but don't restart services"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmations"),  # noqa: ARG001
) -> None:
    """
    Pull latest Docker images and restart services.

    Fetches the newest versions of all Mycelium container images, then
    restarts the stack so the updated images take effect. Also runs
    database migrations.

    \b
    Examples:
        mycelium pull              # pull + restart + migrate
        mycelium pull --no-restart # pull only, restart later with mycelium up
    """
    try:
        compose_path = _get_compose_path()

        if not compose_path.exists():
            typer.secho(f"Compose file not found at {compose_path}", fg=typer.colors.RED)
            typer.echo("Run 'mycelium install' first.")
            raise typer.Exit(1)

        env_path = _get_env_path()
        cfn = _cfn_enabled()

        base = _compose_base_cmd(compose_path, env_path)
        if cfn:
            base = base + ["--profile", "cfn"]

        # Pull
        typer.secho("Pulling latest images...", bold=True)
        pull_result = subprocess.run(base + ["pull"], text=True)
        if pull_result.returncode != 0:
            typer.secho("Pull failed.", fg=typer.colors.RED)
            raise typer.Exit(pull_result.returncode)
        typer.secho("✓ Images pulled", fg=typer.colors.GREEN)

        if no_restart:
            typer.echo("")
            typer.echo("Images updated. Run 'mycelium up' to restart with new images.")
            return

        # Restart
        typer.echo("")
        typer.secho("Restarting services...", bold=True)

        if cfn:
            # Start DB first, provision CFN databases, then bring up everything
            db_cmd = base[:2] + ["--progress=plain"] + base[2:] + ["up", "-d", "mycelium-db"]
            subprocess.run(db_cmd, capture_output=True, text=True)
            _wait_for_db_container(compose_path)
            _ensure_cfn_databases()

        up_args = ["up", "-d", "--force-recreate", "--remove-orphans"]
        up_cmd = base[:2] + ["--progress=plain"] + base[2:] + up_args
        result = subprocess.run(up_cmd, capture_output=True, text=True)

        if result.returncode != 0:
            output = (result.stdout or "") + (result.stderr or "")
            if "is already in use by container" in output:
                _remove_managed_containers()
                result = subprocess.run(base + up_args, check=False)
                if result.returncode != 0:
                    raise typer.Exit(result.returncode)
            else:
                if result.stdout:
                    typer.echo(result.stdout)
                if result.stderr:
                    typer.echo(result.stderr, err=True)
                raise typer.Exit(result.returncode)

        typer.secho("✓ Services restarted", fg=typer.colors.GREEN)

        # Health check
        import time

        api_url = "http://localhost:8000"
        if env_path and env_path.exists():
            from dotenv import dotenv_values

            vals = dotenv_values(env_path)
            port = vals.get("MYCELIUM_BACKEND_PORT", "8000")
            api_url = f"http://localhost:{port}"

        typer.echo("  Waiting for health...")
        deadline = time.time() + 60
        healthy = False
        while time.time() < deadline:
            try:
                r = httpx.get(f"{api_url}/health", timeout=3)
                if r.status_code < 500:
                    healthy = True
                    break
            except Exception:
                pass
            time.sleep(3)

        if healthy:
            typer.secho("✓ Backend healthy", fg=typer.colors.GREEN)
        else:
            typer.secho("⚠  Backend health check timed out", fg=typer.colors.YELLOW)

        # Migrations
        from mycelium.commands.install import _run_migrations

        _run_migrations()

        typer.echo("")
        typer.secho("Done.", fg=typer.colors.GREEN, bold=True)

    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
