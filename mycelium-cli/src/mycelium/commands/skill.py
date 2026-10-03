# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Skill commands: the ``skills/`` memory namespace, promoted (#617).

A skill is just a memory: SKILL.md-style markdown + frontmatter at
``.mycelium/rooms/{room}/skills/<name>.md``. The same way ``decisions/`` memories
get a category view and ``agents/`` a members panel, the ``skills/`` namespace is
promoted into a skills surface. So skills are room-scoped, like memory, and a
skill is reachable as a memory too. Reads and writes resolve against the hub over
HTTP; a spoke keeps no local replica.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from importlib import resources
from pathlib import Path
from typing import Any

import httpx
import typer
from rich.console import Console

from mycelium import identity
from mycelium.client import hub_error_detail, typed_client
from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref
from mycelium.text_input import takes_text
from mycelium_backend_client.errors import UnexpectedStatus

app = typer.Typer(
    help="Create and browse a room's skills: SKILL.md-style markdown in the room's skills/ namespace. Skills back the chat composer's / trigger.",
    no_args_is_help=True,
)
console = Console()


def _get_client():
    """The shared authenticated OpenAPI client (see ``mycelium.client``)."""
    return typed_client()


def _hub_url() -> str:
    """The hub API URL this client resolves skills against."""
    return MyceliumConfig.load().server.api_url


@contextmanager
def _hub_session() -> Iterator[Any]:
    """Yield a hub client, reporting an unreachable hub instead of raising."""
    with _get_client() as client:
        try:
            yield client
        except httpx.HTTPError as exc:
            console.print(f"[red]Error:[/red] can't reach the hub at {_hub_url()}: {exc}")
            console.print(
                "[dim]Check the hub is running ('mycelium status'), or point "
                "server.api_url at it.[/dim]"
            )
            raise typer.Exit(1) from exc
        except UnexpectedStatus as exc:
            detail = hub_error_detail(exc.content)
            suffix = f": {detail}" if detail else "."
            console.print(
                f"[red]Error:[/red] hub at {_hub_url()} returned HTTP {exc.status_code}{suffix}"
            )
            raise typer.Exit(1) from exc


def _get_active_room(room: str | None) -> str:
    """Resolve the room from the arg or the active config, like `mycelium memory`."""
    if room:
        return room
    cfg = MyceliumConfig.load()
    active = getattr(cfg.rooms, "active", None) if hasattr(cfg, "rooms") else None
    if active:
        return active
    console.print(
        "[red]Error:[/red] no room specified and no active room set. Use --room or "
        "'mycelium config set rooms.active <name>'."
    )
    raise typer.Exit(1)


@doc_ref(
    usage="mycelium skill set <name> [<body>] [--body <markdown>] [--file <path>] [--desc <text>]",
    desc="Create or update a skill (upsert) in a room's skills/ namespace. The body is markdown, from the positional argument, <code>--body</code>, or <code>--file</code> (<code>-</code> reads stdin).",
    group="skill",
)
@app.command(name="set")
@takes_text("body", "The skill's instructions, in markdown.", noun="skill body")
def skill_set(
    name: str = typer.Argument(..., help="Skill slug (kebab-case, e.g. 'summarize-room')"),
    body: str = typer.Argument(..., help="Skill body (prose / instructions)"),
    room: str | None = typer.Option(
        None, "--room", "-r", help="Room name (defaults to active room)"
    ),
    description: str = typer.Option(
        "", "--desc", "-d", help="One-line summary shown in listings and the composer"
    ),
    handle: str | None = typer.Option(
        None,
        "--as",
        "--handle",
        "-H",
        help="Author to attribute this to (created_by). Defaults to your hub identity.",
    ),
    tags: str | None = typer.Option(None, "--tags", "-t", help="Comma-separated tags"),
) -> None:
    """Create or upsert a skill in a room's skills/ namespace. Always upserts; version bumps."""
    from mycelium_backend_client.api.skills import (
        create_skill_api_rooms_room_name_skills_post as create_api,
    )
    from mycelium_backend_client.models import SkillCreate

    body_text = body
    room_name = _get_active_room(room)
    handle = identity.resolve_actor(MyceliumConfig.load(), override=handle)
    tag_list = [t.strip() for t in tags.split(",")] if tags else None

    item = SkillCreate(
        name=name,
        body=body_text,
        description=description,
        created_by=handle,
        tags=tag_list,
    )
    with _hub_session() as client:
        skill = create_api.sync(room_name=room_name, client=client, body=item)
        version = f"v{skill.version}" if hasattr(skill, "version") else ""
        console.print(f"[green]Skill set:[/green] {room_name}/{name} ({version})")


