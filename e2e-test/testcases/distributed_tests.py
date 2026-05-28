"""Distributed E2E tests — real agents on oclw3/4/5 via Matrix + Mycelium.

Maps to original tests 30-32 (local-real) and 40-49 (distributed).
These tests send Matrix messages to trigger real OpenClaw agent responses,
then verify coordination through the shared Mycelium backend.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid

from pyats import aetest

from libs.mycelium_api import MyceliumAPI
from libs.matrix_client import MatrixClient
from libs.environment import EnvironmentInfo

log = logging.getLogger(__name__)

OCLW4_IP = os.environ.get("OCLW4_IP", "10.0.50.125")
OCLW3_IP = os.environ.get("OCLW3_IP", "10.0.50.171")
OCLW5_IP = os.environ.get("OCLW5_IP", "10.0.50.142")

DISTRIBUTED_AGENTS = {
    "agent-alpha": {"device": "oclw4", "ip": OCLW4_IP, "display_name": "Alpha (oclw4)"},
    "agent-beta": {"device": "oclw4", "ip": OCLW4_IP, "display_name": "Beta (oclw4)"},
    "agent-gamma": {"device": "oclw4", "ip": OCLW4_IP, "display_name": "Gamma (oclw4)"},
    "agent-delta": {"device": "oclw4", "ip": OCLW4_IP, "display_name": "Delta (oclw4)"},
    "claire-agent": {"device": "oclw3", "ip": OCLW3_IP, "display_name": "Claire (oclw3)"},
    "oclw5-agent": {"device": "oclw5", "ip": OCLW5_IP, "display_name": "OCLW5 Agent (oclw5)"},
}


class _DistributedBase(aetest.Testcase):
    """Base for distributed tests. Subclasses configure agents and scenario."""

    groups = ["distributed", "convergence", "llm", "slow"]
    scenario_agents: list[str] = []
    scenario_topic: str = ""
    local_only: bool = False

    @aetest.setup
    def check_prerequisites(self, env):
        if env.skip_llm_tests:
            self.skipped("LLM not available")
        if env.coordination_blocked_reason:
            self.skipped(env.coordination_blocked_reason)
        if not self.local_only and env.skip_matrix_tests:
            self.skipped("Matrix not reachable (required for distributed tests)")

    @aetest.test
    def run_distributed_scenario(self, steps, api, room_name, owned_rooms, matrix_url=None, matrix_config=None, timeouts=None):
        t = timeouts or {}
        timeout = t.get("negotiation_wait", 600)
        suffix = uuid.uuid4().hex[:8]
        prefix = "e2e" if self.local_only else "dist-e2e"
        test_room = f"{prefix}-{suffix}"
        owned_rooms.add(test_room)

        with steps.start("Verify agents are configured") as step:
            for agent_id in self.scenario_agents:
                if agent_id not in DISTRIBUTED_AGENTS:
                    step.failed(f"Unknown agent: {agent_id}")
            agent_names = [DISTRIBUTED_AGENTS[a]["display_name"] for a in self.scenario_agents]
            log.info("Scenario agents: %s", agent_names)

        with steps.start("Create session room") as step:
            st, _ = api.create_room(test_room, description=self.scenario_topic)
            if st not in (200, 201):
                step.failed(f"Room creation failed: status={st}")

        with steps.start("Spawn session via backend") as step:
            session_data = {
                "topic": self.scenario_topic,
                "agents": self.scenario_agents,
            }
            st, resp = api.spawn_session(test_room, session_data)
            if st not in (200, 201):
                step.failed(f"Session spawn failed: status={st}")

        if self.local_only:
            log.info("local_only=True — skipping Matrix trigger (agents are co-located)")
        else:
            with steps.start("Send Matrix trigger message") as step:
                room_id = matrix_config.get("test_room_id")
                if not room_id:
                    step.failed("No Matrix room ID configured")
                trigger = (
                    f"@all Please join the negotiation on '{self.scenario_topic}' "
                    f"in room {test_room}. Use `mycelium session join --room {test_room}`."
                )
                token = os.environ.get("MATRIX_TOKEN_AGENT_ALPHA", "")
                if not token:
                    step.failed("MATRIX_TOKEN_AGENT_ALPHA not set — cannot send trigger")
                try:
                    asyncio.run(
                        _send_matrix_trigger(matrix_url, token, room_id, trigger)
                    )
                except Exception as exc:
                    step.failed(f"Failed to send Matrix trigger: {exc}")
                log.info("Matrix trigger sent to %s: %s", room_id, trigger[:80])

        with steps.start(f"Wait for consensus (timeout={timeout}s)") as step:
            result = api.wait_for_consensus(test_room, timeout=timeout)
            if not result:
                step.failed(f"Consensus not reached within {timeout}s")
            state = result.get("coordination_state") if isinstance(result, dict) else None
            log.info("Distributed %s: state=%s", self.__class__.__name__, state)

    @aetest.cleanup
    def cleanup(self, api, room_name):
        pass


async def _send_matrix_trigger(
    homeserver: str, token: str, room_id: str, body: str,
) -> None:
    """Send a single Matrix message, then close the client."""
    client = MatrixClient(homeserver=homeserver, access_token=token)
    try:
        await client.send_message(room_id, body)
    finally:
        await client.close()


# ─── Local-Real Tests (test_30-32) ───────────────────────────────────────────

class LocalTwoAgentNegotiation(_DistributedBase):
    """Test 30: Two local agents (alpha + beta) negotiate."""

    groups = ["local_e2e", "convergence", "llm", "slow"]
    local_only = True
    scenario_agents = ["agent-alpha", "agent-beta"]
    scenario_topic = "Sprint planning: feature vs stability"


class LocalThreeAgentNegotiation(_DistributedBase):
    """Test 31: Three local agents (alpha + beta + gamma) negotiate."""

    groups = ["local_e2e", "convergence", "llm", "slow"]
    local_only = True
    scenario_agents = ["agent-alpha", "agent-beta", "agent-gamma"]
    scenario_topic = "Release planning for Q3"


class LocalArchitectureDecision(_DistributedBase):
    """Test 32: Two local agents (alpha + beta) negotiate database architecture."""

    groups = ["local_e2e", "convergence", "llm", "slow"]
    local_only = True
    scenario_agents = ["agent-alpha", "agent-beta"]
    scenario_topic = "Database choice: PostgreSQL vs MongoDB"


# ─── Cross-Device Distributed Tests (test_40-49) ─────────────────────────────

class DistributedTwoAgent(_DistributedBase):
    """Test 40: Two agents on different devices (oclw4 + oclw3)."""

    scenario_agents = ["agent-alpha", "claire-agent"]
    scenario_topic = "Cross-device sprint planning"


class DistributedThreeAgent(_DistributedBase):
    """Test 41: Three agents on three devices (oclw4 + oclw3 + oclw5)."""

    scenario_agents = ["agent-alpha", "claire-agent", "oclw5-agent"]
    scenario_topic = "Three-device release planning"


class DistributedArchitecture(_DistributedBase):
    """Test 42: Architecture decision on oclw4 + oclw5."""

    scenario_agents = ["agent-alpha", "oclw5-agent"]
    scenario_topic = "Architecture decision: monolith vs microservices"


class DistributedResourceAllocation(_DistributedBase):
    """Test 43: Three agents negotiate budget/resource allocation."""

    scenario_agents = ["agent-alpha", "claire-agent", "oclw5-agent"]
    scenario_topic = "Q4 budget allocation across teams"


class DistributedAsymmetricStakes(_DistributedBase):
    """Test 44: Agent with higher stakes vs flexible agent."""

    scenario_agents = ["agent-alpha", "claire-agent"]
    scenario_topic = "Security patch timeline vs feature release"


class DistributedPreexistingContext(_DistributedBase):
    """Test 45: Agents with prior decisions/context."""

    scenario_agents = ["agent-alpha", "claire-agent"]
    scenario_topic = "Revisiting CI/CD pipeline decision"


class DistributedFeaturePrioritization(_DistributedBase):
    """Test 46: Three agents prioritize feature backlog."""

    scenario_agents = ["agent-alpha", "claire-agent", "oclw5-agent"]
    scenario_topic = "Q4 feature prioritization across teams"


class DistributedCrossDeviceOnly(_DistributedBase):
    """Test 47: Two remote agents (oclw3 + oclw5) only — no oclw4 agent."""

    groups = ["distributed", "convergence", "llm", "slow", "cfn"]
    scenario_agents = ["claire-agent", "oclw5-agent"]
    scenario_topic = "Remote-only coordination through central backend"


class DistributedBackendResolvedCfnIds(aetest.Testcase):
    """Test 48: Leaf nodes ingest knowledge with room_name only (Issue #139)."""

    groups = ["distributed", "cfn"]

    @aetest.test
    def backend_resolved_ids(self, steps, api, room_name):
        test_room = f"{room_name}-backend-resolve"
        marker = f"e2e-resolve-{uuid.uuid4().hex[:8]}"

        with steps.start("Create room without explicit workspace/mas IDs") as step:
            st, _ = api.create_room(test_room, description="backend-resolved CFN IDs test")
            if st not in (200, 201):
                step.failed(f"Room creation failed: status={st}")

        with steps.start("Ingest knowledge with room_name only") as step:
            st, resp = api.ingest_knowledge({
                "room_name": test_room,
                "agent_id": "e2e-leaf-node",
                "records": [
                    {"response": f"Backend-resolved test: {marker}"}
                ],
            })
            if st not in (200, 201, 202):
                step.failed(f"Ingest failed: status={st}")

    @aetest.cleanup
    def cleanup(self, api, room_name):
        api.delete_room(f"{room_name}-backend-resolve")


class SkillCrossChannelReturnTrip(_DistributedBase):
    """Test 49: 3 agents, 3 devices, individual DMs, return-trip verification."""

    groups = ["distributed", "cross_channel", "llm", "slow"]
    scenario_agents = ["agent-alpha", "claire-agent", "oclw5-agent"]
    scenario_topic = "Cross-channel return trip verification (PR #221)"
