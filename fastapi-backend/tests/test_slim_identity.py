# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for the SLIM channel-identity seam (slim_identity.py).

Node-free: these cover what is decided *before* a socket exists — which tier is
selected, which token is presented, where it lands on disk, and the shapes handed
to slim-bindings. Whether a node with a JWT verifier actually admits the
resulting member is the live-node slice (``test_slim_roundtrip.py``).

The behaviour these lock down hardest is the **default**: an install that
configures nothing must go on deriving the shared secret exactly as it did
before per-member identity existed.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path
from types import ModuleType

import pytest

from app.services import slim_identity
from app.services.slim_client import SlimIdentity
from app.services.slim_identity import (
    IDENTITY_MODE_JWT,
    IDENTITY_MODE_PSK,
    SlimIdentityError,
    build_configs,
    build_provider,
    build_verifier,
    materialize_token,
    resolve_jwt_identity,
    resolve_mode,
    token_file_path,
)

_ENV_VARS = (
    slim_identity.IDENTITY_ENV,
    slim_identity.TOKEN_ENV,
    slim_identity.TOKEN_FILE_ENV,
    slim_identity.ISSUER_ENV,
    slim_identity.AUDIENCE_ENV,
    slim_identity.JWKS_ENV,
    slim_identity.JWKS_FILE_ENV,
    slim_identity.ALGORITHM_ENV,
    slim_identity.DURATION_ENV,
    slim_identity.REQUIRE_ENV,
)

IDENTITY = SlimIdentity("acme", "planning", "agent-7")


@pytest.fixture(autouse=True)
def _clean_identity_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Start every test from an unconfigured host with its own data dir."""
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    slim_identity._warned.clear()


def _bindings():
    return pytest.importorskip("slim_bindings")


# ── Tier selection ──────────────────────────────────────────────────────────


def test_default_tier_is_the_shared_secret() -> None:
    assert resolve_mode() == IDENTITY_MODE_PSK


def test_tier_is_selected_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(slim_identity.IDENTITY_ENV, "JWT")
    assert resolve_mode() == IDENTITY_MODE_JWT


def test_an_unknown_tier_is_refused_rather_than_read_as_psk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(slim_identity.IDENTITY_ENV, "spire")
    with pytest.raises(SlimIdentityError, match="not a SLIM identity mode"):
        resolve_mode()


def test_psk_tier_builds_no_identity_configs() -> None:
    """The shipped default never reaches slim-bindings' identity API at all.

    The bindings stand-in is empty on purpose: touching it would raise.
    """
    assert build_configs(ModuleType("not-slim-bindings"), IDENTITY, token="a-token") is None


# ── Token resolution ────────────────────────────────────────────────────────


def test_a_caller_supplied_token_wins_over_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One process joining as several agents presents each agent's own token."""
    monkeypatch.setenv(slim_identity.TOKEN_ENV, "ambient")
    assert resolve_jwt_identity(token="mine").token == "mine"


def test_the_environment_supplies_the_token_when_the_caller_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(slim_identity.TOKEN_ENV, "ambient")
    assert resolve_jwt_identity().token == "ambient"


def test_settings_are_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(slim_identity.ISSUER_ENV, "https://idp/realm")
    monkeypatch.setenv(slim_identity.AUDIENCE_ENV, "mycelium")
    monkeypatch.setenv(slim_identity.ALGORITHM_ENV, "es256")
    monkeypatch.setenv(slim_identity.DURATION_ENV, "120")

    jwt = resolve_jwt_identity()
    assert jwt.issuer == "https://idp/realm"
    assert jwt.audience == "mycelium"
    assert jwt.algorithm == "ES256"
    assert jwt.duration_s == 120.0


