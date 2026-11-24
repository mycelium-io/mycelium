# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Hub commands: what a hub is set up with."""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer

from mycelium.cli_options import emits_json
from mycelium.doc_ref import doc_ref

if TYPE_CHECKING:
    from mycelium_backend_client.models import HubSettings

app = typer.Typer(
    help="Read what a hub is set up with.",
    no_args_is_help=True,
)


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
