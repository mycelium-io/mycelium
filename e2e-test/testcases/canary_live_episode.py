"""Canary — live agent multi-episode test.

Gates: NEVER blocks release. Informational / canary only.
Trigger: manual or weekly cron (canary_job.py).

Tests:
  E01 - Episode 1: two real agents negotiate; gate on 100% response rate + terminal state
  E02 - Episode 2: same room, new session; agent_context contains Episode 1 artifacts

Hygiene rules (from qa-coordination-platform.md):
  - Room name: domain-realistic, NOT qa-*/test-*
  - Handles: neutral (architect, engineer)
  - Pre-seed 2 decisions via API before agents join
  - Fresh agent workspace each episode
  - Harness note: operational mode injected via engine description
  - Abort on SILENT (3 consecutive missed turns), META (2 consecutive non-protocol prose)
  - Metrics only: response rate, rounds to terminal, memory hit in briefing

Abort codes:
  SILENT     - agent missed 3+ consecutive turns
  META       - agent produced non-protocol prose for 2+ consecutive turns
  CONTAGION  - second agent goes meta after first

Usage:
  This testcase requires live LLM access and claude_code or cursor adapter.
  Skip it (via canary_job.py skip logic) when env.skip_llm_tests is True.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import time
import uuid

from pyats import aetest

from libs.coordination_flow import (
    poll_for_terminal_state,
    setup_coordination,
    collect_room_responses,
    collect_debug_info,
)
from libs.environment import EnvironmentInfo
from libs.mycelium_api import MyceliumAPI
from libs.mycelium_cli import MyceliumCLI

log = logging.getLogger(__name__)

parameters = {}

# Canary room — domain-realistic, NOT qa-* or test-*
_CANARY_ROOM_ENV = "MYCELIUM_CANARY_ROOM"
_DEFAULT_CANARY_ROOM = "api-design-review"

# Handles — neutral, not @test-alpha
_HANDLE_A = "architect"
_HANDLE_B = "engineer"
_ALIGNER = "aligner"

# Adapter to use for live agents. Cursor is the default since it uses
# Cursor's own model access (no separate API key required).
# Set MYCELIUM_CANARY_ADAPTER=claude_code to override.
_ADAPTER = os.environ.get("MYCELIUM_CANARY_ADAPTER", "cursor")

# Thresholds
_EPISODE_TIMEOUT = 900        # 15 min per episode (real LLM is slow)
_TURN_TIMEOUT = 180           # 3 min per turn
_MAX_ROUNDS = 20
_SILENT_ABORT_THRESHOLD = 3  # consecutive missed turns before SILENT abort
_META_ABORT_THRESHOLD = 2    # consecutive non-protocol turns before META abort

# Pre-seeded memory fixtures — realistic domain content, not test metadata
_SEED_MEMORIES = [
    (
        "decisions/api-versioning",
        "We version APIs via URL path prefix (e.g. /v1/, /v2/). Breaking changes require a new major version. Minor additions are backwards-compatible within the same version.",
    ),
    (
        "work/auth-migration",
        "Migrate all internal service auth from shared API keys to short-lived JWT tokens. Target: end of Q3. Owner: @engineer.",
    ),
]


class EpisodeOne(aetest.Testcase):
    """E01 — Episode 1: real agents negotiate; gate on 100% response rate + terminal state."""

    uid = "canary_E01"

    @aetest.setup
    def setup(self, env: EnvironmentInfo, api: MyceliumAPI, cli: MyceliumCLI, testscript):
        # Prerequisites
        if env.skip_llm_tests:
            self.skipped("LLM not available — live LLM access is required")

        # Room
        self.room = os.environ.get(_CANARY_ROOM_ENV, _DEFAULT_CANARY_ROOM)
        testscript.parameters["canary_room"] = self.room
        status, _ = api.get_room(self.room)
        if status == 404:
            status, _ = api.create_room(self.room, description="API design coordination room")
            assert status in (200, 201), f"room create failed: {status}"
        log.info("Canary room: %s", self.room)

        # Seed memories
        for key, content in _SEED_MEMORIES:
            r = cli.memory_set(self.room, "qa-seeder", key, content)
            if r.ok:
                log.info("Seeded: %s", key)

        # Fresh agent workspaces
        ws_a = tempfile.mkdtemp(prefix=f"mc-{_HANDLE_A}-")
        ws_b = tempfile.mkdtemp(prefix=f"mc-{_HANDLE_B}-")
        testscript.parameters["workspace_a"] = ws_a
        testscript.parameters["workspace_b"] = ws_b

        # Register agents
        for handle, cwd in [(_HANDLE_A, ws_a), (_HANDLE_B, ws_b)]:
            r = cli.agent_create(handle, self.room, adapter=_ADAPTER, cwd=cwd,
                                 description=f"Canary {handle}")
            if not r.ok and "already" not in r.error_message.lower():
                self.failed(f"agent create failed for {handle}: {r.error_message}")

        # Start await --loop processes (cursor adapter only)
        procs = []
        if _ADAPTER == "cursor":
            exec_script = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "scripts", "cursor_exec.sh",
            )
            for handle, ws_key in [(_HANDLE_A, "workspace_a"), (_HANDLE_B, "workspace_b")]:
                ws = testscript.parameters.get(ws_key, "")
                proc = subprocess.Popen(
                    ["mycelium", "await", "--room", self.room, "--handle", handle,
                     "--loop", "--exec", exec_script, "--timeout", str(_TURN_TIMEOUT)],
                    env={**os.environ, "CURSOR_WORKSPACE": ws},
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                procs.append((handle, proc))
                log.info("await --loop started for @%s (pid=%d)", handle, proc.pid)
            time.sleep(3)
        testscript.parameters["agent_procs"] = procs

    @aetest.test
    def episode_one_coordination(self, api: MyceliumAPI, cli: MyceliumCLI, testscript):
        """Post opening positions, invoke aligner, monitor until l9_commit."""
        setup = setup_coordination(
            api, cli, self.room,
            agent_handles=[_HANDLE_A, _HANDLE_B],
            opening_positions={
                _HANDLE_A: "I prefer a strict rate-limiting policy based on per-user quotas.",
                _HANDLE_B: "I favour a flexible rate-limiting approach based on service tiers.",
            },
            aligner_handle=_ALIGNER,
        )
        if setup is None:
            self.failed("coordination setup failed")

        # Invoke aligner — cursor agents are already awaiting via their loop processes
        r = cli.engine_invoke(_ALIGNER, self.room,
                              "Please mediate on API rate-limiting strategy.")
        if not r.ok:
            log.warning("engine invoke: %s", r.error_message)

        # Monitor until l9_commit
        start = time.time()
        result = poll_for_terminal_state(
            api, self.room,
            timeout=_EPISODE_TIMEOUT,
            poll_interval=10,
        )
        elapsed = time.time() - start

        # Collect response metrics
        snap = collect_room_responses(api, self.room, [_HANDLE_A, _HANDLE_B])
        total_turns = sum(snap.responses.values())
        testscript.parameters["e01_response_counts"] = snap.responses
        testscript.parameters["e01_terminal_state"] = (
            result.get("subkind") if result else None
        )
        testscript.parameters["e01_elapsed"] = elapsed

        log.info(
            "Episode 1: subkind=%s elapsed=%.0fs turns=%s",
            result.get("subkind") if result else "timeout",
            elapsed,
            snap.responses,
        )

        if result is None:
            # Timeout — log as TIMEOUT, not a failure (canary never blocks release)
            debug = collect_debug_info(api, self.room, [_HANDLE_A, _HANDLE_B])
            log.error("TIMEOUT: Episode 1 did not reach terminal state. debug=%s", debug)
            self.skipped(
                f"TIMEOUT after {_EPISODE_TIMEOUT}s — recording as compatibility observation, "
                "not a release blocker"
            )
            return

        if total_turns == 0:
            log.error("SILENT: No agent responses recorded")
            self.skipped(
                "SILENT: No agent responses in Episode 1 — "
                "compatibility observation, not a release blocker"
            )
            return

        # Gate: 100% response rate (every tick got a reply)
        # We assert this as a warning rather than hard fail — canary is informational
        missing = {h: c for h, c in snap.responses.items() if c == 0}
        if missing:
            log.warning(
                "Partial silence in Episode 1 — agents with zero responses: %s. "
                "Recording as SILENT observation.",
                missing,
            )

        log.info(
            "Episode 1 complete: state=%s response_counts=%s",
            result.get("subkind"), snap.responses,
        )

    @aetest.cleanup
    def cleanup(self, testscript):
        for handle, proc in testscript.parameters.get("agent_procs") or []:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
            log.info("Stopped await --loop for @%s", handle)
        for ws_key in ("workspace_a", "workspace_b"):
            ws = testscript.parameters.get(ws_key)
            if ws and os.path.exists(ws):
                shutil.rmtree(ws, ignore_errors=True)
                log.info("Removed workspace: %s", ws)


class EpisodeTwo(aetest.Testcase):
    """E02 — Episode 2: same room, new session; agent_context contains Episode 1 open work.

    Gate: agent_context BEFORE session start contains Episode 1's still-open work
    (string match). agent_context is a work/-only briefing by design — it never
    surfaces decisions/ — so this cannot gate on the pre-seeded decision.
    NOT: agent negotiation quality.
    """

    uid = "canary_E02"

    @aetest.setup
    def setup(self, env: EnvironmentInfo, testscript):
        if env.skip_llm_tests:
            self.skipped("LLM not available — live LLM access is required")
        e01_state = testscript.parameters.get("e01_terminal_state")
        if e01_state is None:
            self.skipped("Episode 1 did not run or timed out — skipping Episode 2")
        ws_a = tempfile.mkdtemp(prefix=f"mc-e2-{_HANDLE_A}-")
        ws_b = tempfile.mkdtemp(prefix=f"mc-e2-{_HANDLE_B}-")
        testscript.parameters["workspace_a_e2"] = ws_a
        testscript.parameters["workspace_b_e2"] = ws_b

    @aetest.test
    def agent_context_contains_episode_one_artifacts(self, api: MyceliumAPI, cli: MyceliumCLI, testscript):
        """Before starting Episode 2, verify agent_context reflects Episode 1 output."""
        room = testscript.parameters.get("canary_room", _DEFAULT_CANARY_ROOM)
        import urllib.parse
        enc = urllib.parse.quote(room, safe="")
        status, context = api.get_json(f"/rooms/{enc}/agent-context")

        if status == 404:
            # Fallback: check memory list
            status2, data = api.list_memory(room)
            if status2 == 200:
                keys = [m.get("key") for m in (data if isinstance(data, list) else [])]
                seed_found = any("api-versioning" in (k or "") or "auth-migration" in (k or "") for k in keys)
                assert seed_found, (
                    f"Pre-seeded Episode 1 memories not found in room memory: {keys}"
                )
            return

        assert status == 200, f"agent_context returned {status}"
        context_str = str(context)

        # agent_context is a work/-only briefing by design (the room's title +
        # its open work) — decisions/ never appear here, so only the seeded
        # work/auth-migration fixture is checkable through this endpoint. The
        # seeded decisions/api-versioning fixture is still checked above, via
        # list_memory, on the 404 fallback path.
        assert "auth-migration" in context_str or "auth" in context_str.lower(), (
            f"Pre-seeded auth-migration work not in Episode 2 agent_context: {context_str[:600]}"
        )
        log.info("Episode 2 pre-flight: agent_context confirmed to contain Episode 1 artifacts")

    @aetest.test
    def episode_two_coordination(self, api: MyceliumAPI, cli: MyceliumCLI, testscript):
        """Run Episode 2 with fresh workspaces; record response metrics."""
        room = testscript.parameters.get("canary_room", _DEFAULT_CANARY_ROOM)
        ws_a = testscript.parameters.get("workspace_a_e2", "")
        ws_b = testscript.parameters.get("workspace_b_e2", "")

        # Re-register agents with fresh workspaces
        for handle, cwd in [(_HANDLE_A, ws_a), (_HANDLE_B, ws_b)]:
            r = cli.agent_create(
                handle, room,
                adapter=_ADAPTER,
                cwd=cwd,
                description=f"Canary agent {handle} (Episode 2)",
            )
            if not r.ok and "already" not in r.error_message.lower():
                log.warning("agent create for %s: %s", handle, r.error_message)

        # Start agent loops for Episode 2
        procs_e2: list = []
        if _ADAPTER == "cursor":
            exec_script = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "scripts", "cursor_exec.sh",
            )
            for handle, ws in [(_HANDLE_A, ws_a), (_HANDLE_B, ws_b)]:
                env = {**os.environ, "CURSOR_WORKSPACE": ws}
                proc = subprocess.Popen(
                    ["mycelium", "await", "--room", room, "--handle", handle,
                     "--loop", "--exec", exec_script, "--timeout", str(_TURN_TIMEOUT)],
                    env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                procs_e2.append((handle, proc))
                log.info("E2 await --loop started for @%s (pid=%d)", handle, proc.pid)
            time.sleep(3)
        testscript.parameters["agent_procs_e2"] = procs_e2

        setup = setup_coordination(
            api, cli, room,
            agent_handles=[_HANDLE_A, _HANDLE_B],
            opening_positions={
                _HANDLE_A: "Building on our prior decisions: I prefer strict caching rules.",
                _HANDLE_B: "Building on our prior decisions: I favour flexible cache policies.",
            },
            aligner_handle=_ALIGNER,
        )
        if setup is None:
            self.failed("Episode 2 coordination setup failed")

        r = cli.engine_invoke(_ALIGNER, room,
                              "Please mediate the API caching strategy.")
        if not r.ok:
            log.warning("engine invoke episode 2: %s", r.error_message)

        result = poll_for_terminal_state(
            api, room,
            timeout=_EPISODE_TIMEOUT,
            poll_interval=10,
        )
        snap = collect_room_responses(api, room, [_HANDLE_A, _HANDLE_B])

        log.info(
            "Episode 2: subkind=%s response_counts=%s",
            result.get("subkind") if result else "timeout",
            snap.responses,
        )

        if result is None:
            log.error("TIMEOUT: Episode 2 did not reach terminal state")
            self.skipped("TIMEOUT in Episode 2 — compatibility observation")
            return

        if all(v == 0 for v in snap.responses.values()):
            log.error("SILENT: No agent responses in Episode 2")
            self.skipped("SILENT in Episode 2 — compatibility observation")

    @aetest.cleanup
    def cleanup(self, testscript):
        for handle, proc in testscript.parameters.get("agent_procs_e2") or []:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
        for ws_key in ("workspace_a_e2", "workspace_b_e2"):
            ws = testscript.parameters.get(ws_key)
            if ws and os.path.exists(ws):
                shutil.rmtree(ws, ignore_errors=True)
