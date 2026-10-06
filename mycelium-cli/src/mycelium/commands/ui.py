# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
`mycelium ui`: open and inspect the frontend.

The frontend ships as a separate Docker image and is part of the stack that
`mycelium up` brings up. It runs at http://localhost:3000 by default; the
browser only talks to that origin, and the Next.js server proxies /api/* to
the backend over the compose network (see mycelium-frontend/Dockerfile).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import webbrowser

import typer

from mycelium.cli_options import confirms, emits_json
from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref

app = typer.Typer(
    name="ui",
    help="Open and inspect the frontend.",
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
    if not shutil.which("docker"):
        return False
    r = subprocess.run(
        ["docker", "ps", "--filter", f"name=^{name}$", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
    )
    return r.returncode == 0 and name in r.stdout.strip().splitlines()


def _open_app_ui() -> None:
    """Open the UI the Mac app serves, or the app itself when it isn't up."""
    from mycelium.desktop.supervisor import HOST, UI_PORT, port_open

    url = f"http://{HOST}:{UI_PORT}"
    if port_open(UI_PORT):
        typer.echo(f"Opening {url}")
        webbrowser.open(url)
        return
    typer.secho("⚠ The Mycelium app isn't serving its UI.", fg=typer.colors.YELLOW)
    if shutil.which("open"):
        typer.echo("  Opening the Mycelium app…")
        subprocess.run(["open", "-b", "io.mycelium.desktop"], check=False)  # noqa: S607
    else:
        typer.echo("  Open the Mycelium app to start it.")


@doc_ref(
    usage="mycelium ui open [-y]",
    desc="Open the frontend in your default browser.",
    group="setup",
)
@confirms("yes")
def ui_open(
    ctx: typer.Context,
    yes: bool = False,
) -> None:
    """Open the frontend in your default browser.

    When the Mac app runs this machine's hub, opens the app's UI (or the
    app, when it isn't running). Otherwise, if the frontend container isn't
    running, offers to start the stack with `mycelium up` first. Pass `-y`
    to skip the prompt and start it automatically.

    Examples:
        mycelium ui open
        mycelium ui open -y
    """
    from mycelium.desktop.checks import app_hub

    if app_hub():
        _open_app_ui()
        return
    url = _ui_url()
    if not _container_running(_FRONTEND_CONTAINER):
        typer.secho(
            f"⚠ {_FRONTEND_CONTAINER} is not running.",
            fg=typer.colors.YELLOW,
        )
        if not yes and not typer.confirm("Start it now with 'mycelium up'?", default=True):
            typer.echo("  Start it later with: mycelium up")
            return
        # Proxy to `mycelium up`. Imported lazily to avoid a circular import
        # between the commands modules.
        from mycelium.commands import instance

        instance.start(ctx, build=False)
    typer.echo(f"Opening {url}")
    webbrowser.open(url)


@doc_ref(
    usage="mycelium ui status",
    desc="Show whether the frontend container is running.",
    group="setup",
)
@emits_json("as_json")
def ui_status(as_json: bool = False) -> None:
    """Show whether the frontend container is running.

    Examples:
        mycelium ui status
    """
    url = _ui_url()
    running = _container_running(_FRONTEND_CONTAINER)
    if as_json:
        try:
            backend: str | None = MyceliumConfig.load().server.api_url
        except Exception:
            backend = None
        state = {
            "container": _FRONTEND_CONTAINER,
            "running": running,
            "url": url,
            "backend": backend,
        }
        typer.echo(json.dumps(state, indent=2))
        return
    if running:
        typer.secho(f"✓ {_FRONTEND_CONTAINER} is running", fg=typer.colors.GREEN)
        typer.echo(f"  URL: {url}")
    else:
        typer.secho(f"✗ {_FRONTEND_CONTAINER} is not running", fg=typer.colors.RED)
        from mycelium.desktop.checks import start_hub

        typer.echo(f"  Start it with: {start_hub()}")
        # Surface the configured backend so the user can sanity-check.
        try:
            cfg = MyceliumConfig.load()
            typer.echo(f"  Backend: {cfg.server.api_url}")
        except Exception:
            pass


app.command(name="open")(ui_open)
app.command(name="status")(ui_status)
