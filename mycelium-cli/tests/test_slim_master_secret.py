# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The CLI's MLS master secret is env-configurable and byte-for-byte compatible
with the backend so cross-host channel keys match.
"""

import hashlib
import hmac

import pytest

from mycelium.slim import naming
from mycelium.slim.naming import SlimIdentity, mint_shared_secret, resolve_master_secret

_ID = SlimIdentity(workspace="acme", room="sprint", agent="alice")


def _expected(secret: str) -> str:
    return hmac.new(secret.encode(), b"acme/sprint", hashlib.sha256).hexdigest()


def test_defaults_to_dev_secret_when_unset(monkeypatch):
    monkeypatch.delenv("MYCELIUM_SLIM_MASTER_SECRET", raising=False)
    monkeypatch.delenv("MYCELIUM_SLIM_REQUIRE_SECRET", raising=False)
    assert resolve_master_secret() == naming._DEV_MASTER_SECRET
    assert mint_shared_secret(_ID) == _expected(naming._DEV_MASTER_SECRET)


def test_env_override_changes_the_secret(monkeypatch):
    monkeypatch.setenv("MYCELIUM_SLIM_MASTER_SECRET", "a-real-private-secret")
    assert mint_shared_secret(_ID) == _expected("a-real-private-secret")


def test_require_secret_refuses_dev_default(monkeypatch):
    monkeypatch.delenv("MYCELIUM_SLIM_MASTER_SECRET", raising=False)
    monkeypatch.setenv("MYCELIUM_SLIM_REQUIRE_SECRET", "1")
    with pytest.raises(RuntimeError, match="refusing"):
        resolve_master_secret()


def test_env_var_names_match_backend_contract():
    """The env var the CLI reads must match the backend's, or cross-host secrets
    silently diverge. Frozen here as the cross-package contract."""
    assert naming._MASTER_SECRET_ENV == "MYCELIUM_SLIM_MASTER_SECRET"
    assert naming._REQUIRE_SECRET_ENV == "MYCELIUM_SLIM_REQUIRE_SECRET"
