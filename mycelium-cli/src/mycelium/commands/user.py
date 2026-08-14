# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
User commands — the human as a first-class, room-spanning principal.

A user is one global record at ``~/.mycelium/users/<handle>`` (markdown +
frontmatter, same format as any memory). An agent's ``owner`` points at one of
these handles; a ``team`` groups them. Trust is self-asserted: the handle is
consistent, not cryptographic.

The store is global rather than room-scoped (unlike ``agents/<handle>``) because
a person spans rooms.
"""

from __future__ import annotations

import json as json_module
import logging

import typer
import yaml
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref
from mycelium.error_handler import print_error
from mycelium.filesystem import get_users_dir, list_memories, read_memory, write_memory
from mycelium.protocol import AgentManifest, UserManifest

app = typer.Typer(
    help=(
        "The human as a first-class entity. A user is a global "
        "users/<handle> record that an agent's --owner points at."
    ),
    no_args_is_help=True,
)
console = Console()
_log = logging.getLogger(__name__)


def load_user(handle: str) -> UserManifest | None:
    """Read a user record off the global store and rehydrate the model.

    Returns ``None`` for both "missing" and "unreadable"; a corrupt record is
    logged at WARNING so it never fails silently.
    """
    handle = handle.strip().lstrip("@").lower()
    result = read_memory(get_users_dir(), handle)
    if result is None:
        return None
    _, content = result
    try:
        data = yaml.safe_load(content) or {}
    except yaml.YAMLError as exc:
        _log.warning("user %s: invalid YAML — %s", handle, exc)
        return None
    if not isinstance(data, dict):
        return None
    data.setdefault("handle", handle)
    try:
        return UserManifest(**data)
    except ValidationError as exc:
        _log.warning("user %s: schema validation failed — %s", handle, exc)
        return None


def list_users() -> list[UserManifest]:
    """All user records in the global store, newest first."""
    out: list[UserManifest] = []
    for key, _meta, _content in list_memories(get_users_dir(), limit=500):
        # The store is flat — one record per handle, no nested keys.
        if "/" in key:
            continue
        user = load_user(key)
        if user is not None:
            out.append(user)
    return out


def _write_user(user: UserManifest, created_by: str) -> None:
    body = user.model_dump(exclude={"handle"})
    yaml_body = yaml.safe_dump(body, sort_keys=False, default_flow_style=False).strip()
    existing = read_memory(get_users_dir(), user.handle)
    version = 1
    if existing is not None:
        try:
            version = int(existing[0].get("version", 1)) + 1
        except (TypeError, ValueError):
            version = 1
    write_memory(
        get_users_dir(),
        user.handle,
        yaml_body,
        created_by=created_by,
        version=version,
        tags=["user-manifest"],
    )


@doc_ref(
    usage="mycelium user create <handle> [--name <display>] [--team <slug>]",
    desc="Register a human as a first-class user in the global store.",
    group="user",
)
@app.command("create")
def user_create(
    ctx: typer.Context,
    handle: str = typer.Argument(..., help="User handle (lowercase slug, e.g. 'julia')."),
    display_name: str = typer.Option(
        "", "--name", "-n", help="Human-readable display name, e.g. 'Julia Valenti'."
    ),
    team: list[str] | None = typer.Option(
        None, "--team", help="Team slug this person belongs to (repeatable)."
    ),
    notify: str | None = typer.Option(
        None, "--notify", help="Where to route 'needs you' escalations (email/webhook)."
    ),
    handle_flag: str = typer.Option(
        "cli-user", "--as", "-H", help="Your own handle (recorded as created_by)."
    ),
) -> None:
    """Create (or upsert) a user in the global store.

    Examples:
        mycelium user create julia --name "Julia Valenti" --team core
    """
    try:
        try:
            user = UserManifest(
                handle=handle,
                display_name=display_name,
                teams=team or [],
                notify=notify,
            )
        except ValidationError as exc:
            typer.secho(f"Invalid user: {exc}", fg=typer.colors.RED)
            raise typer.Exit(1) from exc

        _write_user(user, created_by=handle_flag)
        teams = f" · teams: {', '.join(user.teams)}" if user.teams else ""
        console.print(
            f"[green]User registered:[/green] [cyan]@{user.handle}[/cyan]"
            f"{f' ({user.display_name})' if user.display_name else ''}{teams}"
        )
    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None


@doc_ref(
    usage="mycelium user ls [--team <slug>]",
    desc="List registered users in the global store.",
    group="user",
)
@app.command("ls")
def user_ls(
    ctx: typer.Context,
    team: str | None = typer.Option(None, "--team", help="Filter to one team slug."),
) -> None:
    """List users in the global store."""
    try:
        users = list_users()
        if team:
            wanted = team.strip().lstrip("@").lower()
            users = [u for u in users if wanted in u.teams]

        json_output = ctx.obj.get("json", False) if ctx.obj else False
        if json_output:
            typer.echo(json_module.dumps([u.model_dump() for u in users], indent=2, default=str))
            return

        if not users:
            console.print("[dim]No users registered.[/dim]")
            console.print('  Create one with: mycelium user create <handle> --name "…"')
            return

        table = Table(title="users", show_lines=False)
        table.add_column("Handle", style="cyan", no_wrap=True)
        table.add_column("Name")
        table.add_column("Teams", style="magenta")
        table.add_column("Notify", overflow="fold")
        for u in users:
            table.add_row(
                f"@{u.handle}",
                u.display_name or "",
                ", ".join(u.teams),
                u.notify or "",
            )
        console.print(table)
    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None


@doc_ref(
    usage="mycelium user show <handle>",
    desc="Show a user's record plus the agents they own.",
    group="user",
)
@app.command("show")
def user_show(
    ctx: typer.Context,
    handle: str = typer.Argument(..., help="User handle."),
) -> None:
    """Inspect a user: record plus a roll-up of the agents they own."""
    try:
        user = load_user(handle)
        if user is None:
            console.print(f"[red]Not found:[/red] no user '{handle}' in the global store.")
            raise typer.Exit(1)

        console.print(f"[bold cyan]@{user.handle}[/bold cyan]")
        if user.display_name:
            console.print(f"  name: {user.display_name}")
        if user.teams:
            console.print(f"  teams: {', '.join(user.teams)}")
        if user.notify:
            console.print(f"  notify: {user.notify}")

        # Roll up owned agents across every room, summing their manifest budgets.
        owned, total = _owned_agents(user.handle)
        if owned:
            console.print(f"\n[bold]owns {len(owned)} agent(s)[/bold]  [dim]${total:.2f}/mo[/dim]")
            for room_name, m in owned:
                console.print(
                    f"  @{m.handle} [dim]({m.adapter}, {room_name})[/dim] "
                    f"${m.budget_usd_per_month:.2f}/mo"
                )
        else:
            console.print("\n[dim]No agents owned yet.[/dim]")
    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None


def _owned_agents(owner: str) -> tuple[list[tuple[str, AgentManifest]], float]:
    """Every agent whose manifest owner matches, across all rooms, + total budget.

    The roll-up sums each owned agent's manifest ``budget_usd_per_month`` cap —
    a budget figure, not measured spend (there's no per-action cost ledger yet).
    """
    from mycelium.commands.agent import load_owned_agents

    return load_owned_agents(owner=owner)


@doc_ref(
    usage="mycelium whoami",
    desc="Print the user you're acting as, plus the agents you own.",
    group="user",
)
def whoami(ctx: typer.Context) -> None:
    """Resolve the current identity to a user handle and roll up owned agents."""
    try:
        config = MyceliumConfig.load()
        # The attribution handle can be session-qualified (``julia#a8f3``); the
        # principal is the bare name it derives from.
        identity = config.get_current_identity()
        principal = (config.identity.name or identity).split("#", 1)[0].lower()

        json_output = ctx.obj.get("json", False) if ctx.obj else False
        user = load_user(principal)
        owned, total = _owned_agents(principal)

        if json_output:
            typer.echo(
                json_module.dumps(
                    {
                        "identity": identity,
                        "principal": principal,
                        "registered": user is not None,
                        "user": user.model_dump() if user else None,
                        "owns": [
                            {"room": r, "handle": m.handle, "budget": m.budget_usd_per_month}
                            for r, m in owned
                        ],
                        "budget_usd_per_month": total,
                    },
                    indent=2,
                    default=str,
                )
            )
            return

        console.print(f"[bold]acting as[/bold] [cyan]@{principal}[/cyan]  [dim]({identity})[/dim]")
        if user is None:
            console.print(
                f"[dim]Not registered. Add yourself with: "
                f'mycelium user create {principal} --name "…"[/dim]'
            )
        else:
            if user.display_name:
                console.print(f"  name: {user.display_name}")
            if user.teams:
                console.print(f"  teams: {', '.join(user.teams)}")
        if owned:
            console.print(f"\n[bold]owns {len(owned)} agent(s)[/bold]  [dim]${total:.2f}/mo[/dim]")
            for room_name, m in owned:
                console.print(
                    f"  @{m.handle} [dim]({room_name})[/dim] ${m.budget_usd_per_month:.2f}/mo"
                )
    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None
