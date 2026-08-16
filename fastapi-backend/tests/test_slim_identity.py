# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for the SignerJwt-floor SLIM identity (#476), node-independent half.

The live MLS path (two identified members over a real 2.1.0 node) needs the rig
and is out of scope here; these cover everything offline: the mode switch and its
off-by-default posture, key generation + registration, roster assembly, and that
the connect seam degrades/fails-closed correctly when material is absent.
"""

import json
import stat

import pytest

from app.services import slim_identity


# ── mode switch (off by default, #567) ───────────────────────────────────────
def test_mode_defaults_to_psk_when_unset(monkeypatch):
    monkeypatch.delenv("MYCELIUM_SLIM_IDENTITY", raising=False)
    assert slim_identity.resolve_identity_mode() == slim_identity.MODE_PSK


def test_mode_unknown_value_falls_back_to_psk(monkeypatch):
    monkeypatch.setenv("MYCELIUM_SLIM_IDENTITY", "spire-maybe")
    assert slim_identity.resolve_identity_mode() == slim_identity.MODE_PSK


def test_mode_signerjwt_selected(monkeypatch):
    monkeypatch.setenv("MYCELIUM_SLIM_IDENTITY", "SignerJWT")
    assert slim_identity.resolve_identity_mode() == slim_identity.MODE_SIGNERJWT


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, False), ("", False), ("0", False), ("false", False), ("1", True), ("yes", True)],
)
def test_identity_required(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("MYCELIUM_SLIM_IDENTITY_REQUIRE", raising=False)
    else:
        monkeypatch.setenv("MYCELIUM_SLIM_IDENTITY_REQUIRE", value)
    assert slim_identity.identity_required() is expected


# ── keypair generation + JWK ─────────────────────────────────────────────────
def test_generate_es256_keypair_is_pkcs8_and_loadable():
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    private_pem, public_pem = slim_identity.generate_es256_keypair()
    # PKCS#8 header, not SEC1 (`-----BEGIN EC PRIVATE KEY-----`) which the provider
    # rejects with InvalidKeyFormat (#587).
    assert "BEGIN PRIVATE KEY" in private_pem
    assert "BEGIN EC PRIVATE KEY" not in private_pem
    key = load_pem_private_key(private_pem.encode(), password=None)
    assert isinstance(key, ec.EllipticCurvePrivateKey)
    assert "BEGIN PUBLIC KEY" in public_pem


def test_public_jwk_shape():
    _, public_pem = slim_identity.generate_es256_keypair()
    jwk = slim_identity.public_jwk_from_pem("alice", public_pem)
    assert jwk["kty"] == "EC"
    assert jwk["crv"] == "P-256"
    assert jwk["alg"] == "ES256"
    assert jwk["use"] == "sig"
    assert jwk["kid"] == "alice"  # the raw @handle, for O(1) verifier lookup
    # x/y are 32-byte base64url with no padding.
    assert jwk["x"] and "=" not in jwk["x"]
    assert jwk["y"] and "=" not in jwk["y"]


# ── ensure_agent_keypair: idempotent, 0600, registered ───────────────────────
def test_ensure_agent_keypair_creates_key_and_roster(tmp_path):
    key_path, jwk = slim_identity.ensure_agent_keypair("alice", tmp_path)
    assert key_path.exists()
    # Private key is 0600 like agent_credentials.
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600
    assert jwk["kid"] == "alice"
    roster_path = slim_identity.public_jwk_path("alice", tmp_path)
    assert json.loads(roster_path.read_text())["kid"] == "alice"


def test_ensure_agent_keypair_reuses_existing_key(tmp_path):
    key_path, jwk1 = slim_identity.ensure_agent_keypair("alice", tmp_path)
    first = key_path.read_text()
    _, jwk2 = slim_identity.ensure_agent_keypair("alice", tmp_path)
    # Same key on disk (no churn) → same public JWK.
    assert key_path.read_text() == first
    assert jwk1 == jwk2


def test_register_public_jwk_is_content_idempotent(tmp_path):
    _, jwk = slim_identity.ensure_agent_keypair("alice", tmp_path)
    path = slim_identity.public_jwk_path("alice", tmp_path)
    mtime_before = path.stat().st_mtime_ns
    # Re-registering the identical JWK must not rewrite the file.
    slim_identity.register_public_jwk("alice", jwk, tmp_path)
    assert path.stat().st_mtime_ns == mtime_before


# ── roster assembly ──────────────────────────────────────────────────────────
def test_load_roster_jwks_assembles_all_registered(tmp_path):
    slim_identity.ensure_agent_keypair("alice", tmp_path)
    slim_identity.ensure_agent_keypair("bob", tmp_path)
    raw = slim_identity.load_roster_jwks(tmp_path)
    assert raw is not None
    roster = json.loads(raw)
    kids = {k["kid"] for k in roster["keys"]}
    assert kids == {"alice", "bob"}


def test_load_roster_jwks_none_when_empty(tmp_path):
    assert slim_identity.load_roster_jwks(tmp_path) is None


def test_load_roster_jwks_file_override(tmp_path, monkeypatch):
    override = tmp_path / "handed-in.json"
    override.write_text('{"keys": [{"kid": "external"}]}')
    monkeypatch.setenv("MYCELIUM_SLIM_ROSTER_FILE", str(override))
    raw = slim_identity.load_roster_jwks(tmp_path)
    assert raw is not None
    roster = json.loads(raw)
    assert roster["keys"][0]["kid"] == "external"


# ── resolve_signerjwt_material: the connect-seam guard ───────────────────────
def test_material_none_without_key(tmp_path):
    # No key registered for this handle → None (seam degrades to PSK / fails closed).
    assert slim_identity.resolve_signerjwt_material("nobody", tmp_path) is None


def test_material_none_with_key_but_empty_roster(tmp_path, monkeypatch):
    slim_identity.ensure_agent_keypair("alice", tmp_path)
    # Point the roster at an empty file so only alice's key is absent from trust.
    empty = tmp_path / "empty.json"
    empty.write_text("")
    monkeypatch.setenv("MYCELIUM_SLIM_ROSTER_FILE", str(empty))
    assert slim_identity.resolve_signerjwt_material("alice", tmp_path) is None


def test_material_built_when_key_and_roster_present(tmp_path):
    pytest.importorskip("slim_bindings")
    slim_identity.ensure_agent_keypair("alice", tmp_path)
    material = slim_identity.resolve_signerjwt_material("alice", tmp_path)
    assert material is not None
    provider, verifier = material
    # Constructed slim-bindings identity configs (exact types are binding-internal).
    assert provider is not None
    assert verifier is not None
