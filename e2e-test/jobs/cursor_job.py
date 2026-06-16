"""Job file for the Cursor adapter E2E suite (tests 75-80)."""

from pyats.easypy import run

import jobs._common as common


def main(runtime):
    datafile = common.get_datafile(default="cursor_datafile.yaml")
    suite = common.get_suite_path("cursor_suite.py")
    max_failures = common.get_max_failures(datafile)
    run(testscript=suite, datafile=datafile, max_failures=max_failures)
