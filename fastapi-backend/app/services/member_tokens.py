# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Tokens the hub signs itself, for an agent that joined a room with a code.

A hub with its auth gate on checks tokens from outside identity providers, and
until now issued none. An agent started somewhere the hub doesn't control has
no browser to log in with and no identity
provider client of its own, so when it redeems a join code (``services/joins``)
the hub hands it a token it signed: ES256, the handle as ``sub``, the agent
role, a month long. Joining again renews it.

The hub trusts its own issuer beside the configured ones, and checks its own
tokens against the key it holds, with nothing fetched (``auth.verify_token``).
The key is made on first use and kept in the data dir, readable only by its
owner, so tokens survive a restart and a new hub does not accept an old hub's.
"""

from __future__ import annotations

import time
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

#: The ``iss`` of every token the hub signs. Fixed, not a URL: nothing fetches it.
ISSUER = "mycelium-hub"
ALGORITHM = "ES256"
#: How long a member token lasts. Joining again renews it.
TOKEN_TTL_S = 30 * 24 * 3600
_KEY_FILE = "member-signing-key.pem"

_key: ec.EllipticCurvePrivateKey | None = None


def _key_path() -> Path:
    from app.services.filesystem import get_data_dir

    return get_data_dir() / "auth" / _KEY_FILE


def signing_key() -> ec.EllipticCurvePrivateKey:
    """The hub's signing key, made and saved the first time it is needed."""
    global _key
    if _key is not None:
        return _key
    path = _key_path()
    if path.exists():
        loaded = serialization.load_pem_private_key(path.read_bytes(), password=None)
        if not isinstance(loaded, ec.EllipticCurvePrivateKey):
            msg = f"{path} does not hold an EC private key"
            raise TypeError(msg)
        _key = loaded
        return _key
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(mode=0o600)
    path.write_bytes(pem)
    _key = key
    return _key


def verification_key() -> ec.EllipticCurvePublicKey:
    return signing_key().public_key()


def mint(handle: str, room: str, *, now: float | None = None) -> tuple[str, float]:
    """A token for ``handle`` and when it expires (epoch seconds)."""
    from app.config import settings

    issued = time.time() if now is None else now
    expires = issued + TOKEN_TTL_S
    claims = {
        "iss": ISSUER,
        "sub": handle,
        "iat": int(issued),
        "exp": int(expires),
        settings.AUTH_ROLE_CLAIM: "agent",
        "mycelium_room": room,
    }
    # The handle claim the gate reads may be configured to something other than
    # ``sub``; the hub's own tokens carry the handle under that name too.
    if settings.AUTH_HANDLE_CLAIM != "sub":
        claims[settings.AUTH_HANDLE_CLAIM] = handle
    audience = settings.AUTH_AUDIENCE
    if audience:
        claims["aud"] = audience
    return jwt.encode(claims, signing_key(), algorithm=ALGORITHM), expires


def reset_for_tests() -> None:
    global _key
    _key = None
