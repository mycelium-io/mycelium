# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Skill commands — the global, folder-based skills store (#617).

Skills are reusable, invokable units of prose (SKILL.md-style markdown +
frontmatter), stored on the hub at ``.mycelium/skills/<name>.md``. Unlike
memory, the store is *global* (project-level), not room-scoped: a skill is
reusable across rooms. Reads and writes resolve against the hub over HTTP; a
spoke keeps no local replica.
"""

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import resources
from pathlib import Path
from typing import Any

import httpx
import typer
from rich.console import Console

from mycelium.client import typed_client
from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref
from mycelium_backend_client.errors import UnexpectedStatus

app = typer.Typer(
    help="Create and browse reusable skills — SKILL.md-style markdown stored globally on the hub. Skills back the chat composer's / trigger.",
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
            console.print(f"[red]Error:[/red] hub at {_hub_url()} returned HTTP {exc.status_code}.")
            raise typer.Exit(1) from exc


def _resolve_body(body: str | None, file: str | None) -> str:
    """Resolve the skill body from the positional arg or a file ('-' is stdin)."""
    if body is not None and file is not None:
        console.print("[red]Error:[/red] pass either a body or --file, not both.")
        raise typer.Exit(1)
    if file is not None:
        if file == "-":
            return sys.stdin.read()
        try:
            return Path(file).read_text(encoding="utf-8")
        except OSError as exc:
            console.print(f"[red]Error:[/red] cannot read {file}: {exc.strerror or exc}")
            raise typer.Exit(1) from exc
        except UnicodeDecodeError as exc:
            console.print(f"[red]Error:[/red] {file} is not valid UTF-8 text.")
            raise typer.Exit(1) from exc
    if body is None:
        console.print("[red]Error:[/red] provide a body or --file <path> (use '-' for stdin).")
        raise typer.Exit(1)
    return body


@doc_ref(
    usage="mycelium skill set <name> [<body>] [--file <path>] [--desc <text>]",
    desc="Create or update a skill (upsert). The body comes from the positional argument or <code>--file</code> (<code>-</code> reads stdin). Skills are global — reusable across rooms.",
    group="skill",
)
@app.command(name="set")
def skill_set(
    name: str = typer.Argument(..., help="Skill slug (kebab-case, e.g. 'summarize-room')"),
    body: str | None = typer.Argument(None, help="Skill body (prose / instructions)"),
    file: str | None = typer.Option(
        None, "--file", "-f", help="Read the body from a file ('-' for stdin)"
    ),
    description: str = typer.Option(
        "", "--desc", "-d", help="One-line summary shown in listings and the composer"
    ),
    handle: str = typer.Option("cli-user", "--handle", "-H", help="Author handle"),
    tags: str | None = typer.Option(None, "--tags", "-t", help="Comma-separated tags"),
) -> None:
    """Create or upsert a skill in the global store. Always upserts; version bumps."""
    from mycelium_backend_client.api.skills import (
        create_skill_api_skills_post as create_api,
    )
    from mycelium_backend_client.models import SkillCreate

    body_text = _resolve_body(body, file)
    tag_list = [t.strip() for t in tags.split(",")] if tags else None

    item = SkillCreate(
        name=name,
        body=body_text,
        description=description,
        created_by=handle,
        tags=tag_list,
    )
    with _hub_session() as client:
        skill = create_api.sync(client=client, body=item)
        version = f"v{skill.version}" if hasattr(skill, "version") else ""
        console.print(f"[green]Skill set:[/green] {name} ({version})")


@doc_ref(
    usage="mycelium skill ls",
    desc="List all skills in the global store, newest-updated first.",
    group="skill",
)
@app.command(name="ls")
def skill_ls() -> None:
    """List skills from the hub."""
    from mycelium_backend_client.api.skills import (
        list_skills_api_skills_get as list_api,
    )

    with _hub_session() as client:
        resp = list_api.sync(client=client)

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
    desc="Read a skill by name from the hub.",
    group="skill",
)
@app.command(name="get")
def skill_get(
    name: str = typer.Argument(..., help="Skill name"),
) -> None:
    """Read a skill by name (from the hub)."""
    from mycelium_backend_client.api.skills import (
        get_skill_api_skills_name_get as get_api,
    )
    from mycelium_backend_client.models import SkillRead

    with _hub_session() as client:
        try:
            skill = get_api.sync(name=name, client=client)
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
    desc="Delete a skill from the hub.",
    group="skill",
)
@app.command(name="rm")
def skill_rm(
    name: str = typer.Argument(..., help="Skill name"),
) -> None:
    """Delete a skill by name."""
    from mycelium_backend_client.api.skills import (
        delete_skill_api_skills_name_delete as delete_api,
    )

    with _hub_session() as client:
        resp = delete_api.sync_detailed(name=name, client=client)
        if resp.status_code == 404:
            console.print(f"[red]Not found:[/red] {name}")
            raise typer.Exit(1)
    console.print(f"[green]Skill removed:[/green] {name}")


@doc_ref(
    usage="mycelium skill adapter-def",
    desc="Print the Mycelium SKILL.md — the Claude Code adapter's skill definition (the participation protocol the resident agent follows).",
    group="skill",
)
@app.command(name="adapter-def")
def skill_adapter_def() -> None:
    """Print the Mycelium SKILL.md (Claude Code adapter skill definition).

    This is the adapter's *own* SKILL.md asset — the participation protocol the
    resident agent runs — not an entry in the skills store above.
    """
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
        fallback = Path(__file__).parent.parent.joinpath(*fallback_parts)
        if fallback.exists():
            typer.echo(fallback.read_text())
        else:
            typer.secho("SKILL.md not found", fg=typer.colors.RED)
            raise typer.Exit(1)
