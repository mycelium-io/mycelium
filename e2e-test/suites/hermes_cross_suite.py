"""Hermes cross-family negotiation suite.

Loads all rows from ``data/scenarios.yaml`` where at least one agent uses
the hermes adapter and at least one uses a different adapter (openclaw or
cursor), filtered to the active tiers (``MYCELIUM_E2E_TIERS``).

Currently covers:
  nightly  — TwoAgentConsensus_oc_he  (two-agent-consensus-oc-he)
             TwoAgentConsensus_cu_he  (two-agent-consensus-cu-he)
             ThreeAgentConsensus_oc_cu_he  (three-agent-consensus-oc-cu-he)
  weekly   — TwoAgentConsensus_he_oc  (two-agent-consensus-he-oc)
             TwoAgentConsensus_he_cu  (two-agent-consensus-he-cu)

Run via job:
    pyats run job jobs/hermes_job.py --testbed-file testbeds/lab.yaml
"""

from __future__ import annotations

import logging
import os

from pyats import aetest

from jobs._common import keep_rooms, no_cleanup
from libs.suite_lifecycle import (
    ProvisionSkipped,
    SessionError,
    provision_agents,
    teardown_provisioned_agents,
    teardown_shared_suite_room,
)
from suites._hermes_prereq import HermesPrereqCommonSetup
from testcases.scenarios import (
    active_tiers,
    filter_by_tier,
    load_rows,
    make_scenarios,
)

log = logging.getLogger(__name__)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_SCENARIOS_FILE = os.environ.get(
    "MYCELIUM_E2E_SCENARIOS_FILE",
    os.path.join(_ROOT, "data", "scenarios.yaml"),
)

_ALL_ROWS = load_rows(_SCENARIOS_FILE)
_ACTIVE_TIERS = active_tiers()
_CROSS_ROWS = filter_by_tier(
    [
        r
        for r in _ALL_ROWS
        if (any(a["adapter"] == "hermes" for a in r["agents"]) and len({a["adapter"] for a in r["agents"]}) > 1)
    ],
    _ACTIVE_TIERS,
)

log.info(
    "hermes_cross_suite: %d cross-family rows active (tiers=%s)",
    len(_CROSS_ROWS),
    sorted(_ACTIVE_TIERS),
)

_CLASSES = make_scenarios(_CROSS_ROWS)


class CommonSetup(HermesPrereqCommonSetup):
    @aetest.subsection
    def provision_agents(self, testscript, testbed=None):
        """Ensure every agent the active cross-family rows need is created."""
        try:
            provision_agents(_CROSS_ROWS, testscript, testbed, room_prefix="scn-he-cross")
        except ProvisionSkipped as exc:
            self.skipped(str(exc))
        except SessionError as exc:
            self.failed(f"setup_shared_suite_room: {exc}")
        except RuntimeError as exc:
            self.failed(str(exc))


class CommonCleanup(aetest.CommonCleanup):
    @aetest.subsection
    def teardown_suite_room(self, testscript, testbed=None):
        if no_cleanup():
            self.skipped("MYCELIUM_E2E_NO_CLEANUP is set — teardown skipped")
            return
        if keep_rooms():
            self.skipped("MYCELIUM_E2E_KEEP_ROOMS is set — suite room preserved")
            return
        if testbed is None:
            return
        backend_url = os.environ.get("MYCELIUM_BACKEND_URL")
        teardown_shared_suite_room(testscript, testbed, backend_url=backend_url)

    @aetest.subsection
    def teardown_hermes_agents(self, testscript, testbed=None):
        """Remove hermes agents that were created (not pre-existing) this run."""
        if no_cleanup():
            self.skipped("MYCELIUM_E2E_NO_CLEANUP is set — teardown skipped")
            return
        teardown_provisioned_agents(testscript, testbed, adapter_filter="hermes")


globals().update(_CLASSES)
for _cls in _CLASSES.values():
    _cls.__module__ = __name__
    _cls.__qualname__ = _cls.__name__


if __name__ == "__main__":
    aetest.main()
