"""
Easypy job: dissent-map "Ship Friday or slip?" demo.

Automated (CI/nightly):
  pyats run job jobs/dissent_demo_job.py --testbed-file testbeds/lab.yaml

Interactive (demo / hackathon):
  MYCELIUM_E2E_AUTO_RULING="" pyats run job jobs/dissent_demo_job.py --testbed-file testbeds/lab.yaml

  The job pauses after session 1 impasse and prompts the operator for a ruling at stdin.
  Session 2 then runs autonomously and produces the plan.
"""

from __future__ import annotations

import logging
import os

from pyats.easypy import run

import jobs._common as common

log = logging.getLogger(__name__)

_DEFAULT_RUNTIME = common.RUNTIME_LAB
_ALLOWED_RUNTIMES = common.RUNTIMES_ALL


def main(runtime):
    testbed, active_runtime, _source = common.prepare_job_testbed(
        runtime,
        log,
        job_default_runtime=_DEFAULT_RUNTIME,
        allowed_runtimes=_ALLOWED_RUNTIMES,
    )

    common.log_job_context(
        log,
        title="Dissent-Map Demo — Ship Friday or slip?",
        runtime=active_runtime,
        default_testbed=common.testbed_path_for_runtime(active_runtime),
        active_testbed=testbed,
    )

    common.ensure_tier_env(default="demo")

    if os.environ.get("MYCELIUM_E2E_AUTO_RULING") == "":
        log.info("MYCELIUM_E2E_AUTO_RULING is explicitly empty — running in interactive mode")

    datafile = common.get_datafile(default="dissent_demo_datafile.yaml")
    # dissent_demo_tests.py is a standalone testcase (not wrapped by a suite)
    testscript = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "testcases", "dissent_demo_tests.py")
    )

    run(
        testscript=testscript,
        testbed=testbed,
        datafile=datafile,
    )
