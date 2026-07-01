"""<PYATS_JOBFILE>

Nightly E2E job — PR canary + nightly tier scenarios (adapter-pair
coverage). Runs against the docker compose stack on a daily cron.

**Runtime:** same resolution as ``pr_job`` (``MYCELIUM_E2E_RUNTIME`` /
``GITHUB_ACTIONS`` / job default). Permitted: compose and lab.

Default tier set: ``pr,nightly`` (8 rows). The PR tier is included so
the nightly run also catches anything that escaped a PR check, and so
"nightly green" is a strict superset of "PR green".

Usage
-----

    # Default
    pyats run job jobs/nightly_e2e_job.py

    # Lab box:
    MYCELIUM_E2E_RUNTIME=lab pyats run job jobs/nightly_e2e_job.py

    # Only the new nightly rows (skip the PR canary):
    MYCELIUM_E2E_TIERS=nightly pyats run job jobs/nightly_e2e_job.py …

    # Filter to openclaw-tagged scenarios (cross-family rows included):
    MYCELIUM_E2E_GROUPS=openclaw pyats run job jobs/nightly_e2e_job.py …

    # Same filter via pyATS logic syntax (note the quotes):
    pyats run job jobs/nightly_e2e_job.py --groups "Or('openclaw')"

Same testscript as ``pr_job.py`` — the tier env var is the difference.
"""

from __future__ import annotations

import logging

from pyats.easypy import run

import jobs._common as common

log = logging.getLogger(__name__)


_DEFAULT_TIERS = "pr,nightly"
_DEFAULT_RUNTIME = common.RUNTIME_COMPOSE
_ALLOWED_RUNTIMES = common.RUNTIMES_ALL
# Matrix suite uses parameters-only datafile — see comment in
# ``pr_job.py`` for the rationale.
_DEFAULT_DATAFILE = "scenarios_datafile.yaml"


def main(runtime):
    """Run the PR + nightly scenarios via easypy."""
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
        title="Mycelium Nightly E2E",
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
