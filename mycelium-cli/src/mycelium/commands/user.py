# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
User commands: the human as a first-class, room-spanning principal.

A user is one global record on the hub at ``users/<handle>``. An agent's
``owner`` points at one of these handles; a ``team`` groups them. Trust is
self-asserted: the handle is consistent, not cryptographic.

The store is global rather than room-scoped (unlike ``agents/<handle>``) because
a person spans rooms — but it is still the hub's store. These commands are
clients of ``/api/users``; nothing here reads or writes a local replica, so a
spoke sees the same people the hub and the app do.
"""

from __future__ import annotations

import json as json_module
import logging
from typing import TYPE_CHECKING, Any

import httpx
import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from mycelium.client import current_token
from mycelium.client import typed_client as _typed_client
from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref
from mycelium.error_handler import print_error
from mycelium.protocol import UserManifest
from mycelium_backend_client.errors import UnexpectedStatus

if TYPE_CHECKING:
    from mycelium_backend_client.models import UserRead

app = typer.Typer(
    help=(
        "The human as a first-class entity. A user is a global "
        "users/<handle> record that an agent's --owner points at."
    ),
    no_args_is_help=True,
)
console = Console()
_log = logging.getLogger(__name__)


def _norm_handle(handle: str) -> str:
    """A handle as the store keys it: trimmed, ``@``-stripped, lower-cased."""
    return handle.strip().lstrip("@").lower()


def _unset_to_none(field: Any) -> Any:
    """Normalize a generated-client UNSET field to ``None``."""
    from mycelium_backend_client.types import UNSET

    return None if isinstance(field, type(UNSET)) else field


def _manifest_from_read(read: UserRead) -> UserManifest | None:
    """Rehydrate the CLI's model from the hub's ``UserRead``.

    A record the hub serves but this CLI's schema rejects is logged at WARNING
    rather than dropped, so a version skew between the two never looks like
    "no such user".
    """
    try:
        return UserManifest(
            handle=read.handle,
            display_name=_unset_to_none(read.display_name) or "",
            teams=_unset_to_none(read.teams) or [],
            notify=_unset_to_none(read.notify),
        )
    except ValidationError as exc:
        _log.warning("user %s: schema validation failed: %s", read.handle, exc)
        return None


def _fetch_user(handle: str, *, client: Any = None) -> UserRead | None:
    """The hub's record for *handle* — the model plus its owned-agent roll-up.

    ``None`` means the hub has no such user. Transport and HTTP failures
    propagate, so no caller mistakes "couldn't look" for "not registered".
    """
    if client is None:
        with _typed_client(MyceliumConfig.load()) as own_client:
            return _fetch_user(handle, client=own_client)

    from mycelium_backend_client.api.users import get_user_api_users_handle_get as get_api
    from mycelium_backend_client.models import UserRead

    try:
        result = get_api.sync(handle=_norm_handle(handle), client=client)
    except UnexpectedStatus as exc:
        if exc.status_code == 404:
            return None
        raise
    return result if isinstance(result, UserRead) else None


def load_user(handle: str) -> UserManifest | None:
    """Read a user record off the hub, or ``None`` if it has no such user.

    People span rooms, so the store is global rather than room-scoped — but it
    is still the hub's store, not a local replica.
    """
    read = _fetch_user(handle)
    return _manifest_from_read(read) if read is not None else None


def list_users() -> list[UserManifest]:
    """Every user registered on the hub."""
    from mycelium_backend_client.api.users import list_users_api_users_get as list_api

    with _typed_client(MyceliumConfig.load()) as client:
        result = list_api.sync(client=client)
    reads = _unset_to_none(getattr(result, "users", None)) or []
    return [u for u in (_manifest_from_read(r) for r in reads) if u is not None]


def _write_user(user: UserManifest, created_by: str) -> None:
    """Upsert the user record on the hub.

    The backend owns the write — versioning, the content-idempotent no-op on an
    unchanged record, and the frontmatter it lands in are all its business.
    """
    from mycelium_backend_client.api.users import create_user_api_users_post as create_api
    from mycelium_backend_client.models import UserCreate

    body = UserCreate(
        handle=user.handle,
        display_name=user.display_name,
        teams=user.teams,
        notify=user.notify,
        created_by=created_by,
    )
    with _typed_client(MyceliumConfig.load()) as client:
        create_api.sync(client=client, body=body)


def align_identity(
    handle: str,
    *,
    config: MyceliumConfig,
    display_name: str | None = None,
    teams: list[str] | None = None,
) -> tuple[UserManifest, bool]:
    """Make *handle* this machine's identity and ensure its ``users/`` record exists.

    Two halves with different homes: the identity is this machine's config, the
    user record is the hub's. Registering can fail on its own, and the local half
    still has to land — otherwise a hub outage leaves you unable to say who you
    are here. The returned flag says whether the hub took the record.

    Raises ``ValidationError`` when *handle* isn't a valid handle.
    """
    manifest = UserManifest(handle=handle, display_name=display_name or "", teams=teams or [])

    registered = True
    try:
        # Preserve an existing display name / teams when the caller didn't pass them.
        existing = load_user(manifest.handle)
        if existing is not None:
            if display_name is None:
                manifest.display_name = existing.display_name
            if not teams:
                manifest.teams = existing.teams
        _write_user(manifest, created_by=manifest.handle)
    except (httpx.HTTPError, UnexpectedStatus):
        registered = False

    config.identity.name = manifest.handle
    config.save()
    return manifest, registered


def _owned_lines(read: UserRead) -> list[tuple[str, str, str]]:
    """The hub's roll-up for a user as ``(handle, adapter, room)`` triples."""
    owns = _unset_to_none(getattr(read, "owns", None)) or []
    return [(o.handle, o.adapter, o.room) for o in owns]


