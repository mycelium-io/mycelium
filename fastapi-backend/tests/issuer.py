# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A test identity provider: keys made in-process, a stubbed JWKS, real signed tokens.

The gate's own tests (``test_auth_gate``) and the tests that sign people in
to a hub (``signed_in_hub`` in ``conftest``) use these, so a token goes through
the real gate, signature and all, with only the JWKS fetch stubbed.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.config import TrustedIssuer
from app.services import auth as auth_service
from app.services import member_tokens

ISSUER = "https://idp.test/realms/mycelium"
JWKS_URL = f"{ISSUER}/jwks"
AUDIENCE = "mycelium"
#: The claim a signed-in hub reads the handle from, as a Keycloak-style
#: provider sets it: ``sub`` is an opaque id there, not a name.
HANDLE_CLAIM = "preferred_username"


def generate_key(kid: str) -> dict[str, Any]:
    """An RSA keypair plus its public JWK, as an issuer would publish it."""
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    algo = jwt.get_algorithm_by_name("RS256")
    public_jwk = algo.to_jwk(private.public_key(), as_dict=True)
    public_jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
    return {"private": private, "jwk": public_jwk, "kid": kid}


def sign(key: dict[str, Any], **overrides: Any) -> str:
    """A token from :data:`ISSUER` signed with ``key``; a claim set to ``None`` is left out."""
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


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@dataclass
class JwksStub:
    """The issuer's JWKS endpoint, in-process.

    ``keys`` is what it serves, swappable to simulate rotation; ``by_prefix``
    serves other keys for a URL under another issuer; ``fail`` makes it
    unreachable.
    """

    keys: list[dict[str, Any]]
    by_prefix: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    fetches: int = 0
    fail: bool = False

    def serve(self, url: str) -> dict[str, Any]:
        if url.endswith("/.well-known/openid-configuration"):
            return {"jwks_uri": JWKS_URL}
        self.fetches += 1
        if self.fail:
            raise httpx.ConnectError("issuer unreachable")
        prefix = next((p for p in self.by_prefix if url.startswith(p)), None)
        return {"keys": self.by_prefix[prefix] if prefix else self.keys}


def stub_jwks(monkeypatch: pytest.MonkeyPatch, keys: list[dict[str, Any]]) -> JwksStub:
    """Answer the gate's JWKS and discovery fetches from a :class:`JwksStub`."""
    server = JwksStub(keys=list(keys))

    class _Response:
        def __init__(self, payload: dict[str, Any]) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return self._payload

    class _Client:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            pass

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        async def get(self, url: str) -> _Response:
            return _Response(server.serve(url))

    monkeypatch.setattr(auth_service.httpx, "AsyncClient", _Client)
    return server


@dataclass
class SignedInHub:
    """A hub with sign-in on, trusting one test issuer whose tokens name people.

    :meth:`token` signs a person's token the way a real provider does: the
    handle under :data:`HANDLE_CLAIM`, an opaque ``sub``.
    """

    key: dict[str, Any]
    jwks: JwksStub
    #: Each handle's opaque subject, made once, so it stays that person's.
    subjects: dict[str, str] = field(default_factory=dict)

    def subject(self, handle: str) -> str:
        return self.subjects.setdefault(handle, str(uuid.uuid4()))

    def token(
        self, handle: str, *, sub: str | None = None, exp: int | None = None, **claims: Any
    ) -> str:
        now = int(time.time())
        return sign(
            self.key,
            sub=sub or self.subject(handle),
            exp=exp if exp is not None else now + 3600,
            **{HANDLE_CLAIM: handle, **claims},
        )

    def headers(self, handle: str, **kwargs: Any) -> dict[str, str]:
        return bearer(self.token(handle, **kwargs))


def sign_in_hub(monkeypatch: pytest.MonkeyPatch) -> SignedInHub:
    """Turn the gate on as a shared hub runs it: no loopback bypass (the test
    transport is loopback, so with it every request would pass), an audience,
    the test issuer for people, and the handle read from ``preferred_username``.
    """
    key = generate_key("people-1")
    jwks = stub_jwks(monkeypatch, [key["jwk"]])
    monkeypatch.setattr("app.config.settings.AUTH_ENABLED", True)
    monkeypatch.setattr("app.config.settings.AUTH_LOCALHOST_BYPASS", False)
    monkeypatch.setattr("app.config.settings.AUTH_AUDIENCE", AUDIENCE)
    monkeypatch.setattr("app.config.settings.AUTH_HANDLE_CLAIM", HANDLE_CLAIM)
    monkeypatch.setattr(
        "app.config.settings.AUTH_ISSUERS",
        [TrustedIssuer(issuer=ISSUER, jwks_url=JWKS_URL, role="user")],
    )
    auth_service.jwks_cache.clear()
    member_tokens.reset_for_tests()
    return SignedInHub(key=key, jwks=jwks)


def sign_out_hub() -> None:
    auth_service.jwks_cache.clear()
    member_tokens.reset_for_tests()
