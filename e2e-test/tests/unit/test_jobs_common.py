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

import logging
import os
from collections.abc import Iterator
from types import SimpleNamespace

import pytest

from jobs import _common as common

_TRACKED_ENV = (
    "MYCELIUM_TESTBED_FILE",
    "MYCELIUM_E2E_TIERS",
    "MYCELIUM_E2E_GROUPS",
    "MYCELIUM_E2E_RUNTIME",
    "GITHUB_ACTIONS",
)


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


# ── runtime / testbed contract ────────────────────────────────────────


class TestRuntimeForTestbed:
    def test_compose_path(self) -> None:
        assert common.runtime_for_testbed("testbeds/compose.yaml") == "local"
        assert common.runtime_for_testbed("/abs/testbeds/compose.yaml") == "local"

    def test_lab_path(self) -> None:
        assert common.runtime_for_testbed("testbeds/lab.yaml") == "lab"

    def test_unknown_path(self) -> None:
        assert common.runtime_for_testbed("testbeds/custom.yaml") == "unknown"


class TestRuntimeForTestbedObject:
    def test_compose_name(self) -> None:
        from pyats import topology

        tb = topology.loader.load(common.get_testbed_file(default=common.TESTBED_COMPOSE))
        assert common.runtime_for_testbed_object(tb) == "local"

    def test_lab_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from pyats import topology

        monkeypatch.setenv("OCLW4_IP", "127.0.0.1")
        tb = topology.loader.load(common.get_testbed_file(default=common.TESTBED_LAB))
        assert common.runtime_for_testbed_object(tb) == "lab"


class TestActiveE2ERuntime:
    def test_explicit_env_wins(self, clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MYCELIUM_E2E_RUNTIME", "lab")
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        assert common.active_e2e_runtime(common.RUNTIME_COMPOSE) == "lab"

    def test_github_actions_when_env_unset(
        self,
        clean_env: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        assert common.active_e2e_runtime(common.RUNTIME_LAB) == "local"

    def test_job_default_when_nothing_set(self, clean_env: None) -> None:
        assert common.active_e2e_runtime(common.RUNTIME_LAB) == "lab"

    def test_invalid_runtime_raises(self, clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MYCELIUM_E2E_RUNTIME", "kubernetes")
        with pytest.raises(common.InvalidE2ERuntimeError):
            common.active_e2e_runtime(common.RUNTIME_COMPOSE)


class TestResolveJobTestbed:
    def test_loads_compose_from_job_default_when_runtime_has_no_testbed(
        self,
        clean_env: None,
    ) -> None:
        runtime = SimpleNamespace(testbed=None)
        tb, active, source = common.resolve_job_testbed(runtime, common.RUNTIME_COMPOSE)
        assert tb is not None
        assert tb.name == common.TESTBED_NAME_COMPOSE
        assert active == common.RUNTIME_COMPOSE
        assert source == "job_default"

    def test_loads_lab_when_runtime_env_set(
        self,
        clean_env: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("MYCELIUM_E2E_RUNTIME", "lab")
        monkeypatch.setenv("OCLW4_IP", "127.0.0.1")
        runtime = SimpleNamespace(testbed=None)
        tb, active, source = common.resolve_job_testbed(runtime, common.RUNTIME_COMPOSE)
        assert tb.name == common.TESTBED_NAME_LAB
        assert active == common.RUNTIME_LAB
        assert source == common.RUNTIME_ENV_VAR

    def test_prefers_runtime_testbed_from_cli(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from pyats import topology

        monkeypatch.setenv("OCLW4_IP", "127.0.0.1")
        lab = topology.loader.load(common.get_testbed_file(default=common.TESTBED_LAB))
        runtime = SimpleNamespace(testbed=lab)
        tb, active, source = common.resolve_job_testbed(runtime, common.RUNTIME_COMPOSE)
        assert tb is lab
        assert active == common.RUNTIME_LAB
        assert source == "cli"


class TestPrepareJobTestbed:
    def test_hermes_rejects_compose_runtime(
        self,
        clean_env: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("MYCELIUM_E2E_RUNTIME", "compose")
        with pytest.raises(common.JobRuntimeMismatchError):
            common.prepare_job_testbed(
                SimpleNamespace(testbed=None),
                logging.getLogger("test"),
                job_default_runtime=common.RUNTIME_LAB,
                allowed_runtimes=common.RUNTIME_LAB_ONLY,
            )


class TestValidateJobRuntime:
    def test_strict_raises_on_mismatch(self) -> None:
        from pyats import topology

        compose = topology.loader.load(common.get_testbed_file(default=common.TESTBED_COMPOSE))
        with pytest.raises(common.JobRuntimeMismatchError):
            common.validate_job_runtime(
                logging.getLogger("test"),
                expected_runtime=common.RUNTIME_LAB,
                testbed=compose,
                strict=True,
            )


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


# ── groups_logic_from_env ─────────────────────────────────────────────


class TestGroupsLogicFromEnv:
    def test_unset_returns_none(self, clean_env: None) -> None:
        assert common.groups_filter_from_env() is None

    def test_single_group(self, clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
        from pyats.datastructures.logic import Or

        monkeypatch.setenv("MYCELIUM_E2E_GROUPS", "openclaw")
        result = common.groups_filter_from_env()
        assert isinstance(result, Or)
        assert str(result) == "Or('openclaw')"

    def test_multiple_groups(self, clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
        from pyats.datastructures.logic import Or

        monkeypatch.setenv("MYCELIUM_E2E_GROUPS", "openclaw, cross_family")
        result = common.groups_filter_from_env()
        assert isinstance(result, Or)
        assert str(result) == "Or('openclaw', 'cross_family')"
