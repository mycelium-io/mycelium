# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Theme commands: the app's themes on this machine.

Themes are files in ``~/.mycelium/themes/``, and the one the app shows is
``~/.mycelium/theme.json`` (see ``mycelium/themes.py``). These commands only
read and write those; the app on this machine follows them as they change, so
an agent can make you a theme and switch you to it while you watch. A theme is
JSON in the shape the app's paste box takes; ``mycelium theme show`` prints one
to start from.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from mycelium import themes
from mycelium.cli_options import emits_json
from mycelium.doc_ref import doc_ref
from mycelium.text_input import takes_text

app = typer.Typer(
    help="Add, pick and remove the app's themes on this machine; the app switches as you do.",
    no_args_is_help=True,
)
console = Console()


#: Who follows these files, said where a switch is made, since nothing else
#: can tell: the app in a Docker stack runs in a container that can't see them.
_WHO_FOLLOWS = (
    "[dim]The desktop app follows this. The app in a Docker stack can't see these files "
    "and keeps the themes picked in its own Settings.[/dim]"
)


def _is_file(text: str) -> bool:
    try:
        return Path(text).expanduser().is_file()
    except OSError:
        return False


def _refuse(err: themes.ThemeError) -> typer.Exit:
    console.print(f"[red]Error:[/red] {err}")
    return typer.Exit(1)


@doc_ref(
    usage="mycelium theme ls",
    desc="Every theme the app can show: its own, then the ones in ~/.mycelium/themes/, marking the one in use.",
    group="theme",
)
@app.command(name="ls")
@emits_json("as_json")
def theme_ls(as_json: bool = False) -> None:
    """List the themes, marking the one in use."""
    current = themes.current()
    builtin = [{"id": i, "label": label, "mode": mode} for i, label, mode in themes.BUILTIN]
    custom = themes.custom_themes()
    if as_json:
        out = {
            "builtin": builtin,
            "themes": [{"id": t.id, **t.as_file()} for t in custom],
            "current": current,
            "folder": str(themes.folder()),
        }
        typer.echo(json.dumps(out, indent=2))
        return
    table = Table(box=None, pad_edge=False, header_style="dim")
    for col in ("", "theme", "id", "mode", "kind"):
        table.add_column(col, no_wrap=True)
    rows = [(b["id"], b["label"], b["mode"], "built in") for b in builtin]
    rows += [(t.id, t.name, t.mode, "yours") for t in custom]
    for theme_id, name, mode, kind in rows:
        mark = "[green]●[/green]" if theme_id == current else ""
        table.add_row(mark, name, f"[dim]{theme_id}[/dim]", mode, kind)
    console.print(table)
    if current == themes.SYSTEM:
        console.print("[dim]The app follows this computer's light or dark setting.[/dim]")
    console.print(f"[dim]Yours are in {themes.folder()}[/dim]")
    console.print(_WHO_FOLLOWS)


@doc_ref(
    usage="mycelium theme use <name>",
    desc=(
        "Switch the app to a theme, built in or yours, by name or id "
        "(<code>system</code> follows the computer). The open app switches as you run it."
    ),
    group="theme",
)
@app.command(name="use")
@emits_json("as_json")
def theme_use(
    name: str = typer.Argument(..., help="A theme's name or id, or system"),
    as_json: bool = False,
) -> None:
    """Switch the app to a theme."""
    try:
        theme_id = themes.use(name)
    except themes.ThemeError as err:
        raise _refuse(err) from err
    if as_json:
        typer.echo(json.dumps({"theme": theme_id}, indent=2))
        return
    console.print(f"[green]Switched[/green] the app to {theme_id}")
    console.print(_WHO_FOLLOWS)


@doc_ref(
    usage="mycelium theme add (<url> | <file> | <json>) [--use]",
    desc=(
        "Add a theme to ~/.mycelium/themes/, or replace the one with its name: from a URL "
        '(downloaded), a file, or JSON (<code>{"name", "mode", "colors"}</code>, the app\'s '
        "color names to hex). <code>--use</code> switches the app to it too."
    ),
    group="theme",
)
@app.command(name="add")
@takes_text("source", "A URL to download it from, a file, or the theme as JSON.", noun="theme")
@emits_json("as_json")
def theme_add(
    source: str | None = None,
    use: bool = typer.Option(False, "--use", help="Switch the app to it as well"),
    as_json: bool = False,
) -> None:
    """Add a theme, from a URL, a file or JSON."""
    text = (source or "").strip()
    try:
        if text.lower().startswith(("https://", "http://")):
            raw: str | bytes = themes.download(text)
        elif text.startswith("{") or not _is_file(text):
            raw = text
        else:
            raw = Path(text).expanduser().read_bytes()
        theme, path = themes.save(raw)
        if use:
            themes.use(theme.id)
    except themes.ThemeError as err:
        raise _refuse(err) from err
    if as_json:
        out = {"id": theme.id, **theme.as_file(), "path": str(path), "current": use}
        typer.echo(json.dumps(out, indent=2))
        return
    console.print(
        f"[green]Added[/green] {theme.name} [dim]({theme.id}, {theme.mode}) to {path}[/dim]"
    )
    if use:
        console.print(f"[green]Switched[/green] the app to {theme.id}")
    console.print(_WHO_FOLLOWS)


@doc_ref(
    usage="mycelium theme show <name>",
    desc="Print one of your themes as JSON, to edit and add back.",
    group="theme",
)
@app.command(name="show")
@emits_json("as_json")
def theme_show(
    name: str = typer.Argument(..., help="One of your themes, by name or id"),
    as_json: bool = False,
) -> None:
    """Print one of your themes as JSON (it always is; --json is accepted for agents)."""
    del as_json
    theme = themes.find(name)
    if theme is None:
        console.print(
            f"[red]Error:[/red] there's no theme of yours called {name!r}. mycelium theme ls lists them."
        )
        raise typer.Exit(1)
    typer.echo(json.dumps(theme.as_file(), indent=2))


@doc_ref(
    usage="mycelium theme rm <name>",
    desc="Remove one of your themes from ~/.mycelium/themes/.",
    group="theme",
)
@app.command(name="rm")
@emits_json("as_json")
def theme_rm(
    name: str = typer.Argument(..., help="One of your themes, by name or id"),
    as_json: bool = False,
) -> None:
    """Remove one of your themes."""
    try:
        theme = themes.remove(name)
    except themes.ThemeError as err:
        raise _refuse(err) from err
    if as_json:
        typer.echo(json.dumps({"id": theme.id, **theme.as_file()}, indent=2))
        return
    console.print(f"[green]Removed[/green] {theme.name}")
