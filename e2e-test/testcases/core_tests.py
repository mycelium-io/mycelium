"""Core Mycelium E2E tests: rooms, memory, CLI, sessions, search, synthesis.

Maps to original tests 01-06, 06b-06d, 11-14, 22.
"""

from __future__ import annotations

import logging
import time

from pyats import aetest

from libs.mycelium_api import MyceliumAPI
from libs.mycelium_cli import CLIResult, MyceliumCLI
from libs.environment import EnvironmentInfo

log = logging.getLogger(__name__)


def _parse_session_room(result: CLIResult) -> str | None:
    """Extract session_room from ``mycelium --json session create`` output."""
    data = result.json
    if isinstance(data, dict):
        return data.get("session_room") or data.get("display_name")
    return None


class RoomLifecycle(aetest.Testcase):
    """Test 01: Room create, use, list, delete via CLI.

    Creates a dedicated room (``{room_name}-lifecycle``) so it does not
    collide with the session-scoped room from CommonSetup.
    """

    groups = ["core", "sanity"]

    @aetest.setup
    def setup(self, api, cli, room_name):
        self.api = api
        self.cli = cli
        self.test_room = f"{room_name}-lifecycle"

    @aetest.test
    def create_room(self, steps):
        with steps.start("Create room via CLI") as step:
            r = self.cli.room_create(self.test_room)
            if not r.ok:
                step.failed(f"room create failed: {r.error_message}")

    @aetest.test
    def use_room(self, steps):
        with steps.start("Set active room via CLI") as step:
            r = self.cli.room_use(self.test_room)
            if not r.ok:
                step.failed(f"room use failed: {r.error_message}")

    @aetest.test
    def list_rooms(self, steps):
        with steps.start("Room appears in ls output") as step:
            r = self.cli.room_ls()
            if not r.ok:
                step.failed(f"room ls failed: {r.error_message}")
            if self.test_room not in r.stdout:
                step.failed(f"Room {self.test_room} not found in ls output")

    @aetest.cleanup
    def cleanup(self):
        self.api.delete_room(self.test_room)
        log.info("Deleted lifecycle test room: %s", self.test_room)


class MultiAgentMemory(aetest.Testcase):
    """Test 02: Store memories from 4 agents across categories."""

    groups = ["core", "sanity"]

    @aetest.test
    def store_memories(self, steps, cli, room_name, memories=None):
        default_memories = [
            ("alpha", "decisions/database", "Decided to use PostgreSQL for persistence."),
            ("alpha", "decisions/llm", "Using Claude Haiku for synthesis, Sonnet for complex reasoning."),
            ("beta", "status/frontend", "React 19 migration complete. Server components working."),
            ("beta", "work/tailwind-v4", "Upgraded to Tailwind v4. Removed autoprefixer."),
            ("gamma", "context/dep-updates", "Dependabot PRs: 3 pending. lodash is security-critical."),
            ("gamma", "decisions/no-autoprefixer", "Dropped autoprefixer from deps. Tailwind v4 includes it."),
            ("delta", "status/backend-deps", "All backend deps up to date. LiteLLM pinned to 1.55.3."),
            ("delta", "decisions/litellm-pin", "Pinned LiteLLM to 1.55.3. Version 1.56 broke streaming."),
        ]
        if memories:
            mem_list = [(m["agent"], m["key"], m["content"]) for m in memories]
        else:
            mem_list = default_memories

        for agent, key, content in mem_list:
            with steps.start(f"{agent}: {key}") as step:
                r = cli.memory_set(room_name, agent, key, content)
                if not r.ok:
                    step.failed(r.error_message)


