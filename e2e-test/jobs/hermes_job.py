"""
<PYATS_JOBFILE>

Hermes adapter E2E job — three suites in sequence:

1. hermes_suite        — adapter plumbing: gateway PID format tolerance (085)
                         and deque-based loop suppression (089).
2. hermes_he_suite     — hermes-hermes negotiation: two-agent shakedown (pr)
                         and three-agent proposer-rotation (nightly).
3. hermes_cross_suite  — cross-family negotiation: hermes + openclaw and
                         hermes + cursor rows (nightly / weekly).

Usage:
    pyats run job jobs/hermes_job.py
    pyats run job jobs/hermes_job.py --testbed-file testbeds/lab.yaml
    MYCELIUM_E2E_TIERS=pr pyats run job jobs/hermes_job.py --testbed-file testbeds/lab.yaml
"""

import logging
import os

from pyats.easypy import run

import jobs._common as common

log = logging.getLogger(__name__)


def main(runtime):
    log.info("=== Mycelium Hermes Adapter Tests ===")

    # hermes_suite uses hermes_datafile.yaml (has HermesGatewayPidFormats +
    # HermesLoopSuppression entries). The scenario suites use
    # scenarios_datafile.yaml — it has no testcases: block so pyATS won't
    # error when it can't find the plumbing test class names in those scripts.
    hermes_datafile = common.get_datafile(default="hermes_datafile.yaml")
    scenarios_datafile = common.get_datafile(default="scenarios_datafile.yaml")
    max_failures = common.get_max_failures(hermes_datafile)

    plumbing_suite = common.get_suite_path("hermes_suite.py")
    log.info("suite = %s (exists=%s)", plumbing_suite, os.path.isfile(plumbing_suite))
    run(testscript=plumbing_suite, datafile=hermes_datafile, max_failures=max_failures)

    for suite_name in ("hermes_he_suite.py", "hermes_cross_suite.py"):
        suite = common.get_suite_path(suite_name)
        log.info("suite = %s (exists=%s)", suite, os.path.isfile(suite))
        run(testscript=suite, datafile=scenarios_datafile, max_failures=max_failures)
