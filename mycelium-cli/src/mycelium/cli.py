"""
Mycelium CLI — Multi-agent coordination + persistent memory.
"""

import typer

from mycelium import __version__
from mycelium.commands import (
    adapter,
    config,
    docs,
    install,
    instance,
    memory,
    message,
    room,
)

app = typer.Typer(
    name="mycelium",
    help="Mycelium CLI — Multi-agent coordination + persistent memory",
    add_completion=True,
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
    rich_markup_mode=None,
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
    """Mycelium CLI — Multi-agent coordination + persistent memory."""
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    ctx.obj["quiet"] = quiet
    ctx.obj["json"] = json_output


# Top-level instance commands
app.command(name="init")(instance.init)
app.command(name="install")(install.install)
app.command(name="up")(instance.start)
app.command(name="down")(instance.stop)
app.command(name="status")(instance.status)
app.command(name="logs")(instance.logs)

# Top-level shortcuts
app.command(name="watch")(room.watch)

# Command groups
app.add_typer(room.app, name="room")
app.add_typer(message.app, name="message")
app.add_typer(memory.app, name="memory")
app.add_typer(config.app, name="config")
app.add_typer(adapter.app, name="adapter")
app.add_typer(docs.app, name="docs")


if __name__ == "__main__":
    app()
