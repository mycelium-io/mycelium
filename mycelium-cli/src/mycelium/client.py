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
first call that needs it. A refresh the issuer refuses degrades to "no header"
rather than failing the command: against an ungated hub the call still works,
and against a gated one the 401 says what a fabricated error never could. A
refresh that can't reach the issuer is different: the session may be fine once
it's back, so the call fails as the hub being unreachable
(:class:`RenewalUnreachable`), and whoever retries an unreachable hub retries
it, rather than sending it with no credential for the hub to refuse.

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
    from types import ModuleType

    from mycelium.config import MyceliumConfig
    from mycelium.tokens import StoredToken
    from mycelium_backend_client import Client
    from mycelium_backend_client.types import Response

_DEFAULT_TIMEOUT_S = 30.0

_stderr = Console(stderr=True)

#: One warning per process when a session can't be renewed; every command would
#: otherwise repeat it for each client it builds.
_refresh_warned = False


class RenewalUnreachable(httpx.ConnectError):
    """The session needed renewing and the issuer couldn't be reached.

    An ``httpx.ConnectError``, so every caller that handles an unreachable hub
    (the runner's heartbeat and job poll, a command's "hub unreachable")
    handles this the same way.
    """


def _resolve_config(config: MyceliumConfig | None) -> MyceliumConfig:
    from mycelium.config import MyceliumConfig

    return config if config is not None else MyceliumConfig.load()


def current_token(config: MyceliumConfig | None = None) -> StoredToken | None:
    """The usable cached session, renewed first if it has expired.

    Returns ``None`` when logged out, and also when the session is expired and
    the issuer refused to renew it; an expired token is worse than no token,
    since it turns a working call against an ungated hub into a 401. Raises
    :class:`RenewalUnreachable` when it's expired, the issuer can't be
    reached, and the hub has sign-in on (or can't say); a hub with it off
    gets ``None``, and the call goes out with no credential as before. Where
    it's kept, and that an agent's pane never gets it, is ``session_store``'s
    business.
    """
    from mycelium import session_store

    cfg = _resolve_config(config)
    stored, where = session_store.load(cfg)
    if stored is None or not stored.is_expired():
        return stored

    try:
        refreshed = _refresh(stored, cfg)
    except RenewalUnreachable:
        # A hub with sign-in off takes the call with no credential, as it
        # always did: only a hub that needs one has to wait for the issuer.
        if _needs_credential(cfg) is False:
            return None
        raise
    if refreshed is not None:
        session_store.renewed(cfg, refreshed, where)
        return refreshed

    global _refresh_warned  # noqa: PLW0603, process-wide "say this once" latch
    if not _refresh_warned:
        _refresh_warned = True
        _stderr.print(
            "[yellow]Your Mycelium session has expired.[/yellow] "
            "[dim]Run 'mycelium login' to sign in again.[/dim]"
        )
    return None


#: ``{hub url: whether it has sign-in on}``, as its ``/health`` said, per process.
_GATED: dict[str, bool] = {}


def _needs_credential(config: MyceliumConfig) -> bool | None:
    """Whether the hub has sign-in on, by its public ``/health``; ``None`` when it
    can't be asked. Not ``/api/whoami``: asking that needs the credential."""
    from mycelium.hub_check import health

    url = config.server.api_url
    if url not in _GATED:
        auth = health(url).auth
        if auth is None:
            return None
        _GATED[url] = auth.enabled
    return _GATED[url]


def _refresh(stored: StoredToken, config: MyceliumConfig) -> StoredToken | None:
    """Renew an expired session with its refresh token. ``None`` if the issuer
    refused; :class:`RenewalUnreachable` if it couldn't be asked."""
    from mycelium import oidc

    if not stored.refresh_token:
        return None

    endpoint = stored.token_endpoint
    try:
        if not endpoint:
            # Sessions cached before the endpoint was recorded, or minted by an
            # issuer reached some other way: rediscover it.
            issuer = stored.issuer or config.login.issuer
            if not issuer:
                return None
            endpoint = oidc.discover(issuer).token_endpoint
        resp = oidc.refresh_grant(
            endpoint,
            stored.client_id or config.login.client_id,
            stored.refresh_token,
            client_secret=config.login.client_secret,
        )
    except oidc.IssuerUnreachable as e:
        raise RenewalUnreachable(f"couldn't renew this computer's sign-in: {e}") from e
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
    return renewed


