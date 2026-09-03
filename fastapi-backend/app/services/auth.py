# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""HTTP-API JWT gate — validate a bearer token against a configured issuer + JWKS.

The backend's HTTP surface is otherwise unauthenticated: whoever reaches ``:8000``
can read and write every room. This module closes that, **as an opt-in**. With
``AUTH_ENABLED`` false (the shipped default) the gate is inert and every request
is anonymous, which is the whole point — auth must never be a wall between
someone and trying the app.

It is deliberately **issuer-agnostic**: trust is a list of ``TrustedIssuer``
entries matched by exact ``iss``, each with its own keys. Nothing here knows or
cares whether the root is Keycloak, Dex, the dev mock issuer, or a workload-identity
trust domain, so adding the agent trust root later (#564/#476) is a config entry.

Scope is authentication only. Resolving a validated token into the *authoritative*
actor for a write — replacing body-supplied ``created_by`` / ``sender_handle`` —
is handle binding, and lives in ``services/actor.py``; this module proves the
token and records the principal on ``request.state.principal`` for it to consume.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
import jwt
from fastapi import HTTPException, Request

from app.config import PrincipalRole, TrustedIssuer, settings
from app.services.agent_registry import norm_handle

logger = logging.getLogger(__name__)

#: Asymmetric signatures only. ``none`` and the whole ``HS*`` family are refused
#: before verification is attempted: with a public JWKS, accepting an HMAC
#: algorithm would let anyone sign a token using the published key as the shared
#: secret — the classic algorithm-confusion forgery.
ALLOWED_ALGORITHMS = frozenset(
    {"RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512"}
)

#: Paths served without a token even when the gate is on. Health is here because
#: orchestrator probes (the compose healthcheck, `mycelium doctor`) are
#: unauthenticated by nature and reveal no room content; the schema/docs routes
#: describe the API rather than exposing any of it.
PUBLIC_PATHS = frozenset({"/", "/health", "/healthz", "/docs", "/redoc", "/openapi.json"})

#: The A2A Agent Card is per-room, so it can't be a fixed PUBLIC_PATHS entry; it's
#: matched by suffix. The A2A spec serves the card to unauthenticated GET (like
#: /.well-known/openid-configuration) — it's discovery metadata (room name +
#: advertised skills), not room content. The room's RPC endpoint stays gated.
A2A_CARD_SUFFIX = "/.well-known/agent-card.json"

#: Shortest gap between forced JWKS re-fetches triggered by an unknown ``kid``.
#: Rotation is picked up within this bound; without it, a flood of junk ``kid``s
#: would be an amplified request generator pointed at the issuer.
_ROTATION_REFRESH_COOLDOWN_S = 10.0

_JWKS_FETCH_TIMEOUT_S = 5.0


@dataclass(frozen=True)
class Principal:
    """The verified actor behind a request.

    ``handle`` is the canonical ``@handle`` — normalized identically to
    ``principals._norm`` so a token-derived handle and a stored one compare equal.
    """

    subject: str
    handle: str
    role: PrincipalRole
    issuer: str
    claims: dict[str, Any] = field(default_factory=dict)


class AuthError(HTTPException):
    """401 with the ``WWW-Authenticate`` challenge RFC 6750 expects."""

    def __init__(self, detail: str, *, error: str = "invalid_token") -> None:
        challenge = f'Bearer error="{error}", error_description="{detail}"'
        super().__init__(status_code=401, detail=detail, headers={"WWW-Authenticate": challenge})


@dataclass
class _CachedKeys:
    keyset: jwt.PyJWKSet
    fetched_at: float
    last_forced_refresh: float = 0.0


class JwksCache:
    """Fetches and caches each issuer's JWKS, and picks up key rotation.

    Three behaviors matter and none of them is the default of a naive fetch:

    * **Cached** for ``AUTH_JWKS_TTL_S`` so validation isn't an HTTP round trip.
    * **Refreshed on an unseen ``kid``** (rate-limited) so a rotated signing key
      is honoured without restarting the backend.
    * **Stale-on-error**: if the issuer is briefly unreachable, previously fetched
      keys keep serving. Availability wins here — the keys are still the issuer's,
      only their freshness is in doubt, and failing closed would take the hub down
      for the length of an IdP blip.
    """

    def __init__(self) -> None:
        self._cache: dict[str, _CachedKeys] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        # Resolved ``jwks_uri`` per issuer, for entries configured without one.
        self._discovered: dict[str, str] = {}

    def clear(self) -> None:
        self._cache.clear()
        self._discovered.clear()

    def _lock(self, url: str) -> asyncio.Lock:
        # Single-flight per URL: a burst of concurrent requests behind an expired
        # entry refreshes once rather than once each.
        if url not in self._locks:
            self._locks[url] = asyncio.Lock()
        return self._locks[url]

    async def jwks_url_for(self, entry: TrustedIssuer) -> str:
        """The configured JWKS URL, or the one from the issuer's OIDC discovery."""
        if entry.jwks_url:
            return entry.jwks_url
        if cached := self._discovered.get(entry.issuer):
            return cached
        discovery = f"{entry.issuer}/.well-known/openid-configuration"
        try:
            async with httpx.AsyncClient(timeout=_JWKS_FETCH_TIMEOUT_S) as client:
                resp = await client.get(discovery)
                resp.raise_for_status()
                jwks_uri = resp.json().get("jwks_uri")
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(
                status_code=503,
                detail=f"OIDC discovery failed for issuer {entry.issuer}: {type(exc).__name__}",
            )
        if not isinstance(jwks_uri, str) or not jwks_uri:
            raise HTTPException(
                status_code=503,
                detail=f"OIDC discovery for {entry.issuer} returned no jwks_uri",
            )
        self._discovered[entry.issuer] = jwks_uri
        return jwks_uri

    async def get_key(self, entry: TrustedIssuer, kid: str | None, alg: str) -> jwt.PyJWK:
        """Resolve the signing key for a token header, refreshing on an unseen kid."""
        url = await self.jwks_url_for(entry)
        keyset = await self._keyset(url)
        key = _select_key(keyset, kid, alg)
        if key is None:
            keyset = await self._keyset(url, force=True)
            key = _select_key(keyset, kid, alg)
        if key is None:
            raise AuthError(
                f"no signing key for kid={kid!r} at the issuer's JWKS"
                if kid
                else "no usable signing key at the issuer's JWKS"
            )
        return key

    async def _keyset(self, url: str, *, force: bool = False) -> jwt.PyJWKSet:
        now = time.monotonic()
        cached = self._cache.get(url)
        if cached is not None and not force and now - cached.fetched_at < settings.AUTH_JWKS_TTL_S:
            return cached.keyset
        if (
            cached is not None
            and force
            and now - cached.last_forced_refresh < _ROTATION_REFRESH_COOLDOWN_S
        ):
            return cached.keyset

        async with self._lock(url):
            # Another waiter may have refreshed while this one queued.
            cached = self._cache.get(url)
            now = time.monotonic()
            if (
                cached is not None
                and not force
                and now - cached.fetched_at < settings.AUTH_JWKS_TTL_S
            ):
                return cached.keyset
            if (
                cached is not None
                and force
                and now - cached.last_forced_refresh < _ROTATION_REFRESH_COOLDOWN_S
            ):
                return cached.keyset
            if force and cached is not None:
                cached.last_forced_refresh = now

            try:
                async with httpx.AsyncClient(timeout=_JWKS_FETCH_TIMEOUT_S) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    keyset = jwt.PyJWKSet.from_dict(resp.json())
            except (httpx.HTTPError, ValueError, jwt.PyJWKSetError) as exc:
                if cached is not None:
                    logger.warning(
                        "JWKS refresh failed for %s (%s) — serving cached keys", url, exc
                    )
                    return cached.keyset
                raise HTTPException(
                    status_code=503,
                    detail=f"JWKS unavailable at {url}: {type(exc).__name__}",
                )

            self._cache[url] = _CachedKeys(
                keyset=keyset,
                fetched_at=time.monotonic(),
                last_forced_refresh=now if force else 0.0,
            )
            return keyset


def _select_key(keyset: jwt.PyJWKSet, kid: str | None, alg: str) -> jwt.PyJWK | None:
    """Pick the verification key for a token header, or None if the set has none.

    A ``kid`` selects exactly; without one (legal, and what some issuers emit for
    a single-key setup) any key compatible with the header algorithm is a
    candidate — verification itself then rejects the wrong ones.
    """
    candidates = [k for k in keyset.keys if _is_verification_key(k)]
    if kid is not None:
        return next((k for k in candidates if k.key_id == kid), None)
    compatible = [k for k in candidates if k.algorithm_name in (None, alg)]
    return compatible[0] if len(compatible) == 1 else None


def _is_verification_key(key: jwt.PyJWK) -> bool:
    """Exclude JWKS entries published for encryption rather than signing."""
    return key.public_key_use in (None, "sig")


#: Process-wide, so cached keys survive across requests.
jwks_cache = JwksCache()


def _issuer_entry(iss: object) -> TrustedIssuer | None:
    if not isinstance(iss, str):
        return None
    normalized = iss.rstrip("/")
    return next((e for e in settings.AUTH_ISSUERS if e.issuer == normalized), None)


def _resolve_role(claims: dict[str, Any], entry: TrustedIssuer) -> PrincipalRole:
    """Token role claim, else the issuer's default role.

    Which trust root signed a token is usually the whole answer to user-vs-agent
    (humans from the OIDC issuer, workloads from the service-account issuer), so
    the issuer default carries the common case and the claim is the
    escape hatch for one issuer serving both.
    """
    raw = claims.get(settings.AUTH_ROLE_CLAIM)
    if raw is None:
        return entry.role
    value = str(raw).strip().lower()
    if value not in ("user", "agent"):
        # Coercing an unrecognised role to a default would silently mislabel the
        # principal; a token that asserts something we can't honour is malformed.
        raise AuthError(f"unsupported {settings.AUTH_ROLE_CLAIM!r} claim: {raw!r}")
    return "user" if value == "user" else "agent"


def normalize_handle(raw: object) -> str | None:
    """The canonical handle normalizer, so token and stored handles compare equal."""
    return norm_handle(raw)


async def verify_token(token: str) -> Principal:
    """Validate a bearer token and resolve it to a principal, or raise 401."""
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise AuthError(f"malformed token: {exc}")

    alg = header.get("alg")
    if alg not in ALLOWED_ALGORITHMS:
        raise AuthError(f"unsupported signing algorithm: {alg!r}")

    try:
        unverified = jwt.decode(token, options={"verify_signature": False})
    except jwt.PyJWTError as exc:
        raise AuthError(f"malformed token: {exc}")

    entry = _issuer_entry(unverified.get("iss"))
    if entry is None:
        raise AuthError(f"untrusted issuer: {unverified.get('iss')!r}")

    key = await jwks_cache.get_key(entry, header.get("kid"), alg)

    audience = entry.audience or settings.AUTH_AUDIENCE
    try:
        claims = jwt.decode(
            token,
            key=key,
            algorithms=[alg],
            issuer=entry.issuer,
            audience=audience,
            leeway=settings.AUTH_LEEWAY_S,
            options={
                "verify_aud": audience is not None,
                "require": ["exp", "iss"],
            },
        )
    except jwt.PyJWTError as exc:
        raise AuthError(f"token rejected: {exc}")

    handle = normalize_handle(claims.get(settings.AUTH_HANDLE_CLAIM))
    if handle is None:
        raise AuthError(f"token carries no {settings.AUTH_HANDLE_CLAIM!r} claim")

    return Principal(
        subject=str(claims.get("sub") or handle),
        handle=handle,
        role=_resolve_role(claims, entry),
        issuer=entry.issuer,
        claims=claims,
    )


def is_loopback_client(request: Request) -> bool:
    """Whether the request came from the machine the backend runs on.

    Decided from the peer address only. ``X-Forwarded-For`` is deliberately
    ignored: it is caller-supplied, so honouring it would let any remote request
    claim to be local. Note that this is also why the bypass does *not* fire for
    a backend in Docker — traffic through a published port arrives from the
    bridge gateway and is indistinguishable from LAN traffic, so the containerized
    local tier is served by leaving auth disabled rather than by this bypass.
    """
    client = request.client
    if client is None or not client.host:
        return False
    try:
        addr = ipaddress.ip_address(client.host)
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return addr.is_loopback


def _bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization")
    if not header:
        raise AuthError("missing bearer token", error="invalid_request")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthError("malformed Authorization header", error="invalid_request")
    return token.strip()


async def auth_gate(request: Request) -> Principal | None:
    """App-wide dependency: enforce the gate and record the principal.

    Applied globally rather than per-router so a route added later is protected
    by default. Returns ``None`` — anonymous, today's behavior — when the gate is
    off, the path is public, or a loopback caller is bypassed.
    """
    request.state.principal = None
    if not settings.AUTH_ENABLED:
        return None
    path = request.url.path
    if path in PUBLIC_PATHS or path.rstrip("/") in PUBLIC_PATHS:
        return None
    if path.endswith(A2A_CARD_SUFFIX):
        return None
    if settings.AUTH_LOCALHOST_BYPASS and is_loopback_client(request):
        return None
    if not settings.AUTH_ISSUERS:
        # Enabled with nothing to trust can only fail closed: no token could ever
        # validate, so say why rather than 401-ing every request opaquely.
        raise HTTPException(
            status_code=503,
            detail="auth is enabled but no trusted issuers are configured (auth.issuers)",
        )

    principal = await verify_token(_bearer_token(request))
    request.state.principal = principal
    return principal


def config_warnings() -> list[str]:
    """Ways the gate is on but weaker than an operator probably intends."""
    if not settings.AUTH_ENABLED:
        return []
    warnings: list[str] = []
    if not settings.AUTH_ISSUERS:
        warnings.append("auth is enabled but no trusted issuers are configured")
    # No audience means *any* token the issuer ever minted validates here,
    # including one a user obtained for an unrelated application on the same IdP.
    # That token's holder was never authorized against this hub, so an audience
    # is what makes "valid token" mean "token meant for us".
    if not settings.AUTH_AUDIENCE and not any(e.audience for e in settings.AUTH_ISSUERS):
        warnings.append(
            "no audience configured — any token from a trusted issuer is accepted, "
            "including tokens minted for other applications; set auth.audience"
        )
    return warnings


def status() -> dict[str, Any]:
    """Gate configuration for ``/health`` — what an operator needs to see to know
    whether the hub is actually protected."""
    result: dict[str, Any] = {
        "enabled": settings.AUTH_ENABLED,
        "issuers": [e.issuer for e in settings.AUTH_ISSUERS],
        "localhost_bypass": settings.AUTH_LOCALHOST_BYPASS,
        "audience": settings.AUTH_AUDIENCE,
    }
    if warnings := config_warnings():
        result["warnings"] = warnings
    return result
