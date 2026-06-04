"""Unit tests for :mod:`jobs._common`.

These cover the new helpers added in Stage 4 of the three-axis matrix
refactor:

* :func:`get_testbed_file` — env / bare-filename / absolute-path
  resolution
* :func:`ensure_tier_env` — idempotent ``MYCELIUM_E2E_TIERS`` defaulting

The existing helpers (``get_datafile``, ``get_max_failures``,
``_read_datafile_param``) already had implicit coverage via the legacy
job files, so we only spot-check the new surfaces.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from jobs import _common as common

_TRACKED_ENV = ("MYCELIUM_TESTBED_FILE", "MYCELIUM_E2E_TIERS")


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Strip the env vars this module touches so tests start from a
    deterministic baseline regardless of the developer's shell or CI.

    ``ensure_tier_env`` mutates ``os.environ`` directly (not via
    monkeypatch), so we add explicit post-yield cleanup to keep leaks
    from contaminating sibling test modules (e.g. ``test_scenarios.py``
    has ``active_tiers(None)`` cases that read the live env)."""
    for key in _TRACKED_ENV:
        monkeypatch.delenv(key, raising=False)
    yield
    for key in _TRACKED_ENV:
        os.environ.pop(key, None)


# ── get_testbed_file ──────────────────────────────────────────────────


class TestGetTestbedFile:
    def test_returns_none_when_no_env_no_default(self, clean_env: None) -> None:
        assert common.get_testbed_file() is None

    def test_uses_default_when_env_unset(self, clean_env: None) -> None:
        result = common.get_testbed_file(default="testbeds/compose.yaml")
        assert result is not None
        assert result.endswith("/testbeds/compose.yaml")
        assert os.path.isabs(result)

    def test_env_overrides_default(
        self,
        clean_env: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("MYCELIUM_TESTBED_FILE", "testbeds/lab.yaml")
        result = common.get_testbed_file(default="testbeds/compose.yaml")
        assert result is not None
        assert result.endswith("/testbeds/lab.yaml")

    def test_bare_filename_resolves_against_testbeds_dir(
        self,
        clean_env: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("MYCELIUM_TESTBED_FILE", "compose.yaml")
        result = common.get_testbed_file()
        assert result is not None
        # bare filename should be normalised to testbeds/compose.yaml
        assert result.endswith("/testbeds/compose.yaml")

    def test_absolute_path_passes_through(
        self,
        clean_env: None,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ) -> None:
        target = tmp_path / "custom.yaml"
        target.write_text("testbed: {name: custom}\n")
        monkeypatch.setenv("MYCELIUM_TESTBED_FILE", str(target))
        assert common.get_testbed_file() == str(target)

    def test_relative_path_with_separator_preserved(
        self,
        clean_env: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # A path that already contains testbeds/ shouldn't be doubled.
        monkeypatch.setenv("MYCELIUM_TESTBED_FILE", "testbeds/lab.yaml")
        result = common.get_testbed_file()
        assert result is not None
        assert result.count("/testbeds/") == 1
        assert result.endswith("/testbeds/lab.yaml")

    def test_custom_env_var_name(
        self,
        clean_env: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("CUSTOM_TESTBED", "testbeds/compose.yaml")
        result = common.get_testbed_file(env_var="CUSTOM_TESTBED")
        assert result is not None
        assert result.endswith("/testbeds/compose.yaml")


# ── ensure_tier_env ───────────────────────────────────────────────────


class TestEnsureTierEnv:
    def test_sets_default_when_unset(self, clean_env: None) -> None:
        result = common.ensure_tier_env("pr")
        assert result == "pr"
        assert os.environ["MYCELIUM_E2E_TIERS"] == "pr"

    def test_preserves_existing_value(
        self,
        clean_env: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("MYCELIUM_E2E_TIERS", "weekly")
        result = common.ensure_tier_env("pr")
        assert result == "weekly"
        assert os.environ["MYCELIUM_E2E_TIERS"] == "weekly"

    def test_empty_existing_value_treated_as_unset(
        self,
        clean_env: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The implementation treats an empty string as "unset" (falsy
        # check on os.environ.get(...)); pin this contract so callers
        # can rely on `MYCELIUM_E2E_TIERS=""` not silently disabling
        # all tests.
        monkeypatch.setenv("MYCELIUM_E2E_TIERS", "")
        result = common.ensure_tier_env("pr,nightly")
        assert result == "pr,nightly"
        assert os.environ["MYCELIUM_E2E_TIERS"] == "pr,nightly"

    def test_default_default_is_all(self, clean_env: None) -> None:
        result = common.ensure_tier_env()
        assert result == "all"
        assert os.environ["MYCELIUM_E2E_TIERS"] == "all"
