# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
`mycelium ui` — manage the optional frontend.

The frontend ships as a separate Docker image gated behind the `ui` profile
in the bundled compose file. It runs at http://localhost:3000 by default and
talks to the backend at http://localhost:<backend_port> (baked into the
image at build time — see mycelium-frontend/Dockerfile).
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

# Container name set in the bundled compose.yml.
_FRONTEND_CONTAINER = "mycelium-frontend"
_DEFAULT_PORT = 3000


def _ui_url() -> str:
    """The URL the user opens in their browser. Honors MYCELIUM_UI_PORT."""
    port = os.environ.get("MYCELIUM_UI_PORT") or str(_DEFAULT_PORT)
    return f"http://localhost:{port}"


def _container_running(name: str) -> bool:
    """True if a Docker container with this name is currently running."""
    if not shutil.which("docker"):
        return False
    r = subprocess.run(
        ["docker", "ps", "--filter", f"name=^{name}$", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
    )
    return r.returncode == 0 and name in r.stdout.strip().splitlines()


@doc_ref(
    usage="mycelium ui open",
    desc="Open the frontend in your default browser.",
    group="setup",
)
def ui_open() -> None:
    """Open the frontend in your default browser.

    Tries to launch the OS default browser at http://localhost:<port>.
    Doesn't check whether the frontend container is actually up — use
    `mycelium ui status` for that.

    Examples:
        mycelium ui open
    """
    url = _ui_url()
    if not _container_running(_FRONTEND_CONTAINER):
        typer.secho(
            f"⚠ {_FRONTEND_CONTAINER} is not running — opening anyway.",
            fg=typer.colors.YELLOW,
        )
        typer.echo("  Start it with: mycelium up --ui")
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
