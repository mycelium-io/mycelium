"""
<PYATS_JOBFILE>

Hermes adapter E2E job — gateway health, return-address sidecar,
notify-home, and loop suppression.

Covers tests 85-89 (commit 28aca63 changes).

Usage:
    pyats run job jobs/hermes_job.py
    pyats run job jobs/hermes_job.py --datafile data/hermes_datafile.yaml
"""

import logging
import os

from pyats.easypy import run

import jobs._common as common

log = logging.getLogger(__name__)


def main(runtime):
    log.info("=== Mycelium Hermes Adapter Tests ===")

    datafile = common.get_datafile(default="hermes_datafile.yaml")
    suite = common.get_suite_path("hermes_suite.py")
    max_failures = common.get_max_failures(datafile)

    log.info("datafile = %s (exists=%s)", datafile, os.path.isfile(datafile))
    log.info("suite    = %s (exists=%s)", suite, os.path.isfile(suite))
    log.info("Max failures: %s", max_failures or "unlimited")

    run(testscript=suite, datafile=datafile, max_failures=max_failures)
