"""
<PYATS_JOBFILE>

Convergence job — multi-agent simulated negotiation scenarios.

Covers tests 15-21. Requires LLM and CFN stack.

Usage:
    pyats run job jobs/convergence_job.py
    pyats run job jobs/convergence_job.py --datafile data/lab_datafile.yaml
"""

import logging

from pyats.easypy import run

import jobs._common as common

log = logging.getLogger(__name__)


def main(runtime):
    log.info("=== Mycelium Convergence Tests ===")

    datafile = common.get_datafile(default="base_datafile.yaml")
    suite = common.get_suite_path("convergence_suite.py")
    max_failures = common.get_max_failures(datafile)

    log.info("Max failures: %s", max_failures or "unlimited")
    run(testscript=suite, datafile=datafile, max_failures=max_failures)
