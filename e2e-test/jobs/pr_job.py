"""<PYATS_JOBFILE>

PR canary job — runs the **pr-tier** scenarios against the docker
compose stack inside a 30-minute budget.

This is the gate that fires on every PR + every push to a non-main
branch. The default tier set is ``pr`` (3 broad-coverage rows in
``data/scenarios.yaml``). Override with ``MYCELIUM_E2E_TIERS=…`` for
ad-hoc local runs.

Usage
-----

    # Default — compose stack, pr tier
    pyats run job jobs/pr_job.py --testbed-file testbeds/compose.yaml

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
_DEFAULT_TESTBED = "testbeds/compose.yaml"
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
    testbed_hint = common.get_testbed_file(default=_DEFAULT_TESTBED)

    log.info("=== Mycelium PR Canary ===")
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
