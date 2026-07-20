"""
<PYATS_JOBFILE>

Cross-family negotiation job — agents of different adapter types negotiating.

Covers:
  hermes_cross_suite  — Hermes ↔ OpenClaw and Hermes ↔ Cursor scenarios
                        (nightly: oc_he, cu_he, oc_cu_he; weekly: he_oc, he_cu)
  cursor_suite        — Cursor ↔ OpenClaw (test_80) and Cursor ↔ Cursor
                        cross-host (test_79)

Does NOT include same-family or adapter-plumbing tests (use hermes_job.py or
cursor_job.py for those).

**Runtime:** lab only (``MYCELIUM_E2E_RUNTIME=lab`` or job default).

Usage:
    pyats run job jobs/cross_family_job.py
    MYCELIUM_E2E_TIERS=nightly pyats run job jobs/cross_family_job.py
"""

from __future__ import annotations

import logging
import os

from pyats.datastructures.logic import Or
from pyats.easypy import run

import jobs._common as common

log = logging.getLogger(__name__)

_DEFAULT_RUNTIME = common.RUNTIME_LAB
_ALLOWED_RUNTIMES = common.RUNTIME_LAB_ONLY


def main(runtime):
    testbed, active_runtime, _source = common.prepare_job_testbed(
        runtime,
        log,
        job_default_runtime=_DEFAULT_RUNTIME,
        allowed_runtimes=_ALLOWED_RUNTIMES,
    )

    common.log_job_context(
        log,
        title="Mycelium Cross-Family Negotiation Tests",
        runtime=active_runtime,
        default_testbed=common.testbed_path_for_runtime(active_runtime),
        active_testbed=testbed,
    )

    scenarios_datafile = common.get_datafile(default="scenarios_datafile.yaml")
    cursor_datafile = common.get_datafile(default="cursor_datafile.yaml")
    max_failures = common.get_max_failures(scenarios_datafile)

    common.install_job_sigint_cleanup(common.resolve_backend_url(scenarios_datafile))

    # Hermes ↔ OpenClaw and Hermes ↔ Cursor
    hermes_cross = common.get_suite_path("hermes_cross_suite.py")
    log.info("suite = %s (exists=%s)", hermes_cross, os.path.isfile(hermes_cross))
    run(
        testscript=hermes_cross,
        datafile=scenarios_datafile,
        max_failures=max_failures,
        testbed=testbed,
    )

    # Cursor ↔ OpenClaw (test_80) and Cursor ↔ Cursor cross-host (test_79)
    cursor_cross = common.get_suite_path("cursor_suite.py")
    log.info("suite = %s (exists=%s)", cursor_cross, os.path.isfile(cursor_cross))
    run(
        testscript=cursor_cross,
        datafile=cursor_datafile,
        max_failures=max_failures,
        testbed=testbed,
        uids=Or("common_setup", "test_79_cursor_cross_family_cursor",
                "test_80_cursor_cross_family_openclaw", "common_cleanup"),
    )
