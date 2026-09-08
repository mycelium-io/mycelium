# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
The one factory for clients that talk to the hub's HTTP API.

Every call into the backend (the generated typed client and the raw ``httpx``
ones alike) is built here, so there is exactly one place that decides what
credentials a request carries. Before this, each command module built its own
client and none of them attached anything; a bearer token added in one place
would have authenticated one command and quietly missed the rest.

**Auth is additive and off by default.** With no cached session (``mycelium
login`` never run) the factory attaches no ``Authorization`` header and the CLI
behaves exactly as it did before tokens existed, which is what makes it safe
against a hub whose gate is off, i.e. the shipped default.

An expired access token is refreshed here, transparently, on the way into the
first call that needs it. A refresh that fails degrades to "no header" rather
than failing the command: against an ungated hub the call still works, and
against a gated one the 401 says what a fabricated error never could.

An agent attaches here too, through the same one factory: when the caller is
acting as an agent (``await``/``respond`` naming a handle, or a resident runtime
that says which handle it runs as), the credential resolved for *that agent*
(``mycelium.agent_credentials``) is preferred over the human session, so an
agent's writes carry the agent's own identity rather than whoever last logged in
on the machine.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import httpx
from rich.console import Console

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig
    from mycelium.tokens import StoredToken
    from mycelium_backend_client import Client

_DEFAULT_TIMEOUT_S = 30.0

_stderr = Console(stderr=True)

#: One warning per process when a session can't be renewed; every command would
#: otherwise repeat it for each client it builds.
_refresh_warned = False


def _resolve_config(config: MyceliumConfig | None) -> MyceliumConfig:
    from mycelium.config import MyceliumConfig

    return config if config is not None else MyceliumConfig.load()


def current_token(config: MyceliumConfig | None = None) -> StoredToken | None:
    """The usable cached session, renewed first if it has expired.

    Returns ``None`` when logged out, and also when the session is expired and
    can't be refreshed; an expired token is worse than no token, since it turns
    a working call against an ungated hub into a 401.
    """
    from mycelium.tokens import load_token

    stored = load_token()
    if stored is None or not stored.is_expired():
        return stored

    refreshed = _refresh(stored, _resolve_config(config))
    if refreshed is not None:
        return refreshed

    global _refresh_warned  # noqa: PLW0603, process-wide "say this once" latch
    if not _refresh_warned:
        _refresh_warned = True
        _stderr.print(
            "[yellow]Your Mycelium session has expired.[/yellow] "
            "[dim]Run 'mycelium login' to sign in again.[/dim]"
        )
    return None


def _refresh(stored: StoredToken, config: MyceliumConfig) -> StoredToken | None:
    """Renew an expired session with its refresh token. ``None`` if it can't be."""
    from mycelium import oidc
    from mycelium.tokens import save_token

    if not stored.refresh_token:
        return None

    endpoint = stored.token_endpoint
    if not endpoint:
        # Sessions cached before the endpoint was recorded, or minted by an
        # issuer reached some other way: rediscover it.
        issuer = stored.issuer or config.login.issuer
        if not issuer:
            return None
        try:
            endpoint = oidc.discover(issuer).token_endpoint
        except oidc.OidcError:
            return None

    try:
        resp = oidc.refresh_grant(
            endpoint,
            stored.client_id or config.login.client_id,
            stored.refresh_token,
            client_secret=config.login.client_secret,
        )
    except oidc.OidcError:
        return None

    renewed = replace(
        stored,
        access_token=resp.access_token,
        # Issuers that don't rotate refresh tokens omit it; keep the one we have.
        refresh_token=resp.refresh_token or stored.refresh_token,
        expires_at=resp.expires_at,
        # The renewal deadline moves with the token it belongs to: a rotated
        # refresh token brings its own, and a kept one keeps its own.
        refresh_expires_at=(
            resp.refresh_expires_at if resp.refresh_token else stored.refresh_expires_at
        ),
        token_endpoint=endpoint,
        scope=resp.scope or stored.scope,
    )
    save_token(renewed)
    return renewed


def auth_headers(
    config: MyceliumConfig | None = None, *, handle: str | None = None
) -> dict[str, str]:
    """``{"Authorization": "Bearer …"}`` when there's a credential, ``{}`` when not.

    ``handle`` names the agent the call is being made *as*. Its own credential
    wins over the human session when it has one: a resident agent driven from a
    developer's logged-in shell must still write as itself, not as the developer.
    """
    from mycelium import agent_credentials

    cfg = _resolve_config(config)
    agent_token = agent_credentials.access_token(cfg, handle)
    if agent_token:
        return {"Authorization": f"Bearer {agent_token}"}
    token = current_token(cfg)
    return {"Authorization": f"Bearer {token.access_token}"} if token else {}


def typed_client(config: MyceliumConfig | None = None, *, handle: str | None = None) -> Client:
    """The generated OpenAPI client, authenticated when there's a credential."""
    from mycelium_backend_client import Client

    cfg = _resolve_config(config)
    client = Client(base_url=cfg.server.api_url, raise_on_unexpected_status=True)
    headers = auth_headers(cfg, handle=handle)
    return client.with_headers(headers) if headers else client


def hub_error_detail(content: bytes) -> str:
    """Extract a human-readable message from a hub HTTP error response body.

    FastAPI serializes ``HTTPException`` as ``{"detail": "..."}``; we surface
    that string so the caller sees the backend's actual message rather than a
    bare status code.  Falls back to the raw decoded body, and to an empty
    string for truly empty responses.
    """
    try:
        body = json.loads(content)
        if isinstance(body, dict) and "detail" in body:
            return str(body["detail"])
    except (ValueError, KeyError):
        pass
    return content.decode(errors="replace").strip()


def hub_client(
    config: MyceliumConfig | None = None,
    *,
    base_url: str | None = None,
    timeout: float | None = _DEFAULT_TIMEOUT_S,
    headers: dict[str, str] | None = None,
    handle: str | None = None,
    **kwargs: Any,
) -> httpx.Client:
    """A raw ``httpx`` client against the hub, authenticated when there's a credential.

    ``base_url`` overrides the configured hub (``room clone`` reads from a
    *remote* hub) and the credential still applies, since the token is the
    caller's identity rather than a property of one address.
    """
    cfg = _resolve_config(config)
    merged = {**auth_headers(cfg, handle=handle), **(headers or {})}
    return httpx.Client(
        base_url=base_url or cfg.server.api_url,
        timeout=timeout,
        headers=merged,
        **kwargs,
    )
