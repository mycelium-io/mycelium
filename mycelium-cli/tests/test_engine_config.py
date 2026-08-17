# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Tests for the engine runtime config field."""

from __future__ import annotations

import pytest
import toml

from mycelium.config import EngineConfig, MyceliumConfig


def test_default_runtime_is_backend() -> None:
    assert MyceliumConfig().engine.runtime == "backend"


@pytest.mark.parametrize(("given", "expected"), [("BACKEND", "backend"), (" backend ", "backend")])
def test_runtime_normalized(given: str, expected: str) -> None:
    # given is a dynamic str exercising the normalizer; the field is the EngineRuntime Literal.
    assert EngineConfig(runtime=given).runtime == expected  # ty: ignore[invalid-argument-type]


def test_legacy_host_coerces_to_backend() -> None:
    """The retired ``host`` runtime (rode the removed daemon) coerces to backend
    so a pre-existing config.toml keeps loading."""
    assert EngineConfig(runtime="host").runtime == "backend"  # ty: ignore[invalid-argument-type]


def test_invalid_runtime_rejected() -> None:
    with pytest.raises(ValueError, match="Input should be 'backend'"):
        EngineConfig(runtime="cloud")  # ty: ignore[invalid-argument-type]


def test_env_override_legacy_host_coerces(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENGINE_RUNTIME", "host")
    assert MyceliumConfig.load().engine.runtime == "backend"


def test_save_roundtrips_engine_even_with_project_config(tmp_path) -> None:
    """Regression: ``save()`` used to filter to a hardcoded allowlist of sections
    when a project config exists — ``engine`` had to be remembered on that list,
    or ``config set engine.*`` was silently dropped. See
    ``test_save_preserves_every_global_section`` for the generic version of this
    check that doesn't require remembering a new section per bug (#648)."""
    global_path = tmp_path / "global.toml"
    project_path = tmp_path / "project.toml"
    project_path.write_text("[identity]\n", encoding="utf-8")

    cfg = MyceliumConfig.load(config_path=global_path)
    cfg._global_config_path = global_path
    cfg._project_config_path = project_path
    cfg.engine.runtime = "backend"
    cfg.save()

    assert MyceliumConfig.load(config_path=global_path).engine.runtime == "backend"


def test_save_preserves_every_global_section(tmp_path) -> None:
    """Regression for #648, generalized: ``save()`` used to filter to a
    hardcoded *allowlist* of sections whenever a project-local config.toml
    existed alongside the global one, so a top-level section someone forgot to
    add to that list (``auth``, ``agent_auth``) was silently dropped —
    ``config set`` reported success while the value never reached disk.

    Rather than adding one more section-specific test the next time this
    happens, assert the mechanism directly: every ``MyceliumConfig`` section
    except the ones deliberately project-scoped must survive a save when a
    project config is present. This is derived from the model's own fields, so
    a new top-level section added later is covered automatically — no one has
    to remember to extend an allowlist (or write a matching test) again."""
    global_path = tmp_path / "global.toml"
    project_path = tmp_path / "project.toml"
    project_path.write_text("[identity]\n", encoding="utf-8")

    cfg = MyceliumConfig.load(config_path=global_path)
    cfg._global_config_path = global_path
    cfg._project_config_path = project_path
    cfg.save()

    saved_sections = set(toml.load(global_path).keys())
    project_only_sections = {"rooms"}
    expected_sections = set(MyceliumConfig.model_fields) - project_only_sections
    missing = expected_sections - saved_sections
    assert not missing, (
        f"sections dropped from global config.toml despite a project config: {missing}"
    )
