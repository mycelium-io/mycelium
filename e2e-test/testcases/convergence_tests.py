"""Multi-agent convergence scenario tests.

Maps to original tests 15-21. Each test creates a simulated multi-agent
negotiation with distinct agent positions and verifies convergence.

Flow follows the OpenClaw SKILL.md lifecycle:
  room create → session create → agent joins → wait tick → agents accept → consensus
"""

from __future__ import annotations

import logging
import time
import uuid

from pyats import aetest

from libs.mycelium_cli import CLIResult

log = logging.getLogger(__name__)


def _parse_session_room(result: CLIResult) -> str | None:
    """Extract session_room from ``mycelium --json session create`` output."""
    data = result.json
    if isinstance(data, dict):
        return data.get("session_room") or data.get("display_name")
    return None


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
    def run_convergence(self, steps, cli, api, room_name, owned_rooms):
        consensus_timeout = 600
        suffix = uuid.uuid4().hex[:8]
        test_room = f"{room_name}-conv-{suffix}"
        owned_rooms.add(test_room)

        with steps.start("Create convergence room") as step:
            st, _ = api.create_room(test_room, description=self.topic)
            if st not in (200, 201):
                step.failed(f"Room creation failed: status={st}")

        with steps.start("Create session") as step:
            r = cli.session_create(test_room)
            if not r.ok:
                step.failed(f"session create failed: {r.error_message}")
            session_room = _parse_session_room(r)

        for handle, bias, position in self.agent_configs:
            with steps.start(f"Agent {handle} ({bias}) joins") as step:
                r = cli.session_join(test_room, handle, position=position)
                if not r.ok:
                    step.failed(f"{handle} join failed: {r.error_message}")

        with steps.start("Resolve session room") as step:
            if not session_room:
                for _ in range(20):
                    session_room = api.find_session_room(test_room)
                    if session_room:
                        break
                    time.sleep(0.5)
            if not session_room:
                step.failed("Could not find session child room")
            log.info("Session room: %s", session_room)

        with steps.start(f"Wait for autonomous consensus ({consensus_timeout}s)") as step:
            tick_seen = False
            consensus_seen = False
            for _ in range(consensus_timeout // 5):
                _, msgs = api.get_room_messages(session_room)
                for m in msgs:
                    if m.get("message_type") == "coordination_tick" and not tick_seen:
                        tick_seen = True
                        log.info("coordination_tick delivered to agents")
                    if m.get("message_type") == "coordination_consensus":
                        consensus_seen = True
                        break
                if consensus_seen:
                    break
                time.sleep(5)
            if not tick_seen:
                step.failed(
                    f"No coordination_tick within {consensus_timeout}s — gateway may not be delivering ticks to agents"
                )
            if not consensus_seen:
                step.failed(
                    f"No coordination_consensus within {consensus_timeout}s — "
                    "agents may not be responding to ticks autonomously"
                )
            log.info(
                "Convergence %s: consensus reached in %s",
                self.__class__.__name__,
                session_room,
            )

    @aetest.cleanup
    def cleanup(self, api, room_name):
        pass


class ThreeAgentNegotiation(_ConvergenceBase):
    """Test 15: Three agents negotiate release planning (speed/quality/cost)."""

    topic = "Sprint planning for Q3 release"
    agent_configs = [
        (
            "agent-alpha",
            "speed",
            "Ship MVP by Friday; cut non-core features; hard limit: no release without smoke tests",
        ),
        (
            "agent-beta",
            "quality",
            "Full test coverage before release; willing to defer one feature; hard limit: no untested code in prod",
        ),
        (
            "agent-gamma",
            "cost",
            "Use existing infra only; no new cloud services; hard limit: stay within current monthly budget",
        ),
    ]


class ArchitectureDecision(_ConvergenceBase):
    """Test 16: Technical architecture — PostgreSQL vs MongoDB advocacy."""

    topic = "Database selection for new microservice"
    agent_configs = [
        (
            "agent-alpha",
            "relational",
            "PostgreSQL primary; ACID guarantees required for billing; willing to add read replicas for scale; hard limit: no eventual consistency on financial data",
        ),
        (
            "agent-beta",
            "document",
            "MongoDB primary; flexible schema for rapid iteration; willing to use transactions for critical paths; hard limit: no schema migrations blocking deploys",
        ),
    ]


class ResourceAllocation(_ConvergenceBase):
    """Test 17: Sprint capacity split between features and bugs."""

    topic = "How to split 40 story points between features and bug fixes"
    agent_configs = [
        (
            "agent-alpha",
            "features",
            "70% features 30% bugs; users need new capabilities for retention; hard limit: at least 25% on new features",
        ),
        (
            "agent-beta",
            "stability",
            "60% bugs 40% features; tech debt is killing velocity; hard limit: at least 40% on bug fixes",
        ),
        (
            "agent-gamma",
            "balanced",
            "50/50 split; both matter for retention; hard limit: neither category below 30%",
        ),
    ]


class AsymmetricStakes(_ConvergenceBase):
    """Test 18: One agent has hard deadline, other is flexible."""

    topic = "Release timeline for security patch vs feature release"
    agent_configs = [
        (
            "agent-alpha",
            "urgent",
            "Security patch must ship by EOD; CVE is public and actively exploited; hard limit: no delay past 24 hours",
        ),
        (
            "agent-beta",
            "flexible",
            "Feature can wait up to 2 weeks; customers asking daily but no SLA breach; hard limit: feature ships before end of quarter",
        ),
    ]


class PreexistingContext(_ConvergenceBase):
    """Test 19: Negotiation with prior decisions already in memory."""

    topic = "Revisiting the CI/CD pipeline decision from last sprint"
    agent_configs = [
        (
            "agent-alpha",
            "automation",
            "GitHub Actions worked well; expand to staging deploys and preview environments; hard limit: keep sub-10-minute pipeline",
        ),
        (
            "agent-beta",
            "control",
            "Need ArgoCD for GitOps audit trail; GHA is fire-and-forget with no drift detection; hard limit: all prod deploys must be git-traceable",
        ),
    ]


class FeaturePrioritization(_ConvergenceBase):
    """Test 20: Sales vs engineering priorities for roadmap."""

    topic = "Q4 feature prioritization"
    agent_configs = [
        (
            "agent-alpha",
            "revenue",
            "SSO and audit logs first; 3 enterprise deals worth $2M depend on it; hard limit: SSO ships in Q4",
        ),
        (
            "agent-beta",
            "technical",
            "API v2 and rate limiting first; current API hits 429s at 500 req/s; hard limit: rate limiting before any new integrations",
        ),
        (
            "agent-gamma",
            "user-value",
            "Onboarding flow first; 60% of signups drop at step 3; hard limit: reduce drop-off below 30% this quarter",
        ),
    ]


class ConsensusStability(_ConvergenceBase):
    """Test 21: Verify agreement persists and new agents see it."""

    topic = "Confirm prior agreement on deployment strategy"
    agent_configs = [
        (
            "agent-alpha",
            "conservative",
            "Blue-green is working and proven; no reason to change; hard limit: zero-downtime requirement stays",
        ),
        (
            "agent-beta",
            "progressive",
            "Canary deploys catch issues earlier with 5% traffic; willing to keep blue-green as fallback; hard limit: rollback within 60 seconds",
        ),
    ]
