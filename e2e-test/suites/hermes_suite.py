"""Hermes adapter E2E suite — gateway health and loop suppression.

Tests 85 and 89: cover the changes landed in mycelium-cli commit 28aca63
(PID file format tolerance, deque-based loop suppression).

Prerequisites:
  - hermes installed (``hermes`` on PATH of hub and spoke)
  - mycelium CLI up to date on all devices
  - hermes gateway running on hub (oclw4)
  - SSH key at $SSH_KEY_PATH (default: ~/.ssh/ioc.pem)

Run standalone:
    python suites/hermes_suite.py

Run via job:
    pyats run job jobs/hermes_job.py
"""

import logging
import os
import sys

from pyats import aetest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from testcases.hermes_tests import (
    HermesGatewayPidFormats,
    HermesLoopSuppression,
    HUB_HOST,
    SSH_KEY,
    SSH_USER,
)

log = logging.getLogger(__name__)


class CommonSetup(aetest.CommonSetup):
    @aetest.subsection
    def check_cli(self):
        import shutil
        if not shutil.which("mycelium"):
            self.failed("mycelium CLI not found on PATH")

    @aetest.subsection
    def check_ssh_key(self):
        key = os.path.expanduser(os.environ.get("SSH_KEY_PATH", "~/.ssh/ioc.pem"))
        if not os.path.exists(key):
            self.skipped(f"SSH key not found at {key} — set SSH_KEY_PATH")

    @aetest.subsection
    def check_hermes_prereqs(self, testscript):
        """Verify the hermes adapter is installed on the hub.

        Does not install anything — that is handled by
        ``scripts/provision_hermes_lab.py``.  Skips the suite with a clear
        message if prereqs are missing so CI catches the gap early.
        """
        from libs.hermes_lab import check_prereqs
        issues = check_prereqs(HUB_HOST, SSH_USER, SSH_KEY)
        if issues:
            self.skipped(
                "Hermes lab prerequisites not met — run scripts/provision_hermes_lab.py:\n"
                + "\n".join(f"  • {i}" for i in issues)
            )


class test_85_hermes_gateway_pid_formats(HermesGatewayPidFormats):
    pass

class test_89_hermes_loop_suppression(HermesLoopSuppression):
    pass


if __name__ == "__main__":
    aetest.main()
