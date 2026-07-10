"""
<PYATS_JOBFILE>

Weekly full E2E job — runs all test tiers in sequence.

This is the primary job for the weekly long-running integration test
of the Mycelium multi-agent coordination platform.

**Runtime:** resolved from ``MYCELIUM_E2E_RUNTIME``, ``GITHUB_ACTIONS`` /
job default. Permitted: compose and lab.

- **compose** — docker stack on the CI runner (``testbeds/compose.yaml``)
- **lab** — orch EC2 cluster (``testbeds/lab.yaml``) via
  ``.github/workflows/weekly-e2e.yaml``

Usage:
    pyats run job jobs/weekly_e2e_job.py

    # Lab cluster (default when not in CI):
    MYCELIUM_E2E_RUNTIME=lab pyats run job jobs/weekly_e2e_job.py

    # Compose stack (CI / local docker):
    MYCELIUM_E2E_RUNTIME=compose pyats run job jobs/weekly_e2e_job.py

    # With explicit datafile
    pyats run job jobs/weekly_e2e_job.py \\
        --datafile data/weekly_datafile.yaml

    # Filter to specific groups
    TESTCASES="test_01_room_lifecycle, test_02_multi_agent_memory" \\
        pyats run job jobs/weekly_e2e_job.py

    # HTML logs for review
    pyats run job jobs/weekly_e2e_job.py --html-logs
"""

import logging
import os

from pyats.datastructures.logic import Or
from pyats.easypy import run

# Ensure project root on path
import jobs._common as common

log = logging.getLogger(__name__)

_DEFAULT_RUNTIME = common.RUNTIME_LAB
_ALLOWED_RUNTIMES = common.RUNTIMES_ALL

testcases_filter = os.getenv("TESTCASES")
if testcases_filter:
    tcs = [t.strip() for t in testcases_filter.split(",")]
    uids = Or("common_setup", *tcs, "common_cleanup")
else:
    uids = None


def main(runtime):
    testbed, active_runtime, _source = common.prepare_job_testbed(
        runtime,
        log,
        job_default_runtime=_DEFAULT_RUNTIME,
        allowed_runtimes=_ALLOWED_RUNTIMES,
    )
    common.log_job_context(
        log,
        title="Mycelium Weekly E2E Test",
        runtime=active_runtime,
        default_testbed=common.testbed_path_for_runtime(active_runtime),
        active_testbed=testbed,
    )
    log.info("Runtime directory: %s", runtime.directory)

    datafile = common.get_datafile(default="weekly_datafile.yaml")
    suite = common.get_suite_path("weekly_full_suite.py")
    max_failures = common.get_max_failures(datafile)

    log.info("Datafile: %s", datafile)
    log.info("Suite: %s", suite)
    log.info("Max failures: %s", max_failures or "unlimited")

    kwargs = {"testscript": suite, "datafile": datafile}
    if uids:
        kwargs["uids"] = uids
        log.info("Filtering to testcases: %s", testcases_filter)
    if max_failures:
        kwargs["max_failures"] = max_failures
    if testbed is not None:
        kwargs["testbed"] = testbed

    run(**kwargs)
