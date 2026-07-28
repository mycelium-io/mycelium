"""
<PYATS_JOBFILE>

Integration job — Claude Code adapter + Cursor stubs.

Covers tests 70-75.

Usage:
    pyats run job jobs/integration_job.py
"""

import logging

import jobs._common as common

log = logging.getLogger(__name__)


def main(runtime):
    common.simple_job_main(
        runtime,
        log,
        title="Mycelium Integration Adapter Tests",
        suite_name="integration_suite.py",
        datafile_name="integration_datafile.yaml",
    )
