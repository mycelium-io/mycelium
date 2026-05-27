"""
<PYATS_JOBFILE>

Sanity job — quick smoke test of core functionality.

Does NOT exercise LLM, convergence, distributed, or slow tests.
Suitable for pre-merge gating or environment verification.

Usage:
    pyats run job jobs/sanity_job.py
    pyats run job jobs/sanity_job.py --datafile data/local_datafile.yaml
"""

import logging

from pyats.easypy import run

import jobs._common as common

log = logging.getLogger(__name__)


def main(runtime):
    log.info("=== Mycelium Sanity Test ===")

    datafile = common.get_datafile(default="local_datafile.yaml")
    suite = common.get_suite_path("sanity_suite.py")

    run(testscript=suite, datafile=datafile)
