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

import jobs._common as common

log = logging.getLogger(__name__)


def main(runtime):
    common.simple_job_main(
        runtime,
        log,
        title="Mycelium Sanity Test",
        suite_name="sanity_suite.py",
        datafile_name="sanity_datafile.yaml",
    )
