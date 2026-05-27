"""
<PYATS_JOBFILE>

Core job — rooms, memory, CLI, sessions, CFN basics.

Covers tests 01-14 and 22.

Usage:
    pyats run job jobs/core_job.py
    pyats run job jobs/core_job.py --datafile data/lab_datafile.yaml
"""

import logging

from pyats.easypy import run

import jobs._common as common

log = logging.getLogger(__name__)


def main(runtime):
    log.info("=== Mycelium Core Tests ===")

    datafile = common.get_datafile(default="base_datafile.yaml")
    suite = common.get_suite_path("core_suite.py")

    run(testscript=suite, datafile=datafile)
