"""
<PYATS_JOBFILE>

Weekly full E2E job — runs all test tiers in sequence.

This is the primary job for the weekly long-running integration test
of the Mycelium multi-agent coordination platform.

Usage:
    # Full weekly run against lab
    pyats run job jobs/weekly_e2e_job.py

    # With explicit datafile
    pyats run job jobs/weekly_e2e_job.py \\
        --datafile data/lab_datafile.yaml

    # Filter to specific groups
    TESTCASES="test_01_room_lifecycle, test_02_multi_agent_memory" \\
        pyats run job jobs/weekly_e2e_job.py

    # HTML logs for review
    pyats run job jobs/weekly_e2e_job.py --html-logs
"""

import os
import logging

from pyats.easypy import run
from pyats.datastructures.logic import Or

# Ensure project root on path
import jobs._common as common

log = logging.getLogger(__name__)

testcases_filter = os.getenv("TESTCASES")
if testcases_filter:
    tcs = [t.strip() for t in testcases_filter.split(",")]
    uids = Or("common_setup", *tcs, "common_cleanup")
else:
    uids = None


def main(runtime):
    log.info("=== Mycelium Weekly E2E Test ===")
    log.info("Runtime directory: %s", runtime.directory)

    datafile = common.get_datafile(default="lab_datafile.yaml")
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

    run(**kwargs)
