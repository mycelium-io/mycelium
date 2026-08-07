# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Tests for the engine runtime config field (the Stage-B transition switch)."""

from __future__ import annotations

import pytest

from mycelium.config import EngineConfig, MyceliumConfig


def test_default_runtime_is_backend() -> None:
    assert MyceliumConfig().engine.runtime == "backend"


@pytest.mark.parametrize(("given", "expected"), [("host", "host"), ("BACKEND", "backend")])
def test_runtime_normalized(given: str, expected: str) -> None:
    assert EngineConfig(runtime=given).runtime == expected


def test_invalid_runtime_rejected() -> None:
    with pytest.raises(ValueError, match="engine.runtime"):
        EngineConfig(runtime="cloud")


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENGINE_RUNTIME", "host")
    assert MyceliumConfig.load().engine.runtime == "host"


def test_save_roundtrips_engine_even_with_project_config(tmp_path) -> None:
    """Regression: ``save()`` filters to an allowlist of sections when a project
    config exists — ``engine`` must be in it, or ``config set engine.runtime`` is
    silently dropped (the Stage-B switch would never take effect)."""
    global_path = tmp_path / "global.toml"
    project_path = tmp_path / "project.toml"
    project_path.write_text("[identity]\n", encoding="utf-8")

    cfg = MyceliumConfig.load(config_path=global_path)
    cfg._global_config_path = global_path
    cfg._project_config_path = project_path
    cfg.engine.runtime = "host"
    cfg.save()

    assert MyceliumConfig.load(config_path=global_path).engine.runtime == "host"
