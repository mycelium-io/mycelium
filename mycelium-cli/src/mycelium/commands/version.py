# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""`mycelium version`: this CLI's version and the configured hub's."""

import json

import httpx
import typer

from mycelium import __version__
from mycelium.cli_options import emits_json
from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref


def hub_version(api_url: str, timeout: float = 3.0) -> str | None:
    """The hub's version from its `/health`, or None when it can't be read."""
    try:
        resp = httpx.get(f"{api_url.rstrip('/')}/health", timeout=timeout)
        resp.raise_for_status()
        version = resp.json().get("version")
    except (httpx.HTTPError, ValueError, AttributeError):
        return None
    return version if isinstance(version, str) and version else None


@doc_ref(
    usage="mycelium version [--cli]",
    desc="Print the CLI's version and the configured hub's.",
    group="setup",
)
@emits_json()
def version(
    ctx: typer.Context,
    cli_only: bool = typer.Option(
        False, "--cli", help="Print only the CLI's version, without asking the hub."
    ),
) -> None:
    """Print the CLI's version and, when it answers, the configured hub's."""
    json_output = bool(ctx.obj and ctx.obj.get("json"))
    if cli_only:
        typer.echo(json.dumps({"cli": __version__}) if json_output else __version__)
        return

    api_url = MyceliumConfig.load().server.api_url
    hub = hub_version(api_url)
    if json_output:
        typer.echo(json.dumps({"cli": __version__, "hub": hub, "hub_url": api_url}, indent=2))
        return
    typer.echo(f"cli  {__version__}")
    typer.echo(f"hub  {hub or 'unreachable'}  ({api_url})")
