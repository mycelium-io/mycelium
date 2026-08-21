# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""SignerJwt-floor SLIM channel identity (issue #476).

The per-agent identity path (topology B in
``docs/design/slim-identity-svid-delivery.md``): each member mints its *own*
credential locally. It generates an ES256 keypair (PKCS#8 PEM), self-signs a
short-lived JWT that embeds its public key, and presents it as
``IdentityProviderConfig.JWT`` (SignerJwt) — the only external-signing provider that
drives MLS (a presented *bearer* token via ``STATIC_JWT`` panics
``MlsNotSupported``, #581).

Peer verification rests on a **static roster JWKS**: each member's verifier
(``JwtKeyType.DECODING`` + ``JwtKeyFormat.JWKS``) holds the public keys of the room's
registered agents, keyed by ``kid = @handle``. A self-signed token is accepted iff its
key is on the roster. That roster **is the registration surface** — the mycelium
analogue of ``mycelium agent credential set``, one JWK per agent, written when the
agent is registered. This module ports the proven spike
``docs/design/signerjwt-floor-spike/`` (PASS on the matched 2.1.0 stack).

**Honest ceiling.** The floor authenticates *possession of a registered key*, not a
machine-attested workload; the handle→key binding is only as trustworthy as the
roster's provenance. It is strictly better than the self-asserted ``name#session``
tier (a key can't be forged; revocation is per-agent — drop the JWK from the roster,
no room-wide rotation), and it is the top of the ladder: attestation against a
workload-identity service is out of scope until there is a real multi-party topology
to attest across (#668, revisit conditions in #669).

**Off by default (#567).** The identity mode is ``psk`` unless
``MYCELIUM_SLIM_IDENTITY=signerjwt`` selects the floor. Selecting it with no
resolvable signing key or roster degrades to the PSK with a one-time warning, unless
``MYCELIUM_SLIM_IDENTITY_REQUIRE=1`` makes it fail closed (mirroring
``MYCELIUM_SLIM_REQUIRE_SECRET``). The try-it path never changes.

The node needs **no configuration** for this: ``IdentityVerifierConfig`` is
app-level (the second arg to ``service.create_app``), how a member verifies its
*peers* inside the MLS group. The stock ``ghcr.io/agntcy/slim:2.1.0`` node forwards
ciphertext and never inspects identity.

The wire constants below (mode names, issuer/audience labels, algorithm/curve, the
``kid = @handle`` convention) are frozen in ``contracts/slim-l9-wire.json`` and
mirrored by ``mycelium-cli/src/mycelium/slim/identity.py`` — the thin CLI can't
import the backend, so a member deriving a different issuer/audience or JWK shape
would silently fail peer verification. Only this docstring differs between the two
copies.
"""

from __future__ import annotations

import base64
import datetime
import json
import logging
import os
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import slim_bindings

logger = logging.getLogger(__name__)

# ── Mode switch (off by default) ─────────────────────────────────────────────
# Mirrors the D1 ``MYCELIUM_SLIM_MASTER_SECRET`` posture: env-only, no config-apply
# coupling, so both the backend and the thin CLI resolve it identically.
_MODE_ENV = "MYCELIUM_SLIM_IDENTITY"
_REQUIRE_ENV = "MYCELIUM_SLIM_IDENTITY_REQUIRE"

MODE_PSK = "psk"
MODE_SIGNERJWT = "signerjwt"
VALID_MODES = (MODE_PSK, MODE_SIGNERJWT)

# ── Self-issued floor labels ─────────────────────────────────────────────────
# A self-issued floor has no OIDC discovery endpoint: issuer/audience are labels
# both sides agree on, and verification rests on the roster JWKS, not the issuer.
# Both members MUST agree on these or peer verification fails — hence frozen in the
# wire contract.
SIGNERJWT_ISSUER = "mycelium-resident"
SIGNERJWT_AUDIENCE = "mycelium-slim"
SIGNERJWT_ALG = "ES256"
SIGNERJWT_CURVE = "P-256"
# Short-lived self-signed tokens; the provider re-signs on expiry from the local key.
TOKEN_DURATION_S = 3600

# ── On-disk layout (under the mycelium data dir) ─────────────────────────────
_DATA_DIR_ENV = "MYCELIUM_DATA_DIR"
# A caller-owned roster file (e.g. a spoke that fetched the hub roster, or a
# hand-provisioned bundle). Passthrough: the roster is read as-is.
_ROSTER_FILE_ENV = "MYCELIUM_SLIM_ROSTER_FILE"

IDENTITY_SUBDIR = "slim-identity"
_KEYS_SUBDIR = "keys"
_ROSTER_SUBDIR = "roster"


class SlimIdentityError(RuntimeError):
    """A SignerJwt-floor identity could not be built (bad key, empty roster, …)."""


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() not in ("", "0", "false", "no")


def resolve_identity_mode() -> str:
    """The SLIM channel identity mode: ``psk`` (default) or ``signerjwt``.

    An unset or unrecognized value is ``psk`` — the off-by-default posture (#567).
    """
    raw = os.getenv(_MODE_ENV, "").strip().lower()
    return raw if raw in VALID_MODES else MODE_PSK


def identity_required() -> bool:
    """True when a selected identity mode must fail closed rather than degrade.

    Mirrors ``MYCELIUM_SLIM_REQUIRE_SECRET``: absent resolvable material (a
    ``signerjwt`` signing key or roster) the default is to
    degrade to the PSK (try-it path unchanged), but a host that has committed to
    identity sets this so a missing credential refuses instead.
    """
    return _truthy(os.getenv(_REQUIRE_ENV))


def resolve_data_dir() -> Path:
    """Root of the mycelium store (``MYCELIUM_DATA_DIR`` or ``~/.mycelium``)."""
    override = os.getenv(_DATA_DIR_ENV, "").strip()
    return Path(override).expanduser() if override else Path.home() / ".mycelium"


def identity_dir(data_dir: Path | None = None) -> Path:
    """Directory holding SignerJwt keys + the roster (``<data>/slim-identity``)."""
    return (data_dir or resolve_data_dir()) / IDENTITY_SUBDIR


def signing_key_path(handle: str, data_dir: Path | None = None) -> Path:
    """Where an agent's private ES256 signing key lives (PKCS#8 PEM, 0600)."""
    return identity_dir(data_dir) / _KEYS_SUBDIR / f"{_safe(handle)}.pk8.pem"


def public_jwk_path(handle: str, data_dir: Path | None = None) -> Path:
    """Where an agent's registered public JWK lives (the roster entry)."""
    return identity_dir(data_dir) / _ROSTER_SUBDIR / f"{_safe(handle)}.jwk.json"


def _safe(handle: str) -> str:
    """A filesystem-safe form of a handle (the ``kid``/``sub`` keep the raw value)."""
    return "".join(c if c.isalnum() or c in "._-" else "-" for c in handle) or "agent"


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _require_cryptography() -> ModuleType:
    try:
        import cryptography.hazmat.primitives.asymmetric.ec as ec_mod
    except ImportError as exc:  # pragma: no cover - dependency always present
        raise SlimIdentityError(
            "cryptography is required for SignerJwt identity but is not installed"
        ) from exc
    return ec_mod


def _require_bindings() -> ModuleType:
    try:
        import slim_bindings
    except ImportError as exc:  # pragma: no cover - platform dependent
        raise SlimIdentityError(
            "slim-bindings is not installed for this platform; SignerJwt identity "
            "needs the native wheel"
        ) from exc
    return slim_bindings


# ── Keypair generation + registration ────────────────────────────────────────
def generate_es256_keypair() -> tuple[str, str]:
    """Generate an ES256 (P-256) keypair as ``(pkcs8_private_pem, public_pem)``.

    PKCS#8 is required: SEC1 (``openssl ecparam -genkey``) → ``InvalidKeyFormat``
    from the SignerJwt provider (#587).
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_pem, public_pem


def public_jwk_from_pem(handle: str, public_pem: str) -> dict[str, str]:
    """Convert an ES256 public-key PEM to a JWK with ``kid = @handle``.

    The ``kid`` lets a verifier do O(1) key lookup and *is* the handle→key binding
    the floor rests on.
    """
    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    ec_mod = _require_cryptography()
    pub = load_pem_public_key(public_pem.encode())
    if not isinstance(pub, ec_mod.EllipticCurvePublicKey):
        raise SlimIdentityError(f"{handle}: expected an EC {SIGNERJWT_CURVE} public key")
    nums = pub.public_numbers()
    return {
        "kty": "EC",
        "crv": SIGNERJWT_CURVE,
        "alg": SIGNERJWT_ALG,
        "use": "sig",
        "kid": handle,
        "x": _b64u(nums.x.to_bytes(32, "big")),
        "y": _b64u(nums.y.to_bytes(32, "big")),
    }


def ensure_agent_keypair(handle: str, data_dir: Path | None = None) -> tuple[Path, dict[str, str]]:
    """Ensure an agent has a signing key + registered public JWK; return both.

    Idempotent: an existing key is reused (never regenerated — that would churn the
    identity), and its public JWK is re-derived so the roster entry always matches
    the key on disk. The private key is written ``0600`` like ``agent_credentials``.
    Returns ``(signing_key_path, public_jwk)``.
    """
    key_path = signing_key_path(handle, data_dir)
    if key_path.exists():
        private_pem = key_path.read_text()
        public_pem = _public_pem_from_private(private_pem)
    else:
        private_pem, public_pem = generate_es256_keypair()
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_text(private_pem)
        key_path.chmod(0o600)
    jwk = public_jwk_from_pem(handle, public_pem)
    register_public_jwk(handle, jwk, data_dir)
    return key_path, jwk


def _public_pem_from_private(private_pem: str) -> str:
    from cryptography.hazmat.primitives import serialization

    key = serialization.load_pem_private_key(private_pem.encode(), password=None)
    return (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )


def register_public_jwk(handle: str, jwk: dict[str, str], data_dir: Path | None = None) -> Path:
    """Add (or refresh) an agent's public JWK on the roster. Returns its path.

    Content-idempotent: an unchanged JWK is not rewritten, so re-registering the
    same key doesn't churn the roster. Revocation is the inverse — delete the file
    (per-agent, no room-wide rotation).
    """
    path = public_jwk_path(handle, data_dir)
    serialized = json.dumps(jwk, sort_keys=True)
    if path.exists() and path.read_text() == serialized:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialized)
    return path


def assemble_roster_jwks(jwks: list[dict[str, str]]) -> str:
    """Serialize member public JWKs into a single ``{"keys": [...]}`` JWKS string."""
    return json.dumps({"keys": jwks})


def load_roster_jwks(data_dir: Path | None = None) -> str | None:
    """Assemble the roster JWKS from every registered public JWK.

    A caller-owned ``MYCELIUM_SLIM_ROSTER_FILE`` (a spoke that fetched the hub
    roster, or a hand-provisioned bundle) takes precedence and is passed through
    untouched. Returns ``None`` when no roster is available — the caller decides
    whether that degrades to PSK or fails closed.
    """
    override = os.getenv(_ROSTER_FILE_ENV, "").strip()
    if override:
        text = Path(override).expanduser().read_text()
        return text or None
    roster_dir = identity_dir(data_dir) / _ROSTER_SUBDIR
    if not roster_dir.is_dir():
        return None
    jwks: list[dict[str, str]] = []
    for entry in sorted(roster_dir.glob("*.jwk.json")):
        jwks.append(json.loads(entry.read_text()))
    if not jwks:
        return None
    return assemble_roster_jwks(jwks)


# ── Provider / verifier construction (ports the spike) ───────────────────────
def build_signerjwt_identity(
    handle: str,
    signing_key_pem: str,
    roster_jwks_json: str,
) -> tuple[slim_bindings.IdentityProviderConfig, slim_bindings.IdentityVerifierConfig]:
    """Build the SignerJwt ``(provider, verifier)`` pair for one resident member.

    Provider: sign our own JWT with the local PKCS#8 ES256 key (``ENCODING``);
    ``subject`` = the ``@handle`` (the SLIM Name leaf).
    Verifier: trust the room roster's public keys — a static multi-key JWKS
    (``DECODING`` + ``JWKS``). **Not ``AUTORESOLVE``**: it falls back to OIDC
    discovery on a non-URL issuer, a dead end for a self-issued floor.
    """
    sb = _require_bindings()
    encoding_key = sb.JwtKeyConfig(
        algorithm=sb.JwtAlgorithm.ES256,
        format=sb.JwtKeyFormat.PEM,
        key=sb.JwtKeyData.DATA(value=signing_key_pem),
    )
    provider = sb.IdentityProviderConfig.JWT(
        config=sb.ClientJwtAuth(
            key=sb.JwtKeyType.ENCODING(key=encoding_key),
            audience=[SIGNERJWT_AUDIENCE],
            issuer=SIGNERJWT_ISSUER,
            subject=handle,
            duration=datetime.timedelta(seconds=TOKEN_DURATION_S),
        )
    )
    decoding_key = sb.JwtKeyConfig(
        algorithm=sb.JwtAlgorithm.ES256,
        format=sb.JwtKeyFormat.JWKS,
        key=sb.JwtKeyData.DATA(value=roster_jwks_json),
    )
    verifier = sb.IdentityVerifierConfig.JWT(
        config=sb.JwtAuth(
            key=sb.JwtKeyType.DECODING(key=decoding_key),
            audience=[SIGNERJWT_AUDIENCE],
            issuer=SIGNERJWT_ISSUER,
            subject=None,
            duration=datetime.timedelta(seconds=TOKEN_DURATION_S),
        )
    )
    return provider, verifier


def resolve_signerjwt_material(
    handle: str, data_dir: Path | None = None
) -> tuple[slim_bindings.IdentityProviderConfig, slim_bindings.IdentityVerifierConfig] | None:
    """Load an agent's signing key + the roster and build its identity pair.

    Returns ``None`` when the material isn't available (no key registered for this
    handle, or an empty roster) so the connect seam can degrade to PSK or fail
    closed per :func:`identity_required`. The signing key must already exist —
    minting it is the registration step (:func:`ensure_agent_keypair`), not a
    side effect of connecting.
    """
    key_path = signing_key_path(handle, data_dir)
    if not key_path.exists():
        return None
    roster = load_roster_jwks(data_dir)
    if roster is None:
        return None
    return build_signerjwt_identity(handle, key_path.read_text(), roster)


# ── Handle ↔ channel-identity reconciliation (the identity spine, #589) ───────
# ``@handle`` is the single logical identity across both planes. On the SLIM plane
# we own the credential, so the handle binds *directly*: the SignerJwt JWK ``kid``
# carries the raw ``@handle``, and a peer reconciles an observed credential back to
# its handle with the inverse below. (On the HTTP
# plane the OIDC ``sub`` is opaque, so handle↔sub is a binding table — the token's
# handle claim plus the actor-authz in ``app.services.actor`` — not this equality.
# We deliberately do not force the OIDC ``sub`` to equal the handle.)
def handle_from_jwk(jwk: dict[str, str]) -> str | None:
    """The ``@handle`` a roster JWK belongs to — its ``kid`` (the direct binding).

    Returns ``None`` for a JWK with no ``kid``: such a key names no handle and so
    can't be reconciled to a member.
    """
    kid = jwk.get("kid")
    return kid or None


def provision_channel_identity(
    handle: str, mode: str | None = None, data_dir: Path | None = None
) -> dict[str, Any]:
    """Provision ``@handle``'s SLIM channel identity for the active mode. Idempotent.

    The registration-time counterpart to the connect-time
    :func:`resolve_identity_material`: ``agent create`` calls this so a handle has a
    usable channel credential the moment it is registered, for whichever mode is
    active. Off-by-default is preserved — under ``psk`` nothing is provisioned.

    * ``psk`` — no per-agent credential exists; a no-op.
    * ``signerjwt`` — mint+register the local ES256 keypair (:func:`ensure_agent_keypair`),
      whose public JWK's ``kid`` is the ``@handle``. Returns the key/roster paths + ``kid``.

    Every result carries ``mode``, ``handle``, and ``provisioned``.
    """
    resolved = mode or resolve_identity_mode()
    if resolved == MODE_SIGNERJWT:
        key_path, jwk = ensure_agent_keypair(handle, data_dir)
        return {
            "mode": MODE_SIGNERJWT,
            "handle": handle,
            "provisioned": True,
            "kid": jwk["kid"],
            "key_path": str(key_path),
            "roster_path": str(public_jwk_path(handle, data_dir)),
        }
    return {"mode": MODE_PSK, "handle": handle, "provisioned": False}


def revoke_channel_identity(
    handle: str, mode: str | None = None, data_dir: Path | None = None
) -> dict[str, Any]:
    """Revoke ``@handle``'s SLIM channel identity for the active mode. Idempotent.

    The deprovisioning-time inverse of :func:`provision_channel_identity`
    (``agent rm`` calls it): it removes the per-agent credential so a removed member
    can no longer authenticate to the room — *without a room-wide re-key*, the
    property the shared-secret PSK never had (#590). Symmetric and idempotent:
    revoking an already-absent member is a no-op, not an error.

    * ``psk`` — there is no per-agent credential to revoke; the only lever is
      rotating ``MYCELIUM_SLIM_MASTER_SECRET`` for the whole room (the blunt
      instrument this tier is stuck with). A no-op here.
    * ``signerjwt`` — drop the member's public JWK from the roster (the inverse of
      :func:`register_public_jwk`) and delete its local signing key. Once its key is
      off the roster, peers' static-JWKS verifiers reject its self-signed tokens, so
      it can't rejoin with the old credential — per-agent, no room-wide rotation.
      Returns the removed paths (empty on a second/idempotent revoke).

    Every result carries ``mode``, ``handle``, and ``revoked``.
    """
    resolved = mode or resolve_identity_mode()
    if resolved == MODE_SIGNERJWT:
        jwk_path = public_jwk_path(handle, data_dir)
        key_path = signing_key_path(handle, data_dir)
        removed: list[str] = []
        for path in (jwk_path, key_path):
            if path.exists():
                path.unlink()
                removed.append(str(path))
        return {
            "mode": MODE_SIGNERJWT,
            "handle": handle,
            "revoked": bool(removed),
            "removed": removed,
            "roster_path": str(jwk_path),
            "key_path": str(key_path),
        }
    return {"mode": MODE_PSK, "handle": handle, "revoked": False}


def resolve_identity_material(
    mode: str,
    handle: str,
    data_dir: Path | None = None,
) -> tuple[slim_bindings.IdentityProviderConfig, slim_bindings.IdentityVerifierConfig] | None:
    """Dispatch to the selected mode's provider/verifier builder.

    Returns ``None`` for ``psk`` (or when the selected mode's material is absent) so
    the one connect seam handles degrade/fail-closed uniformly.
    """
    if mode == MODE_SIGNERJWT:
        return resolve_signerjwt_material(handle, data_dir)
    return None
