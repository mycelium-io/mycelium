"""
<PYATS_JOBFILE>

Convergence job — multi-agent simulated negotiation scenarios.

Covers tests 15-21. Requires LLM and CFN stack.

Usage:
    pyats run job jobs/convergence_job.py
    pyats run job jobs/convergence_job.py --datafile data/convergence_datafile.yaml
"""

import logging

import jobs._common as common

log = logging.getLogger(__name__)


def main(runtime):
    common.simple_job_main(
        runtime,
        log,
        title="Mycelium Convergence Tests",
        suite_name="convergence_suite.py",
        datafile_name="convergence_datafile.yaml",
    )
