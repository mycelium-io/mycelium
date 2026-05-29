"""Core Mycelium E2E tests: rooms, memory, CLI, sessions, search, synthesis.

Maps to original tests 01-06, 06b-06d, 11-14, 22.
"""

from __future__ import annotations

import json
import logging
import time

from pyats import aetest

from libs.mycelium_api import MyceliumAPI
from libs.mycelium_cli import MyceliumCLI
from libs.environment import EnvironmentInfo

log = logging.getLogger(__name__)


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
        with steps.start("Agent A joins session") as step:
            r = cli.session_join(room_name, "agent-a", position="I prefer PostgreSQL")
            if not r.ok:
                step.failed(r.error_message)

        with steps.start("Agent B joins session") as step:
            r = cli.session_join(room_name, "agent-b", position="I prefer MongoDB")
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
                st, _ = api.spawn_session(test_room, {"handle": "test-agent", "position": "test"})
                if st not in (200, 201):
                    step.failed(f"First join failed: status={st}")

            with steps.start("Duplicate join") as step:
                st, _ = api.spawn_session(test_room, {"handle": "test-agent", "position": "test"})
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
                        sessions = (
                            data.get("sessions")
                            or data.get("items")
                            or data.get("results")
                            or []
                        )
                    if sessions:
                        break

                if len(sessions) != 1:
                    step.failed(
                        f"Expected exactly 1 session after duplicate join, "
                        f"got {len(sessions)}"
                    )
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
    """Test 06d: CFN LLM token counters via /observability."""

    groups = ["core", "cfn"]

    @aetest.test
    def verify_counters(self, steps, api, room_name):
        with steps.start("Snapshot counters before") as step:
            st_before, obs_before = api.observability()
            if st_before != 200:
                step.failed(f"Observability endpoint returned status={st_before}")
            before_total = _extract_llm_token_total(obs_before)
            log.info("LLM token total before: %s", before_total)

        with steps.start("Spawn a session to generate LLM activity") as step:
            test_room = f"{room_name}-counters"
            api.create_room(test_room, description="counter test")
            try:
                st, resp = api.spawn_session(
                    test_room, {"handle": "counter-agent", "position": "test position"},
                )
                if st not in (200, 201):
                    step.failed(f"Session spawn failed: status={st}")
                time.sleep(5)
            finally:
                api.delete_room(test_room)

        with steps.start("Verify counters changed") as step:
            st_after, obs_after = api.observability()
            if st_after != 200:
                step.failed(f"Post observability returned status={st_after}")
            after_total = _extract_llm_token_total(obs_after)
            log.info("LLM token total after: %s (before: %s)", after_total, before_total)
            if before_total is not None and after_total is not None:
                if after_total <= before_total:
                    step.failed(
                        f"LLM token counters did not increase: "
                        f"before={before_total}, after={after_total}"
                    )
            elif after_total is None:
                log.warning("Could not extract LLM token totals from observability response")


def _extract_llm_token_total(obs: Any) -> int | None:
    """Sum all LLM token counters from the observability response."""
    if not isinstance(obs, dict):
        return None
    llm = obs.get("llm", obs.get("llm_usage", obs.get("tokens", {})))
    if isinstance(llm, dict):
        total = llm.get("total_tokens", llm.get("total"))
        if isinstance(total, (int, float)):
            return int(total)
        prompt = llm.get("prompt_tokens", llm.get("input_tokens", 0))
        completion = llm.get("completion_tokens", llm.get("output_tokens", 0))
        if isinstance(prompt, (int, float)) and isinstance(completion, (int, float)):
            s = int(prompt) + int(completion)
            return s if s > 0 else None
    return None


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

        with steps.start("Agent A proposes topic") as step:
            r = cli.negotiate_propose(test_room, "agent-a", "Should we use REST or gRPC?")
            if not r.ok:
                step.failed(r.error_message)

        with steps.start("Agent B responds") as step:
            r = cli.negotiate_respond(test_room, "agent-b", "accept")
            if not r.ok:
                step.failed(r.error_message)


class SyncNegotiationCliE2E(aetest.Testcase):
    """Test 13: CLI + IOC coordination_tick polling."""

    groups = ["core", "cfn", "llm", "slow"]

    @aetest.setup
    def check_prerequisites(self, env):
        if env.skip_llm_tests:
            self.skipped("LLM not available")
        if env.coordination_blocked_reason:
            self.skipped(env.coordination_blocked_reason)

    @aetest.test
    def sync_negotiation(self, steps, cli, api, room_name, timeouts=None):
        t = timeouts or {}
        timeout = t.get("negotiation_wait", 600)
        test_room = f"{room_name}-sync-neg"
        with steps.start("Create room and join agents") as step:
            cli.room_create(test_room)
            cli.session_join(test_room, "sync-a", position="I want fast iteration cycles")
            cli.session_join(test_room, "sync-b", position="I want thorough testing")

        with steps.start("Wait for coordination") as step:
            result = api.wait_for_consensus(test_room, timeout=timeout)
            if not result:
                step.failed(f"Consensus not reached within {timeout}s")
            state = result.get("coordination_state") if isinstance(result, dict) else None
            log.info("Sync negotiation result: state=%s", state)


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
            r = cli.memory_set(test_room, "demo-lead", "context/goal", "Ship v2.0 by end of quarter")
            if not r.ok:
                step.failed(f"memory set failed: {r.error_message}")

        with steps.start("Start negotiation") as step:
            r = cli.negotiate_propose(test_room, "demo-lead", "Release planning for v2.0")
            if not r.ok:
                step.failed(f"negotiate propose failed: {r.error_message}")

        with steps.start("Agent responds") as step:
            r = cli.negotiate_respond(test_room, "demo-eng", "accept")
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
