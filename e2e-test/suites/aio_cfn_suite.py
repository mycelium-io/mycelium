"""All-in-one CFN negotiation suite.

Runs every scenario row where **all** agents are assigned ``host: hub``.
No spoke devices required — designed for single-device validation of the
mycelium ↔ Go CFN negotiation path across adapter families.

Currently covers (``category: aio``, tier ``pr``):
  two-agent-aio-oc-he   — openclaw hub vs hermes hub
  two-agent-aio-cu-he   — cursor hub vs hermes hub
  two-agent-aio-cu-oc   — cursor hub vs openclaw hub
  two-agent-aio-he-he   — hermes hub vs hermes hub

Plus any existing hub-only rows (e.g. ``two-agent-consensus-broad-oc-oc``).

Run standalone:
    ./run_tests.sh aio_cfn

Run via job (compose testbed):
    pyats run job jobs/aio_cfn_job.py

Run via job (lab testbed, with oclw4 as hub):
    MYCELIUM_E2E_RUNTIME=lab pyats run job jobs/aio_cfn_job.py
"""

from __future__ import annotations

import logging
import os

from pyats import aetest

from libs.suite_lifecycle import (
    ProvisionSkipped,
    SessionError,
    provision_agents,
    teardown_provisioned_agents,
    teardown_shared_suite_room,
)
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

# Hub-only: every agent on the row must have host == "hub"
_AIO_ROWS = filter_by_tier(
    [
        r
        for r in _ALL_ROWS
        if r.get("agents") and all(a.get("host") == "hub" for a in r["agents"])
    ],
    _ACTIVE_TIERS,
)

log.info(
    "aio_cfn_suite: %d hub-only rows active (tiers=%s)",
    len(_AIO_ROWS),
    sorted(_ACTIVE_TIERS),
)

_CLASSES = make_scenarios(_AIO_ROWS)


class CommonSetup(aetest.CommonSetup):
    @aetest.subsection
    def check_cli(self):
        import shutil

        if not shutil.which("mycelium"):
            self.failed("mycelium CLI not found on PATH")

    @aetest.subsection
    def check_cfn(self):
        """Verify the Go CFN stack is reachable before running negotiation tests."""
        import urllib.request

        cfn_url = os.environ.get("CFN_SVC_URL", "http://localhost:9002")
        health = f"{cfn_url.rstrip('/')}/api/internal/diagnostics/health"
        try:
            with urllib.request.urlopen(health, timeout=5) as resp:
                if resp.status not in (200, 204):
                    self.skipped(f"CFN node svc not healthy at {health} (status {resp.status})")
        except Exception as exc:
            self.skipped(f"CFN node svc unreachable at {health}: {exc}")

    @aetest.subsection
    def provision_agents(self, testscript, testbed=None):
        """Ensure every hub agent the active rows need exists."""
        try:
            provision_agents(_AIO_ROWS, testscript, testbed, room_prefix="scn-aio")
        except ProvisionSkipped as exc:
            self.skipped(str(exc))
        except SessionError as exc:
            self.failed(f"setup_shared_suite_room: {exc}")
        except RuntimeError as exc:
            self.failed(str(exc))


class CommonCleanup(aetest.CommonCleanup):
    @aetest.subsection
    def teardown_suite_room(self, testscript, testbed=None):
        if testbed is None:
            return
        backend_url = os.environ.get("MYCELIUM_BACKEND_URL")
        teardown_shared_suite_room(testscript, testbed, backend_url=backend_url)

    @aetest.subsection
    def teardown_agents(self, testscript, testbed=None):
        """Remove agents created this run (hermes and cursor are ephemeral)."""
        teardown_provisioned_agents(testscript, testbed)


globals().update(_CLASSES)
for _cls in _CLASSES.values():
    _cls.__module__ = __name__
    _cls.__qualname__ = _cls.__name__


if __name__ == "__main__":
    import sys

    _testbed = None
    if "--testbed-file" in sys.argv:
        _idx = sys.argv.index("--testbed-file")
        if _idx + 1 < len(sys.argv):
            from pyats.topology import loader as _loader

            _testbed = _loader.load(sys.argv[_idx + 1])

    aetest.main(testbed=_testbed)
