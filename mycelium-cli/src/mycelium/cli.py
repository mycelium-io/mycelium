# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
Mycelium CLI — Multi-agent coordination + persistent memory.
"""

from importlib import resources
from pathlib import Path

import typer

from mycelium import __version__
from mycelium.commands import (
    adapter,
    config,
    docs,
    doctor,
    install,
    instance,
    memory,
    message,
    notebook,
    room,
    session,
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
def skill(
    claude_code: bool = typer.Option(
        False,
        "--claude-code",
        help="Print the Claude Code adapter SKILL.md instead of the OpenClaw one.",
    ),
) -> None:
    """Print the Mycelium SKILL.md (OpenClaw adapter skill definition).

    Use --claude-code to print the Claude Code adapter skill instead.
    """
    if claude_code:
        rel = "adapters/claude-code/skills/mycelium/SKILL.md"
        fallback_parts = ("adapters", "claude-code", "skills", "mycelium", "SKILL.md")
    else:
        rel = "adapters/openclaw/extensions/mycelium/skills/mycelium/SKILL.md"
        fallback_parts = (
            "adapters",
            "openclaw",
            "extensions",
            "mycelium",
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
app.command(name="pull")(instance.pull)
app.command(name="doctor")(doctor.doctor)
app.command(name="up")(instance.start)
app.command(name="down")(instance.stop)
app.command(name="status")(instance.status)
app.command(name="logs")(instance.logs)
app.command(name="migrate")(instance.migrate)

# Top-level shortcuts
app.command(name="watch")(room.watch)
app.command(name="synthesize")(room.synthesize)
app.command(name="catchup")(memory.memory_catchup)
app.command(name="sync")(memory.memory_sync)

# Command groups
app.add_typer(room.app, name="room")
app.add_typer(message.app, name="message")
app.add_typer(memory.app, name="memory")
app.add_typer(config.app, name="config")
app.add_typer(adapter.app, name="adapter")
app.add_typer(docs.app, name="docs")
app.add_typer(notebook.app, name="notebook")
app.add_typer(session.app, name="session")


if __name__ == "__main__":
    app()
