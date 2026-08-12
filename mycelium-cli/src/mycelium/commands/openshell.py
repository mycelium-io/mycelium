# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium openshell`` — install + run the OpenShell gateway that sandboxes Pi.

Drives the validated local-gateway recipe (see :mod:`mycelium.openshell`) as one
opt-in command so a user doesn't hand-assemble the JWT keys, config, mirrored
mounts, and registration. OpenShell is where our *internal* Pi cognition engines
run sandboxed; user/participant agents are unaffected.
"""

from __future__ import annotations

import typer
from rich.console import Console

from mycelium import openshell
from mycelium.config import MyceliumConfig
from mycelium.error_handler import print_error

app = typer.Typer(help="Install + run the OpenShell sandbox gateway for Pi engines.")
console = Console()

_SECURITY_NOTE = (
    "[yellow]OpenShell's local gateway mounts the Docker socket and runs with TLS "
    "off + unauthenticated local access.[/yellow]\n"
    "That's the documented local-dev setup, but it grants the gateway container "
    "control of your Docker. Only enable it on a trusted machine."
)


@app.command("install")
def install(
    ctx: typer.Context,
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the security confirmation."),
    metrics: bool = typer.Option(
        True, "--metrics/--no-metrics", help="Expose the gateway's /metrics + add a scrape target."
    ),
) -> None:
    """Set up + start a local OpenShell gateway and the bundled Pi sandbox.

    Ensures the ``openshell`` CLI, extracts the supervisor binary, generates the
    JWT keypair, writes the gateway config, runs the gateway container, registers
    it, creates the ``--from pi`` sandbox, and (with ``--metrics``) wires a
    ``grpc_red`` scrape target so it shows up in ``mycelium metrics``.
    """
    try:
        console.print(_SECURITY_NOTE)
        if not yes and not typer.confirm("Set up the OpenShell gateway here?", default=True):
            raise typer.Exit(0)

        config = MyceliumConfig.load()

        steps = [
            ("Ensuring openshell CLI", openshell.ensure_cli),
            (
                "Extracting supervisor binary",
                lambda: openshell.extract_supervisor(openshell.supervisor_bin()),
            ),
            ("Generating JWT keypair", lambda: openshell.generate_jwt_keypair(openshell.jwt_dir())),
            ("Writing gateway config", _write_config),
            ("Starting gateway container", lambda: openshell.run_gateway(enable_metrics=metrics)),
            ("Registering gateway", openshell.register_gateway),
            ("Creating Pi sandbox", openshell.create_pi_sandbox),
        ]
        for label, fn in steps:
            with console.status(f"[cyan]{label}…[/cyan]"):
                fn()
            console.print(f"  [green]✓[/green] {label}")

        if metrics and openshell.ensure_scrape_target(config):
            config.save()
            console.print(
                f"  [green]✓[/green] Added metrics scrape target [dim]({openshell.SCRAPE_TARGET_NAME})[/dim]"
            )
            console.print(
                "    [dim]restart the collector to pick it up: mycelium up --metrics[/dim]"
            )

        console.print(
            f"\n[green]OpenShell ready.[/green] Pi sandbox: [cyan]{openshell.PI_SANDBOX_NAME}[/cyan]\n"
            "  Run an engine sandboxed: [dim]ALIGNER_PI_OPENSHELL=true[/dim]"
        )
    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None


@app.command("status")
def status(ctx: typer.Context) -> None:
    """Show the gateway container + Pi sandbox + CLI state."""
    try:
        console.print(
            f"  openshell CLI: {'[green]installed[/green]' if openshell.cli_installed() else '[red]missing[/red]'}"
        )
        console.print(
            f"  gateway:       {'[green]running[/green]' if openshell.gateway_running() else '[yellow]stopped[/yellow]'} [dim]({openshell.GATEWAY_CONTAINER})[/dim]"
        )
        cfg = MyceliumConfig.load()
        wired = any(t.name == openshell.SCRAPE_TARGET_NAME for t in cfg.metrics.scrape)
        console.print(f"  metrics wired: {'[green]yes[/green]' if wired else '[dim]no[/dim]'}")
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None


@app.command("down")
def down(ctx: typer.Context) -> None:
    """Stop + remove the OpenShell gateway container (artifacts/keys are kept)."""
    try:
        import subprocess

        subprocess.run(
            ["docker", "rm", "-f", openshell.GATEWAY_CONTAINER],
            capture_output=True,
            text=True,
            check=False,
        )
        console.print(f"[green]Stopped[/green] {openshell.GATEWAY_CONTAINER}.")
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None


def _write_config() -> None:
    openshell.state_dir().mkdir(parents=True, exist_ok=True)
    openshell.gateway_toml().write_text(openshell.render_gateway_toml(), encoding="utf-8")
