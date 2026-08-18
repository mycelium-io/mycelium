"""
<PYATS_JOBFILE>

Hub-and-spoke job — real agents on oclw3/4/5 via Matrix + Mycelium.

Requires the full lab topology with Matrix, OpenClaw, and remote agents.

**Runtime:** lab only (``testbeds/lab.yaml``).

Usage:
    pyats run job jobs/hub_and_spoke_job.py --testbed-file testbeds/lab.yaml
"""

import logging

from pyats.easypy import run

import jobs._common as common

log = logging.getLogger(__name__)

_DEFAULT_RUNTIME = common.RUNTIME_LAB
_ALLOWED_RUNTIMES = common.RUNTIME_LAB_ONLY


def main(runtime):
    uids = common.uids_filter_from_env()
    testbed, active_runtime, _source = common.prepare_job_testbed(
        runtime,
        log,
        job_default_runtime=_DEFAULT_RUNTIME,
        allowed_runtimes=_ALLOWED_RUNTIMES,
    )
    common.log_job_context(
        log,
        title="Mycelium Hub-and-Spoke Tests",
        runtime=active_runtime,
        default_testbed=common.testbed_path_for_runtime(active_runtime),
        active_testbed=testbed,
    )

    datafile = common.get_datafile(default="distributed_datafile.yaml")
    suite = common.get_suite_path("hub_and_spoke_suite.py")
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
