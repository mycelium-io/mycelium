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
from mycelium.error_handler import print_error
from mycelium.exceptions import ConfigNotFoundError
from mycelium.http_client import MyceliumHTTPClient  # kept for health check

app = typer.Typer(help="Instance management commands")


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


def stop(
    ctx: typer.Context,
    volumes: bool = typer.Option(False, "--volumes", "-v", help="Also remove volumes (destructive)"),
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


def status(ctx: typer.Context) -> None:
    """
    Show service health.

    Checks if Mycelium backend is running and accessible.
    """
    try:
        import httpx

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


def logs(
    ctx: typer.Context,
    service: str | None = typer.Argument(None, help="Service name (e.g. mycelium-backend, ioc-cfn-mgmt-plane-svc)"),
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
