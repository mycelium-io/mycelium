"""
<PYATS_JOBFILE>

Core job — rooms, memory, CLI, sessions, CFN basics.

Covers tests 01-14 and 22.

Usage:
    pyats run job jobs/core_job.py
    pyats run job jobs/core_job.py --datafile data/core_datafile.yaml
"""

import logging

import jobs._common as common

log = logging.getLogger(__name__)


def main(runtime):
    common.simple_job_main(
        runtime,
        log,
        title="Mycelium Core Tests",
        suite_name="core_suite.py",
        datafile_name="core_datafile.yaml",
    )