@doc_ref(
    usage="mycelium skill ls",
    desc="List a room's skills, newest-updated first.",
    group="skill",
)
@app.command(name="ls")
def skill_ls(
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
) -> None:
    """List a room's skills from the hub."""
    from mycelium_backend_client.api.skills import (
        list_skills_api_rooms_room_name_skills_get as list_api,
    )

    room_name = _get_active_room(room)
    with _hub_session() as client:
        resp = list_api.sync(room_name=room_name, client=client)

    skills = getattr(resp, "skills", None) or []
    if not skills:
        console.print("[dim]No skills found[/dim]")
        return

    console.print(f"[bold]Skills[/bold] ({len(skills)})\n")
    for skill in skills:
        desc = getattr(skill, "description", "") or ""
        console.print(
            f"[cyan]/{skill.name}[/cyan]  [dim]v{skill.version}  {skill.created_by}[/dim]"
        )
        if desc:
            console.print(f"  {desc}")


@doc_ref(
    usage="mycelium skill get <name>",
    desc="Read a skill by name from a room.",
    group="skill",
)
@app.command(name="get")
def skill_get(
    name: str = typer.Argument(..., help="Skill name"),
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
) -> None:
    """Read a skill by name (from the hub)."""
    from mycelium_backend_client.api.skills import (
        get_skill_api_rooms_room_name_skills_name_get as get_api,
    )
    from mycelium_backend_client.models import SkillRead

    room_name = _get_active_room(room)
    with _hub_session() as client:
        try:
            skill = get_api.sync(room_name=room_name, name=name, client=client)
        except UnexpectedStatus as exc:
            if exc.status_code == 404:
                console.print(f"[red]Not found:[/red] {name}")
                raise typer.Exit(1) from exc
            raise

    if not isinstance(skill, SkillRead):
        console.print(f"[red]Not found:[/red] {name}")
        raise typer.Exit(1)

    desc = skill.description or ""
    console.print(f"[cyan]/{skill.name}[/cyan]  [dim]v{skill.version}  {skill.created_by}[/dim]")
    if desc:
        console.print(f"[dim]{desc}[/dim]")
    console.print(skill.body or "")


@doc_ref(
    usage="mycelium skill rm <name>",
    desc="Delete a skill from a room.",
    group="skill",
)
@app.command(name="rm")
def skill_rm(
    name: str = typer.Argument(..., help="Skill name"),
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
) -> None:
    """Delete a skill by name."""
    from mycelium_backend_client.api.skills import (
        delete_skill_api_rooms_room_name_skills_name_delete as delete_api,
    )

    room_name = _get_active_room(room)
    with _hub_session() as client:
        resp = delete_api.sync_detailed(room_name=room_name, name=name, client=client)
        if resp.status_code == 404:
            console.print(f"[red]Not found:[/red] {name}")
            raise typer.Exit(1)
    console.print(f"[green]Skill removed:[/green] {room_name}/{name}")


@doc_ref(
    usage="mycelium skill print",
    desc="Print the Mycelium agent skill (SKILL.md): how an agent takes part in a room. Save it where your agent CLI reads skills, e.g. <code>~/.claude/skills/mycelium/SKILL.md</code>.",
    group="skill",
)
@app.command(name="print")
def skill_print() -> None:
    """Print the Mycelium agent skill, to install by hand into an agent CLI.

    This is Mycelium's own SKILL.md (the protocol an agent follows in a room),
    not an entry in a room's skills store above. Agents the runner, swarm or
    the Mac app start don't need it: their notes and wake prompts carry the
    commands. It is for an agent CLI you start yourself, e.g.:

        mycelium skill print > ~/.claude/skills/mycelium/SKILL.md
    """
    rel = "skills/mycelium/SKILL.md"
    fallback_parts = ("skills", "mycelium", "SKILL.md")
    try:
        with resources.as_file(resources.files("mycelium").joinpath(rel)) as p:
            typer.echo(p.read_text())
    except (TypeError, FileNotFoundError):
        fallback = Path(__file__).parent.parent.joinpath(*fallback_parts)
        if fallback.exists():
            typer.echo(fallback.read_text())
        else:
            typer.secho("SKILL.md not found", fg=typer.colors.RED)
            raise typer.Exit(1)
