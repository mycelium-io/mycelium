"""
<PYATS_JOBFILE>

Sanity job — quick smoke test of core functionality.

Does NOT exercise LLM, convergence, hub_and_spoke, or slow tests.
Suitable for pre-merge gating or environment verification.

Usage:
    pyats run job jobs/sanity_job.py
    pyats run job jobs/sanity_job.py --datafile data/sanity_datafile.yaml
"""

import logging

from pyats.easypy import run

import jobs._common as common

log = logging.getLogger(__name__)


def main(runtime):
    log.info("=== Mycelium Sanity Test ===")

    datafile = common.get_datafile(default="sanity_datafile.yaml")
    suite = common.get_suite_path("sanity_suite.py")
    max_failures = common.get_max_failures(datafile)

    log.info("Max failures: %s", max_failures or "unlimited")
    run(testscript=suite, datafile=datafile, max_failures=max_failures)
