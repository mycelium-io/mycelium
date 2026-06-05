"""<PYATS_JOBFILE>

Nightly E2E job — PR canary + nightly tier scenarios (adapter-pair
coverage). Runs against the docker compose stack on a daily cron.

Default tier set: ``pr,nightly`` (8 rows). The PR tier is included so
the nightly run also catches anything that escaped a PR check, and so
"nightly green" is a strict superset of "PR green".

Usage
-----

    # Default — compose stack, pr+nightly tiers
    pyats run job jobs/nightly_e2e_job.py --testbed-file testbeds/compose.yaml

    # Lab override
    pyats run job jobs/nightly_e2e_job.py --testbed-file testbeds/lab.yaml

    # Only the new nightly rows (skip the PR canary):
    MYCELIUM_E2E_TIERS=nightly pyats run job jobs/nightly_e2e_job.py …

Same testscript as ``pr_job.py`` — the tier env var is the difference.
"""

from __future__ import annotations

import logging

from pyats.easypy import run

import jobs._common as common

log = logging.getLogger(__name__)


_DEFAULT_TIERS = "pr,nightly"
_DEFAULT_TESTBED = "testbeds/compose.yaml"
# Matrix suite uses parameters-only datafile — see comment in
# ``pr_job.py`` for the rationale.
_DEFAULT_DATAFILE = "scenarios_datafile.yaml"


def main(runtime):
    """Run the PR + nightly scenarios via easypy."""
    active_tiers = common.ensure_tier_env(_DEFAULT_TIERS)
    datafile = common.get_datafile(default=_DEFAULT_DATAFILE)
    suite = common.get_suite_path("scenarios_suite.py")
    max_failures = common.get_max_failures(datafile)
    testbed_hint = common.get_testbed_file(default=_DEFAULT_TESTBED)

    log.info("=== Mycelium Nightly E2E ===")
    log.info("Active tiers:    %s", active_tiers)
    log.info("Suite:           %s", suite)
    log.info("Datafile:        %s", datafile)
    log.info("Testbed (hint):  %s", testbed_hint or "<from --testbed-file>")
    log.info("Max failures:    %s", max_failures or "unlimited")

    kwargs: dict[str, object] = {
        "testscript": suite,
        "datafile": datafile,
    }
    if max_failures:
        kwargs["max_failures"] = max_failures

    run(**kwargs)