class MemoryReads(aetest.Testcase):
    """Test 03: Read, list, filter memories."""

    groups = ["core", "sanity"]

    @aetest.test
    def get_single_memory(self, steps, cli, room_name):
        with steps.start("Get decisions/database") as step:
            r = cli.memory_get(room_name, "decisions/database")
            if not r.ok:
                step.failed(r.error_message)
            if "PostgreSQL" not in r.stdout:
                step.failed("Expected 'PostgreSQL' in memory content")

    @aetest.test
    def list_all_memories(self, steps, cli, room_name):
        with steps.start("List all memories") as step:
            r = cli.memory_ls(room_name)
            if not r.ok:
                step.failed(r.error_message)
            if "decisions" not in r.stdout.lower():
                step.failed("Expected 'decisions' category in memory listing")

    @aetest.test
    def decisions_view(self, steps, cli, room_name):
        with steps.start("Decisions view") as step:
            r = cli.memory_decisions(room_name)
            if not r.ok:
                step.failed(r.error_message)

    @aetest.test
    def status_view(self, steps, cli, room_name):
        with steps.start("Status view") as step:
            r = cli.memory_status(room_name)
            if not r.ok:
                step.failed(r.error_message)


class SemanticSearch(aetest.Testcase):
    """Test 04: Semantic memory search."""

    groups = ["core", "sanity"]

    @aetest.test
    def search_database_decisions(self, steps, cli, room_name):
        with steps.start("Search: database decisions") as step:
            r = cli.memory_search(room_name, "database decisions")
            if not r.ok:
                step.failed(r.error_message)

    @aetest.test
    def search_failures(self, steps, cli, room_name):
        with steps.start("Search: what failed or was dropped") as step:
            r = cli.memory_search(room_name, "what failed or was dropped")
            if not r.ok:
                step.failed(r.error_message)


class Synthesis(aetest.Testcase):
    """Test 05: AI synthesis of room state. Requires LLM."""

    groups = ["core", "llm", "slow"]

    @aetest.setup
    def check_llm(self, env):
        if env.skip_llm_tests:
            self.skipped("LLM not available")

    @aetest.test
    def synthesize_room(self, steps, cli, room_name):
        with steps.start("Synthesize room via CLI") as step:
            r = cli.synthesize(room_name)
            if not r.ok:
                step.failed(f"Synthesis failed: {r.error_message}")

    @aetest.test
    def catchup_room(self, steps, cli, room_name):
        with steps.start("Catchup via CLI") as step:
            r = cli.catchup(room_name)
            if not r.ok:
                step.failed(f"Catchup failed: {r.error_message}")


class ConsensusNegotiation(aetest.Testcase):
    """Test 06: Two-agent session negotiation via CLI."""

    groups = ["core", "slow"]

    @aetest.test
    def negotiate_session(self, steps, cli, room_name):
        with steps.start("Agent Alpha joins session") as step:
            r = cli.session_join(room_name, "agent-alpha", position="I prefer PostgreSQL")
            if not r.ok:
                step.failed(r.error_message)

        with steps.start("Agent Beta joins session") as step:
            r = cli.session_join(room_name, "agent-beta", position="I prefer MongoDB")
            if not r.ok:
                step.failed(r.error_message)

        with steps.start("List sessions") as step:
            r = cli.session_ls(room_name)
            if not r.ok:
                step.failed(r.error_message)


class SessionJoinIdempotency(aetest.Testcase):
    """Test 06b: Regression PR #286 — duplicate session joins produce one session."""

    groups = ["core"]

    @aetest.test
    def idempotent_join(self, steps, api, room_name):
        test_room = f"{room_name}-idempotent"
        api.create_room(test_room, description="idempotency test")

        try:
            with steps.start("First join") as step:
                st, _ = api.spawn_session(test_room, {"handle": "agent-alpha", "position": "test"})
                if st not in (200, 201):
                    step.failed(f"First join failed: status={st}")

            with steps.start("Duplicate join") as step:
                st, _ = api.spawn_session(test_room, {"handle": "agent-alpha", "position": "test"})
                if st not in (200, 201, 409):
                    step.failed(f"Duplicate join returned unexpected status={st}")

            with steps.start("Verify single session") as step:
                sessions = []
                for getter in (
                    lambda: api.list_sessions(test_room),
                    lambda: api.get_coordination_sessions(parent_room=test_room),
                ):
                    st, data = getter()
                    if st != 200:
                        continue
                    if isinstance(data, list):
                        sessions = data
                    elif isinstance(data, dict):
                        sessions = data.get("sessions") or data.get("items") or data.get("results") or []
                    if sessions:
                        break

                if len(sessions) != 1:
                    step.failed(f"Expected exactly 1 session after duplicate join, got {len(sessions)}")
        finally:
            api.delete_room(test_room)


