# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
`mycelium ui`: manage the optional frontend.

The frontend ships as a separate Docker image gated behind the `ui` profile
in the bundled compose file. It runs at http://localhost:3000 by default and
talks to the backend at http://localhost:<backend_port> (baked into the
image at build time; see mycelium-frontend/Dockerfile).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import webbrowser

import typer

from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref

app = typer.Typer(
    name="ui",
    help="Manage the optional frontend.",
    no_args_is_help=True,
)

_FRONTEND_CONTAINER = "mycelium-frontend"
_DEFAULT_PORT = 3000


def _ui_url() -> str:
    """The URL the user opens in their browser. Honors config.toml and MYCELIUM_UI_PORT."""
    if env_port := os.environ.get("MYCELIUM_UI_PORT"):
        port = env_port
    else:
        try:
            cfg = MyceliumConfig.load()
            port = str(cfg.runtime.frontend_port)
        except Exception:
            port = str(_DEFAULT_PORT)
    return f"http://localhost:{port}"


def _container_running(name: str) -> bool:
    """True if a Docker container with this name is currently running."""
    """Check if a running Docker container matches the given name."""
    if not shutil.which("docker"):
        return False
    r = subprocess.run(
        ["docker", "ps", "--filter", f"name=^{name}$", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
    )
    return r.returncode == 0 and name in r.stdout.strip().splitlines()


@doc_ref(
    usage="mycelium ui open [-y]",
    desc="Open the frontend in your default browser.",
    group="setup",
)
def ui_open(
    ctx: typer.Context,
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip the confirmation prompt and start the frontend if it isn't running",
    ),
) -> None:
    """Open the frontend in your default browser.

    If the frontend container isn't running, offers to start it with
    `mycelium up --ui` first. Pass `-y` to skip the prompt and start it
    automatically.

    Examples:
        mycelium ui open
        mycelium ui open -y
    """
    url = _ui_url()
    if not _container_running(_FRONTEND_CONTAINER):
        typer.secho(
            f"⚠ {_FRONTEND_CONTAINER} is not running.",
            fg=typer.colors.YELLOW,
        )
        if not yes and not typer.confirm("Start it now with 'mycelium up --ui'?", default=True):
            typer.echo("  Start it later with: mycelium up --ui")
            return
        # Proxy to `mycelium up --ui`. Imported lazily to avoid a circular
        # import between the commands modules.
        from mycelium.commands import instance

        instance.start(ctx, build=False, ui=True)
    typer.echo(f"Opening {url}")
    webbrowser.open(url)


@doc_ref(
    usage="mycelium ui status",
    desc="Show whether the frontend container is running.",
    group="setup",
)
def ui_status() -> None:
    """Show whether the frontend container is running.

    Examples:
        mycelium ui status
    """
    url = _ui_url()
    if _container_running(_FRONTEND_CONTAINER):
        typer.secho(f"✓ {_FRONTEND_CONTAINER} is running", fg=typer.colors.GREEN)
        typer.echo(f"  URL: {url}")
    else:
        typer.secho(f"✗ {_FRONTEND_CONTAINER} is not running", fg=typer.colors.RED)
        typer.echo("  Start it with: mycelium up --ui")
        # Surface the configured backend so the user can sanity-check.
        try:
            cfg = MyceliumConfig.load()
            typer.echo(f"  Backend: {cfg.server.api_url}")
        except Exception:
            pass


app.command(name="open")(ui_open)
app.command(name="status")(ui_status)
