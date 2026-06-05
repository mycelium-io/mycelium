"""Three-axis scenario suite.

Loads ``data/scenarios.yaml``, filters by ``MYCELIUM_E2E_TIERS``, and
materialises one pyATS ``Testcase`` per row at import time.

Run standalone:
    MYCELIUM_E2E_TIERS=pr pyats run job suites/scenarios_suite.py \\
        --testbed-file testbeds/compose.yaml

Optional lab redeploy (only fires when running against
``testbeds/lab.yaml`` with ``MYCELIUM_LAB_REDEPLOY=1`` set):

    MYCELIUM_LAB_REDEPLOY=1 MYCELIUM_LAB_REF=main \\
        MYCELIUM_E2E_TIERS=pr pyats run job suites/scenarios_suite.py \\
        --testbed-file testbeds/lab.yaml

This module is intentionally thin — all the scenario logic lives in
:mod:`testcases.scenarios`. The suite's only job is to wire the
generated classes into the pyATS-discovered namespace and (optionally)
redeploy lab hardware before the first testcase runs.
"""

from __future__ import annotations

import logging
import os
import sys

from pyats import aetest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from libs.lab_redeploy import (  # noqa: E402 - sys.path tweak first
    LabCleanupMode,
    LabRedeployConfig,
    redeploy_testbed,
)
from testcases.scenarios import (  # noqa: E402 - sys.path tweak first
    active_tiers,
    filter_by_tier,
    load_rows,
    make_scenarios,
)

log = logging.getLogger(__name__)


# ── load + filter + materialise ─────────────────────────────────────

_SCENARIOS_FILE = os.environ.get(
    "MYCELIUM_E2E_SCENARIOS_FILE",
    os.path.join(_ROOT, "data", "scenarios.yaml"),
)

_ALL_ROWS = load_rows(_SCENARIOS_FILE)
_ACTIVE_TIERS = active_tiers()
_ACTIVE_ROWS = filter_by_tier(_ALL_ROWS, _ACTIVE_TIERS)

log.info(
    "scenarios_suite: %d/%d rows active (tiers=%s)",
    len(_ACTIVE_ROWS),
    len(_ALL_ROWS),
    sorted(_ACTIVE_TIERS),
)

_CLASSES = make_scenarios(_ACTIVE_ROWS)


# ── optional lab redeploy CommonSetup ───────────────────────────────


def _redeploy_requested() -> bool:
    """Return True when the operator opted into the lab redeploy hook.

    Compose runs never set this (they're born fresh every time), so the
    default is off and the CommonSetup short-circuits with a single
    skipped subsection on the standard PR path.
    """
    return os.environ.get("MYCELIUM_LAB_REDEPLOY", "").lower() in {"1", "true", "yes"}


def _redeploy_config_from_env() -> LabRedeployConfig:
    """Build a :class:`LabRedeployConfig` from environment variables.

    Mirrors the flags supported by ``scripts/redeploy_lab.py`` so the
    same knobs are reachable from either path. Sensitive values
    (LLM_API_KEY, LLM_BASE_URL) are pulled from the live env via
    ``MYCELIUM_LAB_ENV_KEYS`` rather than from the testbed YAML so they
    never land on disk in the repo.
    """
    ref = os.environ.get("MYCELIUM_LAB_REF", "main")
    repo = os.environ.get("MYCELIUM_REPO_URL", "https://github.com/mycelium-io/mycelium.git")
    mode_raw = os.environ.get("MYCELIUM_LAB_CLEANUP", LabCleanupMode.MODERATE.value)
    try:
        mode = LabCleanupMode(mode_raw)
    except ValueError:
        log.warning("Unknown MYCELIUM_LAB_CLEANUP=%r — falling back to moderate", mode_raw)
        mode = LabCleanupMode.MODERATE

    overrides: dict[str, str] = {}
    raw_keys = os.environ.get("MYCELIUM_LAB_ENV_KEYS", "")
    for key in (k.strip() for k in raw_keys.split(",") if k.strip()):
        if key in os.environ:
            overrides[key] = os.environ[key]
        else:
            log.warning(
                "MYCELIUM_LAB_ENV_KEYS lists %r but it isn't in the process env — skipped",
                key,
            )

    return LabRedeployConfig(
        ref=ref,
        repo_url=repo,
        cleanup_mode=mode,
        include_ui=os.environ.get("MYCELIUM_LAB_INCLUDE_UI", "").lower() in {"1", "true", "yes"},
        env_overrides=overrides,
    )


class LabRedeployCommonSetup(aetest.CommonSetup):
    """Opt-in pre-suite lab redeploy.

    Fires only when ``MYCELIUM_LAB_REDEPLOY=1`` is set. When inactive
    the single subsection short-circuits with ``self.skipped(...)`` —
    cheap enough to leave wired up on the compose path. When active,
    iterates the testbed hub-first and runs the full reset/install
    flow; a single device failure marks the entire suite skipped (we
    can't run scenarios against half a stack)."""

    @aetest.subsection
    def redeploy_lab(self, testscript, testbed=None):
        if not _redeploy_requested():
            self.skipped(
                "MYCELIUM_LAB_REDEPLOY unset — skipping lab redeploy",
            )

        if testbed is None:
            self.failed(
                "MYCELIUM_LAB_REDEPLOY=1 but no testbed was provided. Pass --testbed-file testbeds/lab.yaml.",
            )

        cfg = _redeploy_config_from_env()
        log.info(
            "Lab redeploy requested: ref=%s mode=%s include_ui=%s",
            cfg.ref,
            cfg.cleanup_mode.value,
            cfg.include_ui,
        )

        try:
            results = redeploy_testbed(testbed, cfg)
        except ValueError as exc:
            self.failed(f"Lab redeploy aborted: {exc}")
            return

        # Persist results into testscript params so testcases can
        # inspect them if they care (currently nobody does, but it's
        # cheap insurance for debugging a flaky redeploy).
        testscript.parameters["lab_redeploy_results"] = results

        failed = [r for r in results if not r.success]
        if failed:
            details = "; ".join(f"{r.device_name}={r.error}" for r in failed)
            self.failed(f"Lab redeploy failed on {len(failed)} device(s): {details}")


# Inject generated classes into the module namespace so pyATS's class
# discovery picks them up. Names look like ``TwoAgentConsensus_oc_cu``.
#
# pyATS discovers testcase classes by walking the testscript's
# ``__dict__`` and filtering on ``cls.__module__ == testscript_module``.
# Our classes were created via ``type(name, (_ConsensusBase,), ...)``
# inside ``testcases.scenarios.make_scenarios``, so they inherit that
# module name and would otherwise be silently rejected. Rebrand each
# class to this module so discovery (and downstream reporting) treats
# them as native suite members.
globals().update(_CLASSES)
for _cls in _CLASSES.values():
    _cls.__module__ = __name__
    _cls.__qualname__ = _cls.__name__


# ── direct-run entrypoint ───────────────────────────────────────────

if __name__ == "__main__":
    aetest.main()
