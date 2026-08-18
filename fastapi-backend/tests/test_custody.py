# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for the server-side custodial sessions (#666), node-independent half.

The live MLS path (a custodial session as a distinct member, cryptographic wire
attribution, and a within-process ``restore_sessions`` resume) needs a running
SLIM node and lives in ``test_custody_roundtrip.py`` (guarded, skips without one).
These cover the offline surface: the off-by-default gate (#567), the at-rest
passphrase boundary, the per-session store layout, and store enumeration/deletion
for restart + revocation.
"""

import pytest

from app.services import custody, slim_identity
from app.services.slim_client import SlimError


# ── off by default (#567): custody engages only under an identity tier ────────
def test_custody_disabled_under_psk_default(monkeypatch):
    monkeypatch.delenv("MYCELIUM_SLIM_IDENTITY", raising=False)
    monkeypatch.delenv("MYCELIUM_CUSTODY_DISABLE", raising=False)
    assert custody.custody_enabled() is False


def test_custody_enabled_under_signerjwt(monkeypatch):
    monkeypatch.setenv("MYCELIUM_SLIM_IDENTITY", "signerjwt")
    monkeypatch.delenv("MYCELIUM_CUSTODY_DISABLE", raising=False)
    assert custody.custody_enabled() is True


def test_custody_enabled_under_spire(monkeypatch):
    monkeypatch.setenv("MYCELIUM_SLIM_IDENTITY", "spire")
    monkeypatch.delenv("MYCELIUM_CUSTODY_DISABLE", raising=False)
    assert custody.custody_enabled() is True


def test_custody_disable_escape_hatch_overrides_identity(monkeypatch):
    monkeypatch.setenv("MYCELIUM_SLIM_IDENTITY", "signerjwt")
    monkeypatch.setenv("MYCELIUM_CUSTODY_DISABLE", "1")
    assert custody.custody_enabled() is False


# ── at-rest passphrase boundary (Q4) ──────────────────────────────────────────
def test_store_passphrase_is_deterministic(monkeypatch):
    monkeypatch.setenv("MYCELIUM_CUSTODY_STORE_SECRET", "secret-A")
    assert custody.store_passphrase("ws", "room", "alice") == custody.store_passphrase(
        "ws", "room", "alice"
    )


def test_store_passphrase_distinct_per_session(monkeypatch):
    monkeypatch.setenv("MYCELIUM_CUSTODY_STORE_SECRET", "secret-A")
    p_alice = custody.store_passphrase("ws", "room", "alice")
    p_bob = custody.store_passphrase("ws", "room", "bob")
    p_other_room = custody.store_passphrase("ws", "other", "alice")
    # One leaked passphrase must not open the fleet: scope in (workspace, room, handle).
    assert len({p_alice, p_bob, p_other_room}) == 3


def test_store_passphrase_changes_with_secret(monkeypatch):
    monkeypatch.setenv("MYCELIUM_CUSTODY_STORE_SECRET", "secret-A")
    under_a = custody.store_passphrase("ws", "room", "alice")
    monkeypatch.setenv("MYCELIUM_CUSTODY_STORE_SECRET", "secret-B")
    under_b = custody.store_passphrase("ws", "room", "alice")
    assert under_a != under_b
    # HMAC-SHA256 hex digest — comfortably exceeds SLIM's minimum secret length.
    assert len(under_b) == 64


def test_store_secret_prefers_env(monkeypatch):
    monkeypatch.setenv("MYCELIUM_CUSTODY_STORE_SECRET", "a-real-secret")
    assert custody.resolve_store_secret() == "a-real-secret"


def test_store_secret_fails_closed_when_required(monkeypatch):
    monkeypatch.delenv("MYCELIUM_CUSTODY_STORE_SECRET", raising=False)
    monkeypatch.setenv("MYCELIUM_CUSTODY_REQUIRE_SECRET", "1")
    with pytest.raises(SlimError):
        custody.resolve_store_secret()


def test_store_secret_dev_fallback_when_not_required(monkeypatch):
    monkeypatch.delenv("MYCELIUM_CUSTODY_STORE_SECRET", raising=False)
    monkeypatch.delenv("MYCELIUM_CUSTODY_REQUIRE_SECRET", raising=False)
    custody._dev_store_secret_warned = False
    secret = custody.resolve_store_secret()
    assert "do-not-use-in-prod" in secret


# ── per-session store layout + enumeration ────────────────────────────────────
def test_store_dir_is_per_room_per_handle(tmp_path):
    d = custody.store_dir("room", "alice", data_dir=tmp_path)
    assert d == tmp_path / custody._STORE_SUBDIR / "room" / "alice"


def test_store_path_creates_the_directory(tmp_path):
    path = custody.store_path("room", "alice", data_dir=tmp_path)
    assert path.endswith(custody._STORE_DB_NAME)
    # The persistence crate treats the path as a directory it writes a DB into.
    from pathlib import Path

    assert Path(path).is_dir()


def test_iter_persisted_sessions_enumerates_stores(tmp_path):
    custody.store_path("roomA", "alice", data_dir=tmp_path)
    custody.store_path("roomA", "bob", data_dir=tmp_path)
    custody.store_path("roomB", "carol", data_dir=tmp_path)
    found = set(custody.iter_persisted_sessions(data_dir=tmp_path))
    assert found == {("roomA", "alice"), ("roomA", "bob"), ("roomB", "carol")}


def test_iter_persisted_sessions_empty_when_no_root(tmp_path):
    assert list(custody.iter_persisted_sessions(data_dir=tmp_path)) == []


def test_delete_store_removes_the_session_dir(tmp_path):
    custody.store_path("room", "alice", data_dir=tmp_path)
    assert custody.store_dir("room", "alice", data_dir=tmp_path).exists()
    assert custody.delete_store("room", "alice", data_dir=tmp_path) is True
    assert not custody.store_dir("room", "alice", data_dir=tmp_path).exists()
    # Idempotent: deleting an absent store is a no-op that reports nothing removed.
    assert custody.delete_store("room", "alice", data_dir=tmp_path) is False


def test_safe_names_roundtrip_for_valid_handles():
    # Store dir names are the filesystem-safe forms; a handle that is a valid SLIM
    # Name segment (alphanumeric/._-) survives unchanged, so startup restore maps
    # the dir name straight back to the handle.
    for handle in ("alice", "planner-1", "a.b_c"):
        assert slim_identity._safe(handle) == handle
