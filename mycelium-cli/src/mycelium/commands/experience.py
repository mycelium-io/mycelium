# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""mycelium experience: add, list and remove experiences on this machine.

The same experiences the Mac app's Settings shows, for a server or a terminal.
Adding one keeps its content under ``~/.mycelium/experiences`` and points the
hub at it (``mycelium/desktop/experiences.py``); this then writes ``.env`` and,
when a Docker stack is running, recreates the backend so it reads it. A hub the
Mac app runs is restarted by the app instead.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from mycelium.doc_ref import doc_ref

app = typer.Typer(help="Ready-made rooms to explore, added from a file.", no_args_is_help=True)
console = Console()


def _docker_backend_running() -> bool:
    try:
        r = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
    return r.returncode == 0 and "mycelium-backend" in r.stdout.split()


def _apply(config: Any, restart: bool) -> None:
    """Save the change, write .env, and get the hub to read it."""
    from mycelium.commands.config import restart_containers
    from mycelium.docker_utils import write_env_file

    config.save()
    env_path, _ = write_env_file(config)
    if not restart:
        console.print("[dim]Restart Mycelium to load it.[/]")
    elif _docker_backend_running():
        console.print("Restarting the hub…")
        restart_containers(env_path, ["mycelium-backend"])
    else:
        console.print("[dim]Restart Mycelium to load it (in the Mac app: Settings, then Save).[/]")


def _line(x: dict[str, Any]) -> str:
    if not x["added"]:
        return f"[bold]{x['id']}[/]  [dim]not added[/]  {x['description']}"
    unit = x["unit"] + ("" if x["scenarios"] == 1 else "s")
    where = "" if x["active"] else "  [yellow]added, but the hub points elsewhere[/]"
    return f"[bold]{x['id']}[/]  {x['scenarios']} {unit}  opens at {x['open']}{where}"


@doc_ref(
    usage="mycelium experience ls",
    desc="The experiences this machine can add, and which are added.",
    group="setup",
)
@app.command("ls")
def ls() -> None:
    """List the experiences, and which are added here."""
    from mycelium.config import MyceliumConfig
    from mycelium.desktop import experiences as xp

    for x in xp.view(MyceliumConfig.load()):
        console.print(_line(x))


@doc_ref(
    usage="mycelium experience add <id> <file>",
    desc="Add an experience from the .zip or folder it comes in, and restart the hub to load it.",
    group="setup",
)
@app.command("add")
def add(
    experience_id: str = typer.Argument(
        ..., metavar="ID", help="Which experience, e.g. patterns-explorer"
    ),
    source: Path = typer.Argument(..., metavar="FILE", help="The .zip or folder it comes in"),
    restart: bool = typer.Option(
        True, "--restart/--no-restart", help="Restart the hub so it loads it"
    ),
) -> None:
    """Add an experience from the file it comes in.

    Examples:
        mycelium experience add patterns-explorer ~/patterns.zip
        mycelium experience add patterns-explorer ~/code/patterns --no-restart
    """
    from mycelium.config import MyceliumConfig
    from mycelium.desktop import experiences as xp

    config = MyceliumConfig.load()
    try:
        added = xp.add(config, experience_id, source)
    except xp.ExperienceError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(2) from None
    console.print(f"Added {added['title']}: {_line(added)}")
    _apply(config, restart)


@doc_ref(
    usage="mycelium experience rm <id>",
    desc="Remove an experience from this machine. Rooms it made stay.",
    group="setup",
)
@app.command("rm")
def rm(
    experience_id: str = typer.Argument(..., metavar="ID"),
    restart: bool = typer.Option(
        True, "--restart/--no-restart", help="Restart the hub so it lets go of it"
    ),
) -> None:
    """Remove an experience. Rooms it made stay; they are ordinary rooms."""
    from mycelium.config import MyceliumConfig
    from mycelium.desktop import experiences as xp

    config = MyceliumConfig.load()
    try:
        xp.remove(config, experience_id)
    except xp.ExperienceError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(2) from None
    console.print(f"Removed {experience_id}.")
    _apply(config, restart)
