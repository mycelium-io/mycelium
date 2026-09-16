"""Distributed E2E tests — real agents on oclw3/4/5 via Matrix + Mycelium.

Maps to original tests 30-32 (local-real) and 40-49 (hub_and_spoke).
These tests send Matrix messages to trigger real OpenClaw agent responses,
then verify coordination through the shared Mycelium backend.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid

from pyats import aetest

from jobs._common import keep_rooms, no_cleanup
from libs.matrix_client import MatrixClient

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
    """Base for hub_and_spoke tests. Subclasses configure agents and scenario."""

    groups = ["hub_and_spoke", "convergence", "llm", "slow"]
    scenario_agents: list[str] = []
    scenario_topic: str = ""
    local_only: bool = False

    @aetest.setup
    def check_prerequisites(self, env, matrix_url=None, matrix_token_agent_alpha=None):
        if env.skip_llm_tests:
            self.skipped("LLM not available")
        if env.coordination_blocked_reason:
            self.skipped(env.coordination_blocked_reason)
        if not self.local_only:
            # Re-probe Matrix at testcase time — the suite-level check runs once
            # at startup and may be stale if Matrix went down (or was never up).
            from libs.matrix_client import check_matrix_reachable
            if not matrix_url or not check_matrix_reachable(matrix_url):
                self.skipped(
                    f"Matrix not reachable at testcase time (url={matrix_url!r}) "
                    "— required for hub_and_spoke tests"
                )
            # matrix_token_agent_alpha is provisioned by CommonSetup.provision_matrix_tokens.
            # Check here (not just in the send step) so a missing token skips rather than fails,
            # avoiding max_failures cascade onto unrelated testcases.
            if not matrix_token_agent_alpha:
                self.skipped(
                    "No Matrix token for agent-alpha — cannot send trigger "
                    "(set MATRIX_SHARED_SECRET or MATRIX_TOKEN_AGENT_ALPHA)"
                )

    @aetest.test
    def run_distributed_scenario(
        self, steps, api, cli, room_name, owned_rooms, matrix_url=None, matrix_config=None, timeouts=None,
        matrix_token_agent_alpha=None, matrix_token_trigger_sender=None,
    ):
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
            with steps.start("Join agents via CLI (local — no Matrix trigger)") as step:
                # For local-only runs there is no Matrix message to tell agents to join.
                # Join each agent directly; the daemon then delivers CFN ticks and
                # the agents respond autonomously via their adapter.
                positions = [
                    f"Agent {DISTRIBUTED_AGENTS[a]['display_name']}: ready to negotiate on '{self.scenario_topic}'"
                    for a in self.scenario_agents
                ]
                for agent_id, position in zip(self.scenario_agents, positions):
                    jr = cli.session_join(test_room, agent_id, position=position)
                    if not jr.ok:
                        step.failed(f"session join failed for {agent_id}: {jr.error_message}")
                    log.info("Joined %s in %s", agent_id, test_room)
        else:
            with steps.start("Send Matrix trigger message") as step:
                room_id = matrix_config.get("test_room_id")
                if not room_id:
                    step.failed("No Matrix room ID configured")
                # Derive Synapse server_name from room_id (e.g. "!hash:local" → "local").
                server_name = room_id.split(":", 1)[1] if ":" in room_id else "local"
                # Build proper Matrix @mentions so agents with requireMention=true respond.
                mention_parts_plain = [f"@{a}:{server_name}" for a in self.scenario_agents]
                mention_parts_html = [
                    f'<a href="https://matrix.to/#/@{a}:{server_name}">@{a}</a>'
                    for a in self.scenario_agents
                ]
                trigger_plain = (
                    f"{' '.join(mention_parts_plain)} Please join the negotiation on "
                    f"'{self.scenario_topic}' in room {test_room}. "
                    f"Use `mycelium session join --room {test_room}`."
                )
                trigger_html = (
                    f"{' '.join(mention_parts_html)} Please join the negotiation on "
                    f"'{self.scenario_topic}' in room <code>{test_room}</code>. "
                    f"Use <code>mycelium session join --room {test_room}</code>."
                )
                # Use the neutral sender token (test-observer) so the trigger is
                # NOT sent as agent-alpha. The gateway suppresses echo events —
                # a trigger sent AS agent-alpha would be silently dropped for
                # agent-alpha's own Matrix sync loop.
                token = matrix_token_trigger_sender or matrix_token_agent_alpha or ""
                if not token:
                    step.failed("No Matrix token for trigger sender (should have been caught in check_prerequisites)")
                mention_user_ids = [f"@{a}:{server_name}" for a in self.scenario_agents]
                try:
                    asyncio.run(_send_matrix_trigger(
                        matrix_url, token, room_id,
                        trigger_plain, trigger_html,
                        mention_user_ids=mention_user_ids,
                    ))
                except Exception as exc:
                    step.failed(f"Failed to send Matrix trigger: {exc}")
                log.info("Matrix trigger sent to %s: %s", room_id, trigger_plain[:100])

        with steps.start(f"Poll for consensus (timeout={timeout}s)") as step:
            result = api.poll_for_consensus(test_room, timeout=timeout)
            if not result:
                step.failed(f"Consensus not reached within {timeout}s")
            state = result.get("coordination_state") if isinstance(result, dict) else None
            log.info("Distributed %s: state=%s", self.__class__.__name__, state)
            if state in ("failed", "aborted"):
                step.failed(f"Negotiation ended with state={state}")
            if state != "complete":
                step.failed(f"Unexpected coordination state: {state}")

    @aetest.cleanup
    def cleanup(self, api, room_name):
        pass


async def _send_matrix_trigger(
    homeserver: str,
    token: str,
    room_id: str,
    body: str,
    formatted_body: str | None = None,
    mention_user_ids: list | None = None,
) -> None:
    """Send a Matrix message with HTML formatting and explicit m.mentions."""
    client = MatrixClient(homeserver=homeserver, access_token=token)
    try:
        await client.send_message(
            room_id, body,
            formatted_body=formatted_body,
            mention_user_ids=mention_user_ids,
        )
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

    groups = ["hub_and_spoke", "convergence", "llm", "slow", "cfn"]
    scenario_agents = ["claire-agent", "oclw5-agent"]
    scenario_topic = "Remote-only coordination through central backend"


class DistributedBackendResolvedCfnIds(aetest.Testcase):
    """Test 48: Leaf nodes ingest knowledge with room_name only (Issue #139)."""

    groups = ["hub_and_spoke", "cfn"]

    @aetest.test
    def backend_resolved_ids(self, steps, api, room_name):
        test_room = f"{room_name}-backend-resolve"
        marker = f"e2e-resolve-{uuid.uuid4().hex[:8]}"

        with steps.start("Create room without explicit workspace/mas IDs") as step:
            st, _ = api.create_room(test_room, description="backend-resolved CFN IDs test")
            if st not in (200, 201):
                step.failed(f"Room creation failed: status={st}")

        with steps.start("Ingest knowledge with room_name only") as step:
            st, resp = api.ingest_knowledge(
                {
                    "room_name": test_room,
                    "agent_id": "e2e-leaf-node",
                    "records": [{"response": f"Backend-resolved test: {marker}"}],
                }
            )
            if st not in (200, 201, 202):
                log.error("Knowledge ingest body: %s", resp)
                step.failed(f"Ingest failed: status={st}: {resp}")

    @aetest.cleanup
    def cleanup(self, api, room_name):
        if no_cleanup():
            self.skipped("MYCELIUM_E2E_NO_CLEANUP is set — teardown skipped")
            return
        if keep_rooms():
            self.skipped("MYCELIUM_E2E_KEEP_ROOMS is set — room preserved")
            return
        api.delete_room(f"{room_name}-backend-resolve")


class SkillCrossChannelReturnTrip(_DistributedBase):
    """Test 49: 3 agents, 3 devices, individual DMs, return-trip verification."""

    groups = ["hub_and_spoke", "cross_channel", "llm", "slow"]
    scenario_agents = ["agent-alpha", "claire-agent", "oclw5-agent"]
    scenario_topic = "Cross-channel return trip verification (PR #221)"
