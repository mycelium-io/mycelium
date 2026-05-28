"""
<PYATS_JOBFILE>

Distributed job — real agents on oclw3/4/5 via Matrix + Mycelium.

Covers tests 30-32 (local-real) and 40-49 (cross-device).
Requires the full lab topology with Matrix, OpenClaw, and remote agents.

Usage:
    pyats run job jobs/distributed_job.py --datafile data/lab_datafile.yaml

    # Local-real only (no remote agents needed)
    TESTCASES="test_30_local_two_agent, test_31_local_three_agent, test_32_local_architecture" \\
        pyats run job jobs/distributed_job.py
"""

import os
import logging

from pyats.easypy import run
from pyats.datastructures.logic import Or

import jobs._common as common

log = logging.getLogger(__name__)

testcases_filter = os.getenv("TESTCASES")
if testcases_filter:
    tcs = [t.strip() for t in testcases_filter.split(",")]
    uids = Or("common_setup", *tcs, "common_cleanup")
else:
    uids = None


def main(runtime):
    log.info("=== Mycelium Distributed Tests ===")

    datafile = common.get_datafile(default="lab_datafile.yaml")
    suite = common.get_suite_path("distributed_suite.py")
    max_failures = common.get_max_failures(datafile)

    log.info("Max failures: %s", max_failures or "unlimited")

    kwargs = {"testscript": suite, "datafile": datafile}
    if uids:
        kwargs["uids"] = uids
    if max_failures:
        kwargs["max_failures"] = max_failures

    run(**kwargs)
