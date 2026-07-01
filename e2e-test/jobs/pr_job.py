"""<PYATS_JOBFILE>

PR canary job — runs the **pr-tier** scenarios against the docker
compose stack inside a 30-minute budget.

**Runtime:** resolved from ``MYCELIUM_E2E_RUNTIME``, CI auto-detect
(``GITHUB_ACTIONS`` → compose), or job default (compose). Permitted:
compose and lab — no ``--testbed-file`` required.

This is the gate that fires on every PR + every push to a non-main
branch. The default tier set is ``pr`` (3 broad-coverage rows in
``data/scenarios.yaml``). Override with ``MYCELIUM_E2E_TIERS=…`` for
ad-hoc local runs.

Usage
-----

    # Default — runtime from MYCELIUM_E2E_RUNTIME / GITHUB_ACTIONS / job default
    pyats run job jobs/pr_job.py

    # Lab box:
    MYCELIUM_E2E_RUNTIME=lab pyats run job jobs/pr_job.py

    # Explicit testbed override (optional):
    pyats run job jobs/pr_job.py --testbed-file testbeds/lab.yaml

    # Override the tier set:
    MYCELIUM_E2E_TIERS=pr,nightly \\
        pyats run job jobs/pr_job.py --testbed-file testbeds/compose.yaml

    # Drive against the real lab from the hub:
    pyats run job jobs/pr_job.py --testbed-file testbeds/lab.yaml

The job pins ``MYCELIUM_E2E_TIERS=pr`` (only when it isn't already set
in the env) so import-time class generation in
``suites/scenarios_suite.py`` picks up exactly the PR rows.
"""

from __future__ import annotations

import logging

from pyats.easypy import run

import jobs._common as common

log = logging.getLogger(__name__)


_DEFAULT_TIERS = "pr"
_DEFAULT_RUNTIME = common.RUNTIME_COMPOSE
_ALLOWED_RUNTIMES = common.RUNTIMES_ALL
# ``scenarios_datafile.yaml`` carries only the parameter blocks the
# matrix-generated testcases consume. Using ``base_datafile.yaml`` (or
# anything that extends it) errors because pyATS treats its legacy
# ``testcases:`` block as authoritative and the matrix's dynamic class
# names (``TwoAgentConsensus_oc_oc`` etc.) don't match those entries.
_DEFAULT_DATAFILE = "scenarios_datafile.yaml"


def main(runtime):
    """Run the PR-tier scenarios via easypy."""
    active_tiers = common.ensure_tier_env(_DEFAULT_TIERS)
    datafile = common.get_datafile(default=_DEFAULT_DATAFILE)
    suite = common.get_suite_path("scenarios_suite.py")
    max_failures = common.get_max_failures(datafile)
    testbed, active_runtime, _source = common.prepare_job_testbed(
        runtime,
        log,
        job_default_runtime=_DEFAULT_RUNTIME,
        allowed_runtimes=_ALLOWED_RUNTIMES,
    )

    common.log_job_context(
        log,
        title="Mycelium PR Canary",
        runtime=active_runtime,
        default_testbed=common.testbed_path_for_runtime(active_runtime),
        active_testbed=testbed,
        tiers=active_tiers,
        suite=suite,
        datafile=datafile,
        max_failures=max_failures,
    )

    kwargs: dict[str, object] = {
        "testscript": suite,
        "datafile": datafile,
        "testbed": testbed,
    }
    if max_failures:
        kwargs["max_failures"] = max_failures
    groups = common.groups_filter_from_env()
    if groups:
        kwargs["groups"] = groups
        log.info("Groups filter:   %s (from MYCELIUM_E2E_GROUPS)", groups)

    run(**kwargs)
