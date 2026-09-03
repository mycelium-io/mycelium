# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""HTTP-API JWT gate.

Tokens are signed with RSA keys generated in-process and served through a
stubbed JWKS endpoint, so the whole gate — signature, claims, issuer matching,
caching, rotation — is exercised without a live issuer.

The default posture is its own assertion: with ``AUTH_ENABLED`` off, every
request must behave exactly as it did before this gate existed.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import AsyncClient

from app.config import TrustedIssuer
from app.services import auth as auth_service

ISSUER = "https://idp.test/realms/mycelium"
JWKS_URL = f"{ISSUER}/jwks"
AUDIENCE = "mycelium"

# A protected route (any /api route is gated) and a public one.
PROTECTED_PATH = "/api/rooms"
PUBLIC_PATH = "/health"


# ── key + token helpers ───────────────────────────────────────────────────────


def _generate_key(kid: str) -> dict[str, Any]:
    """An RSA keypair plus its public JWK, as an issuer would publish it."""
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    algo = jwt.get_algorithm_by_name("RS256")
    public_jwk = algo.to_jwk(private.public_key(), as_dict=True)
    public_jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
    return {"private": private, "jwk": public_jwk, "kid": kid}


def _sign(key: dict[str, Any], **overrides: Any) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "sub": "poc-agent",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + 3600,
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key["private"], algorithm="RS256", headers={"kid": key["kid"]})


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def signing_key() -> dict[str, Any]:
    return _generate_key("key-1")


@pytest.fixture
def jwks_server(monkeypatch, signing_key):
    """Serve a JWKS from an in-process stub with a swappable ``keys`` list, for
    simulating key rotation at the issuer.
    """

    class _Server:
        def __init__(self) -> None:
            self.keys: list[dict[str, Any]] = [signing_key["jwk"]]
            self.fetches = 0
            self.fail = False

        def document(self) -> dict[str, Any]:
            return {"keys": self.keys}

    server = _Server()

    class _StubResponse:
        def __init__(self, payload: dict[str, Any]) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return self._payload

    class _StubClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self) -> _StubClient:
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

        async def get(self, url: str) -> _StubResponse:
            if url.endswith("/.well-known/openid-configuration"):
                return _StubResponse({"jwks_uri": JWKS_URL})
            server.fetches += 1
            if server.fail:
                import httpx

                raise httpx.ConnectError("issuer unreachable")
            return _StubResponse(server.document())

    monkeypatch.setattr(auth_service.httpx, "AsyncClient", _StubClient)
    return server


@pytest.fixture
def auth_on(monkeypatch, jwks_server):
    """Gate enabled, one trusted issuer, loopback bypass off.

    The bypass is off because the ASGI test transport presents a loopback client
    address — with it on, every request here would be waved through and the
    assertions would be vacuous. It gets its own test below.
    """
    monkeypatch.setattr("app.config.settings.AUTH_ENABLED", True)
    monkeypatch.setattr("app.config.settings.AUTH_LOCALHOST_BYPASS", False)
    monkeypatch.setattr("app.config.settings.AUTH_AUDIENCE", AUDIENCE)
    monkeypatch.setattr(
        "app.config.settings.AUTH_ISSUERS",
        [TrustedIssuer(issuer=ISSUER, jwks_url=JWKS_URL, role="agent")],
    )
    auth_service.jwks_cache.clear()
    yield
    auth_service.jwks_cache.clear()


# ── off by default: the try-it path is untouched ──────────────────────────────


@pytest.mark.asyncio
async def test_disabled_by_default_needs_no_token(client: AsyncClient):
    assert (await client.get(PROTECTED_PATH)).status_code == 200


