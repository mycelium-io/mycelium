"""Canary job — Tier C (live agent multi-episode).

Manual trigger or weekly cron. Requires live LLM.
NEVER blocks release — informational / compatibility telemetry only.

Usage:
  pyats run job jobs/canary_job.py --datafile data/canary_datafile.yaml

  Environment:
    LLM_API_KEY / LLM_BASE_URL / LLM_MODEL — required for live agents
    MYCELIUM_CANARY_ROOM — override the room name (default: api-design-review)
    MYCELIUM_E2E_NO_CLEANUP=1 — preserve room state after the run
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
    datafile = get_datafile(default="canary_datafile.yaml")
    install_job_sigint_cleanup(resolve_backend_url(datafile))

    log.info("=== Canary Job — Tier C (live agent, multi-episode) ===")
    log.info("Datafile: %s", datafile)
    log.info(
        "NOTE: Tier C results are INFORMATIONAL ONLY. Failures do not block release."
    )

    suite_path = os.path.join(root, "suites", "canary_suite.py")
    run(testscript=suite_path, datafile=datafile)
