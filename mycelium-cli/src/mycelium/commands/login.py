# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
``mycelium login`` / ``mycelium logout``: obtain and drop a human's OIDC session.

The browser flow (Authorization Code + PKCE) is the default; ``--device`` is the
fallback for a shell whose browser can't reach this machine's loopback address:
SSH, CI, a container. With the desktop app running, the app runs the browser
sign-in itself and keeps the session, asking the person before a command uses
it (``mycelium.session_store``), so the refresh token never reaches the CLI.
Without it, the CLI signs in, and keeps the session only with ``--remember``,
in a ``0600`` file. Every later backend call carries
it, because they all build their client through ``mycelium.client``. A successful
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
from mycelium.tokens import DEFAULT_LEEWAY_S, StoredToken, format_span, token_path

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
    import httpx

    url = f"{config.server.api_url.rstrip('/')}/health"
    try:
        resp = httpx.get(url, timeout=5)
        resp.raise_for_status()
        body = resp.json()
    except (httpx.HTTPError, ValueError):
        return [], f"couldn't reach {url} to ask it"
    auth = body.get("auth") or {} if isinstance(body, dict) else {}
    if not auth.get("enabled"):
        return [], f"{config.server.api_url} has its gate off, so it needs no login"
    issuers = [str(i).strip().rstrip("/") for i in auth.get("issuers") or [] if str(i).strip()]
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
    refreshable: bool,
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
                    "refreshable": refreshable,
                    # Null means the issuer reported no refresh_expires_in, not
                    # that renewal is unlimited.
                    "refresh_expires_at": token.refresh_expires_at,
                    "renewal_leeway_s": DEFAULT_LEEWAY_S,
                    "identity": config.identity.name,
                    # Where it's kept: the desktop app, a --remember file, or
                    # nowhere (this command only).
                    "kept": kept,
                },
                indent=2,
            )
        )
        return

    console.print(f"[green]Signed in as[/green] [cyan]@{shown}[/cyan] [dim]({token.issuer})[/dim]")
    if remaining is not None:
        console.print(f"[dim]Access token valid for {format_span(remaining)}.[/dim]")
    if refreshable and kept == session_store.APP:
        console.print("[dim]Mycelium renews it when a command asks for it.[/dim]")
    elif refreshable:
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
    if kept == session_store.APP:
        console.print(
            "[dim]Kept by Mycelium. A command that uses it asks you first (Touch ID or your "
            "password on macOS), so an agent running as you can't.[/dim]"
        )
    elif kept == session_store.FILE:
        console.print(
            f"[yellow]Kept in {token_path()}[/yellow] [dim](mode 0600). Any program running "
            "as you can read it, agents included.[/dim]"
        )
    else:
        console.print(
            "[yellow]Not kept:[/yellow] Mycelium isn't running here to keep it. Open "
            "Mycelium and sign in again, or run [cyan]mycelium login --remember[/cyan] to keep "
            "it in a file any program running as you can read."
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
    remember: bool = typer.Option(
        False,
        "--remember",
        help=(
            "Without the desktop app: keep the sign-in in a file. Any program running as "
            "you can read it, agents included."
        ),
    ),
) -> None:
    """Sign in to the hub, through the desktop app when it's running.

    The app asks you, signs in in your browser and keeps the sign-in, and asks
    you again (Touch ID or your password on macOS) before a command uses it,
    so an agent running as you can't. Without the app
    it isn't kept, unless ``--remember`` writes it to a file. An agent's pane
    can't sign in as a person.

    With neither ``--issuer`` nor ``login.issuer``, the hub named by
    ``server.api_url`` is asked for the issuer it trusts, and a single answer is
    used and remembered.

    Examples:
        mycelium login
        mycelium login --issuer https://sso.example.com/realms/mycelium
        mycelium login --device             # headless / SSH / CI
        mycelium login --device --remember  # a server with no desktop app
    """
    from mycelium import caller

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

    from mycelium import session_store

    def finish(token: StoredToken, *, kept: str, refreshable: bool) -> None:
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
        handle = token.handle(config.auth.handle_claim) or token.handle()
        alignment = _align_identity(config, handle) if handle else _SKIPPED
        _report(
            token,
            config,
            handle=handle,
            alignment=alignment,
            json_output=json_output,
            kept=kept,
            refreshable=refreshable,
        )

    # With the app here, the app signs in and keeps the result, so the refresh
    # token never reaches this process (`session_store.login_in_app`). The app
    # takes no client secret, so a client that needs one signs in here.
    if not config.login.client_secret and session_store.app_running():
        if not json_output:
            if device:
                console.print(
                    "[dim]Mycelium signs you in in your browser; --device is for a "
                    "machine without the app.[/dim]"
                )
            console.print("[dim]Mycelium asks you first, then opens your browser to sign in.[/dim]")
        try:
            made = session_store.login_in_app(
                config,
                issuer=resolved_issuer,
                client_id=resolved_client_id,
                scope=resolved_scope,
                audience=resolved_audience,
                redirect_port=config.login.redirect_port,
            )
        except session_store.LoginFailed as exc:
            console.print(f"[red]Login failed:[/red] {exc}")
            raise typer.Exit(1) from exc
        if made is not None:
            finish(made[0], kept=session_store.APP, refreshable=made[1])
            return

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
    kept = session_store.save(config, token, remember=remember)
    finish(token, kept=kept, refreshable=bool(token.refresh_token))


@doc_ref(
    usage="mycelium logout",
    desc="Drop the cached OIDC session; the CLI goes back to sending no token.",
    group="setup",
)
def logout(ctx: typer.Context) -> None:
    """Forget the sign-in, wherever it was kept."""
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
