"""Config commands for Mycelium CLI."""

import json as json_module

import typer

from mycelium.config import MyceliumConfig
from mycelium.error_handler import print_error

app = typer.Typer(help="Configuration management", no_args_is_help=True)

ENVIRONMENTS = {
    "local": {
        "api_url": "http://localhost:8000",
    },
}


@app.command("show")
def show(ctx: typer.Context) -> None:
    """Show current configuration."""
    try:
        json_output = ctx.obj.get("json", False) if ctx.obj else False
        config = MyceliumConfig.load()

        if json_output:
            typer.echo(json_module.dumps({
                "server": {
                    "api_url": config.server.api_url,
                    "workspace_id": config.server.workspace_id,
                    "mas_id": config.server.mas_id,
                },
                "identity": {"name": config.identity.name},
                "room": {"active": config.rooms.active},
            }, indent=2))
        else:
            typer.secho("Current configuration:", bold=True)
            typer.echo(f"  API URL:      {config.server.api_url}")
            if config.server.workspace_id:
                typer.echo(f"  Workspace ID: {config.server.workspace_id}")
            if config.server.mas_id:
                typer.echo(f"  MAS ID:       {config.server.mas_id}")
            if config.identity.name:
                typer.echo(f"  Identity:     {config.identity.name}")
            if config.rooms.active:
                typer.echo(f"  Active Room:  {config.rooms.active}")

    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None


@app.command("set")
def set_config(
    ctx: typer.Context,
    key: str = typer.Argument(None, help="Config key (e.g., server.api_url)"),
    value: str = typer.Argument(None, help="Config value"),
    env: str = typer.Option(None, "--env", "-e", help="Apply environment preset (local)"),
) -> None:
    """
    Set a configuration value or switch environment.

    Examples:
        mycelium config set server.api_url http://myhost:8000
        mycelium config set --env local
    """
    try:
        if env:
            if env not in ENVIRONMENTS:
                typer.secho(
                    f"Error: Unknown environment '{env}'. Valid: {', '.join(ENVIRONMENTS.keys())}",
                    fg=typer.colors.RED,
                )
                raise typer.Exit(1)
            env_vals = ENVIRONMENTS[env]
            config = MyceliumConfig.load()
            config.server.api_url = env_vals["api_url"]
            config.save()
            typer.secho(f"Switched to {env}", fg=typer.colors.GREEN)
            return

        if not key or not value:
            typer.secho("Error: Provide key and value, or use --env", fg=typer.colors.RED)
            raise typer.Exit(1)

        config = MyceliumConfig.load()
        parts = key.split(".")

        if len(parts) == 2:
            section = getattr(config, parts[0])
            setattr(section, parts[1], value)
        elif len(parts) == 1:
            setattr(config, parts[0], value)
        else:
            raise ValueError(f"Unsupported key format: {key}")

        config.save()
        typer.secho(
            f"Set {key} = {value[:20]}{'...' if len(value) > 20 else ''}",
            fg=typer.colors.GREEN,
        )

    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None


@app.command("get")
def get_config(
    ctx: typer.Context,
    key: str = typer.Argument(..., help="Config key (e.g., server.api_url)"),
) -> None:
    """Get a configuration value."""
    try:
        config = MyceliumConfig.load()
        parts = key.split(".")
        value = config
        for part in parts:
            value = getattr(value, part)

        if value is None:
            print_error(f"Config key '{key}' not found")
            raise typer.Exit(1)

        if ctx.obj.get("json", False):
            typer.echo(json_module.dumps({"key": key, "value": value}, indent=2))
        else:
            typer.echo(value)

    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None
