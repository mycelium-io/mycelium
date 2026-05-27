"""Cross-channel memory isolation tests.

Maps to original test 60.
"""

from __future__ import annotations

import logging
import time
import uuid

from pyats import aetest

from libs.mycelium_api import MyceliumAPI
from libs.mycelium_cli import MyceliumCLI
from libs.environment import EnvironmentInfo

log = logging.getLogger(__name__)


class CrossChannelMemoryIsolation(aetest.Testcase):
    """Test 60: Memory is isolated across channels; show bridging pattern."""

    groups = ["cross_channel", "local_e2e", "llm", "slow"]

    @aetest.setup
    def check_prerequisites(self, env):
        if env.skip_llm_tests:
            self.skipped("LLM not available")
        if env.coordination_blocked_reason:
            self.skipped(env.coordination_blocked_reason)

    @aetest.test
    def memory_isolation(self, steps, cli, api, room_name, owned_rooms):
        token = f"XCHECK-{uuid.uuid4().hex[:8]}"
        room_a = f"{room_name}-chan-a"
        room_b = f"{room_name}-chan-b"
        owned_rooms.update({room_a, room_b})

        with steps.start("Create channel A room") as step:
            r = cli.room_create(room_a)
            if not r.ok:
                step.failed(r.error_message)

        with steps.start("Create channel B room") as step:
            r = cli.room_create(room_b)
            if not r.ok:
                step.failed(r.error_message)

        with steps.start("Store token in channel A") as step:
            r = cli.memory_set(room_a, "agent-alpha", "cross-channel/token", f"Decision token: {token}")
            if not r.ok:
                step.failed(r.error_message)

        with steps.start("Verify token NOT visible in channel B") as step:
            r = cli.memory_search(room_b, token)
            if r.ok and token in r.stdout:
                step.failed(f"Token {token} leaked from channel A to channel B!")
            log.info("Memory isolation verified: token not found in channel B")

        with steps.start("Bridge token to channel B explicitly") as step:
            r = cli.memory_set(room_b, "bridge-agent", "bridged/token", f"Bridged from A: {token}")
            if not r.ok:
                step.failed(r.error_message)

        with steps.start("Verify bridged token in channel B") as step:
            r = cli.memory_search(room_b, token)
            if not r.ok or token not in r.stdout:
                step.failed("Bridged token not found in channel B")
            log.info("Bridging pattern verified")

    @aetest.cleanup
    def cleanup(self, api, room_name):
        for suffix in ("-chan-a", "-chan-b"):
            api.delete_room(f"{room_name}{suffix}")
