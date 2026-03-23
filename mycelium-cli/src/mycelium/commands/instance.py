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

import subprocess
from pathlib import Path

import typer

from mycelium.config import MyceliumConfig, ServerConfig
from mycelium.doc_ref import doc_ref
from mycelium.error_handler import print_error
from mycelium.exceptions import ConfigNotFoundError
from mycelium.http_client import MyceliumHTTPClient  # kept for health check

app = typer.Typer(
    help="Docker lifecycle for the Mycelium stack (database, backend, graph viewer).",
    no_args_is_help=True,
)


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
        env_path = _get_env_path()

        if not compose_path.exists():
            typer.secho(f"Compose file not found at {compose_path}", fg=typer.colors.RED)
            typer.echo("Run 'mycelium install' first.")
            raise typer.Exit(1)

        cmd = ["docker", "compose", "-f", str(compose_path)]
        if env_path:
            cmd += ["--env-file", str(env_path)]
        cmd += ["up", "-d"]
        if build:
            cmd.append("--build")

        typer.echo("Starting Mycelium...")
        result = subprocess.run(cmd, check=False)
        if result.returncode != 0:
            raise typer.Exit(result.returncode)

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
        env_path = _get_env_path()

        if not compose_path.exists():
            typer.secho(f"Compose file not found at {compose_path}", fg=typer.colors.RED)
            raise typer.Exit(1)

        cmd = ["docker", "compose", "-f", str(compose_path)]
        if env_path:
            cmd += ["--env-file", str(env_path)]
        cmd += ["down"]
        if volumes:
            cmd.append("-v")

        typer.echo("Stopping Mycelium services...")
        result = subprocess.run(cmd, check=False)
        if result.returncode != 0:
            raise typer.Exit(result.returncode)

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

    Checks if Mycelium backend is running and accessible.
    """
    try:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False  # noqa: F841
        json_output = ctx.obj.get("json", False) if ctx.obj else False

        config_path = MyceliumConfig.get_config_path()
        if not config_path.exists():
            raise ConfigNotFoundError(str(config_path))

        config = MyceliumConfig.load()

        # Check backend health
        backend_running = False
        backend_room_count = 0
        with MyceliumHTTPClient(config=config) as client:
            try:
                response = client.get("/rooms")
                rooms = response.json()
                backend_running = True
                backend_room_count = len(rooms) if isinstance(rooms, list) else 0
            except Exception:
                backend_running = False

        def status_str(running: bool) -> tuple[str, str]:
            return ("Running", typer.colors.GREEN) if running else ("Not running", typer.colors.RED)

        backend_status, backend_color = status_str(backend_running)

        if json_output:
            import json

            output = {
                "services": {
                    "backend": {
                        "url": config.server.api_url,
                        "running": backend_running,
                        "room_count": backend_room_count,
                    },
                },
                "config": {
                    "path": str(config_path),
                    "api_url": config.server.api_url,
                    "active_room": config.get_active_room(),
                },
            }
            typer.echo(json.dumps(output, indent=2))
        else:
            typer.secho("Mycelium Status", bold=True)
            typer.echo("")
            typer.echo("Services:")
            typer.secho(f"  Backend:   {backend_status}", fg=backend_color)
            typer.echo(f"             {config.server.api_url}")
            if backend_running and backend_room_count > 0:
                typer.echo(f"             {backend_room_count} rooms")
            typer.echo("")
            typer.echo("Configuration:")
            typer.echo(f"  Path:        {config_path}")
            if config.get_active_room():
                typer.echo(f"  Active Room: {config.get_active_room()}")
            typer.echo("")
            if backend_running:
                typer.secho("Backend healthy", fg=typer.colors.GREEN)
            else:
                typer.secho("Backend is down", fg=typer.colors.YELLOW)
                typer.echo("\nTo start services:")
                typer.echo("  mycelium start")

    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


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
        compose_path = _get_compose_path()
        env_path = _get_env_path()

        cmd = ["docker", "compose", "-f", str(compose_path)]
        if env_path:
            cmd += ["--env-file", str(env_path)]
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
