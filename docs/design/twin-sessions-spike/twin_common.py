# SPDX-License-Identifier: Apache-2.0
"""Shared SLIM/twin helpers for the #662 spike v2 harness.

Factored out of `twin_sessions_spike.py` (v1) so the two-process harness
(`twin_runner.py` + `spike_v2.py`) builds identical twins: same SignerJwt
identity path, same persistence config, same MLS group session config.
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import os
from pathlib import Path

import slim_bindings

ISSUER = os.environ.get("SIGNERJWT_ISSUER", "mycelium-resident")
AUDIENCE = [os.environ.get("SIGNERJWT_AUDIENCE", "mycelium-slim")]
ORG, NS = "mycelium", "default"

# The at-rest passphrase boundary (Q4): HMAC(server session secret, handle) so
# each twin store gets a distinct key. Deliberately NOT the OIDC/SignerJwt token.
_SESSION_SECRET = os.environ.get("MYCELIUM_TWIN_STORE_SECRET", "dev-twin-store-secret-do-not-ship")


def store_passphrase(handle: str) -> str:
    return hmac.new(_SESSION_SECRET.encode(), handle.encode(), hashlib.sha256).hexdigest()


def store_path(store_root: str, handle: str) -> str:
    p = Path(store_root) / handle
    p.mkdir(parents=True, exist_ok=True)
    return str(p / "mls-state.sqlite")


def _read(path: str) -> str:
    with open(path) as fh:
        return fh.read()


def signerjwt_identity(keydir: str, name: str):
    """Per-actor SignerJwt provider + roster-JWKS verifier (mirrors #587)."""
    encoding_key = slim_bindings.JwtKeyConfig(
        algorithm=slim_bindings.JwtAlgorithm.ES256,
        format=slim_bindings.JwtKeyFormat.PEM,
        key=slim_bindings.JwtKeyData.DATA(value=_read(f"{keydir}/{name}.pk8.pem")),  # type: ignore[call-arg]
    )
    provider = slim_bindings.IdentityProviderConfig.JWT(
        config=slim_bindings.ClientJwtAuth(
            key=slim_bindings.JwtKeyType.ENCODING(key=encoding_key),  # type: ignore[call-arg]
            audience=AUDIENCE,
            issuer=ISSUER,
            subject=name,
            duration=datetime.timedelta(seconds=3600),
        )
    )
    decoding_key = slim_bindings.JwtKeyConfig(
        algorithm=slim_bindings.JwtAlgorithm.ES256,
        format=slim_bindings.JwtKeyFormat.JWKS,
        key=slim_bindings.JwtKeyData.DATA(value=_read(f"{keydir}/roster-jwks.json")),  # type: ignore[call-arg]
    )
    verifier = slim_bindings.IdentityVerifierConfig.JWT(
        config=slim_bindings.JwtAuth(
            key=slim_bindings.JwtKeyType.DECODING(key=decoding_key),  # type: ignore[call-arg]
            audience=AUDIENCE,
            issuer=ISSUER,
            subject=None,
            duration=datetime.timedelta(seconds=3600),
        )
    )
    return provider, verifier


def group_session_config():
    return slim_bindings.SessionConfig(
        session_type=slim_bindings.SessionType.GROUP,
        max_retries=5,
        interval=datetime.timedelta(seconds=5),
        metadata={},
        mls_settings=slim_bindings.MlsSettings(
            header_integrity_validation_percent=100,
            max_seen_control_message_ids_size=None,
        ),
    )


def persistence_config(store_root: str, handle: str, *, passphrase: str | None = None):
    """PersistenceConfig for a twin. `passphrase` override lets the wrong-key test
    point a fresh App at an existing store with the WRONG key."""
    return slim_bindings.PersistenceConfig(
        path=store_path(store_root, handle),
        passphrase=passphrase if passphrase is not None else store_passphrase(handle),
    )


async def make_twin_app(svc, conn, keydir, store_root, handle, *, passphrase=None):
    """Create ONE persistence-backed, SignerJwt-identified twin App + subscribe.

    Note (finding C): there is no `create_app_with_secret_and_persistence` in the
    2.1.0 wheel -- persistence REQUIRES the identity provider/verifier pair, so a
    twin cannot run on the default PSK tier. Persistence mandates signerjwt/spire.
    """
    provider, verifier = signerjwt_identity(keydir, handle)
    name = slim_bindings.Name(ORG, NS, handle)
    app = await svc.create_app_with_persistence_async(
        name,
        provider,
        verifier,
        slim_bindings.Direction.BIDIRECTIONAL,
        persistence_config(store_root, handle, passphrase=passphrase),
    )
    await app.subscribe_async(name, conn)
    return app, name


def sender_leaf(ctx) -> str:
    """Best-effort recover the sender's Name leaf from a MessageContext."""
    for attr in ("source_name", "source", "name"):
        val = getattr(ctx, attr, None)
        if val is None:
            continue
        for meth in ("components", "as_tuple"):
            fn = getattr(val, meth, None)
            if callable(fn):
                try:
                    return fn()[-1]
                except Exception:  # noqa: BLE001
                    pass
        return str(val)
    return repr(ctx)
