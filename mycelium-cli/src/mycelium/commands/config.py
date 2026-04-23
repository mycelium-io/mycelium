# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cisco Systems, Inc. and its affiliates

"""Config commands for Mycelium CLI."""

import json as json_module
import subprocess
from pathlib import Path

import typer

from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref
from mycelium.error_handler import print_error

app = typer.Typer(
    help="View and update Mycelium settings. Global config lives at ~/.mycelium/config.toml.",
    no_args_is_help=True,
)

ENVIRONMENTS = {
    "local": {
        "api_url": "http://localhost:8000",
    },
}


@doc_ref(
    usage="mycelium config show",
    desc="Print current configuration (API URL, identity, active room).",
    group="config",
)
@app.command("show")
def show(ctx: typer.Context) -> None:
    """Show current configuration."""
    try:
        json_output = ctx.obj.get("json", False) if ctx.obj else False
        config = MyceliumConfig.load()

        if json_output:
            typer.echo(
                json_module.dumps(
                    config.model_dump(mode="json", exclude_none=True),
                    indent=2,
                )
            )
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
            if config.llm.model:
                typer.echo(f"  LLM Model:    {config.llm.model}")
            if config.llm.base_url:
                typer.echo(f"  LLM Base URL: {config.llm.base_url}")
            if config.llm.api_key:
                masked = config.llm.api_key[:8] + "..." if len(config.llm.api_key) > 8 else "***"
                typer.echo(f"  LLM API Key:  {masked}")
            typer.echo(f"  DB Port:      {config.runtime.db_port}")
            typer.echo(f"  Backend Port: {config.runtime.backend_port}")

    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None


@doc_ref(
    usage="mycelium config set <key> <value> [--env <preset>]",
    desc="Set a configuration value or switch environment preset.",
    group="config",
)
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

        # Try to coerce JSON arrays/bools/numbers so list fields round-trip correctly
        parsed_value: object = value
        try:
            parsed_value = json_module.loads(value)
        except (json_module.JSONDecodeError, ValueError):
            pass

        if len(parts) == 2:
            section = getattr(config, parts[0])
            setattr(section, parts[1], parsed_value)
        elif len(parts) == 1:
            setattr(config, parts[0], parsed_value)
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


@doc_ref(
    usage="mycelium config get <key>",
    desc="Read a configuration value.",
    group="config",
)
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


@doc_ref(
    usage="mycelium config apply [--restart] [--migrate-env]",
    desc="Regenerate .env from config.toml and optionally restart containers.",
    group="config",
)
@app.command("apply")
def apply_config(
    ctx: typer.Context,
    restart: bool = typer.Option(
        False, "--restart", "-r", help="Restart Docker containers after applying"
    ),
    migrate_env: bool = typer.Option(
        False,
        "--migrate-env",
        help="Import LLM and runtime settings from the existing .env into config.toml before generating",
    ),
) -> None:
    """
    Regenerate ~/.mycelium/.env from config.toml.

    config.toml is the single source of truth. This command derives the
    Docker .env file from it so that ``docker compose`` picks up any
    changes you made via ``mycelium config set``.

    For installs that predate the unified config, use --migrate-env to
    import LLM keys, ports, and CFN settings from the existing .env into
    config.toml first.  This is safe to run multiple times.

    Examples:
        mycelium config apply                  # regenerate .env
        mycelium config apply --migrate-env    # import .env → config.toml, then regenerate
        mycelium config apply --restart        # regenerate .env and restart containers
    """
    try:
        config = MyceliumConfig.load()

        if migrate_env:
            _migrate_env_to_config(config)

        from mycelium.docker_utils import write_env_file

        env_path = write_env_file(config)
        typer.secho(f"  ✓ Wrote {env_path}", fg=typer.colors.GREEN)

        if restart:
            typer.echo("  Restarting containers...")
            compose_path = _find_compose_path()
            if not compose_path:
                typer.secho("  ✗ Could not find compose.yml", fg=typer.colors.RED)
                raise typer.Exit(1)

            result = subprocess.run(
                [
                    "docker",
                    "compose",
                    "-p",
                    "mycelium",
                    "-f",
                    str(compose_path),
                    "--env-file",
                    str(env_path),
                    "up",
                    "--force-recreate",
                    "-d",
                ],
                text=True,
            )
            if result.returncode == 0:
                typer.secho("  ✓ Containers restarted", fg=typer.colors.GREEN)
            else:
                typer.secho("  ✗ Restart failed", fg=typer.colors.RED)
                raise typer.Exit(1)

    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None


