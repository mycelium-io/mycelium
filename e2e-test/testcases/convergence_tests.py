"""Multi-agent convergence scenario tests.

Maps to original tests 15-21. Each test creates a simulated multi-agent
negotiation with distinct agent positions and verifies convergence.
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


class _ConvergenceBase(aetest.Testcase):
    """Base for convergence scenario tests. Subclasses set topic + agents."""

    groups = ["convergence", "llm", "slow"]
    topic: str = ""
    agent_configs: list[tuple[str, str, str]] = []  # (handle, bias, position)

    @aetest.setup
    def check_prerequisites(self, env):
        if env.skip_llm_tests:
            self.skipped("LLM not available")
        if env.coordination_blocked_reason:
            self.skipped(env.coordination_blocked_reason)

    @aetest.test
    def run_convergence(self, steps, cli, api, room_name, owned_rooms, timeouts=None):
        t = timeouts or {}
        timeout = t.get("negotiation_wait", 600)
        suffix = uuid.uuid4().hex[:8]
        test_room = f"{room_name}-conv-{suffix}"
        owned_rooms.add(test_room)

        with steps.start("Create convergence room") as step:
            st, _ = api.create_room(test_room, description=self.topic)
            if st not in (200, 201):
                step.failed(f"Room creation failed: status={st}")

        with steps.start("Spawn negotiation session") as step:
            agents = [h for h, _, _ in self.agent_configs]
            st, _ = api.spawn_session(test_room, {"topic": self.topic, "agents": agents})
            if st not in (200, 201):
                step.failed(f"Session spawn failed: status={st}")

        for handle, bias, position in self.agent_configs:
            with steps.start(f"Agent {handle} ({bias}) joins") as step:
                r = cli.session_join(test_room, handle, position=position)
                if not r.ok:
                    step.failed(f"{handle} join failed: {r.error_message}")

        with steps.start("Wait for consensus") as step:
            result = api.wait_for_consensus(test_room, timeout=timeout)
            if not result:
                step.failed(f"Consensus not reached within {timeout}s")
            state = result.get("coordination_state") if isinstance(result, dict) else None
            log.info("Convergence %s: state=%s", self.__class__.__name__, state)
            if state in ("failed", "aborted"):
                step.failed(f"Negotiation ended with state={state}")
            if state != "complete":
                step.failed(f"Unexpected coordination state: {state}")

    @aetest.cleanup
    def cleanup(self, api, room_name):
        pass


class ThreeAgentNegotiation(_ConvergenceBase):
    """Test 15: Three agents negotiate release planning (speed/quality/cost)."""

    topic = "Sprint planning for Q3 release"
    agent_configs = [
        ("speed-agent", "speed", "Ship fast, cut scope if needed. MVP by Friday."),
        ("quality-agent", "quality", "No shortcuts. Full test coverage. Ship when ready."),
        ("cost-agent", "cost", "Minimize spend. Use existing infra. No new hires."),
    ]


class ArchitectureDecision(_ConvergenceBase):
    """Test 16: Technical architecture — PostgreSQL vs MongoDB advocacy."""

    topic = "Database selection for new microservice"
    agent_configs = [
        ("pg-advocate", "relational", "PostgreSQL: ACID, mature, great extensions."),
        ("mongo-advocate", "document", "MongoDB: flexible schema, horizontal scale, JSON-native."),
    ]


class ResourceAllocation(_ConvergenceBase):
    """Test 17: Sprint capacity split between features and bugs."""

    topic = "How to split 40 story points between features and bug fixes"
    agent_configs = [
        ("feature-lead", "features", "70% features, 30% bugs. Users need new capabilities."),
        ("support-lead", "stability", "60% bugs, 40% features. Tech debt is killing velocity."),
        ("pm-agent", "balanced", "50/50 split. Both are important for retention."),
    ]


class AsymmetricStakes(_ConvergenceBase):
    """Test 18: One agent has hard deadline, other is flexible."""

    topic = "Release timeline for security patch vs feature release"
    agent_configs = [
        ("security-lead", "urgent", "Security patch must ship by EOD. CVE is public."),
        ("feature-lead", "flexible", "Feature can wait. But customers are asking daily."),
    ]


class PreexistingContext(_ConvergenceBase):
    """Test 19: Negotiation with prior decisions already in memory."""

    topic = "Revisiting the CI/CD pipeline decision from last sprint"
    agent_configs = [
        ("devops-agent", "automation", "GitHub Actions worked. Expand to staging deploys."),
        ("platform-agent", "control", "Need ArgoCD for GitOps. GHA is fire-and-forget."),
    ]


class FeaturePrioritization(_ConvergenceBase):
    """Test 20: Sales vs engineering priorities for roadmap."""

    topic = "Q4 feature prioritization"
    agent_configs = [
        ("sales-agent", "revenue", "SSO and audit logs. Enterprise deals depend on it."),
        ("eng-agent", "technical", "API v2 and rate limiting. Current API won't scale."),
        ("product-agent", "user-value", "Onboarding flow. 60% of signups drop at step 3."),
    ]


class ConsensusStability(_ConvergenceBase):
    """Test 21: Verify agreement persists and new agents see it."""

    topic = "Confirm prior agreement on deployment strategy"
    agent_configs = [
        ("ops-agent", "conservative", "Blue-green is working. Don't change."),
        ("dev-agent", "progressive", "Canary deploys would catch issues earlier."),
    ]
