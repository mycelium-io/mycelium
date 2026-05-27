"""
<PYATS_JOBFILE>

Integration job — Claude Code adapter + Cursor stubs.

Covers tests 70-75.

Usage:
    pyats run job jobs/integration_job.py
"""

import logging
import os

from pyats.easypy import run

import jobs._common as common

log = logging.getLogger(__name__)


def main(runtime):
    log.info("=== Mycelium Integration Adapter Tests ===")

    datafile = common.get_datafile(default="integration_datafile.yaml")
    suite = common.get_suite_path("integration_suite.py")

    log.info("datafile = %s (exists=%s)", datafile, os.path.isfile(datafile))
    log.info("suite    = %s (exists=%s)", suite, os.path.isfile(suite))

    run(testscript=suite, datafile=datafile)
