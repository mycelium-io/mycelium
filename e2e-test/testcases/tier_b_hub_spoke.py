"""Tier B — Hub-and-spoke coordination tests.

Gates: nightly. Requires spoke devices in testbed (skips on local.yaml).
Stubs respond mechanically via host_exec on each device by default — no
real LLM needed. Set MYCELIUM_E2E_USE_CURSOR_STUBS=1 (with CURSOR_API_KEY
set) to swap in real cursor-agent-generated replies instead — see
_use_cursor() and libs/remote_stub.py's RemoteStubAgent(use_cursor=...).

Tests:
  HUB01 - Hub stub + spoke1 stub → converged (two-node)
  HUB02 - Hub stub + spoke1 stub + spoke2 stub → converged (three-node)

The key protocol assertion: ticks addressed to a stub on spoke1 (a separate
process/container) are correctly delivered and replied to across the network.
await/respond are stateless HTTP — the spoke needs no SLIM connectivity,
only HTTP to the backend.
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from pyats import aetest

from libs.coordination_flow import (
    collect_debug_info,
    setup_coordination,
)
from libs.mycelium_api import MyceliumAPI
from libs.mycelium_cli import MyceliumCLI
from libs.remote_stub import RemoteStubAgent, RemoteStubRunResult, run_remote_stubs_until_terminal
from testcases.common_setup_cleanup import require_devices

log = logging.getLogger(__name__)

parameters = {}

_STUB_TOTAL_TIMEOUT = 180
_TURN_TIMEOUT = 60
_JOIN_WAIT = 10
_MAX_ROUNDS = 20

_POS_HUB = "I propose we standardise on a 30-day log retention window."
_POS_SPOKE1 = "I believe 90-day retention is required for compliance."
_POS_SPOKE2 = "I suggest 60-day retention as a balanced compromise."


def _fresh_room() -> str:
    return f"qa-coord-fresh-hs-{uuid.uuid4().hex[:8]}"


def _use_cursor() -> bool:
    """Opt-in flag: drive stub replies with a real cursor-agent call.

    Defaults off — the scripted accept/reject/counter prose these tests
    were built and stabilized against is deterministic and doesn't need
    an LLM or CURSOR_API_KEY. Set MYCELIUM_E2E_USE_CURSOR_STUBS=1 to swap
    in real cursor-agent-generated replies on hub + spoke devices (see
    libs/remote_stub.py's RemoteStubAgent(use_cursor=...)).
    """
    return os.environ.get("MYCELIUM_E2E_USE_CURSOR_STUBS", "").strip().lower() in ("1", "true", "yes")


class TwoNodeHubSpoke(aetest.Testcase):
    """HUB01 — Hub stub + spoke1 stub → converged."""

    uid = "tier_b_HUB01"

    @aetest.setup
    def setup(self, api: MyceliumAPI, cli: MyceliumCLI, testscript):
        require_devices(self, testscript, "spoke1")

        self.room = _fresh_room()
        testscript.parameters.setdefault("owned_rooms", set()).add(self.room)
        api.create_room(self.room, description="Hub+spoke1 stub coordination")

        devices = testscript.parameters.get("testbed_devices", {})
        testbed = testscript.parameters.get("testbed")
        self.hub_device = testbed.devices["hub"] if testbed else None
        self.spoke1_device = testbed.devices["spoke1"] if testbed else None

        self.coord = setup_coordination(
            api, cli, self.room,
            agent_handles=["stub-hub", "stub-spoke1"],
            opening_positions={
                "stub-hub": _POS_HUB,
                "stub-spoke1": _POS_SPOKE1,
            },
        )
        if self.coord is None:
            self.failed("coordination setup failed")

    @aetest.test
    def two_node_converges(self, api: MyceliumAPI, cli: MyceliumCLI):
        # backend_url from spoke device custom block — correct URL from inside the container
        spoke1_url = self._device_backend_url(self.spoke1_device)
        use_cursor = _use_cursor()
        stubs = [
            RemoteStubAgent(self.hub_device, self.room, "stub-hub", action="accept",
                            use_cursor=use_cursor),
            RemoteStubAgent(self.spoke1_device, self.room, "stub-spoke1", action="accept",
                            backend_url=spoke1_url, use_cursor=use_cursor),
        ]
        run_result = run_remote_stubs_until_terminal(
            api, stubs, setup=self.coord, cli=cli,
            max_rounds=_MAX_ROUNDS, turn_timeout=_TURN_TIMEOUT,
            join_wait=_JOIN_WAIT, total_timeout=_STUB_TOTAL_TIMEOUT,
        )
        self._assert_result(run_result)

    @staticmethod
    def _device_backend_url(device: Any) -> str:
        """Read backend_url from device custom block (correct URL for that transport)."""
        if device is None:
            return ""
        custom = getattr(device, "custom", None) or {}
        if hasattr(custom, "get"):
            return custom.get("backend_url", "") or ""
        return ""

    def _assert_result(self, r: RemoteStubRunResult) -> None:
        if r.timed_out:
            self.failed(f"TIMEOUT: no terminal state within {_STUB_TOTAL_TIMEOUT}s")
        assert r.terminal is not None, "No terminal state detected"
        log.info(
            "Hub-spoke: subkind=%s converged=%s response_rate=%.0f%% turns=%d",
            r.terminal.get("subkind"), r.converged,
            r.response_rate * 100, len(r.turns),
        )
        # Gate: every stub responded to every tick
        silent = [t for t in r.turns if not t.ok]
        assert not silent, (
            f"SILENT turns: {[(t.handle, t.device, t.round_num) for t in silent]}"
        )

    @aetest.cleanup
    def teardown(self, api: MyceliumAPI):
        api.delete_room(self.room)


class ThreeNodeHubSpoke(aetest.Testcase):
    """HUB02 — Hub stub + spoke1 stub + spoke2 stub → terminal state."""

    uid = "tier_b_HUB02"

    @aetest.setup
    def setup(self, api: MyceliumAPI, cli: MyceliumCLI, testscript):
        require_devices(self, testscript, "spoke1", "spoke2")

        self.room = _fresh_room()
        testscript.parameters.setdefault("owned_rooms", set()).add(self.room)
        api.create_room(self.room, description="Hub+spoke1+spoke2 stub coordination")

        testbed = testscript.parameters.get("testbed")
        self.hub_device = testbed.devices["hub"] if testbed else None
        self.spoke1_device = testbed.devices["spoke1"] if testbed else None
        self.spoke2_device = testbed.devices["spoke2"] if testbed else None

        self.coord = setup_coordination(
            api, cli, self.room,
            agent_handles=["stub-hub", "stub-spoke1", "stub-spoke2"],
            opening_positions={
                "stub-hub": _POS_HUB,
                "stub-spoke1": _POS_SPOKE1,
                "stub-spoke2": _POS_SPOKE2,
            },
        )
        if self.coord is None:
            self.failed("coordination setup failed")

    @aetest.test
    def three_node_reaches_terminal(self, api: MyceliumAPI, cli: MyceliumCLI):
        spoke1_url = TwoNodeHubSpoke._device_backend_url(self.spoke1_device)
        spoke2_url = TwoNodeHubSpoke._device_backend_url(self.spoke2_device)
        use_cursor = _use_cursor()
        stubs = [
            RemoteStubAgent(self.hub_device, self.room, "stub-hub", action="accept",
                            use_cursor=use_cursor),
            RemoteStubAgent(self.spoke1_device, self.room, "stub-spoke1", action="accept",
                            backend_url=spoke1_url, use_cursor=use_cursor),
            RemoteStubAgent(self.spoke2_device, self.room, "stub-spoke2", action="accept",
                            backend_url=spoke2_url, use_cursor=use_cursor),
        ]
        run_result = run_remote_stubs_until_terminal(
            api, stubs, setup=self.coord, cli=cli,
            max_rounds=_MAX_ROUNDS, turn_timeout=_TURN_TIMEOUT,
            join_wait=_JOIN_WAIT, total_timeout=_STUB_TOTAL_TIMEOUT,
        )

        if run_result.timed_out:
            self.failed(f"TIMEOUT: three-node session did not terminate in {_STUB_TOTAL_TIMEOUT}s")
        assert run_result.terminal is not None

        silent = [t for t in run_result.turns if not t.ok]
        log.info(
            "Three-node: subkind=%s response_rate=%.0f%% silent=%d",
            run_result.terminal.get("subkind"),
            run_result.response_rate * 100,
            len(silent),
        )
        assert not silent, (
            f"SILENT turns from remote stubs: "
            f"{[(t.handle, t.device, t.round_num) for t in silent]}"
        )

    @aetest.cleanup
    def teardown(self, api: MyceliumAPI):
        api.delete_room(self.room)
