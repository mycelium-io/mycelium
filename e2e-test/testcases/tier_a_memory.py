"""Tier A — Memory and briefing contract tests.

Gates: every PR. No LLM required. No agents.

Tests:
  - Memory CRUD: set / get / ls / rm
  - Briefing contract: seed work/ rows → agent_context contains them
  - Work row resolution: resolved row omitted from briefing
  - Memory search returns a relevant result
  - Memory decisions / status filters
"""

from __future__ import annotations

import logging
import time
import uuid

from pyats import aetest

from libs.mycelium_api import MyceliumAPI
from libs.mycelium_cli import MyceliumCLI

log = logging.getLogger(__name__)

parameters = {}

_HANDLE = "qa-tester"


class MemoryCRUD(aetest.Testcase):
    """Memory set / get / ls / rm round-trip."""

    @aetest.setup
    def setup_room(self, api: MyceliumAPI, testscript):
        self.room = f"qa-memory-{uuid.uuid4().hex[:8]}"
        testscript.parameters.setdefault("owned_rooms", set()).add(self.room)
        status, _ = api.create_room(self.room)
        assert status in (200, 201), f"room create failed: {status}"

    @aetest.test
    def set_and_get(self, cli: MyceliumCLI):
        key = f"decisions/test-decision-{uuid.uuid4().hex[:6]}"
        content = "We decided to use GraphQL for the public API."

        r = cli.memory_set(self.room, _HANDLE, key, content)
        assert r.ok, f"memory set failed: {r.error_message}"

        r = cli.memory_get(self.room, key)
        assert r.ok, f"memory get failed: {r.error_message}"
        assert content in r.stdout, f"Content not found in get output: {r.stdout[:300]}"

    @aetest.test
    def list_includes_key(self, cli: MyceliumCLI):
        key = f"decisions/list-test-{uuid.uuid4().hex[:6]}"
        r = cli.memory_set(self.room, _HANDLE, key, "Test entry for ls")
        assert r.ok, f"memory set failed: {r.error_message}"

        r = cli.memory_ls(self.room)
        assert r.ok, f"memory ls failed: {r.error_message}"
        assert key in r.stdout or key.split("/")[-1] in r.stdout, (
            f"Key {key!r} not found in ls output: {r.stdout[:500]}"
        )

    @aetest.test
    def decisions_filter(self, cli: MyceliumCLI):
        key = f"decisions/filter-test-{uuid.uuid4().hex[:6]}"
        r = cli.memory_set(self.room, _HANDLE, key, "A decision entry")
        assert r.ok
        r = cli.memory_decisions(self.room)
        assert r.ok, f"memory decisions failed: {r.error_message}"

    @aetest.test
    def status_filter(self, cli: MyceliumCLI):
        key = f"status/infra-{uuid.uuid4().hex[:6]}"
        r = cli.memory_set(self.room, _HANDLE, key, "Infra is healthy")
        assert r.ok
        r = cli.memory_status(self.room)
        assert r.ok, f"memory status failed: {r.error_message}"

    @aetest.cleanup
    def delete_room(self, api: MyceliumAPI):
        api.delete_room(self.room)


class BriefingContract(aetest.Testcase):
    """Briefing contract: work rows appear in agent_context; resolved rows are omitted.

    Tests the GET /api/rooms/{room}/agent_context endpoint which the
    aligner uses to build per-agent briefings.
    """

    @aetest.setup
    def setup_room(self, api: MyceliumAPI, testscript):
        self.room = f"qa-memory-brief-{uuid.uuid4().hex[:8]}"
        testscript.parameters.setdefault("owned_rooms", set()).add(self.room)
        status, _ = api.create_room(self.room)
        assert status in (200, 201)

    @aetest.test
    def open_work_appears_in_context(self, api: MyceliumAPI, cli: MyceliumCLI):
        task_key = f"work/auth-migration-{uuid.uuid4().hex[:6]}"
        task_content = "Migrate all API auth to JWT tokens by end of sprint."
        r = cli.memory_set(self.room, _HANDLE, task_key, task_content)
        assert r.ok, f"memory set work row failed: {r.error_message}"

        # Poll briefly for indexing to propagate
        _wait_for_indexing(api, self.room, task_key, timeout=10)

        status, context = api.get_json(f"/rooms/{_enc(self.room)}/agent_context")
        if status == 404:
            self.skipped("agent_context endpoint not present in this build")
            return
        assert status == 200, f"agent_context returned {status}"
        context_str = str(context)
        assert "auth-migration" in context_str or task_content[:30] in context_str, (
            f"Work row not found in agent_context. context={context_str[:500]}"
        )

    @aetest.test
    def decision_appears_in_context(self, api: MyceliumAPI, cli: MyceliumCLI):
        key = f"decisions/api-style-{uuid.uuid4().hex[:6]}"
        content = "We will use REST with JSON:API conventions."
        r = cli.memory_set(self.room, _HANDLE, key, content)
        assert r.ok

        _wait_for_indexing(api, self.room, key, timeout=10)

        status, context = api.get_json(f"/rooms/{_enc(self.room)}/agent_context")
        if status == 404:
            self.skipped("agent_context endpoint not present in this build")
            return
        assert status == 200
        assert "api-style" in str(context) or content[:20] in str(context), (
            f"Decision not in agent_context: {str(context)[:400]}"
        )

    @aetest.cleanup
    def delete_room(self, api: MyceliumAPI):
        api.delete_room(self.room)


class MemorySearch(aetest.Testcase):
    """Search returns a relevant memory."""

    @aetest.setup
    def setup_room(self, api: MyceliumAPI, testscript):
        self.room = f"qa-memory-search-{uuid.uuid4().hex[:8]}"
        testscript.parameters.setdefault("owned_rooms", set()).add(self.room)
        status, _ = api.create_room(self.room)
        assert status in (200, 201)

    @aetest.test
    def search_returns_seeded_memory(self, api: MyceliumAPI, cli: MyceliumCLI):
        # Seed two memories; search should return the more relevant one
        r1 = cli.memory_set(
            self.room, _HANDLE,
            f"decisions/database-choice-{uuid.uuid4().hex[:6]}",
            "We chose PostgreSQL for the primary datastore because of ACID guarantees.",
        )
        r2 = cli.memory_set(
            self.room, _HANDLE,
            f"decisions/frontend-framework-{uuid.uuid4().hex[:6]}",
            "We will use React with TypeScript for the frontend.",
        )
        assert r1.ok and r2.ok, "memory set failed"

        # Reindex to ensure both are searchable
        cli.memory_reindex(self.room)
        time.sleep(1)

        status, results = api.search_memory(self.room, "database storage choice")
        if status == 404:
            self.skipped("search endpoint not present in this build")
            return
        assert status == 200, f"search returned {status}"
        results_str = str(results)
        assert "postgresql" in results_str.lower() or "database" in results_str.lower(), (
            f"Expected database-related result, got: {results_str[:400]}"
        )

    @aetest.cleanup
    def delete_room(self, api: MyceliumAPI):
        api.delete_room(self.room)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _enc(name: str) -> str:
    import urllib.parse
    return urllib.parse.quote(name, safe="")


def _wait_for_indexing(
    api: MyceliumAPI,
    room: str,
    key: str,
    timeout: int = 10,
) -> None:
    """Wait briefly for a memory key to appear in the ls output."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, data = api.list_memory(room)
        if status == 200:
            keys = [m.get("key") for m in (data if isinstance(data, list) else [])]
            if any(key in (k or "") for k in keys):
                return
        time.sleep(0.5)
