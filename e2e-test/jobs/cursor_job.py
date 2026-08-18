"""Job file for the Cursor adapter E2E suite (tests 75-80)."""

import logging

import jobs._common as common

log = logging.getLogger(__name__)


def main(runtime):
    common.simple_job_main(
        runtime,
        log,
        title="Mycelium Cursor Adapter Tests",
        suite_name="cursor_suite.py",
        datafile_name="cursor_datafile.yaml",
    )
