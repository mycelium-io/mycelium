"""Hermes-hermes negotiation suite.

Loads all rows from ``data/scenarios.yaml`` where every agent uses the
hermes adapter, filtered to the active tiers (``MYCELIUM_E2E_TIERS``).

Currently covers:
  pr tier    — TwoAgentShakedown_he_he (two-agent-shakedown-he-he)
  nightly    — TwoAgentConsensus_he_he (two-agent-consensus-he-he)
               ThreeAgentConsensus_he_he_he (three-agent-consensus-he-he-he)

Run standalone:
    MYCELIUM_E2E_TIERS=pr pyats run job jobs/hermes_job.py

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
_HERMES_ROWS = filter_by_tier(
    [r for r in _ALL_ROWS if all(a["adapter"] == "hermes" for a in r["agents"])],
    _ACTIVE_TIERS,
)

log.info(
    "hermes_he_suite: %d hermes-only rows active (tiers=%s)",
    len(_HERMES_ROWS),
    sorted(_ACTIVE_TIERS),
)

_CLASSES = make_scenarios(_HERMES_ROWS)


class CommonSetup(HermesPrereqCommonSetup):
    @aetest.subsection
    def provision_hermes_agents(self, testscript, testbed=None):
        """Create hermes agents that don't already exist in the bootstrap room."""
        try:
            provision_agents(_HERMES_ROWS, testscript, testbed, room_prefix="scn-he-suite")
        except ProvisionSkipped as exc:
            self.skipped(str(exc))
        except SessionError as exc:
            self.failed(f"setup_shared_suite_room: {exc}")
        except RuntimeError as exc:
            self.failed(str(exc))


class CommonCleanup(aetest.CommonCleanup):
    @aetest.subsection
    def teardown_suite_room(self, testscript, testbed=None):
        """Drop the shared negotiation room before agent teardown."""
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
