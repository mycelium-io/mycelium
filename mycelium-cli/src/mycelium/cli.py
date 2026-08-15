# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Mycelium CLI — Multi-agent coordination + persistent memory.
"""

from importlib import resources
from pathlib import Path

import typer

from mycelium import __version__
from mycelium.commands import (
    adapter,
    agent,
    config,
    demo,
    docs,
    doctor,
    engine,
    hub,
    install,
    instance,
    join,
    memory,
    metrics,
    network,
    openshell,
    participate,
    plan,
    room,
    ui,
    user,
    wire,
)

app = typer.Typer(
    name="mycelium",
    help="[bold]Mycelium[/bold] — Multi-agent coordination + persistent memory",
    add_completion=True,
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
)


def version_callback(value: bool) -> None:
    if value:
        typer.echo(f"Mycelium CLI version {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    version: bool | None = typer.Option(  # noqa: ARG001
        None,
        "--version",
        "-V",
        callback=version_callback,
        is_eager=True,
        help="Print version information",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose/debug output"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress non-essential output"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
) -> None:
    """[bold]Mycelium[/bold] — Multi-agent coordination + persistent memory."""
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    ctx.obj["quiet"] = quiet
    ctx.obj["json"] = json_output


@app.command(name="skill")
def skill() -> None:
    """Print the Mycelium SKILL.md (Claude Code adapter skill definition)."""
    rel = "integrations/claude_code/assets/skills/mycelium/SKILL.md"
    fallback_parts = (
        "integrations",
        "claude_code",
        "assets",
        "skills",
        "mycelium",
        "SKILL.md",
    )

    try:
        with resources.as_file(resources.files("mycelium").joinpath(rel)) as p:
            typer.echo(p.read_text())
    except (TypeError, FileNotFoundError):
        fallback = Path(__file__).parent.joinpath(*fallback_parts)
        if fallback.exists():
            typer.echo(fallback.read_text())
        else:
            typer.secho("SKILL.md not found", fg=typer.colors.RED)
            raise typer.Exit(1)


# Top-level instance commands
app.command(name="init")(instance.init)
app.command(name="install")(install.install)
app.command(name="upgrade")(install.upgrade)
app.command(name="_refresh-templates", hidden=True)(install.refresh_templates)
app.command(name="pull")(instance.pull)
app.command(name="doctor")(doctor.doctor)
app.command(name="up")(instance.start)
app.command(name="down")(instance.stop)
app.command(name="status")(instance.status)
app.command(name="network")(network.network)
app.command(name="logs")(instance.logs)

# Top-level shortcuts
app.command(name="whoami")(user.whoami)
app.command(name="iam")(user.iam)
app.command(name="watch")(room.watch)
app.command(name="sync")(memory.memory_sync)
app.command(name="connect")(hub.connect)

# Participation primitives — join a room's SLIM channel and reply, no daemon.
app.command(name="await")(participate.await_room)
app.command(name="respond")(participate.respond)

# Thin spoke — hold membership on a hub-hosted room and apply its memory writes.
app.command(name="join")(join.join)

# Command groups
app.add_typer(room.app, name="room")
app.add_typer(memory.app, name="memory")
app.add_typer(plan.app, name="plan")
app.add_typer(config.app, name="config")
app.add_typer(adapter.app, name="adapter")
app.add_typer(docs.app, name="docs")
app.add_typer(metrics.app, name="metrics")
app.add_typer(ui.app, name="ui")
app.add_typer(agent.app, name="agent")
app.add_typer(user.app, name="user")
app.add_typer(engine.app, name="engine")
app.add_typer(openshell.app, name="openshell")
app.add_typer(demo.app, name="demo")
app.add_typer(hub.app, name="hub")

# Hidden dev/testing plumbing — inject raw L9/SLIM traffic (see commands/wire.py).
app.add_typer(wire.l9_app, name="l9", hidden=True)
app.add_typer(wire.slim_app, name="slim", hidden=True)


if __name__ == "__main__":
    app()
