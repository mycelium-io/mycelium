# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Hub commands: run and connect to a SLIM node (the messaging fabric).

``mycelium hub host`` spins up the ``slim`` node container and prints the
address peers connect to. ``mycelium connect <address>`` stores a node endpoint
in config. The connect address is the same whether the node is self-hosted or a
shared mycelium-hosted rendezvous; MLS makes the node a blind ciphertext
forwarder, so there's no separate command per host.
"""

import socket
import subprocess

import typer

from mycelium.commands.instance import (
    _COMPOSE_PROJECT,
    _get_compose_path,
    _get_env_path,
)
from mycelium.config import MyceliumConfig, SlimConfig
from mycelium.doc_ref import doc_ref
from mycelium.error_handler import print_error

app = typer.Typer(
    help="Run and manage the SLIM node (messaging fabric).",
    no_args_is_help=True,
)


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
        services = ["slim"]
        # When attested identity is on (slim.identity=spire), bring the SPIRE server
        # up alongside the node, one control, config-driven (#588). The agent is
        # co-located with the backend (shared PID namespace), so it pulls the backend
        # in too; that's intended, SPIRE needs a workload to attest. The node daemon
        # itself starts in a second phase (it needs a join token minted against the
        # live server). On the default psk this is a no-op and only `slim` starts.
        from mycelium.commands.instance import _spire_enabled, bootstrap_spire_node

        spire = _spire_enabled()
        if spire:
            cmd += ["--profile", "spire"]
            services += ["mycelium-backend", "spire-server"]
        cmd += ["up", "-d", *services]

        typer.echo("Starting SLIM node...")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            if result.stdout:
                typer.echo(result.stdout)
            if result.stderr:
                typer.echo(result.stderr, err=True)
            raise typer.Exit(result.returncode)

        if spire:
            # `cmd[:-len(...)]` would be brittle; rebuild the compose prefix minus the
            # up args for the phase-2 agent bootstrap.
            base = ["docker", "compose", "-p", _COMPOSE_PROJECT, "-f", str(compose_path)]
            if env_path:
                base += ["--env-file", str(env_path)]
            base += ["--profile", "spire"]
            bootstrap_spire_node(base)

        port = _slim_port()
        local_endpoint = f"http://127.0.0.1:{port}"

        # Self-host: wire this machine up immediately.
        config = MyceliumConfig.load()
        config.slim = SlimConfig(node_endpoint=local_endpoint)
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


# Register `host` on the hub group. `connect` is registered as a top-level
# command in cli.py (`mycelium connect`), so it isn't attached here.
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
        config.slim = SlimConfig(node_endpoint=address)
        config.save()
        typer.secho(
            f"Connected to SLIM node at {config.slim.node_endpoint}",
            fg=typer.colors.GREEN,
        )
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
