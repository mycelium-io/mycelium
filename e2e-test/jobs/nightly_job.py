"""Nightly job — PR checks + stub coordination.

Runs nightly and before release cuts. No LLM required (stubs only).
Blocks release on any failure.
"""

import logging
import os
import sys

from pyats.easypy import run

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jobs._common import get_datafile, get_project_root, install_job_sigint_cleanup, resolve_backend_url

log = logging.getLogger(__name__)


def main(runtime):
    root = get_project_root()
    datafile = get_datafile(default="nightly_datafile.yaml")
    install_job_sigint_cleanup(resolve_backend_url(datafile))

    log.info("=== Nightly Job — PR checks + stub coordination ===")
    log.info("Datafile: %s", datafile)

    for suite_name in ("pr_suite.py", "nightly_suite.py"):
        suite_path = os.path.join(root, "suites", suite_name)
        run(testscript=suite_path, datafile=datafile)