class DoctorClean(aetest.Testcase):
    """Test 06c: ``mycelium doctor`` reports no error-level checks."""

    groups = ["core", "sanity"]

    @aetest.test
    def doctor_clean(self, steps, cli):
        with steps.start("Run mycelium doctor --json") as step:
            r = cli.doctor()
            if not r.ok:
                step.failed(f"doctor failed: {r.error_message}")
            data = r.json
            if data and isinstance(data, dict):
                checks = data.get("checks", [])
                errors = [c for c in checks if c.get("level") == "error"]
                if errors:
                    names = ", ".join(c.get("name", "?") for c in errors)
                    step.failed(f"Doctor found errors: {names}")


class CfnLlmCounters(aetest.Testcase):
    """Test 06d: CFN LLM token counters via /observability.

    Aligned with bundle.py ``test_cfn_llm_counters``: counters live under
    ``counters.cfn_llm.by_pipeline.<name>.<key>`` (node-svc >= 0.1.5).

    Two-phase wait:
      Phase 1 — ``coordination_start`` posted to session room (60s).
      Phase 2 — ``cfn_llm.calls`` counter advances (240s).
    """

    groups = ["core", "cfn", "llm"]

    @aetest.setup
    def check_prerequisites(self, env):
        if env.skip_llm_tests:
            self.skipped("LLM not available")
        if env.coordination_blocked_reason:
            self.skipped(env.coordination_blocked_reason)

    @aetest.test
    def verify_counters(self, steps, cli, api, room_name):
        test_room = f"{room_name}-cfn-llm"

        with steps.start("Snapshot counters before") as step:
            before = _fetch_cfn_llm_counters(api)
            calls_before = _cfn_llm_counter(before, "calls")
            log.info("cfn_llm.calls before: %d", calls_before)

        with steps.start("Create room, session, and join two agents") as step:
            st, _ = api.create_room(test_room, description="cfn-llm counter test")
            if st not in (200, 201):
                step.failed(f"Room creation failed: status={st}")
            r = cli.session_create(test_room)
            if not r.ok:
                step.failed(f"session create failed: {r.error_message}")
            session_room = _parse_session_room(r)
            r = cli.session_join(
                test_room,
                "agent-alpha",
                position="Low-latency primary; batch processing acceptable for analytics; hard limit: p99 < 50ms for user-facing calls",
            )
            if not r.ok:
                step.failed(f"agent-alpha join failed: {r.error_message}")
            r = cli.session_join(
                test_room,
                "agent-beta",
                position="Throughput primary; willing to relax latency for non-interactive paths; hard limit: sustain 10k req/s",
            )
            if not r.ok:
                step.failed(f"agent-beta join failed: {r.error_message}")

        with steps.start("Resolve session room and wait for coordination_start (60s)") as step:
            if not session_room:
                for _ in range(20):
                    session_room = api.find_session_room(test_room)
                    if session_room:
                        break
                    time.sleep(0.5)
            if not session_room:
                step.failed("Could not resolve session sub-room")
            log.info("Session room: %s", session_room)
            deadline = time.time() + 60
            while time.time() < deadline:
                _, msgs = api.get_room_messages(session_room)
                if any(m.get("message_type") == "coordination_start" for m in msgs):
                    log.info("coordination_start seen in %s", session_room)
                    break
                time.sleep(2)
            else:
                step.failed("No coordination_start within 60s")

        with steps.start("Wait for cfn_llm.calls to advance (Phase 2, 240s)") as step:
            deadline = time.time() + 240
            after = before
            while time.time() < deadline:
                time.sleep(3)
                after = _fetch_cfn_llm_counters(api)
                if _cfn_llm_counter(after, "calls") > calls_before:
                    break

            calls_after = _cfn_llm_counter(after, "calls")
            in_after = _cfn_llm_counter(after, "input_tokens")
            out_after = _cfn_llm_counter(after, "output_tokens")
            calls_delta = calls_after - calls_before
            log.info(
                "cfn_llm counters: calls=%d→%d (Δ%d), input_tokens=%d, output_tokens=%d",
                calls_before,
                calls_after,
                calls_delta,
                in_after,
                out_after,
            )
            if calls_delta <= 0:
                step.failed(f"cfn_llm.calls did not advance: before={calls_before}, after={calls_after}")

    @aetest.cleanup
    def cleanup(self, api, room_name):
        api.delete_room(f"{room_name}-cfn-llm")


