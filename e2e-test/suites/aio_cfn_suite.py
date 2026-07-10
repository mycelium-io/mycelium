"""All-in-one CFN negotiation suite.

Runs every scenario row where **all** agents are assigned ``host: hub``.
No spoke devices required — designed for single-device validation of the
mycelium ↔ Go CFN negotiation path across adapter families.

Currently covers (``category: aio``, tier ``pr``):
  two-agent-aio-oc-he   — openclaw hub vs hermes hub
  two-agent-aio-cu-he   — cursor hub vs hermes hub
  two-agent-aio-cu-oc   — cursor hub vs openclaw hub
  two-agent-aio-he-he   — hermes hub vs hermes hub

Plus any existing hub-only rows (e.g. ``two-agent-consensus-broad-oc-oc``).

Run standalone:
    ./run_tests.sh aio_cfn

Run via job (compose testbed):
    pyats run job jobs/aio_cfn_job.py

Run via job (lab testbed, with oclw4 as hub):
    MYCELIUM_E2E_RUNTIME=lab pyats run job jobs/aio_cfn_job.py
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
from libs.scenario_row import agent_role  # noqa: E402
from libs.suite_lifecycle import setup_shared_suite_room, teardown_shared_suite_room  # noqa: E402
from libs.sessions import SessionError  # noqa: E402
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

# Hub-only: every agent on the row must have host == "hub"
_AIO_ROWS = filter_by_tier(
    [
        r
        for r in _ALL_ROWS
        if r.get("agents") and all(a.get("host") == "hub" for a in r["agents"])
    ],
    _ACTIVE_TIERS,
)

log.info(
    "aio_cfn_suite: %d hub-only rows active (tiers=%s)",
    len(_AIO_ROWS),
    sorted(_ACTIVE_TIERS),
)

_CLASSES = make_scenarios(_AIO_ROWS)


class CommonSetup(aetest.CommonSetup):
    @aetest.subsection
    def check_cli(self):
        import shutil

        if not shutil.which("mycelium"):
            self.failed("mycelium CLI not found on PATH")

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

    @aetest.subsection
    def provision_agents(self, testscript, testbed=None):
        """Ensure every hub agent the active rows need exists."""
        if os.environ.get("MYCELIUM_E2E_SKIP_AGENT_PROVISIONING", "").lower() in {
            "1", "true", "yes",
        }:
            testscript.parameters["provisioned_agents"] = {}
            self.skipped("MYCELIUM_E2E_SKIP_AGENT_PROVISIONING set")

        if not _AIO_ROWS:
            testscript.parameters["provisioned_agents"] = {}
            return

        if testbed is None:
            testscript.parameters["provisioned_agents"] = {}
            log.warning("aio_cfn_suite: no testbed — skipping agent provisioning")
            return

        wants: set[tuple[str, str, str]] = set()
        for row in _AIO_ROWS:
            for ag in row.get("agents", []):
                wants.add((ag["adapter"], agent_role(ag), ag["host"]))

        device = testbed.devices.get("hub")
        if device is not None:
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
                log.warning("chown pre-flight failed on hub (continuing): %s", exc)

        provisioned: dict[tuple[str, str, str], AgentRef] = {}
        failures: list[str] = []
        for adapter, role, host in sorted(wants):
            dev = testbed.devices.get(host)
            if dev is None:
                failures.append(f"{role}@{host}: no such device in testbed")
                continue
            try:
                provisioner = get_provisioner(adapter)
                provisioner.check_prereqs(dev)
                ref = provisioner.ensure_runtime(dev, role)
                provisioned[(adapter, role, host)] = ref
            except (PrereqMissing, HostExecError) as exc:
                failures.append(f"{role}@{host} ({adapter}): {exc}")

        testscript.parameters["provisioned_agents"] = provisioned
        if failures:
            self.failed(
                f"provision_agents: {len(failures)} agent(s) failed:\n  "
                + "\n  ".join(failures)
            )

        try:
            setup_shared_suite_room(
                testscript,
                testbed,
                wants,
                room_prefix="scn-aio",
            )
        except SessionError as exc:
            self.failed(f"setup_shared_suite_room: {exc}")


class CommonCleanup(aetest.CommonCleanup):
    @aetest.subsection
    def teardown_suite_room(self, testscript, testbed=None):
        if testbed is None:
            return
        backend_url = os.environ.get("MYCELIUM_BACKEND_URL")
        teardown_shared_suite_room(testscript, testbed, backend_url=backend_url)

    @aetest.subsection
    def teardown_agents(self, testscript, testbed=None):
        """Remove agents created this run (hermes and cursor are ephemeral)."""
        if os.environ.get("MYCELIUM_E2E_KEEP_AGENTS", "").lower() in {"1", "true", "yes"}:
            log.info("teardown_agents: skipped via MYCELIUM_E2E_KEEP_AGENTS")
            return

        provisioned: dict[tuple[str, str, str], AgentRef] = (
            testscript.parameters.get("provisioned_agents") or {}
        )
        if not provisioned or testbed is None:
            return

        for (adapter, role, host), ref in provisioned.items():
            dev = testbed.devices.get(host)
            if dev is None:
                continue
            try:
                provisioner = get_provisioner(adapter)
                provisioner.teardown_runtime(dev, ref)
            except Exception as exc:  # noqa: BLE001
                log.warning("teardown failed for %s@%s (%s): %s", role, host, adapter, exc)


globals().update(_CLASSES)
for _cls in _CLASSES.values():
    _cls.__module__ = __name__
    _cls.__qualname__ = _cls.__name__


if __name__ == "__main__":
    aetest.main()
