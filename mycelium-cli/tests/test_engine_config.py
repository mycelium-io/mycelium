# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Tests for the engine runtime config field."""

from __future__ import annotations

import pytest

from mycelium.config import EngineConfig, MyceliumConfig


def test_default_runtime_is_backend() -> None:
    assert MyceliumConfig().engine.runtime == "backend"


@pytest.mark.parametrize(("given", "expected"), [("BACKEND", "backend"), (" backend ", "backend")])
def test_runtime_normalized(given: str, expected: str) -> None:
    # given is a dynamic str exercising the normalizer; the field is the EngineRuntime Literal.
    assert EngineConfig(runtime=given).runtime == expected  # ty: ignore[invalid-argument-type]


def test_legacy_host_coerces_to_backend() -> None:
    """The ``host`` runtime coerces to backend for backward compatibility."""
    assert EngineConfig(runtime="host").runtime == "backend"  # ty: ignore[invalid-argument-type]


def test_invalid_runtime_rejected() -> None:
    with pytest.raises(ValueError, match="Input should be 'backend'"):
        EngineConfig(runtime="cloud")  # ty: ignore[invalid-argument-type]


def test_env_override_legacy_host_coerces(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENGINE_RUNTIME", "host")
    assert MyceliumConfig.load().engine.runtime == "backend"


def test_save_roundtrips_engine_even_with_project_config(tmp_path) -> None:
    """Regression: ``save()`` filters to an allowlist of sections when a project
    config exists — ``engine`` must be in it, or ``config set engine.*`` is
    silently dropped."""
    global_path = tmp_path / "global.toml"
    project_path = tmp_path / "project.toml"
    project_path.write_text("[identity]\n", encoding="utf-8")

    cfg = MyceliumConfig.load(config_path=global_path)
    cfg._global_config_path = global_path
    cfg._project_config_path = project_path
    cfg.engine.runtime = "backend"
    cfg.save()

    assert MyceliumConfig.load(config_path=global_path).engine.runtime == "backend"


def test_save_roundtrips_auth_even_with_project_config(tmp_path) -> None:
    """Regression: ``auth`` (and ``agent_auth``) were missing from the section
    allowlist, so ``mycelium config set auth.handle_claim ...`` reported success
    but the value never reached the global config.toml when a project-local
    config existed alongside it (e.g. running from inside a cloned repo)."""
    global_path = tmp_path / "global.toml"
    project_path = tmp_path / "project.toml"
    project_path.write_text("[identity]\n", encoding="utf-8")

    cfg = MyceliumConfig.load(config_path=global_path)
    cfg._global_config_path = global_path
    cfg._project_config_path = project_path
    cfg.auth.handle_claim = "preferred_username"
    cfg.agent_auth.issuer = "https://issuer.example.com"
    cfg.save()

    reloaded = MyceliumConfig.load(config_path=global_path)
    assert reloaded.auth.handle_claim == "preferred_username"
    assert reloaded.agent_auth.issuer == "https://issuer.example.com"