@pytest.mark.asyncio
async def test_disabled_ignores_a_garbage_token(client: AsyncClient):
    """Off means off — a bad token isn't even inspected, let alone rejected."""
    resp = await client.get(PROTECTED_PATH, headers=_bearer("not-a-jwt"))
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_disabled_leaves_principal_unset(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["auth"]["enabled"] is False


# ── enabled: valid tokens pass ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_valid_token_is_accepted(client: AsyncClient, auth_on, signing_key):
    resp = await client.get(PROTECTED_PATH, headers=_bearer(_sign(signing_key)))
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_valid_token_resolves_a_principal(auth_on, signing_key):
    principal = await auth_service.verify_token(_sign(signing_key, sub="@Poc-Agent"))
    # Normalized the way stored handles are, so the two compare equal.
    assert principal.handle == "poc-agent"
    assert principal.role == "agent"
    assert principal.issuer == ISSUER


@pytest.mark.asyncio
async def test_role_claim_overrides_the_issuer_default(auth_on, signing_key):
    principal = await auth_service.verify_token(_sign(signing_key, mycelium_role="user"))
    assert principal.role == "user"


@pytest.mark.asyncio
async def test_unsupported_role_claim_is_rejected(auth_on, signing_key):
    """An unsupported role claim is rejected with 401."""
    with pytest.raises(auth_service.AuthError):
        await auth_service.verify_token(_sign(signing_key, mycelium_role="superuser"))


@pytest.mark.asyncio
async def test_configured_handle_claim_is_honored(monkeypatch, auth_on, signing_key):
    monkeypatch.setattr("app.config.settings.AUTH_HANDLE_CLAIM", "preferred_username")
    principal = await auth_service.verify_token(_sign(signing_key, preferred_username="avery"))
    assert principal.handle == "avery"


# ── enabled: everything else is 401 ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_token_is_401(client: AsyncClient, auth_on):
    resp = await client.get(PROTECTED_PATH)
    assert resp.status_code == 401
    assert resp.headers["WWW-Authenticate"].startswith("Bearer ")


@pytest.mark.asyncio
async def test_non_bearer_scheme_is_401(client: AsyncClient, auth_on):
    resp = await client.get(PROTECTED_PATH, headers={"Authorization": "Basic abc"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_forged_token_is_401(client: AsyncClient, auth_on):
    """Signed by a key the issuer never published."""
    forged = _generate_key("key-1")  # same kid, different key material
    resp = await client.get(PROTECTED_PATH, headers=_bearer(_sign(forged)))
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_expired_token_is_401(client: AsyncClient, auth_on, signing_key):
    now = int(time.time())
    token = _sign(signing_key, iat=now - 7200, exp=now - 3600)
    assert (await client.get(PROTECTED_PATH, headers=_bearer(token))).status_code == 401


@pytest.mark.asyncio
async def test_wrong_audience_is_401(client: AsyncClient, auth_on, signing_key):
    token = _sign(signing_key, aud="some-other-app")
    assert (await client.get(PROTECTED_PATH, headers=_bearer(token))).status_code == 401


@pytest.mark.asyncio
async def test_wrong_issuer_is_401(client: AsyncClient, auth_on, signing_key):
    token = _sign(signing_key, iss="https://evil.test/realms/mycelium")
    assert (await client.get(PROTECTED_PATH, headers=_bearer(token))).status_code == 401


@pytest.mark.asyncio
async def test_token_without_exp_is_401(client: AsyncClient, auth_on, signing_key):
    """A token that never expires is not a credential we accept."""
    token = _sign(signing_key, exp=None)
    assert (await client.get(PROTECTED_PATH, headers=_bearer(token))).status_code == 401


@pytest.mark.asyncio
async def test_token_without_handle_claim_is_401(client: AsyncClient, auth_on, signing_key):
    token = _sign(signing_key, sub=None)
    assert (await client.get(PROTECTED_PATH, headers=_bearer(token))).status_code == 401


@pytest.mark.asyncio
async def test_hmac_algorithm_confusion_is_refused(client: AsyncClient, auth_on, signing_key):
    """The published RSA public key must never be usable as an HMAC secret.

    Hand-rolled rather than built with ``jwt.encode``, which refuses to sign this
    shape at all — the point is to present the attacker's wire format to the gate
    and confirm it is turned away on the algorithm, before any key is consulted.
    """
    now = int(time.time())
    public_pem = (
        signing_key["private"]
        .public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )

    def _segment(payload: dict[str, Any]) -> bytes:
        return base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=")

    signing_input = b".".join(
        [
            _segment({"alg": "HS256", "typ": "JWT", "kid": signing_key["kid"]}),
            _segment(
                {"sub": "poc-agent", "iss": ISSUER, "aud": AUDIENCE, "iat": now, "exp": now + 3600}
            ),
        ]
    )
    signature = base64.urlsafe_b64encode(
        hmac.new(public_pem, signing_input, hashlib.sha256).digest()
    ).rstrip(b"=")
    forged = b".".join([signing_input, signature]).decode()

    assert (await client.get(PROTECTED_PATH, headers=_bearer(forged))).status_code == 401


@pytest.mark.asyncio
async def test_unsigned_token_is_refused(client: AsyncClient, auth_on):
    token = jwt.encode({"sub": "poc-agent", "iss": ISSUER}, key="", algorithm="none")
    assert (await client.get(PROTECTED_PATH, headers=_bearer(token))).status_code == 401


# ── public paths + localhost bypass ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_stays_public_when_enabled(client: AsyncClient, auth_on):
    """Health endpoint stays public even when auth is enabled."""
    resp = await client.get(PUBLIC_PATH)
    assert resp.status_code == 200
    assert resp.json()["auth"]["enabled"] is True


@pytest.mark.asyncio
async def test_localhost_bypass_lets_a_loopback_caller_through(
    monkeypatch, client: AsyncClient, auth_on
):
    """The ASGI transport presents 127.0.0.1, which is what the bypass keys off."""
    monkeypatch.setattr("app.config.settings.AUTH_LOCALHOST_BYPASS", True)
    assert (await client.get(PROTECTED_PATH)).status_code == 200


def test_bypass_ignores_forwarded_for_headers():
    """A caller-supplied header must never be able to claim locality."""
    from starlette.requests import Request

    def _request(client: tuple[str, int] | None, headers: list[tuple[bytes, bytes]]) -> Request:
        return Request(
            {
                "type": "http",
                "http_version": "1.1",
                "method": "GET",
                "path": "/api/rooms",
                "headers": headers,
                "client": client,
            }
        )

    spoofed = [(b"x-forwarded-for", b"127.0.0.1")]
    assert auth_service.is_loopback_client(_request(("10.1.2.3", 5000), spoofed)) is False
    assert auth_service.is_loopback_client(_request(("127.0.0.1", 5000), [])) is True
    assert auth_service.is_loopback_client(_request(("::1", 5000), [])) is True
    # IPv4-mapped IPv6, which a dual-stack listener reports.
    assert auth_service.is_loopback_client(_request(("::ffff:127.0.0.1", 5000), [])) is True
    assert auth_service.is_loopback_client(_request(None, [])) is False


# ── JWKS caching + rotation ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_jwks_is_fetched_once_and_cached(auth_on, signing_key, jwks_server):
    for _ in range(3):
        await auth_service.verify_token(_sign(signing_key))
    assert jwks_server.fetches == 1


@pytest.mark.asyncio
async def test_rotated_key_is_picked_up_without_restart(auth_on, signing_key, jwks_server):
    """A token signed by a key minted after the cache was filled still validates:
    an unseen kid forces a re-fetch."""
    await auth_service.verify_token(_sign(signing_key))
    assert jwks_server.fetches == 1

    rotated = _generate_key("key-2")
    jwks_server.keys = [signing_key["jwk"], rotated["jwk"]]

    principal = await auth_service.verify_token(_sign(rotated))
    assert principal.handle == "poc-agent"
    assert jwks_server.fetches == 2


@pytest.mark.asyncio
async def test_unknown_kid_still_401s_after_refresh(auth_on, jwks_server):
    """Refreshing on an unseen kid must not become a way in."""
    stranger = _generate_key("key-unknown")
    with pytest.raises(auth_service.AuthError):
        await auth_service.verify_token(_sign(stranger))


@pytest.mark.asyncio
async def test_stale_keys_serve_through_an_issuer_outage(
    monkeypatch, auth_on, signing_key, jwks_server
):
    """Cached keys serve through an issuer outage."""
    await auth_service.verify_token(_sign(signing_key))

    # Expire the cache so the next call must re-fetch, then break the issuer.
    monkeypatch.setattr("app.config.settings.AUTH_JWKS_TTL_S", 0.0)
    jwks_server.fail = True

    principal = await auth_service.verify_token(_sign(signing_key))
    assert principal.handle == "poc-agent"


@pytest.mark.asyncio
async def test_jwks_url_resolved_from_discovery_when_unset(monkeypatch, auth_on, signing_key):
    """An issuer entry with no jwks_url falls back to OIDC discovery."""
    monkeypatch.setattr(
        "app.config.settings.AUTH_ISSUERS",
        [TrustedIssuer(issuer=ISSUER, role="agent")],
    )
    auth_service.jwks_cache.clear()
    principal = await auth_service.verify_token(_sign(signing_key))
    assert principal.handle == "poc-agent"


# ── multiple trust roots ──────────────────────────────────────────────────────


HUMAN_ISSUER = "https://sso.test/realms/people"


@pytest.fixture
def two_issuers(monkeypatch, auth_on, signing_key):
    """The shape a real deployment lands on: a human OIDC issuer alongside an
    agent/service-account one, each with its own keys.

    Returns the human issuer's key; ``signing_key`` remains the agent one.
    """
    human_key = _generate_key("human-1")

    class _StubResponse:
        def __init__(self, payload: dict[str, Any]) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return self._payload

    class _StubClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self) -> _StubClient:
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

        async def get(self, url: str) -> _StubResponse:
            keys = [human_key["jwk"]] if url.startswith(HUMAN_ISSUER) else [signing_key["jwk"]]
            return _StubResponse({"keys": keys})

    monkeypatch.setattr(auth_service.httpx, "AsyncClient", _StubClient)
    monkeypatch.setattr(
        "app.config.settings.AUTH_ISSUERS",
        [
            TrustedIssuer(issuer=ISSUER, jwks_url=JWKS_URL, role="agent"),
            TrustedIssuer(issuer=HUMAN_ISSUER, jwks_url=f"{HUMAN_ISSUER}/jwks", role="user"),
        ],
    )
    auth_service.jwks_cache.clear()
    return human_key


@pytest.mark.asyncio
async def test_each_issuer_carries_its_own_keys_and_role(two_issuers, signing_key):
    """Same gate, two trust roots, role falling out of which root signed."""
    agent = await auth_service.verify_token(_sign(signing_key))
    assert agent.role == "agent"

    human = await auth_service.verify_token(_sign(two_issuers, iss=HUMAN_ISSUER, sub="avery"))
    assert (human.role, human.handle) == ("user", "avery")


@pytest.mark.asyncio
async def test_one_issuers_key_cannot_vouch_for_another(two_issuers, signing_key):
    """Trusting two roots must not make them interchangeable — a token signed by
    the agent root but claiming the human root is checked against the *human*
    root's keys, and fails."""
    token = _sign(signing_key, iss=HUMAN_ISSUER)
    with pytest.raises(auth_service.AuthError):
        await auth_service.verify_token(token)


# ── misconfiguration ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_enabled_with_no_issuers_fails_closed(monkeypatch, client: AsyncClient, auth_on):
    monkeypatch.setattr("app.config.settings.AUTH_ISSUERS", [])
    resp = await client.get(PROTECTED_PATH)
    assert resp.status_code == 503
    assert "issuer" in resp.json()["detail"]


def test_missing_audience_is_warned_about(monkeypatch, auth_on):
    """Without an audience, any token the issuer ever minted validates here —
    the operator should be told, not left to discover it."""
    monkeypatch.setattr("app.config.settings.AUTH_AUDIENCE", None)
    warnings = auth_service.config_warnings()
    assert any("audience" in w for w in warnings)


def test_no_warnings_when_disabled(monkeypatch):
    monkeypatch.setattr("app.config.settings.AUTH_ENABLED", False)
    assert auth_service.config_warnings() == []


# ── the gate feeds handle binding ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_real_token_becomes_the_author_of_a_write(
    client: AsyncClient, auth_on, signing_key
):
    """End-to-end: signature → principal → stored ``created_by``.

    The binding matrix lives in ``test_handle_binding``; this is the one pass
    that proves the two stages are actually wired to each other, signature and
    all, rather than each working against a stand-in for the other.
    """
    token = _sign(signing_key, sub="poc-agent")
    await client.post("/api/rooms", json={"name": "gated"}, headers=_bearer(token))

    resp = await client.post(
        "/api/rooms/gated/memory",
        json={"items": [{"key": "n", "value": "v", "created_by": "someone-else", "embed": False}]},
        headers=_bearer(token),
    )
    assert resp.status_code == 403

    resp = await client.post(
        "/api/rooms/gated/memory",
        json={"items": [{"key": "n", "value": "v", "created_by": "poc-agent", "embed": False}]},
        headers=_bearer(token),
    )
    assert resp.status_code == 201
    assert resp.json()[0]["created_by"] == "poc-agent"


# ── A2A inbound: card is public discovery, RPC is gated (#717) ─────────────────


@pytest.mark.asyncio
async def test_a2a_agent_card_is_public_when_gate_on(client: AsyncClient, auth_on):
    """The Agent Card is discovery metadata, exempt from the auth gate: a
    missing room returns 404 (the route ran), not 401 (the gate blocked it).
    """
    resp = await client.get("/api/rooms/ghost/.well-known/agent-card.json")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_a2a_rpc_endpoint_is_gated_when_gate_on(client: AsyncClient, auth_on):
    """The room's JSON-RPC endpoint is not exempt — no token means 401."""
    rpc = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "message/send",
        "params": {"message": {"kind": "message", "messageId": "x", "role": "user", "parts": []}},
    }
    resp = await client.post("/api/rooms/ghost/a2a", json=rpc)
    assert resp.status_code == 401


# ── /api/whoami: the one source of truth a client defaults its author to ───────


@pytest.mark.asyncio
async def test_whoami_ungated_reports_no_principal(client: AsyncClient):
    """Gate off: a caller names itself, so there is no principal to report."""
    resp = await client.get("/api/whoami")
    assert resp.status_code == 200
    body = resp.json()
    assert body["gated"] is False
    assert body["handle"] is None


@pytest.mark.asyncio
async def test_whoami_gated_returns_the_token_principal(client: AsyncClient, auth_on, signing_key):
    """The handle here is exactly what the gate enforces created_by against —
    derived from the same claim, and normalized the same way — so a client that
    defaults its write author to it never trips the mismatch."""
    resp = await client.get("/api/whoami", headers=_bearer(_sign(signing_key, sub="@Julia")))
    assert resp.status_code == 200
    body = resp.json()
    assert body["gated"] is True
    assert body["handle"] == "julia"


@pytest.mark.asyncio
async def test_whoami_gated_without_token_is_401(client: AsyncClient, auth_on):
    """Gated and unauthenticated: the gate 401s before the handler, which a
    client reads as "can't tell who I am" and falls back to local identity."""
    resp = await client.get("/api/whoami")
    assert resp.status_code == 401
