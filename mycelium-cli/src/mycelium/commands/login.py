# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
``mycelium login`` / ``mycelium logout``: obtain and drop a human's OIDC session.

The browser flow (Authorization Code + PKCE) is the default; ``--device`` is the
fallback for a shell whose browser can't reach this machine's loopback address:
SSH, CI, a container. Both end the same way: the session, refresh token
included, is kept in the system keychain (or a ``0600`` file where there's no
keychain, ``mycelium.session_store``), and every later backend call carries it
and renews it quietly, because they all build their client through
``mycelium.client``. An agent's pane can't sign in as a person. A successful
login also points this machine's ``identity.name`` at the token's own handle,
since a gated hub refuses a write that claims a different one.

With no issuer configured, login asks the hub for one: a gated hub advertises
what it trusts at ``/health``, so the URL is the backend's to supply rather than
the human's to look up.

Logging in is opt-in. Nothing here runs unless the user asks for it, and a hub
with its gate off never needs it.
"""

from __future__ import annotations

import json as json_module
import webbrowser

import typer
from rich.console import Console

from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref
from mycelium.oidc import (
    DevicePrompt,
    OidcError,
    ProviderMetadata,
    authorization_code_login,
    device_code_login,
    discover,
)
from mycelium.tokens import DEFAULT_LEEWAY_S, StoredToken, format_span

console = Console()


def _browser_available() -> bool:
    """Whether this machine has a browser the CLI could actually open."""
    try:
        webbrowser.get()
    except webbrowser.Error:
        return False
    return True


def _announce_url(url: str) -> None:
    console.print("[dim]Opening your browser to sign in. If it doesn't open, visit:[/dim]")
    console.print(f"  {url}\n")


def _announce_device(prompt: DevicePrompt) -> None:
    target = prompt.verification_uri_complete or prompt.verification_uri
    console.print("\n[bold]To sign in, visit:[/bold]")
    console.print(f"  {target}")
    console.print(f"[bold]and enter the code:[/bold] [cyan]{prompt.user_code}[/cyan]\n")
    console.print("[dim]Waiting for you to approve…[/dim]")


def _hub_issuers(config: MyceliumConfig) -> tuple[list[str], str | None]:
    """The OIDC issuers the hub advertises at ``/health``, and why there are none.

    The hub has to be reachable for a session to be worth anything, and it already
    publishes what it trusts — so a spoke should not need a human to look the
    issuer up and copy it back in. Returns the issuers and, when the list is
    empty, a reason to print instead of a bare "no issuer configured".
    """
    from mycelium.hub_check import health

    said = health(config.server.api_url, timeout=5)
    if said.read is None:
        return [], f"couldn't reach {said.url}/health to ask it"
    auth = said.auth
    if auth is None or not auth.enabled:
        return [], f"{config.server.api_url} has its gate off, so it needs no login"
    issuers = [i.strip().rstrip("/") for i in auth.issuers if i.strip()]
    if not issuers:
        return [], f"{config.server.api_url} is gated but advertises no issuer"
    return issuers, None


def _issuer_from_hub(config: MyceliumConfig, *, json_output: bool) -> str | None:
    """The hub's issuer, when it names exactly one.

    Several trusted issuers is not a default to guess at: which one you sign in
    against decides who the hub thinks you are, so the choice is named rather
    than taken. Prints what it found either way — the lookup is the friction, and
    a listed issuer is one ``--issuer`` away even when it can't be picked here.
    """
    issuers, why = _hub_issuers(config)
    if not issuers:
        console.print(f"[red]Error:[/red] no OIDC issuer configured, and {why}.")
        console.print(
            "[dim]Set one with: mycelium config set login.issuer "
            "https://sso.example.com/realms/mycelium[/dim]"
        )
        console.print("[dim]Or pass it once: mycelium login --issuer <url>[/dim]")
        return None
    if len(issuers) > 1:
        console.print(f"[red]Error:[/red] {config.server.api_url} trusts more than one issuer:")
        for candidate in issuers:
            console.print(f"  {candidate}")
        console.print("[dim]Pick one: mycelium login --issuer <url>[/dim]")
        return None
    if not json_output:
        console.print(f"[dim]Issuer discovered from {config.server.api_url}: {issuers[0]}[/dim]")
    return issuers[0]


def _persist_login_config(
    config: MyceliumConfig,
    *,
    issuer: str | None,
    client_id: str | None,
    audience: str | None,
    scope: str | None,
    json_output: bool,
) -> None:
    """Remember the login settings this run resolved, so the next needs no flags."""
    changed = False
    for field, value in (
        ("issuer", issuer),
        ("client_id", client_id),
        ("audience", audience),
        ("scopes", scope),
    ):
        if value and getattr(config.login, field) != value:
            setattr(config.login, field, value)
            changed = True
    if changed:
        config.save()
        if not json_output:
            console.print(f"[dim]Saved login settings to {MyceliumConfig.get_config_path()}[/dim]")


# What ``_align_identity`` did with the token's handle, for ``_report`` to narrate.
_SKIPPED = "skipped"  # no readable handle claim; there is nothing to align to
_ALREADY = "already"  # identity.name already names the token's principal
_ALIGNED = "aligned"
_UNREGISTERED = "unregistered"  # identity.name landed, the hub didn't take the record
_FAILED = "failed"


def _hub_handle(config: MyceliumConfig) -> str | None:
    """Who the hub says the new token is: the handle its gate enforces.

    The hub reads the handle from its own ``auth.handle_claim``, which this
    machine's copy of the setting may not match (a UUID ``sub`` here, a
    ``preferred_username`` there). ``None`` when the hub can't be reached,
    runs with auth off, or refuses the token, and the local claim is used.
    """
    from mycelium.identity import _WHOAMI_CACHE, _hub_whoami

    # Asked earlier in this process, the answer was for the old credential.
    _WHOAMI_CACHE.pop(config.server.api_url, None)
    who = _hub_whoami(config)
    handle = str((who.handle if who else None) or "").strip().lstrip("@").lower()
    return handle or None


def _align_identity(config: MyceliumConfig, handle: str) -> str:
    """Point this machine's identity at the token's own handle.

    A token is authoritative over a self-asserted local name, and a gated hub
    refuses a write that claims a different one — so login does the alignment
    itself rather than printing a second command for the human to relay back.
    Same path ``mycelium iam <handle>`` takes: ``identity.name`` plus the
    ``users/`` record.
    """
    asserted = (config.identity.name or "").strip().lstrip("@").lower()
    if asserted == handle:
        return _ALREADY

    from mycelium.commands.user import align_identity

    try:
        _manifest, registered = align_identity(handle, config=config)
    except Exception:  # noqa: BLE001 — a login that worked must not fail on this
        return _FAILED
    return _ALIGNED if registered else _UNREGISTERED


def _report(
    token: StoredToken,
    config: MyceliumConfig,
    *,
    handle: str | None,
    alignment: str,
    json_output: bool,
    kept: str,
) -> None:
    from mycelium import session_store

    shown = handle or "(unknown)"
    remaining = token.expires_in()

    if json_output:
        typer.echo(
            json_module.dumps(
                {
                    "handle": shown,
                    "issuer": token.issuer,
                    "client_id": token.client_id,
                    "expires_at": token.expires_at,
                    "refreshable": bool(token.refresh_token),
                    # Null means the issuer reported no refresh_expires_in, not
                    # that renewal is unlimited.
                    "refresh_expires_at": token.refresh_expires_at,
                    "renewal_leeway_s": DEFAULT_LEEWAY_S,
                    "identity": config.identity.name,
                    # Where it's kept: the system keychain, or a 0600 file.
                    "kept": kept,
                },
                indent=2,
            )
        )
        return

    console.print(f"[green]Signed in as[/green] [cyan]@{shown}[/cyan] [dim]({token.issuer})[/dim]")
    if remaining is not None:
        console.print(f"[dim]Access token valid for {format_span(remaining)}.[/dim]")
    if token.refresh_token:
        # A short access-token lifetime reads as "sign in again in four minutes"
        # unless the renewal is stated with it. There is no schedule to state:
        # the next call that needs the token is what renews it.
        console.print(
            f"[dim]It renews on demand — the next command that needs it swaps in a fresh "
            f"one once under {format_span(DEFAULT_LEEWAY_S)} is left. Nothing renews in the "
            "background.[/dim]"
        )
        renewal_left = token.refresh_expires_in()
        if renewal_left is not None:
            console.print(
                f"[dim]Signing in again is due in {format_span(renewal_left)}, when the "
                "refresh token itself expires.[/dim]"
            )
    else:
        console.print(
            "[dim]No refresh token was issued, so the session ends when this access token "
            "does; add the 'offline_access' scope if you want it renewed automatically.[/dim]"
        )
    if kept == session_store.KEYCHAIN:
        console.print("[dim]Kept in the system keychain.[/dim]")
    elif kept == session_store.REFUSED:
        console.print(
            f"[yellow]Kept in {session_store.where_described(kept)}[/yellow] [dim](mode 0600): "
            "the system keychain wouldn't keep it. Either its prompt was declined, or the "
            "entry is too large for it. Run mycelium login again and allow it to use the "
            "keychain.[/dim]"
        )
    else:
        console.print(
            f"[yellow]Kept in {session_store.where_described(kept)}[/yellow] [dim](mode 0600): "
            "there's no system keychain to keep it in here.[/dim]"
        )

    if alignment in (_ALIGNED, _UNREGISTERED):
        console.print(f"[dim]This machine now writes as @{shown} (identity.name).[/dim]")
    if alignment == _UNREGISTERED:
        console.print(
            f"[yellow]Not registered on the hub[/yellow] [dim]— couldn't reach "
            f"{config.server.api_url}. Re-run: mycelium iam {shown}[/dim]"
        )
    if alignment == _FAILED:
        # Couldn't align, so say what a self-asserted identity naming someone
        # else costs: a gated hub turns it into a 403 at the first write.
        asserted = (config.identity.name or "").strip().lstrip("@").lower() or "(unset)"
        console.print(
            f"\n[yellow]Heads up:[/yellow] this machine writes as [cyan]@{asserted}[/cyan], "
            f"but your token says [cyan]@{shown}[/cyan]. A gated hub refuses writes that "
            "claim a different handle."
        )
        console.print(f"[dim]Align them with: mycelium iam {shown}[/dim]")


@doc_ref(
    usage="mycelium login [--issuer URL] [--device] [--no-browser] [--client-id ID]",
    desc=(
        "Sign in to a gated hub via OIDC (Authorization Code + PKCE, or device code); "
        "the issuer is discovered from the hub when it isn't configured."
    ),
    group="setup",
)
def login(
    ctx: typer.Context,
    issuer: str | None = typer.Option(
        None,
        "--issuer",
        help="OIDC issuer URL (default: login.issuer, else discovered from the hub).",
    ),
    client_id: str | None = typer.Option(
        None, "--client-id", help="OAuth client id to log in as (default: login.client_id)."
    ),
    scope: str | None = typer.Option(
        None, "--scope", help="Space-separated scopes to request (default: login.scopes)."
    ),
    audience: str | None = typer.Option(
        None, "--audience", help="Audience to request; should match the hub's auth.audience."
    ),
    device: bool = typer.Option(
        False, "--device", help="Use the device-code flow (headless, SSH, CI)."
    ),
    no_browser: bool = typer.Option(
        False, "--no-browser", help="Print the sign-in URL instead of opening a browser."
    ),
    timeout: float = typer.Option(
        300.0, "--timeout", "-t", help="Seconds to wait for you to finish signing in."
    ),
) -> None:
    """Obtain an OIDC token for the hub and keep it for later commands.

    It's kept in the system keychain (a ``0600`` file where there's none), and
    renewed quietly when it runs out. An agent's pane can't sign in as a person.

    With neither ``--issuer`` nor ``login.issuer``, the hub named by
    ``server.api_url`` is asked for the issuer it trusts, and a single answer is
    used and remembered.

    Examples:
        mycelium login
        mycelium login --issuer https://sso.example.com/realms/mycelium
        mycelium login --device        # headless / SSH / CI
    """
    from mycelium import caller, session_store

    config = MyceliumConfig.load()
    json_output = ctx.obj.get("json", False) if ctx.obj else False
    if pane := caller.in_agent_pane():
        console.print(
            f"[red]Error:[/red] this is @{pane}'s pane. An agent can't sign in as a person; "
            "run mycelium login in your own terminal."
        )
        raise typer.Exit(1)

    resolved_issuer = (issuer or config.login.issuer or "").strip().rstrip("/")
    discovered = None
    if not resolved_issuer:
        discovered = _issuer_from_hub(config, json_output=json_output)
        if not discovered:
            raise typer.Exit(1)
        resolved_issuer = discovered

    resolved_client_id = (client_id or config.login.client_id).strip()
    resolved_scope = (scope or config.login.scopes).strip()
    resolved_audience = audience or config.login.audience

    try:
        meta: ProviderMetadata = discover(resolved_issuer)
    except OidcError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc

    use_device = device
    if not use_device and not _browser_available() and meta.device_authorization_endpoint:
        console.print("[dim]No browser available here; falling back to the device-code flow.[/dim]")
        use_device = True

    try:
        if use_device:
            grant = device_code_login(
                meta,
                resolved_client_id,
                scope=resolved_scope,
                audience=resolved_audience,
                client_secret=config.login.client_secret,
                timeout_s=timeout,
                announce=_announce_device,
            )
        else:
            grant = authorization_code_login(
                meta,
                resolved_client_id,
                scope=resolved_scope,
                audience=resolved_audience,
                client_secret=config.login.client_secret,
                redirect_port=config.login.redirect_port,
                open_browser=not no_browser,
                timeout_s=timeout,
                announce=_announce_url,
            )
    except OidcError as exc:
        console.print(f"[red]Login failed:[/red] {exc}")
        raise typer.Exit(1) from exc

    token = StoredToken(
        access_token=grant.access_token,
        issuer=meta.issuer,
        client_id=resolved_client_id,
        refresh_token=grant.refresh_token,
        expires_at=grant.expires_at,
        refresh_expires_at=grant.refresh_expires_at,
        token_endpoint=meta.token_endpoint,
        scope=grant.scope or resolved_scope,
    )
    kept = session_store.save(config, token)

    _persist_login_config(
        config,
        # A discovered issuer is remembered like a passed one: it cost a round
        # trip, and it is only written once the login it drove actually worked.
        issuer=issuer or discovered,
        client_id=client_id,
        audience=audience,
        scope=scope,
        json_output=json_output,
    )

    handle = _hub_handle(config) or token.handle(config.auth.handle_claim) or token.handle()
    alignment = _align_identity(config, handle) if handle else _SKIPPED
    _report(token, config, handle=handle, alignment=alignment, json_output=json_output, kept=kept)


@doc_ref(
    usage="mycelium logout",
    desc="Drop the cached OIDC session; the CLI goes back to sending no token.",
    group="setup",
)
def logout(ctx: typer.Context) -> None:
    """Forget the session, wherever it was kept."""
    from mycelium import session_store

    json_output = ctx.obj.get("json", False) if ctx.obj else False
    existed = session_store.clear(MyceliumConfig.load())

    if json_output:
        typer.echo(json_module.dumps({"logged_out": existed}))
        return
    if existed:
        console.print("[green]Signed out.[/green] [dim]Cached session removed.[/dim]")
    else:
        console.print("[dim]Not signed in; nothing to do.[/dim]")