def _find_compose_path() -> Path | None:
    """Find the compose file — same logic as install.py but simplified."""
    import importlib.resources

    bundled = Path.home() / ".mycelium" / "docker" / "compose.yml"
    if bundled.exists():
        return bundled

    cwd_candidate = Path.cwd() / "services" / "docker-compose.yml"
    if cwd_candidate.exists():
        return cwd_candidate

    try:
        pkg_path = Path(str(importlib.resources.files("mycelium")))
        for depth in range(2, 7):
            candidate = pkg_path.parents[depth] / "services" / "docker-compose.yml"
            if candidate.exists():
                return candidate
    except Exception:
        pass

    try:
        ref = importlib.resources.files("mycelium.docker") / "compose.yml"
        dest = Path.home() / ".mycelium" / "docker" / "compose.yml"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(ref.read_bytes())
        return dest
    except Exception:
        return None


# ── .env → config.toml migration ─────────────────────────────────────────


def _parse_env_file(env_path: Path) -> dict[str, str]:
    """Read a .env file into a dict, skipping comments and blank lines."""
    vals: dict[str, str] = {}
    if not env_path.exists():
        return vals
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        vals[key.strip()] = value.strip()
    return vals


def _migrate_env_to_config(config: "MyceliumConfig") -> None:
    """Import LLM and runtime settings from the existing .env into config.

    Only fills in fields that are empty/default in config.toml — never
    overwrites values the user already set in TOML.
    """
    env_path = config.get_global_config_dir() / ".env"
    env = _parse_env_file(env_path)
    if not env:
        typer.secho("  ⚠ No .env found to migrate", fg=typer.colors.YELLOW)
        return

    changed = False

    # LLM
    if not config.llm.model and env.get("LLM_MODEL"):
        config.llm.model = env["LLM_MODEL"]
        changed = True
    if not config.llm.api_key and env.get("LLM_API_KEY"):
        config.llm.api_key = env["LLM_API_KEY"]
        changed = True
    base_url = env.get("LLM_BASE_URL", "").strip()
    if not config.llm.base_url and base_url:
        config.llm.base_url = base_url
        changed = True

    # Runtime — ports
    env_db_port = env.get("MYCELIUM_DB_PORT")
    if env_db_port and config.runtime.db_port == 5432:  # still default
        try:
            config.runtime.db_port = int(env_db_port)
            changed = True
        except ValueError:
            pass
    env_backend_port = env.get("MYCELIUM_BACKEND_PORT")
    if env_backend_port and config.runtime.backend_port == 8000:  # still default
        try:
            config.runtime.backend_port = int(env_backend_port)
            changed = True
        except ValueError:
            pass

    # Runtime — passwords
    env_db_pw = env.get("MYCELIUM_DB_PASSWORD")
    if env_db_pw and config.runtime.db_password == "password":  # still default
        config.runtime.db_password = env_db_pw
        changed = True

    # Runtime — data dir
    if not config.runtime.data_dir and env.get("MYCELIUM_DATA_DIR"):
        config.runtime.data_dir = env["MYCELIUM_DATA_DIR"]
        changed = True

    # Runtime — CFN
    if not config.runtime.cfn_mgmt_url and env.get("CFN_MGMT_URL"):
        config.runtime.cfn_mgmt_url = env["CFN_MGMT_URL"]
        changed = True
    if not config.runtime.cognition_fabric_node_url and env.get("COGNITION_FABRIC_NODE_URL"):
        config.runtime.cognition_fabric_node_url = env["COGNITION_FABRIC_NODE_URL"]
        changed = True
    if not config.runtime.workspace_id and env.get("WORKSPACE_ID"):
        config.runtime.workspace_id = env["WORKSPACE_ID"]
        changed = True

    if changed:
        config.save()
        typer.secho("  ✓ Migrated .env settings into config.toml", fg=typer.colors.GREEN)
    else:
        typer.echo("  ℹ config.toml already has all settings — nothing to migrate")
