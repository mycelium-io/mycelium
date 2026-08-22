# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

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

from mycelium.client import hub_error_detail
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
    help="Docker lifecycle for the Mycelium stack (backend, collector).",
    no_args_is_help=True,
)

_COMPOSE_PROJECT = "mycelium"

# Every container the CLI is willing to stop and remove. `docker compose down`
# only reaches its own project, so this is the net for containers started under
# another project name or outside compose. The ioc-cfn entries are a separate
# deployment the CLI can stop but does not define.
_MANAGED_CONTAINERS = [
    "mycelium-slim",
    "mycelium-backend",
    "mycelium-frontend",
    "mycelium-collector",
    "ioc-cfn-mgmt-plane-svc",
    "ioc-cfn-svc",
]


def _get_compose_path() -> Path:
    """
    Resolve docker-compose file path.

    Priority:
      1. MYCELIUM_COMPOSE_FILE env var
      2. Walk up from package location to find repo's services/docker-compose.yml
         (editable installs; keeps relative build contexts correct)
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


def _compose_base_cmd(
    compose_path: Path | None = None,
    env_path: Path | None = None,
    project_name: str | None = None,
    *,
    include_cfn_profile: bool = True,
    include_metrics_profile: bool = True,
) -> list[str]:
    """Build the docker compose prefix with consistent project name.

    When *include_cfn_profile* is True (the default) and CFN is enabled in
    the user's .env, ``--profile cfn`` is appended automatically so callers
    don't need to duplicate that logic.

    When *include_metrics_profile* is True (the default) and the collector
    container is running, ``--profile metrics`` is appended so stop/logs/down
    commands include it without ad-hoc detection.
    """
    if compose_path is None:
        compose_path = _get_compose_path()
    if env_path is None:
        env_path = _get_env_path()
    cmd = ["docker", "compose", "-p", project_name or _COMPOSE_PROJECT, "-f", str(compose_path)]
    if env_path:
        cmd += ["--env-file", str(env_path)]
    if include_cfn_profile and _cfn_enabled():
        cmd += ["--profile", "cfn"]
    if include_metrics_profile and _collector_container_running():
        cmd += ["--profile", "metrics"]
    return cmd


def _detect_compose_project() -> str:
    """Return the compose project name that running Mycelium containers belong to.

    Inspects the ``mycelium-backend`` container label to discover the project
    name that was used at ``docker compose up`` time.  Falls back to the
    default ``_COMPOSE_PROJECT`` if the container isn't running or doesn't
    have the expected label.
    """
    try:
        result = subprocess.run(
            [
                "docker",
                "inspect",
                "mycelium-backend",
                "--format",
                '{{ index .Config.Labels "com.docker.compose.project" }}',
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return _COMPOSE_PROJECT


def _patch_env_image_tag(env_path: Path, tag: str) -> None:
    """Set MYCELIUM_IMAGE_TAG=<tag> in ~/.mycelium/.env (insert if absent).

    Used by ``mycelium pull --version`` to pin compose's ``${MYCELIUM_IMAGE_TAG:-latest}``
    substitution across restarts. Pass ``tag="latest"`` to unpin.
    """
    if not env_path.exists():
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.write_text(f"MYCELIUM_IMAGE_TAG={tag}\n", encoding="utf-8")
        return
    lines = env_path.read_text(encoding="utf-8").splitlines()
    found = False
    new_lines = []
    for line in lines:
        if "=" in line and not line.lstrip().startswith("#"):
            key = line.split("=", 1)[0].strip()
            if key == "MYCELIUM_IMAGE_TAG":
                new_lines.append(f"MYCELIUM_IMAGE_TAG={tag}")
                found = True
                continue
        new_lines.append(line)
    if not found:
        new_lines.append(f"MYCELIUM_IMAGE_TAG={tag}")
    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def _announce_image_tag() -> None:
    """Print the effective ``MYCELIUM_IMAGE_TAG`` after ``mycelium up``.

    Compose silently falls back to ``:latest`` when the pin is absent, which
    is a UX trap: users assume the version they last pulled is still running.
    Surface the resolved tag (and a hint when unpinned) so the next person
    triaging an image-mismatch bug doesn't have to dig through .env.
    """
    env_path = _get_env_path()
    pinned = None
    if env_path is not None:
        from mycelium.docker_utils import read_pinned_image_tag

        pinned = read_pinned_image_tag(env_path)

    if pinned and pinned != "latest":
        typer.secho(
            f"  → image tag: {pinned} (pinned via 'mycelium pull --version')",
            fg=typer.colors.CYAN,
        )
    else:
        typer.secho(
            "  → image tag: latest (unpinned; run 'mycelium pull --version X' to pin)",
            fg=typer.colors.YELLOW,
        )


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


def _container_running(name: str) -> bool:
    """Return True if the named container is running."""
    try:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", name],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        return result.returncode == 0 and result.stdout.strip().lower() == "true"
    except Exception:
        return False


def _collector_container_running() -> bool:
    """Return True if the mycelium-collector container is running."""
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

        from mycelium.config import MetricsConfig

        # Auto-derive collector_url for spoke nodes (non-local api_url).
        metrics_config = MetricsConfig()
        from urllib.parse import urlparse

        parsed = urlparse(api_url)
        hub_host = parsed.hostname or ""
        if hub_host not in ("localhost", "127.0.0.1", "::1", "0.0.0.0", ""):
            default_collector = f"http://{hub_host}:4318"
            collector_url = typer.prompt(
                "Hub collector URL (for metrics)",
                default=default_collector,
                show_default=True,
            )
            metrics_config = MetricsConfig(collector_url=collector_url)

        config = MyceliumConfig(
            server=ServerConfig(
                api_url=api_url,
            ),
            metrics=metrics_config,
        )
        config.save(config_path)

        typer.secho(f"Created configuration at {config_path}", fg=typer.colors.GREEN)
        typer.echo("")
        typer.echo("Configuration:")
        typer.echo(f"  API URL: {api_url}")
        if metrics_config.collector_url:
            typer.echo(f"  Collector URL: {metrics_config.collector_url}  (hub-centric metrics)")
        typer.echo("")
        if metrics_config.collector_url:
            typer.echo("Next steps:")
            typer.echo("  - Run 'mycelium metrics status' to verify collector connectivity")
        else:
            typer.echo("Next steps:")
            typer.echo("  - Run 'mycelium install' to pull and start all services")
            typer.echo("  - Run 'mycelium status' to check service health")

    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


@doc_ref(
    usage="mycelium up [--build] [--metrics]",
    desc="Start the Mycelium stack via <code>docker compose up</code>.",
    group="setup",
)
def start(
    ctx: typer.Context,
    build: bool = typer.Option(False, "--build", help="Rebuild images before starting"),
    metrics: bool = typer.Option(
        False, "--metrics", help="Also start the OTLP collector (mycelium-collector)"
    ),
) -> None:
    """
    Start Mycelium services.

    Runs docker compose up -d using the bundled compose file and
    ~/.mycelium/.env for configuration. The SLIM node, the backend and the
    frontend all start; the OTLP collector is opt-in.

    Examples:
        mycelium up              # start all services
        mycelium up --build      # rebuild images first
        mycelium up --metrics    # also start the OTLP collector on :4318
    """
    try:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False  # noqa: F841
        compose_path = _get_compose_path()

        if not compose_path.exists():
            typer.secho(f"Compose file not found at {compose_path}", fg=typer.colors.RED)
            typer.echo("Run 'mycelium install' first.")
            raise typer.Exit(1)

        # `up` is flag-driven: the metrics profile is controlled by --metrics
        # here, not by what happens to be running, so disable the auto-detection
        # that logs/down/stop/status rely on.
        base = _compose_base_cmd(compose_path, include_metrics_profile=False)
        if metrics:
            base = base + ["--profile", "metrics"]
            # Pre-create the metrics data dir with group-write perms so the
            # in-container collector user (uid != root) can write to the
            # bind-mounted host directory. Without this, fresh installs hit
            # PermissionError on first start.
            from mycelium.collector import _ensure_shared_dir

            _ensure_shared_dir(Path.home() / ".mycelium" / "metrics")
        up_args = ["up", "-d", "--remove-orphans"]
        build_env: dict[str, str] | None = None
        if build:
            # Include compose-dev.yml so `--build` builds from the local source
            # tree instead of downloading pre-built GHCR images. compose-dev.yml
            # adds build: stanzas and sets pull_policy: never for all first-party
            # services.
            #
            # Build contexts in compose-dev.yml use ${MYCELIUM_REPO_ROOT} (an
            # absolute path) so that Docker BuildKit resolves them correctly when
            # the bake definition is piped via stdin — relative paths break in
            # that transport because buildkit uses CWD, not the compose file
            # location.
            dev_compose: Path | None = None
            try:
                # instance.py → commands/ → mycelium/ → docker/compose-dev.yml
                here = Path(__file__).parent.parent / "docker" / "compose-dev.yml"
                if here.exists():
                    dev_compose = here
            except Exception:
                pass
            if dev_compose is not None:
                base = base + ["-f", str(dev_compose)]
                # Compute repo root: mycelium-cli/src/mycelium/docker/ → up 4 → repo root
                repo_root = dev_compose.parent.parent.parent.parent.parent
                build_env = {**__import__("os").environ, "MYCELIUM_REPO_ROOT": str(repo_root)}
            else:
                typer.secho(
                    "  ⚠  --build requires an editable (development) install; "
                    "compose-dev.yml not found in the package source tree. "
                    "Falling back to pulling released images.",
                    fg=typer.colors.YELLOW,
                )
            up_args.append("--build")

        typer.echo("Starting Mycelium...")

        quiet_cmd = base[:2] + ["--progress=plain"] + base[2:] + up_args
        result = subprocess.run(quiet_cmd, capture_output=True, text=True, env=build_env)

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
                result = subprocess.run(base + up_args, check=False, env=build_env)
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

        # Pull the configured ports from .env so the summary matches reality
        # (MYCELIUM_BACKEND_PORT / MYCELIUM_UI_PORT / MYCELIUM_METRICS_PORT are
        # written by `config apply`).
        backend_port = "8000"
        ui_port = "3000"
        metrics_port = "4318"
        env_path = _get_env_path()
        if env_path and env_path.exists():
            from dotenv import dotenv_values

            vals = dotenv_values(env_path)
            backend_port = vals.get("MYCELIUM_BACKEND_PORT") or backend_port
            ui_port = vals.get("MYCELIUM_UI_PORT") or ui_port
            metrics_port = vals.get("MYCELIUM_METRICS_PORT") or metrics_port

        typer.secho("Services started.", fg=typer.colors.GREEN)
        _announce_image_tag()
        typer.echo(f"  mycelium-backend    → http://localhost:{backend_port}")
        typer.echo(f"  mycelium-frontend   → http://localhost:{ui_port}")
        if metrics:
            typer.echo(f"  mycelium-collector  → http://localhost:{metrics_port}")

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

        project = _detect_compose_project()
        base = _compose_base_cmd(compose_path, project_name=project)
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
                    detail = hub_error_detail(exc.response.content)
                    if detail:
                        backend_error = (
                            f"Backend returned HTTP {exc.response.status_code}: {detail}"
                        )
                    else:
                        backend_error = f"Backend returned HTTP {exc.response.status_code}"
                else:
                    backend_error = str(exc)

            if backend_running:
                try:
                    response = client.get("/api/rooms")
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
                    msg = f"{label}: {model}" + (f" ({key_hint})" if key_hint else "")
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
            # Informational block (no checks): path + active room.
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
                    else "Backend is down. Run: mycelium up"
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


# -- End of status helpers; see mycelium.ui_status for shared presentation -----


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

        project = _detect_compose_project()
        cmd = _compose_base_cmd(project_name=project)
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


# ── Pull command ─────────────────────────────────────────────────────────────


@doc_ref(
    usage="mycelium pull [--version <tag>] [--no-restart]",
    desc="Pull Mycelium Docker images and restart services. Pass --version to pin a preview/specific build.",
    group="setup",
)
def pull(
    ctx: typer.Context,
    target_version: str | None = typer.Option(
        None,
        "--version",
        help="Pin the mycelium-backend image tag to a specific version "
        "(e.g. 0.1.84rc1). Without --version, pulls :latest. Persisted to ~/.mycelium/.env "
        "as MYCELIUM_IMAGE_TAG so subsequent restarts stay pinned. Pass --version=latest to "
        "unpin and return to tracking the latest stable.",
    ),
    no_restart: bool = typer.Option(
        False, "--no-restart", help="Pull images but don't restart services"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmations"),  # noqa: ARG001
) -> None:
    """
    Pull Mycelium Docker images and restart services.

    By default, pulls the :latest tag of each Mycelium image. Pass
    --version <tag> to pin to a specific build (typically used with preview
    releases). The tag is persisted to ~/.mycelium/.env as
    MYCELIUM_IMAGE_TAG so the stack stays pinned across restarts.

    \b
    Examples:
        mycelium pull                       # latest stable
        mycelium pull --version 0.1.84rc1   # pin to preview build
        mycelium pull --version latest      # unpin (back to latest stable)
        mycelium pull --no-restart          # pull only, restart later
    """
    try:
        compose_path = _get_compose_path()

        if not compose_path.exists():
            typer.secho(f"Compose file not found at {compose_path}", fg=typer.colors.RED)
            typer.echo("Run 'mycelium install' first.")
            raise typer.Exit(1)

        env_path = _get_env_path()

        # If the user explicitly pinned a version (or asked to unpin via
        # --version=latest), persist that to .env *before* compose pull so the
        # ${MYCELIUM_IMAGE_TAG:-latest} substitution in compose.yml resolves
        # correctly. Stripping a leading 'v' lets users pass tag names freely.
        if target_version is not None and env_path is not None:
            normalized = target_version.lstrip("v") or "latest"
            _patch_env_image_tag(env_path, normalized)
            if normalized == "latest":
                typer.echo("  ✓ Unpinned image tag (back to :latest)")
            else:
                typer.echo(f"  ✓ Pinned image tag to {normalized} (in {env_path})")

        base = _compose_base_cmd(compose_path, env_path)

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

        typer.echo("")
        typer.secho("Done.", fg=typer.colors.GREEN, bold=True)

    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
