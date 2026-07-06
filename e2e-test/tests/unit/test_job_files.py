"""Collection smoke + dry-run for the new tier-driven job files.

We don't actually invoke ``pyats.easypy.run`` here — that would spin up
an entire run. Instead we:

1. Import each job file to confirm the module is collectible
   (no syntax errors, no import-time side effects that blow up in CI).
2. Pin the module-level constants (default tier, runtime, datafile) so
   the contract documented in the file headers can't drift silently.
3. Call ``main()`` with ``run()`` patched out to verify the wiring —
   that ``ensure_tier_env`` actually sets the env and that we hand the
   right ``testscript`` + ``datafile`` + ``testbed`` to easypy.
"""

from __future__ import annotations

import importlib
import os
from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from jobs import _common as common

_TRACKED_ENV = (
    "MYCELIUM_E2E_TIERS",
    "MYCELIUM_E2E_RUNTIME",
    "MYCELIUM_TESTBED_FILE",
    "MYCELIUM_DATAFILE",
    "MAX_FAILURES",
    "GITHUB_ACTIONS",
)


@pytest.fixture
def clean_tier_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Strip env vars jobs touch; cleanup after yield."""
    for key in _TRACKED_ENV:
        monkeypatch.delenv(key, raising=False)
    yield
    for key in _TRACKED_ENV:
        os.environ.pop(key, None)


# ── module collectibility ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "module_name",
    ["jobs.pr_job", "jobs.nightly_e2e_job"],
)
def test_job_module_importable(module_name: str) -> None:
    """Smoke: each job module imports without raising."""
    module = importlib.import_module(module_name)
    assert hasattr(module, "main"), f"{module_name} must expose main(runtime)"


# ── constant contract pins ────────────────────────────────────────────


def test_pr_job_constants() -> None:
    from jobs import pr_job

    assert pr_job._DEFAULT_TIERS == "pr"
    assert pr_job._DEFAULT_RUNTIME == "compose"
    assert pr_job._ALLOWED_RUNTIMES == common.RUNTIMES_ALL
    assert pr_job._DEFAULT_DATAFILE == "scenarios_datafile.yaml"


def test_nightly_job_constants() -> None:
    from jobs import nightly_e2e_job

    assert nightly_e2e_job._DEFAULT_TIERS == "pr,nightly"
    assert nightly_e2e_job._DEFAULT_RUNTIME == "compose"
    assert nightly_e2e_job._ALLOWED_RUNTIMES == common.RUNTIMES_ALL
    assert nightly_e2e_job._DEFAULT_DATAFILE == "scenarios_datafile.yaml"


def test_hermes_job_constants() -> None:
    from jobs import hermes_job

    assert hermes_job._DEFAULT_RUNTIME == "lab"
    assert hermes_job._ALLOWED_RUNTIMES == common.RUNTIME_LAB_ONLY


# ── main() wiring with easypy mocked out ──────────────────────────────


def _run_main(module_name: str) -> dict[str, object]:
    """Call ``main()`` with ``pyats.easypy.run`` patched; return the
    kwargs it would have passed to easypy."""
    module = importlib.import_module(module_name)
    captured: dict[str, object] = {}

    def fake_run(**kwargs: object) -> None:
        captured.update(kwargs)

    with patch.object(module, "run", fake_run):
        module.main(SimpleNamespace(testbed=None))

    return captured


def test_pr_job_main_sets_tier_and_passes_compose_testbed(
    clean_tier_env: None,
) -> None:
    kwargs = _run_main("jobs.pr_job")

    assert os.environ["MYCELIUM_E2E_TIERS"] == "pr"
    assert kwargs["testscript"].endswith("/suites/scenarios_suite.py")
    assert kwargs["datafile"].endswith("/data/scenarios_datafile.yaml")
    testbed = kwargs.get("testbed")
    assert testbed is not None
    assert getattr(testbed, "name", None) == "mycelium-compose"


def test_pr_job_main_uses_lab_when_runtime_env_set(
    clean_tier_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MYCELIUM_E2E_RUNTIME", "lab")
    kwargs = _run_main("jobs.pr_job")
    testbed = kwargs.get("testbed")
    assert testbed is not None
    assert getattr(testbed, "name", None) == "mycelium-lab"


def test_pr_job_main_uses_compose_on_github_actions(
    clean_tier_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    kwargs = _run_main("jobs.pr_job")
    testbed = kwargs.get("testbed")
    assert getattr(testbed, "name", None) == "mycelium-compose"


def test_nightly_job_main_sets_tier_and_passes_suite(clean_tier_env: None) -> None:
    kwargs = _run_main("jobs.nightly_e2e_job")

    assert os.environ["MYCELIUM_E2E_TIERS"] == "pr,nightly"
    assert kwargs["testscript"].endswith("/suites/scenarios_suite.py")


def test_pr_job_respects_preset_tier_env(
    clean_tier_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MYCELIUM_E2E_TIERS", "weekly")
    _run_main("jobs.pr_job")
    assert os.environ["MYCELIUM_E2E_TIERS"] == "weekly"


def test_nightly_job_respects_preset_tier_env(
    clean_tier_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MYCELIUM_E2E_TIERS", "pr")
    _run_main("jobs.nightly_e2e_job")
    assert os.environ["MYCELIUM_E2E_TIERS"] == "pr"


def test_hermes_job_rejects_compose_runtime(
    clean_tier_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MYCELIUM_E2E_RUNTIME", "compose")
    with pytest.raises(common.JobRuntimeMismatchError):
        _run_main("jobs.hermes_job")
