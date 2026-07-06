"""
<PYATS_JOBFILE>

Distributed job — real agents on oclw3/4/5 via Matrix + Mycelium.

Covers tests 30-32 (local-real) and 40-49 (cross-device).
Requires the full lab topology with Matrix, OpenClaw, and remote agents.

**Runtime:** lab only (``testbeds/lab.yaml``).

Usage:
    pyats run job jobs/distributed_job.py --testbed-file testbeds/lab.yaml

    # Local-real only (no remote agents needed)
    TESTCASES="test_30_local_two_agent, test_31_local_three_agent, test_32_local_architecture" \\
        pyats run job jobs/distributed_job.py --testbed-file testbeds/lab.yaml
"""

import logging
import os

from pyats.datastructures.logic import Or
from pyats.easypy import run

import jobs._common as common

log = logging.getLogger(__name__)

_DEFAULT_RUNTIME = common.RUNTIME_LAB
_ALLOWED_RUNTIMES = common.RUNTIME_LAB_ONLY

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
        title="Mycelium Distributed Tests",
        runtime=active_runtime,
        default_testbed=common.testbed_path_for_runtime(active_runtime),
        active_testbed=testbed,
    )

    datafile = common.get_datafile(default="distributed_datafile.yaml")
    suite = common.get_suite_path("distributed_suite.py")
    max_failures = common.get_max_failures(datafile)

    log.info("Max failures: %s", max_failures or "unlimited")

    kwargs = {"testscript": suite, "datafile": datafile}
    if uids:
        kwargs["uids"] = uids
    if max_failures:
        kwargs["max_failures"] = max_failures
    if testbed is not None:
        kwargs["testbed"] = testbed

    run(**kwargs)
