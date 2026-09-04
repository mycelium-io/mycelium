# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The one identity seam: :func:`mycelium.identity.resolve_actor`.

Every write's author and every sender handle resolve through this, so its
precedence (override -> env -> hub principal -> local iam -> fallback) is the
contract the whole CLI leans on.
"""

import pytest

from mycelium import identity
from mycelium.config import MyceliumConfig


@pytest.fixture
def config() -> MyceliumConfig:
    cfg = MyceliumConfig()
    cfg.server.api_url = "http://hub.example:8000"
    cfg.identity.name = None
    return cfg


@pytest.fixture(autouse=True)
def _clear(monkeypatch: pytest.MonkeyPatch):
    # A fresh whoami cache and no ambient agent handle per test.
    identity._WHOAMI_CACHE.clear()
    monkeypatch.delenv("MYCELIUM_AGENT_HANDLE", raising=False)
    # No session file, so get_current_handle is driven only by identity.name.
    monkeypatch.setattr(identity, "load_session", lambda: None)


def _whoami(monkeypatch: pytest.MonkeyPatch, value: dict | None) -> None:
    monkeypatch.setattr(identity, "_hub_whoami", lambda _cfg: value)


def test_override_wins_over_everything(config, monkeypatch):
    _whoami(monkeypatch, {"gated": True, "handle": "principal@x"})
    monkeypatch.setenv("MYCELIUM_AGENT_HANDLE", "env-agent")
    assert identity.resolve_actor(config, override="design-agent") == "design-agent"


def test_legacy_sentinel_override_is_treated_as_unset(config, monkeypatch):
    _whoami(monkeypatch, {"gated": True, "handle": "principal@x"})
    # A legacy override value resolves to the real caller, not itself.
    assert identity.resolve_actor(config, override="cli-user") == "principal@x"


def test_env_handle_beats_hub_and_local(config, monkeypatch):
    _whoami(monkeypatch, {"gated": True, "handle": "principal@x"})
    config.identity.name = "local-name"
    monkeypatch.setenv("MYCELIUM_AGENT_HANDLE", "env-agent")
    assert identity.resolve_actor(config) == "env-agent"


def test_hub_principal_is_the_default_on_a_gated_hub(config, monkeypatch):
    # The value a gated hub enforces created_by against, so a write just works.
    _whoami(monkeypatch, {"gated": True, "handle": "juliarvalenti@gmail.com"})
    config.identity.name = "some-local"
    assert identity.resolve_actor(config) == "juliarvalenti@gmail.com"


def test_local_identity_when_ungated(config, monkeypatch):
    _whoami(monkeypatch, {"gated": False, "handle": None})
    config.identity.name = "local-name"
    assert identity.resolve_actor(config) == "local-name"


def test_sentinel_fallback_keeps_zero_config_local_working(config, monkeypatch):
    # Ungated hub, no identity anywhere: the write still lands (author defaults).
    _whoami(monkeypatch, {"gated": False, "handle": None})
    assert identity.resolve_actor(config) == identity.LEGACY_ACTOR_SENTINEL


def test_gated_and_unauthenticated_raises_when_required(config, monkeypatch):
    import typer

    # 401 -> gated with no principal: stamping a placeholder would just 403, so
    # guide the caller instead of failing obscurely later.
    _whoami(monkeypatch, {"gated": True, "handle": None})
    with pytest.raises(typer.BadParameter):
        identity.resolve_actor(config)


def test_gated_unauthenticated_falls_back_when_not_required(config, monkeypatch):
    _whoami(monkeypatch, {"gated": True, "handle": None})
    assert identity.resolve_actor(config, require=False) == identity.LEGACY_ACTOR_SENTINEL


def test_unreachable_hub_does_not_block_a_local_identity(config, monkeypatch):
    _whoami(monkeypatch, None)  # couldn't reach the hub
    config.identity.name = "local-name"
    assert identity.resolve_actor(config) == "local-name"


def test_get_current_identity_delegates_with_unknown_fallback(config, monkeypatch):
    _whoami(monkeypatch, {"gated": False, "handle": None})
    # No identity anywhere -> the sender fallback, not the author sentinel.
    assert config.get_current_identity() == "unknown"


def test_get_current_identity_uses_hub_principal(config, monkeypatch):
    _whoami(monkeypatch, {"gated": True, "handle": "principal@x"})
    assert config.get_current_identity() == "principal@x"
