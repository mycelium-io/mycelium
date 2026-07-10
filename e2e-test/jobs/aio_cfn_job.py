"""
<PYATS_JOBFILE>

All-in-one CFN negotiation job — hub-only cross-adapter scenarios.

Runs every scenario where all agents are on the hub (no spokes required).
Exercises openclaw ↔ hermes, cursor ↔ hermes, cursor ↔ openclaw, and
hermes ↔ hermes negotiation via the Go CFN stack on a single device.

**Runtime:** compose (default) or lab.

Usage:
    pyats run job jobs/aio_cfn_job.py
    MYCELIUM_E2E_TIERS=pr pyats run job jobs/aio_cfn_job.py
    MYCELIUM_E2E_RUNTIME=lab pyats run job jobs/aio_cfn_job.py
"""

from __future__ import annotations

import logging
import os

from pyats.easypy import run

import jobs._common as common

log = logging.getLogger(__name__)

_DEFAULT_RUNTIME = common.RUNTIME_COMPOSE
_ALLOWED_RUNTIMES = common.RUNTIMES_ALL


def main(runtime):
    testbed, active_runtime, _source = common.prepare_job_testbed(
        runtime,
        log,
        job_default_runtime=_DEFAULT_RUNTIME,
        allowed_runtimes=_ALLOWED_RUNTIMES,
    )

    common.log_job_context(
        log,
        title="Mycelium AIO CFN Negotiation Tests",
        runtime=active_runtime,
        default_testbed=common.testbed_path_for_runtime(active_runtime),
        active_testbed=testbed,
    )

    datafile = common.get_datafile(default="aio_cfn_datafile.yaml")
    common.install_job_sigint_cleanup(common.resolve_backend_url(datafile))
    max_failures = common.get_max_failures(datafile)

    suite = common.get_suite_path("aio_cfn_suite.py")
    log.info("suite = %s (exists=%s)", suite, os.path.isfile(suite))
    run(
        testscript=suite,
        datafile=datafile,
        max_failures=max_failures,
        testbed=testbed,
    )
