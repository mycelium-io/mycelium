# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Hub commands: run and connect to a SLIM node (the messaging fabric).

``mycelium hub host`` spins up the ``slim`` node container and prints the
address peers connect to. ``mycelium connect <address>`` stores a node endpoint
in config. The connect address is the same whether the node is self-hosted or a
shared mycelium-hosted rendezvous; MLS makes the node a blind ciphertext
forwarder, so there's no separate command per host.
"""

from __future__ import annotations

import socket
import subprocess
from typing import TYPE_CHECKING

import typer

from mycelium.cli_options import emits_json
from mycelium.commands.instance import (
    _COMPOSE_PROJECT,
    _get_compose_path,
    _get_env_path,
)
from mycelium.config import MyceliumConfig, SlimConfig
from mycelium.doc_ref import doc_ref
from mycelium.error_handler import print_error

if TYPE_CHECKING:
    from mycelium_backend_client.models import HubSettings

app = typer.Typer(
    help="Run and manage the SLIM node (messaging fabric).",
    no_args_is_help=True,
)

# The compose service `mycelium hub host` starts on its own.
SLIM_SERVICE = "slim"


def _slim_port() -> str:
    """Resolve the node's published port from ~/.mycelium/.env (default 46357)."""
    env_path = _get_env_path()
    if env_path and env_path.exists():
        from dotenv import dotenv_values

        if port := dotenv_values(env_path).get("MYCELIUM_SLIM_PORT"):
            return port
    return "46357"


def _lan_ip() -> str | None:
    """Best-effort LAN IP so peers on the network can reach a self-hosted node."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return None


@doc_ref(
    usage="mycelium hub host",
    desc="Start the SLIM node and print the address peers connect to.",
    group="setup",
)
def host(ctx: typer.Context) -> None:
    """Spin up the SLIM node container and print the connect address.

    Starts only the ``slim`` service from the compose stack and stores the local
    endpoint in config so this machine is immediately connected. Share the
    printed LAN address and have peers run ``mycelium connect <address>``.
    """
    try:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False  # noqa: F841
        compose_path = _get_compose_path()

        if not compose_path.exists():
            typer.secho(f"Compose file not found at {compose_path}", fg=typer.colors.RED)
            typer.echo("Run 'mycelium install' first.")
            raise typer.Exit(1)

        cmd = ["docker", "compose", "-p", _COMPOSE_PROJECT, "-f", str(compose_path)]
        env_path = _get_env_path()
        if env_path:
            cmd += ["--env-file", str(env_path)]
        cmd += ["up", "-d", SLIM_SERVICE]

        typer.echo("Starting SLIM node...")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            if result.stdout:
                typer.echo(result.stdout)
            if result.stderr:
                typer.echo(result.stderr, err=True)
            raise typer.Exit(result.returncode)

        port = _slim_port()
        local_endpoint = f"http://127.0.0.1:{port}"

        # Self-host: wire this machine up immediately.
        config = MyceliumConfig.load()
        config.slim = config.slim.model_copy(update={"node_endpoint": local_endpoint})
        config.save()

        typer.secho("SLIM node running.", fg=typer.colors.GREEN)
        typer.echo(f"  local     → {local_endpoint}  (this machine, saved to config)")
        lan_ip = _lan_ip()
        if lan_ip:
            typer.echo(f"  for peers → http://{lan_ip}:{port}")
            typer.echo("")
            typer.echo(f"  Peers connect with:  mycelium connect http://{lan_ip}:{port}")

    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


app.command(name="host")(host)


@doc_ref(
    usage="mycelium connect <address>",
    desc="Store the SLIM node endpoint to connect to (self- or mycelium-hosted).",
    group="setup",
)
def connect(
    ctx: typer.Context,
    address: str = typer.Argument(
        ...,
        help="SLIM node address, e.g. http://hub-ip:46357 (scheme optional)",
    ),
) -> None:
    """Store a SLIM node endpoint in config.

    Same command whether the node is self-hosted or a shared mycelium-hosted
    rendezvous: just point at a different address.
    """
    try:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False  # noqa: F841
        config = MyceliumConfig.load()
        # Construct through SlimConfig so its validator adds the scheme and trims
        # slashes (pydantic v2 doesn't validate plain attribute assignment).
        normalized = SlimConfig(
            node_endpoint=address,
            identity=config.slim.identity,
            master_secret=config.slim.master_secret,
        )
        config.slim = normalized
        config.save()
        typer.secho(
            f"Connected to SLIM node at {config.slim.node_endpoint}",
            fg=typer.colors.GREEN,
        )
        typer.echo(
            "  Stored the SLIM node endpoint. Default participation (memory, "
            "await/respond) uses the hub HTTP API (server.api_url), not SLIM."
        )
        typer.echo("  Spokes do not need MYCELIUM_SLIM_MASTER_SECRET for that path.")
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


def _settings_lines(s: HubSettings) -> list[str]:
    name = s.model.model or "none set"
    key = "key set" if s.model.has_key else "no key"
    lines = [
        f"  Model         {name} ({key}{', custom endpoint' if s.model.custom_endpoint else ''})"
    ]
    if s.experiences:
        for x in s.experiences:
            unit = "scenario" if x.scenarios == 1 else "scenarios"
            lines.append(f"  Experience    {x.title}: {x.scenarios} {unit}, at {x.open_}")
    else:
        lines.append("  Experiences   none")
    lines.append(f"  Personas only {'yes' if s.personas_only else 'no'}")
    lines.append(f"  Usage stats   {'shared' if s.share_usage else 'not shared'}")
    return lines


@doc_ref(
    usage="mycelium hub settings [--hub <url>] [--json]",
    desc="What the hub is set up with (model, experiences, usage stats). Read-only; no key is shown.",
    group="setup",
)
@app.command("settings")
@emits_json("json_output")
def hub_settings(
    hub: str | None = typer.Option(None, "--hub", help="The hub to ask. Default: this machine's."),
    json_output: bool = False,
) -> None:
    """What the hub is set up with, read-only.

    For a hub on another machine, the one place that knows what it runs. It says
    whether a key is set, never the key. Change settings on the hub's machine.

    Examples:
        mycelium hub settings
        mycelium hub settings --hub https://hub.example.com --json
    """
    import json

    import httpx

    from mycelium.client import hub_error_detail, typed_client
    from mycelium_backend_client.api.hub import hub_settings_api_hub_settings_get
    from mycelium_backend_client.models import HubSettings

    client = typed_client(base_url=hub, timeout=30, raise_on_unexpected_status=False)
    with client:
        try:
            resp = hub_settings_api_hub_settings_get.sync_detailed(client=client)
        except httpx.HTTPError as exc:
            typer.secho(f"Couldn't reach the hub: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(1) from None
    if resp.status_code == 404:  # noqa: PLR2004
        typer.secho("This hub is older and doesn't say what it's set up with.", err=True)
        raise typer.Exit(1)
    settings = resp.parsed
    if not isinstance(settings, HubSettings):
        typer.secho(
            f"The hub said no: {hub_error_detail(resp.content)}", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(1)
    if json_output:
        typer.echo(json.dumps(settings.to_dict()))
        return
    typer.echo(f"  {hub or client.get_httpx_client().base_url}")
    for line in _settings_lines(settings):
        typer.echo(line)