def auth_headers(
    config: MyceliumConfig | None = None, *, handle: str | None = None
) -> dict[str, str]:
    """``{"Authorization": "Bearer …"}`` when there's a credential, ``{}`` when not.

    ``handle`` names the agent the call is being made *as*. Its own credential
    wins over the human session when it has one: a resident agent driven from a
    developer's logged-in shell must still write as itself, not as the developer.
    Which credential that is, in which order, is ``caller.credential``'s call.
    """
    from mycelium import caller

    token = caller.credential(_resolve_config(config), handle).value
    return {"Authorization": f"Bearer {token}"} if token else {}


def typed_client(
    config: MyceliumConfig | None = None,
    *,
    handle: str | None = None,
    timeout: float | None = None,
    base_url: str | None = None,
    raise_on_unexpected_status: bool = True,
) -> Client:
    """The generated OpenAPI client, authenticated when there's a credential.

    ``timeout`` bounds each call; without one a call waits as long as the hub takes.
    ``base_url`` points it at another hub, which gets no credential unless it
    issued it, as with :func:`hub_client`.

    With ``raise_on_unexpected_status`` off, a status ``openapi.json`` doesn't
    list (a 404, a 409) comes back as the response rather than raising, so a
    caller that answers each refusal its own way reads ``status_code`` and
    ``content``; ``parsed`` is set only for a status the spec declares.
    """
    from mycelium_backend_client import Client

    cfg = _resolve_config(config)
    target = base_url or cfg.server.api_url
    client = Client(
        base_url=target,
        raise_on_unexpected_status=raise_on_unexpected_status,
        timeout=httpx.Timeout(timeout) if timeout is not None else None,
    )
    ours = base_url is None or issued_by(cfg, target)
    headers = auth_headers(cfg, handle=handle) if ours else {}
    return client.with_headers(headers) if headers else client


def sent_unparsed(route: ModuleType, client: Client, *args: Any, **kwargs: Any) -> httpx.Response:
    """Send a generated route's own request (its method, path, params and body,
    from ``route._get_kwargs``) and hand back the answer unparsed.

    For the runner's own loops, where an answer that won't parse must never end
    a thread or lose work the hub already handed over: a job taken off the
    queue, wakes drained, a heartbeat. The caller reads the status, and the body
    as JSON where it needs one, so a hub a version apart can't stop it.
    """
    return client.get_httpx_client().request(**route._get_kwargs(*args, **kwargs))  # noqa: SLF001


def answered[T](resp: Response[Any], expected: type[T]) -> T:
    """The hub's answer when it is the ``expected`` model (or ``list``).

    Anything else is a refusal the route declares (a 404, a 409, a sentence
    422), and is raised as the generated client raises a status it wasn't told
    about, ``UnexpectedStatus`` with the status and body. So a caller handles a
    declared refusal the way it handled one before the route declared it.
    """
    if isinstance(resp.parsed, expected):
        return resp.parsed
    from mycelium_backend_client.errors import UnexpectedStatus

    raise UnexpectedStatus(resp.status_code, resp.content)


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

    ``base_url`` points it at another hub (``room clone --from``, ``hub
    settings --hub``). A credential goes only to the hub that issued it, so a
    client for any other address carries none, and that hub's own gate decides
    what it may read.
    """
    cfg = _resolve_config(config)
    target = base_url or cfg.server.api_url
    credentials = auth_headers(cfg, handle=handle) if issued_by(cfg, target) else {}
    return httpx.Client(
        base_url=target,
        timeout=timeout,
        headers={**credentials, **(headers or {})},
        **kwargs,
    )


def issued_by(config: MyceliumConfig, url: str) -> bool:
    """Whether ``url`` is the hub this caller's credentials were issued for: the
    configured hub, or the hub this folder joined (``mycelium join``)."""
    from mycelium import caller

    hubs = [config.server.api_url]
    member = caller.find_membership()
    if member is not None:
        hubs.append(member.hub)
    return any(same_origin(url, hub) for hub in hubs if hub)


def same_origin(a: str, b: str) -> bool:
    """Whether two URLs name the same server: scheme, host and port."""

    def origin(url: str) -> tuple[str, str, int | None]:
        parsed = httpx.URL(url.strip())
        port = parsed.port or {"http": 80, "https": 443}.get(parsed.scheme)
        return parsed.scheme, parsed.host.lower(), port

    try:
        return origin(a) == origin(b)
    except (httpx.InvalidURL, TypeError):
        return False
