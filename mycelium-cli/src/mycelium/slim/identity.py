# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""SignerJwt-floor SLIM channel identity (daemon side, issue #476).

A **byte-for-byte mirror** of ``fastapi-backend/app/services/slim_identity.py`` —
only this docstring differs. The thin ``uv tool`` CLI can't import the backend, so
a resident member (the CLI side of a room channel) reproduces the SignerJwt-floor
primitives here: generate a local ES256 keypair, self-sign a JWT that embeds its
public key, present it as ``IdentityProviderConfig.JWT`` (SignerJwt), and verify its
peers against the room roster JWKS (``DECODING`` + ``JWKS``).

Keep the wire constants (mode names, issuer/audience labels, algorithm/curve, the
``kid = @handle`` convention) identical to the backend copy — they are frozen in
``contracts/slim-l9-wire.json`` and asserted by both ``test_slim_l9_wire.py``
copies. A member deriving a different issuer/audience or JWK shape silently fails
peer verification against the moderator, exactly the failure the contract test
guards. ``psk`` stays the default (#567); ``MYCELIUM_SLIM_IDENTITY=signerjwt`` opts
in, and a missing key/roster degrades to the PSK unless
``MYCELIUM_SLIM_IDENTITY_REQUIRE=1`` fails closed.

See the backend module's docstring for the full design and the honest ceiling
(possession of a registered key, not attestation; SPIRE #579 is the upgrade).
"""

from __future__ import annotations

import base64
import datetime
import json
import logging
import os
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING

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
# hand-provisioned bundle). Passthrough — the same shape the SPIRE seam (#579)
# will reuse for a caller-owned JWT-SVID source.
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
    """True when a selected ``signerjwt`` mode must fail closed rather than degrade.

    Mirrors ``MYCELIUM_SLIM_REQUIRE_SECRET``: absent a resolvable key/roster the
    default is to degrade to the PSK (try-it path unchanged), but a host that has
    committed to identity sets this so a missing credential refuses instead.
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
