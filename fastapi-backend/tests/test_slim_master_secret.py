# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Debt D1 (minimal hardening): the MLS master secret is env-configurable.

The built-in literal is a public dev default; a deployment overrides it via
``MYCELIUM_SLIM_MASTER_SECRET`` (the same value on every host that shares rooms),
and ``MYCELIUM_SLIM_REQUIRE_SECRET`` makes a host fail closed rather than derive
channel keys anyone could reproduce.
"""

import hashlib
import hmac

import pytest

from app.services import slim_client
from app.services.slim_client import SlimIdentity, mint_shared_secret, resolve_master_secret

_ID = SlimIdentity(workspace="acme", room="sprint", agent="alice")


def _expected(secret: str) -> str:
    return hmac.new(secret.encode(), b"acme/sprint", hashlib.sha256).hexdigest()


def test_defaults_to_dev_secret_when_unset(monkeypatch):
    monkeypatch.delenv("MYCELIUM_SLIM_MASTER_SECRET", raising=False)
    monkeypatch.delenv("MYCELIUM_SLIM_REQUIRE_SECRET", raising=False)
    assert resolve_master_secret() == slim_client._DEV_MASTER_SECRET
    # Behaviour unchanged from before the env override: the dev digest stands.
    assert mint_shared_secret(_ID) == _expected(slim_client._DEV_MASTER_SECRET)


def test_env_override_changes_the_secret(monkeypatch):
    monkeypatch.setenv("MYCELIUM_SLIM_MASTER_SECRET", "a-real-private-secret")
    assert resolve_master_secret() == "a-real-private-secret"
    minted = mint_shared_secret(_ID)
    assert minted == _expected("a-real-private-secret")
    assert minted != _expected(slim_client._DEV_MASTER_SECRET)


def test_require_secret_refuses_dev_default(monkeypatch):
    monkeypatch.delenv("MYCELIUM_SLIM_MASTER_SECRET", raising=False)
    monkeypatch.setenv("MYCELIUM_SLIM_REQUIRE_SECRET", "1")
    with pytest.raises(slim_client.SlimError, match="refusing"):
        resolve_master_secret()


def test_require_secret_satisfied_by_real_secret(monkeypatch):
    monkeypatch.setenv("MYCELIUM_SLIM_MASTER_SECRET", "prod-secret")
    monkeypatch.setenv("MYCELIUM_SLIM_REQUIRE_SECRET", "1")
    assert resolve_master_secret() == "prod-secret"


def test_explicit_master_secret_still_honoured(monkeypatch):
    """An explicit argument bypasses env resolution (used by the golden test)."""
    monkeypatch.setenv("MYCELIUM_SLIM_MASTER_SECRET", "ignored")
    assert mint_shared_secret(_ID, master_secret="explicit") == _expected("explicit")