def _fetch_cfn_llm_counters(api) -> dict:
    """GET /observability and return the ``counters`` dict."""
    st, obs = api.observability()
    if st != 200 or not isinstance(obs, dict):
        return {}
    return obs.get("counters") or {}


def _cfn_llm_counter(counters: dict, key: str) -> int:
    """Sum cfn_llm.by_pipeline.<pipeline>.<key> across all pipelines."""
    grp = counters.get("cfn_llm") or {}
    suffix = f".{key}"
    total = 0
    for k, v in grp.items():
        if k.startswith("by_pipeline.") and k.endswith(suffix):
            try:
                total += int(v)
            except (TypeError, ValueError):
                continue
    return total


class SharedMemoryCliE2E(aetest.Testcase):
    """Test 11: End-to-end CLI: store -> read -> search -> reindex."""

    groups = ["core"]

    @aetest.test
    def full_cli_flow(self, steps, cli, room_name):
        with steps.start("Store a memory") as step:
            r = cli.memory_set(room_name, "e2e-agent", "e2e/test-key", "E2E test content for CLI flow")
            if not r.ok:
                step.failed(r.error_message)

        with steps.start("Read it back") as step:
            r = cli.memory_get(room_name, "e2e/test-key")
            if not r.ok:
                step.failed(r.error_message)
            if "E2E test content" not in r.stdout:
                step.failed("Memory content mismatch")

        with steps.start("Search for it") as step:
            r = cli.memory_search(room_name, "E2E test content")
            if not r.ok:
                step.failed(r.error_message)

        with steps.start("Reindex") as step:
            r = cli.memory_reindex(room_name)
            if not r.ok:
                step.failed(r.error_message)


class ConsensusCliE2E(aetest.Testcase):
    """Test 12: Two-agent consensus workflow via CLI."""

    groups = ["core", "llm", "slow"]

    @aetest.setup
    def check_llm(self, env):
        if env.skip_llm_tests:
            self.skipped("LLM not available")

    @aetest.test
    def consensus_flow(self, steps, cli, room_name):
        test_room = f"{room_name}-consensus-cli"
        with steps.start("Create dedicated room") as step:
            r = cli.room_create(test_room)
            if not r.ok:
                step.failed(r.error_message)

        with steps.start("Agent Alpha proposes topic") as step:
            r = cli.negotiate_propose(test_room, "agent-alpha", "Should we use REST or gRPC?")
            if not r.ok:
                step.failed(r.error_message)

        with steps.start("Agent Beta responds") as step:
            r = cli.negotiate_respond(test_room, "agent-beta", "accept")
            if not r.ok:
                step.failed(r.error_message)


