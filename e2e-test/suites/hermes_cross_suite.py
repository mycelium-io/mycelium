"""Hermes cross-family negotiation suite.

Loads all rows from ``data/scenarios.yaml`` where at least one agent uses
the hermes adapter and at least one uses a different adapter (openclaw or
cursor), filtered to the active tiers (``MYCELIUM_E2E_TIERS``).

Currently covers:
  nightly  — TwoAgentConsensus_oc_he  (two-agent-consensus-oc-he)
             TwoAgentConsensus_cu_he  (two-agent-consensus-cu-he)
             ThreeAgentConsensus_oc_cu_he  (three-agent-consensus-oc-cu-he)
  weekly   — TwoAgentConsensus_he_oc  (two-agent-consensus-he-oc)
             TwoAgentConsensus_he_cu  (two-agent-consensus-he-cu)

Run via job:
    pyats run job jobs/hermes_job.py --testbed-file testbeds/lab.yaml
"""

from __future__ import annotations

import logging
import os
import sys

from pyats import aetest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from libs import host_exec  # noqa: E402
from libs.host_exec import HostExecError  # noqa: E402
from libs.provisioners import AgentRef, PrereqMissing, get_provisioner  # noqa: E402
from testcases.hermes_tests import HUB_HOST, SSH_KEY, SSH_USER  # noqa: E402
from testcases.scenarios import (  # noqa: E402
    active_tiers,
    filter_by_tier,
    load_rows,
    make_scenarios,
)

log = logging.getLogger(__name__)

_SCENARIOS_FILE = os.environ.get(
    "MYCELIUM_E2E_SCENARIOS_FILE",
    os.path.join(_ROOT, "data", "scenarios.yaml"),
)

_ALL_ROWS = load_rows(_SCENARIOS_FILE)
_ACTIVE_TIERS = active_tiers()
_CROSS_ROWS = filter_by_tier(
    [
        r
        for r in _ALL_ROWS
        if (any(a["adapter"] == "hermes" for a in r["agents"]) and len({a["adapter"] for a in r["agents"]}) > 1)
    ],
    _ACTIVE_TIERS,
)

log.info(
    "hermes_cross_suite: %d cross-family rows active (tiers=%s)",
    len(_CROSS_ROWS),
    sorted(_ACTIVE_TIERS),
)

_CLASSES = make_scenarios(_CROSS_ROWS)


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
    def check_hermes_prereqs(self):
        from libs.hermes_lab import check_prereqs

        issues = check_prereqs(HUB_HOST, SSH_USER, SSH_KEY)
        if issues:
            self.skipped(
                "Hermes lab prerequisites not met — run scripts/provision_hermes_lab.py:\n"
                + "\n".join(f"  • {i}" for i in issues)
            )

    @aetest.subsection
    def provision_agents(self, testscript, testbed=None):
        """Ensure every agent the active cross-family rows need is created."""
        if os.environ.get("MYCELIUM_E2E_SKIP_AGENT_PROVISIONING", "").lower() in {
            "1",
            "true",
            "yes",
        }:
            testscript.parameters["provisioned_agents"] = {}
            self.skipped("MYCELIUM_E2E_SKIP_AGENT_PROVISIONING set")

        if testbed is None:
            self.skipped("no testbed; agent provisioning needs device handles")

        if not _CROSS_ROWS:
            testscript.parameters["provisioned_agents"] = {}
            return

        wants: set[tuple[str, str, str]] = set()
        for row in _CROSS_ROWS:
            for ag in row.get("agents", []):
                wants.add((ag["adapter"], ag["handle"], ag["host"]))

        for host in sorted({h for (_, _, h) in wants}):
            device = testbed.devices.get(host)
            if device is None:
                continue
            try:
                host_exec.execute(
                    device,
                    'if [ -d "$HOME/.mycelium" ]; then '
                    'sudo chown -R "$USER:$USER" "$HOME/.mycelium" '
                    "2>/dev/null || true; fi",
                    shell=True,
                    timeout=20.0,
                )
            except HostExecError as exc:
                log.warning("chown failed on %s (continuing): %s", host, exc)

        provisioned: dict[tuple[str, str, str], AgentRef] = {}
        failures: list[str] = []
        for adapter, handle, host in sorted(wants):
            device = testbed.devices.get(host)
            if device is None:
                failures.append(f"{handle}@{host}: no such device in testbed")
                continue
            try:
                provisioner = get_provisioner(adapter)
                provisioner.check_prereqs(device)
                ref = provisioner.ensure_runtime(device, handle)
                provisioned[(adapter, handle, host)] = ref
            except (PrereqMissing, HostExecError) as exc:
                failures.append(f"{handle}@{host} ({adapter}): {exc}")

        testscript.parameters["provisioned_agents"] = provisioned
        if failures:
            self.failed(f"provision_agents: {len(failures)} agent(s) failed:\n  " + "\n  ".join(failures))


class CommonCleanup(aetest.CommonCleanup):
    @aetest.subsection
    def teardown_hermes_agents(self, testscript, testbed=None):
        """Remove hermes agents that were created (not pre-existing) this run."""
        if os.environ.get("MYCELIUM_E2E_KEEP_AGENTS", "").lower() in {"1", "true", "yes"}:
            log.info("teardown_hermes_agents: skipped via MYCELIUM_E2E_KEEP_AGENTS")
            return

        provisioned: dict[tuple[str, str, str], AgentRef] = testscript.parameters.get("provisioned_agents") or {}
        if not provisioned:
            return

        if testbed is None:
            log.warning("teardown_hermes_agents: no testbed; skipping teardown")
            return

        for (adapter, handle, host), ref in provisioned.items():
            if adapter != "hermes":
                continue
            device = testbed.devices.get(host)
            if device is None:
                log.warning("teardown_hermes_agents: device %r not in testbed; skipping %s", host, handle)
                continue
            try:
                provisioner = get_provisioner(adapter)
                provisioner.teardown_runtime(device, ref)
            except Exception as exc:  # noqa: BLE001 - cleanup is best-effort
                log.warning("teardown_hermes_agents: teardown failed for %s@%s: %s", handle, host, exc)


globals().update(_CLASSES)
for _cls in _CLASSES.values():
    _cls.__module__ = __name__
    _cls.__qualname__ = _cls.__name__


if __name__ == "__main__":
    aetest.main()
