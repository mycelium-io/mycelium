"""Three-axis scenario suite.

Loads ``data/scenarios.yaml``, filters by ``MYCELIUM_E2E_TIERS``, and
materialises one pyATS ``Testcase`` per row at import time.

Run standalone:
    MYCELIUM_E2E_TIERS=pr pyats run job suites/scenarios_suite.py \\
        --testbed-file testbeds/compose.yaml

This module is intentionally thin — all the scenario logic lives in
:mod:`testcases.scenarios`. The suite's only job is to wire the
generated classes into the pyATS-discovered namespace.
"""

from __future__ import annotations

import logging
import os
import sys

from pyats import aetest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

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

# Inject generated classes into the module namespace so pyATS's class
# discovery picks them up. Names look like ``TwoAgentConsensus_oc_cu``.
globals().update(_CLASSES)


# ── direct-run entrypoint ───────────────────────────────────────────

if __name__ == "__main__":
    aetest.main()