class SyncNegotiationCliE2E(aetest.Testcase):
    """Test 13: CLI + IOC coordination via session sub-room.

    Aligned with bundle.py ``test_sync_negotiation_cli_e2e``:
    1. Create room, two session joins
    2. Poll session-room messages for coordination_tick (240s)
    3. CLI negotiate respond accept for each agent on the session room
    4. Poll for coordination_consensus message
    """

    groups = ["core", "cfn", "llm", "slow"]

    @aetest.setup
    def check_prerequisites(self, env):
        if env.skip_llm_tests:
            self.skipped("LLM not available")
        if env.coordination_blocked_reason:
            self.skipped(env.coordination_blocked_reason)

    @aetest.test
    def sync_negotiation(self, steps, cli, api, room_name):
        test_room = f"{room_name}-sync-neg"

        with steps.start("Create room, session, and join agents") as step:
            r = cli.room_create(test_room)
            if not r.ok:
                step.failed(f"room create failed: {r.error_message}")
            r = cli.session_create(test_room)
            if not r.ok:
                step.failed(f"session create failed: {r.error_message}")
            session_room = _parse_session_room(r)
            cli.session_join(
                test_room,
                "agent-alpha",
                position="Fast iteration primary; 2-week sprints; hard limit: ship MVP within 6 weeks",
            )
            cli.session_join(
                test_room,
                "agent-beta",
                position="Thorough testing primary; 90%+ coverage; hard limit: no release without integration tests",
            )

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

        with steps.start("Wait for coordination_tick (240s)") as step:
            tick_seen = False
            for _ in range(48):
                _, msgs = api.get_room_messages(session_room)
                if any(m.get("message_type") == "coordination_tick" for m in msgs):
                    tick_seen = True
                    break
                time.sleep(5)
            if not tick_seen:
                step.failed("No coordination_tick within 240s")

        with steps.start("Agents accept negotiation") as step:
            r = cli.negotiate_respond(session_room, "agent-alpha", "accept")
            if not r.ok:
                log.warning("agent-alpha accept: %s", r.error_message)
            time.sleep(2)
            r = cli.negotiate_respond(session_room, "agent-beta", "accept")
            if not r.ok:
                log.warning("agent-beta accept: %s", r.error_message)

        with steps.start("Wait for coordination_consensus (240s)") as step:
            consensus_seen = False
            for _ in range(48):
                _, msgs = api.get_room_messages(session_room)
                if any(m.get("message_type") == "coordination_consensus" for m in msgs):
                    consensus_seen = True
                    break
                time.sleep(5)
            if not consensus_seen:
                step.failed("No coordination_consensus within 240s after accepts")
            log.info("Sync negotiation: consensus reached in %s", session_room)

    @aetest.cleanup
    def cleanup(self, api, room_name):
        api.delete_room(f"{room_name}-sync-neg")


class DemoScriptNegotiation(aetest.Testcase):
    """Test 14: Demo-script flow — watch/await/respond."""

    groups = ["core", "cfn", "llm", "slow"]

    @aetest.setup
    def check_prerequisites(self, env):
        if env.skip_llm_tests:
            self.skipped("LLM not available")
        if env.coordination_blocked_reason:
            self.skipped(env.coordination_blocked_reason)

    @aetest.test
    def demo_script_flow(self, steps, cli, room_name):
        test_room = f"{room_name}-demo"
        with steps.start("Create and populate room") as step:
            r = cli.room_create(test_room)
            if not r.ok:
                step.failed(f"room create failed: {r.error_message}")
            r = cli.memory_set(test_room, "agent-alpha", "context/goal", "Ship v2.0 by end of quarter")
            if not r.ok:
                step.failed(f"memory set failed: {r.error_message}")

        with steps.start("Start negotiation") as step:
            r = cli.negotiate_propose(test_room, "agent-alpha", "Release planning for v2.0")
            if not r.ok:
                step.failed(f"negotiate propose failed: {r.error_message}")

        with steps.start("Agent responds") as step:
            r = cli.negotiate_respond(test_room, "agent-beta", "accept")
            if not r.ok:
                step.failed(f"negotiate respond failed: {r.error_message}")

        with steps.start("Query negotiation state") as step:
            r = cli.negotiate_query(test_room, "Release planning for v2.0")
            if not r.ok:
                step.failed(f"negotiate query failed: {r.error_message}")


class Reindex(aetest.Testcase):
    """Test 22: Memory reindex."""

    groups = ["core"]

    @aetest.test
    def reindex(self, steps, cli, room_name):
        with steps.start("Reindex via CLI") as step:
            r = cli.memory_reindex(room_name)
            if not r.ok:
                step.failed(r.error_message)
