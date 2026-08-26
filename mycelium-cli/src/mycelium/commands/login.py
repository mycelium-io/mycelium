# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
``mycelium login`` / ``mycelium logout``: obtain and drop a human's OIDC session.

The browser flow (Authorization Code + PKCE) is the default; ``--device`` is the
fallback for a shell whose browser can't reach this machine's loopback address:
SSH, CI, a container. Both end the same way: the session lands in the ``0600``
token cache (``mycelium.tokens``) and every subsequent backend call carries it,
because they all build their client through ``mycelium.client``. A successful
login also points this machine's ``identity.name`` at the token's own handle,
since a gated hub refuses a write that claims a different one.

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
from mycelium.tokens import StoredToken, clear_token, load_token, save_token, token_path

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


def _persist_login_config(
    config: MyceliumConfig,
    *,
    issuer: str | None,
    client_id: str | None,
    audience: str | None,
    scope: str | None,
) -> None:
    """Remember explicitly-passed login settings so the next login needs no flags."""
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
) -> None:
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
                    "identity": config.identity.name,
                },
                indent=2,
            )
        )
        return

    console.print(f"[green]Signed in as[/green] [cyan]@{shown}[/cyan] [dim]({token.issuer})[/dim]")
    if remaining is not None:
        console.print(f"[dim]Access token valid for {int(remaining // 60)} min[/dim]")
    if not token.refresh_token:
        console.print(
            "[dim]No refresh token was issued; add the 'offline_access' scope "
            "if you want the session renewed automatically.[/dim]"
        )
    console.print(f"[dim]Session cached at {token_path()} (mode 0600).[/dim]")

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
    desc="Sign in to a gated hub via OIDC (Authorization Code + PKCE, or device code).",
    group="setup",
)
def login(
    ctx: typer.Context,
    issuer: str | None = typer.Option(
        None, "--issuer", help="OIDC issuer URL (default: login.issuer from config)."
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
    """Obtain an OIDC token for the hub and cache it for subsequent commands.

    Examples:
        mycelium login
        mycelium login --issuer https://sso.example.com/realms/mycelium
        mycelium login --device        # headless / SSH / CI
    """
    config = MyceliumConfig.load()
    json_output = ctx.obj.get("json", False) if ctx.obj else False

    resolved_issuer = (issuer or config.login.issuer or "").strip().rstrip("/")
    if not resolved_issuer:
        console.print("[red]Error:[/red] no OIDC issuer configured.")
        console.print(
            "[dim]Set one with: mycelium config set login.issuer "
            "https://sso.example.com/realms/mycelium[/dim]"
        )
        console.print("[dim]Or pass it once: mycelium login --issuer <url>[/dim]")
        raise typer.Exit(1)

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
        token_endpoint=meta.token_endpoint,
        scope=grant.scope or resolved_scope,
    )
    save_token(token)

    _persist_login_config(
        config,
        issuer=issuer,
        client_id=client_id,
        audience=audience,
        scope=scope,
    )

    handle = token.handle(config.auth.handle_claim) or token.handle()
    alignment = _align_identity(config, handle) if handle else _SKIPPED
    _report(token, config, handle=handle, alignment=alignment, json_output=json_output)


@doc_ref(
    usage="mycelium logout",
    desc="Drop the cached OIDC session; the CLI goes back to sending no token.",
    group="setup",
)
def logout(ctx: typer.Context) -> None:
    """Forget the cached session."""
    json_output = ctx.obj.get("json", False) if ctx.obj else False
    existed = load_token() is not None
    clear_token()

    if json_output:
        typer.echo(json_module.dumps({"logged_out": existed}))
        return
    if existed:
        console.print("[green]Signed out.[/green] [dim]Cached session removed.[/dim]")
    else:
        console.print("[dim]Not signed in; nothing to do.[/dim]")
