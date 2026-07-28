"""Shared CommonSetup base for hermes-containing suites.

Provides check_cli, check_ssh_key, check_hermes_prereqs, and check_cfn
subsections that every hermes suite needs. Subclass this instead of
duplicating the four checks across hermes_he_suite, hermes_cross_suite,
and future hermes variants.
"""

from __future__ import annotations

import logging
import os

from pyats import aetest

log = logging.getLogger(__name__)


class HermesPrereqCommonSetup(aetest.CommonSetup):
    """CommonSetup base for suites that require hermes lab prerequisites."""

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
        from libs.hermes_lab import check_prereqs
        from testcases.hermes_tests import HUB_HOST, SSH_KEY, SSH_USER

        issues = check_prereqs(HUB_HOST, SSH_USER, SSH_KEY)
        if issues:
            self.failed(
                "Hermes lab prerequisites not met — run scripts/provision_hermes_lab.py:\n"
                + "\n".join(f"  • {i}" for i in issues),
                goto=["common_cleanup"],
            )

    @aetest.subsection
    def check_cfn(self):
        """Verify the Go CFN stack is reachable before running negotiation tests."""
        import urllib.request

        cfn_url = os.environ.get("CFN_SVC_URL", "http://localhost:9002")
        health = f"{cfn_url.rstrip('/')}/api/internal/diagnostics/health"
        try:
            with urllib.request.urlopen(health, timeout=5) as resp:
                if resp.status not in (200, 204):
                    self.skipped(f"CFN node svc not healthy at {health} (status {resp.status})")
        except Exception as exc:
            self.skipped(f"CFN node svc unreachable at {health}: {exc}")