@doc_ref(
    usage="mycelium user create <handle> [--name <display>] [--team <slug>]",
    desc="Register a human as a first-class user in the global store.",
    group="user",
)
@app.command("create")
def user_create(
    ctx: typer.Context,
    handle: str = typer.Argument(..., help="User handle (lowercase slug, e.g. 'avery')."),
    display_name: str = typer.Option(
        "", "--name", "-n", help="Human-readable display name, e.g. 'Avery Quinn'."
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
        mycelium user create avery --name "Avery Quinn" --team core
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
        read = _fetch_user(handle)
        user = _manifest_from_read(read) if read is not None else None
        if read is None or user is None:
            console.print(f"[red]Not found:[/red] no user '{handle}' on the hub.")
            raise typer.Exit(1)

        console.print(f"[bold cyan]@{user.handle}[/bold cyan]")
        if user.display_name:
            console.print(f"  name: {user.display_name}")
        if user.teams:
            console.print(f"  teams: {', '.join(user.teams)}")
        if user.notify:
            console.print(f"  notify: {user.notify}")

        # The hub rolls up owned agents across every room, in the same request.
        owned = _owned_lines(read)
        if owned:
            console.print(f"\n[bold]owns {len(owned)} agent(s)[/bold]")
            for agent_handle, adapter, room_name in owned:
                console.print(f"  @{agent_handle} [dim]({adapter}, {room_name})[/dim]")
        else:
            console.print("\n[dim]No agents owned yet.[/dim]")
    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None


def _principal_view(handle: str) -> tuple[UserManifest | None, list[tuple[str, str, str]]] | None:
    """A principal's hub record and owned-agent roll-up, or ``None`` if the hub is down.

    ``whoami`` answers "who am I on this machine" with the hub unreachable, so
    that case is a ``None`` view the caller reports rather than an error. A
    registered user carries the hub's own roll-up; ``/api/users`` is keyed by
    user record, so an unregistered principal's agents come from the room
    manifests instead.
    """
    try:
        read = _fetch_user(handle)
        if read is not None:
            return _manifest_from_read(read), _owned_lines(read)
        from mycelium.commands.agent import load_owned_agents

        owned = load_owned_agents(owner=handle)
        return None, [(m.handle, m.adapter, room) for room, m in owned]
    except (httpx.HTTPError, UnexpectedStatus):
        return None


@doc_ref(
    usage="mycelium whoami",
    desc="Print the user you're acting as, plus the agents you own.",
    group="user",
)
def whoami(ctx: typer.Context) -> None:
    """Resolve the current identity to a user handle and roll up owned agents.

    Logged in (``mycelium login``), the token is the answer: the principal is the
    handle it asserts, which is also the handle a gated hub will attribute writes
    to. Logged out (the default), this is the self-asserted ``identity.name``
    exactly as before.
    """
    try:
        config = MyceliumConfig.load()
        # The attribution handle can be session-qualified (``avery#a8f3``); the
        # principal is the bare name it derives from.
        identity = config.get_current_identity()
        principal = (config.identity.name or identity).split("#", 1)[0].lower()

        token = current_token(config)
        token_handle = token.handle(config.auth.handle_claim) if token else None
        if token_handle:
            principal = token_handle

        json_output = ctx.obj.get("json", False) if ctx.obj else False
        view = _principal_view(principal)
        hub_down = view is None
        user, owned = (None, []) if view is None else view

        if json_output:
            typer.echo(
                json_module.dumps(
                    {
                        "identity": identity,
                        "principal": principal,
                        "api_url": config.server.api_url,
                        "authenticated": token is not None,
                        "token": {
                            "handle": token_handle,
                            "issuer": token.issuer,
                            "expires_at": token.expires_at,
                            "refreshable": token.refresh_token is not None,
                        }
                        if token
                        else None,
                        "hub_reachable": not hub_down,
                        "registered": None if hub_down else user is not None,
                        "user": user.model_dump() if user else None,
                        "owns": (
                            None
                            if hub_down
                            else [{"room": room, "handle": h} for h, _adapter, room in owned]
                        ),
                    },
                    indent=2,
                    default=str,
                )
            )
            return

        console.print(f"[bold]acting as[/bold] [cyan]@{principal}[/cyan]  [dim]({identity})[/dim]")
        console.print(f"  [dim]hub: {config.server.api_url}[/dim]")
        if token is not None:
            from mycelium.tokens import format_span

            remaining = token.expires_in()
            expiry = f", expires in {format_span(remaining)}" if remaining is not None else ""
            source = "signed in" if token_handle else "signed in, no handle claim"
            console.print(f"  [green]{source}[/green] [dim]({token.issuer}{expiry})[/dim]")
            if token.refresh_token:
                # The refresh token is opaque, so its own deadline is only known
                # when the issuer volunteered one; without it, say that renewal
                # happens rather than inventing how long it keeps working.
                renewal_left = token.refresh_expires_in()
                due = (
                    f", re-login due in {format_span(renewal_left)}"
                    if renewal_left is not None
                    else ""
                )
                console.print(f"  [dim]renewed on the next command that needs it{due}[/dim]")
            else:
                console.print("  [dim]no refresh token — re-login required after expiry[/dim]")
        if hub_down:
            console.print(
                "[yellow]Can't reach the hub[/yellow] [dim]— registration and the "
                "owned-agent roll-up are unavailable.[/dim]"
            )
        elif user is None:
            console.print(
                f'[dim]Not registered. Claim it with: mycelium iam {principal} --name "…"[/dim]'
            )
        else:
            if user.display_name:
                console.print(f"  name: {user.display_name}")
            if user.teams:
                console.print(f"  teams: {', '.join(user.teams)}")
        if owned:
            console.print(f"\n[bold]owns {len(owned)} agent(s)[/bold]")
            for agent_handle, _adapter, room_name in owned:
                console.print(f"  @{agent_handle} [dim]({room_name})[/dim]")
    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None


@doc_ref(
    usage='mycelium iam [<handle>] [--name "Display Name"]',
    desc="Set this machine's identity (or, with no handle, report it) and ensure the user record exists.",
    group="user",
)
def iam(
    ctx: typer.Context,
    handle: str | None = typer.Argument(
        None, help="Your user handle (lowercase slug, e.g. 'avery'). Omit to report who you are."
    ),
    name: str | None = typer.Option(None, "--name", "-n", help="Display name to set/update."),
    team: list[str] | None = typer.Option(None, "--team", help="Team slug to join (repeatable)."),
) -> None:
    """Declare who you are on this machine.

    Sets ``identity.name`` (what ``whoami``, attribution, and the default reply
    handle resolve to) and upserts the ``users/<handle>`` record so the principal
    actually exists. The one-liner counterpart to the app's acting-as picker.

    With no handle it reports the current identity instead: the token's handle
    when signed in, the self-asserted one when not.

    Examples:
        mycelium iam avery --name "Avery Quinn" --team core
        mycelium iam
    """
    if handle is None:
        whoami(ctx)
        return

    try:
        config = MyceliumConfig.load()
        try:
            manifest, registered = align_identity(
                handle, config=config, display_name=name, teams=team
            )
        except ValidationError as exc:
            typer.secho(f"Invalid handle: {exc}", fg=typer.colors.RED)
            raise typer.Exit(1) from exc

        team_line = f" · teams: {', '.join(manifest.teams)}" if manifest.teams else ""
        console.print(
            f"[green]You are[/green] [cyan]@{manifest.handle}[/cyan]"
            f"{f' ({manifest.display_name})' if manifest.display_name else ''}{team_line}"
        )
        console.print(f"[dim]hub: {config.server.api_url}[/dim]")
        console.print("[dim]Set as this machine's identity. Check with: mycelium whoami[/dim]")
        if not registered:
            console.print(
                f"[yellow]Not registered on the hub[/yellow] [dim]— couldn't reach "
                f"{config.server.api_url}. Re-run this once it's up so others can "
                f"resolve @{manifest.handle}.[/dim]"
            )

        # A gated hub attributes writes to the token, and refuses a body that
        # claims a different handle (#562), so a mismatch is worth saying now
        # rather than at the first 403.
        token = current_token(config)
        token_handle = token.handle(config.auth.handle_claim) if token else None
        if token_handle and token_handle != manifest.handle:
            console.print(
                f"[yellow]Note:[/yellow] you're signed in as [cyan]@{token_handle}[/cyan]; "
                "a hub with auth enabled will refuse writes claiming a different handle."
            )
    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None
