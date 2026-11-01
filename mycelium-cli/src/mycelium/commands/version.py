# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""`mycelium version`: this CLI's version and the configured hub's."""

import json

import typer

from mycelium import __version__
from mycelium.cli_options import emits_json
from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref


def hub_version(api_url: str, timeout: float = 3.0) -> str | None:
    """The hub's version from its health answer, or None when it can't be read."""
    from mycelium.hub_check import health

    return health(api_url, timeout=timeout).version or None


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

    from mycelium.hub_check import credential

    config = MyceliumConfig.load()
    api_url = config.server.api_url
    hub = hub_version(api_url)
    # Asked only of a hub that answered: an unreachable one has nothing to say.
    check = credential(config) if hub else None
    if json_output:
        body: dict = {"cli": __version__, "hub": hub, "hub_url": api_url}
        if check is not None:
            body["credential"] = {
                "accepted": check.accepted,
                "as": check.handle,
                "source": check.source,
                "fix": check.fix,
            }
        typer.echo(json.dumps(body, indent=2))
        return
    typer.echo(f"cli  {__version__}")
    typer.echo(f"hub  {hub or 'unreachable'}  ({api_url})")
    if check is not None:
        typer.echo(f"     {check.line()}")
