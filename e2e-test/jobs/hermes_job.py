"""
<PYATS_JOBFILE>

Hermes adapter E2E job — two suites in sequence:

1. hermes_he_suite     — hermes-hermes negotiation: two-agent shakedown (pr)
                         and three-agent proposer-rotation (nightly).
2. hermes_cross_suite  — cross-family negotiation: hermes + openclaw and
                         hermes + cursor rows (nightly / weekly).

**Runtime:** compose (default in CI) or lab (``MYCELIUM_E2E_RUNTIME=lab``).

Usage:
    pyats run job jobs/hermes_job.py
    MYCELIUM_E2E_TIERS=pr pyats run job jobs/hermes_job.py
"""

from __future__ import annotations

import logging
import os

from pyats.easypy import run

import jobs._common as common

log = logging.getLogger(__name__)

_DEFAULT_RUNTIME = common.RUNTIME_LAB
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
        title="Mycelium Hermes Adapter Tests",
        runtime=active_runtime,
        default_testbed=common.testbed_path_for_runtime(active_runtime),
        active_testbed=testbed,
    )

    scenarios_datafile = common.get_datafile(default="scenarios_datafile.yaml")
    max_failures = common.get_max_failures(scenarios_datafile)

    # Install Ctrl-C handler so a job-level interrupt sweeps e2e rooms even
    # when the interrupt fires between run() calls (pyATS only guarantees
    # CommonCleanup runs for the *currently executing* suite, not for suites
    # that haven't started yet).
    common.install_job_sigint_cleanup(common.resolve_backend_url(scenarios_datafile))

    suite_name = "hermes_he_suite.py"
    suite = common.get_suite_path(suite_name)
    log.info("suite = %s (exists=%s)", suite, os.path.isfile(suite))
    run(
        testscript=suite,
        datafile=scenarios_datafile,
        max_failures=max_failures,
        testbed=testbed,
    )
