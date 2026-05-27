"""Minimal job to test pyATS task subprocess."""

import os
import logging

from pyats.easypy import run

log = logging.getLogger(__name__)

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "suites", "minimal_test.py")
DATAFILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "data", "minimal_datafile.yaml")


def main(runtime):
    log.info("script=%s exists=%s", SCRIPT, os.path.isfile(SCRIPT))
    log.info("datafile=%s exists=%s", DATAFILE, os.path.isfile(DATAFILE))
    run(testscript=SCRIPT, datafile=DATAFILE)