@pytest.mark.parametrize("bad", ["soon", "0", "-1"])
def test_an_unusable_duration_is_refused(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    monkeypatch.setenv(slim_identity.DURATION_ENV, bad)
    with pytest.raises(SlimIdentityError, match=slim_identity.DURATION_ENV):
        resolve_jwt_identity()


# ── The token file slim-bindings reads ──────────────────────────────────────


def test_the_token_file_is_owner_only(tmp_path: Path) -> None:
    path = materialize_token("agent-7", "a.b.c")
    assert path == token_file_path("agent-7")
    assert path.is_relative_to(tmp_path)
    assert path.read_text(encoding="utf-8") == "a.b.c"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_an_unchanged_token_is_not_rewritten() -> None:
    """slim-bindings reloads the file when it changes; identical is not a change."""
    path = materialize_token("agent-7", "a.b.c")
    before = path.stat().st_mtime_ns
    assert materialize_token("agent-7", "a.b.c").stat().st_mtime_ns == before


def test_a_refreshed_token_replaces_the_old_one() -> None:
    materialize_token("agent-7", "old")
    path = materialize_token("agent-7", "new")
    assert path.read_text(encoding="utf-8") == "new"


def test_each_agent_gets_its_own_token_file() -> None:
    assert token_file_path("alpha") != token_file_path("beta")


def test_a_handle_cannot_escape_the_token_directory() -> None:
    path = token_file_path("../../etc/passwd")
    assert path.parent == token_file_path("x").parent


# ── The configs handed to slim-bindings ─────────────────────────────────────


def test_the_provider_presents_the_materialized_token() -> None:
    sb = _bindings()
    jwt = resolve_jwt_identity(token="a.b.c")
    provider = build_provider(sb, jwt, agent="agent-7")

    assert provider.is_static_jwt()
    assert Path(token_file_path("agent-7")).read_text(encoding="utf-8") == "a.b.c"


def test_a_caller_owned_token_file_is_passed_through_untouched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A SPIRE sidecar (or CI) owns the file's lifetime; nothing here rewrites it."""
    svid = tmp_path / "svid.jwt"
    svid.write_text("from.the.sidecar", encoding="utf-8")
    monkeypatch.setenv(slim_identity.TOKEN_FILE_ENV, str(svid))

    build_provider(_bindings(), resolve_jwt_identity(), agent="agent-7")
    assert not token_file_path("agent-7").exists()


def test_the_provider_refuses_to_present_nothing() -> None:
    with pytest.raises(SlimIdentityError, match="needs a token"):
        build_provider(_bindings(), resolve_jwt_identity(), agent="agent-7")


def test_the_verifier_pins_a_configured_jwks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(slim_identity.JWKS_ENV, json.dumps({"keys": []}))
    monkeypatch.setenv(slim_identity.ISSUER_ENV, "https://idp/realm")
    verifier = build_verifier(_bindings(), resolve_jwt_identity())
    assert verifier.is_jwt()


def test_the_verifier_resolves_keys_from_the_issuer_when_no_jwks_is_pinned() -> None:
    verifier = build_verifier(_bindings(), resolve_jwt_identity())
    assert verifier.is_jwt()


def test_an_unknown_algorithm_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(slim_identity.ALGORITHM_ENV, "RS999")
    monkeypatch.setenv(slim_identity.JWKS_ENV, json.dumps({"keys": []}))
    with pytest.raises(SlimIdentityError, match="not a JWT algorithm"):
        build_verifier(_bindings(), resolve_jwt_identity())


def test_jwt_tier_with_a_token_builds_every_half(monkeypatch: pytest.MonkeyPatch) -> None:
    """One token, three places it is presented: peers, peers' checks, the node."""
    monkeypatch.setenv(slim_identity.IDENTITY_ENV, IDENTITY_MODE_JWT)
    built = build_configs(_bindings(), IDENTITY, token="a.b.c")
    assert built is not None
    assert built.provider.is_static_jwt()
    assert built.verifier.is_jwt()
    assert built.connection_auth.is_static_jwt()


# ── Degradation ─────────────────────────────────────────────────────────────


def test_jwt_tier_without_a_token_falls_back_to_the_psk(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """No credential is today's behaviour, so it stays joinable — but says so."""
    monkeypatch.setenv(slim_identity.IDENTITY_ENV, IDENTITY_MODE_JWT)
    with caplog.at_level("WARNING"):
        assert build_configs(_bindings(), IDENTITY, token=None) is None
    assert "no token to present" in caplog.text


def test_the_fallback_can_be_made_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    """A host that means to run on verified identity fails closed instead."""
    monkeypatch.setenv(slim_identity.IDENTITY_ENV, IDENTITY_MODE_JWT)
    monkeypatch.setenv(slim_identity.REQUIRE_ENV, "1")
    with pytest.raises(SlimIdentityError, match="refusing to fall back"):
        build_configs(_bindings(), IDENTITY, token=None)
