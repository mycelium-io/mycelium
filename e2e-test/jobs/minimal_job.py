"""Minimal job to test pyATS task subprocess."""

import logging

from pyats.easypy import run

import jobs._common as common

log = logging.getLogger(__name__)


def main(runtime):
    suite = common.get_suite_path("minimal_test.py")
    datafile = common.get_datafile(default="minimal_datafile.yaml")
    log.info("script=%s", suite)
    log.info("datafile=%s", datafile)
    run(testscript=suite, datafile=datafile)
