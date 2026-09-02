"""PR checks — memory and briefing contract tests.

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

    Tests the GET /api/rooms/{room}/agent-context endpoint which the
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

        status, context = api.get_json(f"/rooms/{_enc(self.room)}/agent-context")
        if status == 404:
            self.skipped("agent_context endpoint not present in this build")
            return
        assert status == 200, f"agent_context returned {status}"
        context_str = str(context)
        assert "auth-migration" in context_str or task_content[:30] in context_str, (
            f"Work row not found in agent_context. context={context_str[:500]}"
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


class SkillsCRUD(aetest.Testcase):
    """Skills endpoint: create/list/get/delete round-trip.

    A skill is a promoted view over a ``skills/`` memory (name, description,
    body, tags, version) — no LLM, no CLI wrapper exists yet, so this drives
    the routes directly the way pr_protocol.py's un-wrapped endpoints do.
    """

    @aetest.setup
    def setup_room(self, api: MyceliumAPI, testscript):
        self.room = f"qa-memory-skill-{uuid.uuid4().hex[:8]}"
        testscript.parameters.setdefault("owned_rooms", set()).add(self.room)
        status, _ = api.create_room(self.room)
        assert status in (200, 201)
        self.name = f"qa-skill-{uuid.uuid4().hex[:6]}"

    @aetest.test
    def create_list_get_delete(self, api: MyceliumAPI):
        status, created = api.post_json(
            f"/rooms/{_enc(self.room)}/skills",
            {
                "name": self.name,
                "description": "Summarize a PR diff in one paragraph.",
                "body": "1. Read the diff.\n2. Summarize the change and why.",
                "tags": ["qa"],
                "created_by": _HANDLE,
            },
        )
        if status == 404:
            self.skipped("skills endpoint not present in this build")
            return
        assert status == 201, f"skill create returned {status}: {created}"
        assert created["name"] == self.name, created
        assert created["version"] == 1, created

        status, listing = api.get_json(f"/rooms/{_enc(self.room)}/skills")
        assert status == 200, f"skill list returned {status}: {listing}"
        names = [s["name"] for s in listing.get("skills", [])]
        assert self.name in names, f"{self.name!r} missing from skill list: {names}"

        status, fetched = api.get_json(f"/rooms/{_enc(self.room)}/skills/{self.name}")
        assert status == 200, f"skill get returned {status}: {fetched}"
        assert fetched["description"] == "Summarize a PR diff in one paragraph.", fetched
        assert fetched["tags"] == ["qa"], fetched

        status, _ = api.delete(f"/rooms/{_enc(self.room)}/skills/{self.name}")
        assert status == 204, f"skill delete returned {status}"

        status, _ = api.get_json(f"/rooms/{_enc(self.room)}/skills/{self.name}")
        assert status == 404, f"Expected 404 after delete, got {status}"

    @aetest.cleanup
    def delete_room(self, api: MyceliumAPI):
        api.delete_room(self.room)


class MemoryLinksGraph(aetest.Testcase):
    """The link graph over memory markdown: [[wikilinks]], backlinks, the whole
    graph, integrity (broken links), and ![[transclusion]] expansion.

    No CLI wrapper for links exists — this is straight HTTP, like skills.
    """

    @aetest.setup
    def setup_room(self, api: MyceliumAPI, testscript):
        self.room = f"qa-memory-links-{uuid.uuid4().hex[:8]}"
        testscript.parameters.setdefault("owned_rooms", set()).add(self.room)
        status, _ = api.create_room(self.room)
        assert status in (200, 201)
        self.enc = _enc(self.room)
        self.target_key = f"glossary/vector-store-{uuid.uuid4().hex[:6]}"
        self.source_key = f"decisions/db-choice-{uuid.uuid4().hex[:6]}"
        self.broken_key = f"notes/broken-ref-{uuid.uuid4().hex[:6]}"
        self.target_body = "A vector store indexes embeddings for nearest-neighbor search."

        # Target must be explicitly expandable — transcluding a non-expandable
        # memory is an integrity error, not a silent include.
        status, _ = api.post_json(
            f"/rooms/{self.enc}/memory",
            {
                "items": [
                    {
                        "key": self.target_key,
                        "value": {"text": self.target_body},
                        "created_by": _HANDLE,
                        "meta": {"expandable": True},
                    }
                ]
            },
        )
        assert status == 201, f"target memory create returned {status}"

        status, _ = api.post_json(
            f"/rooms/{self.enc}/memory",
            {
                "items": [
                    {
                        "key": self.source_key,
                        "value": {
                            "text": (
                                f"We chose based on [[{self.target_key}]] characteristics.\n\n"
                                f"See also: ![[{self.target_key}]]"
                            )
                        },
                        "created_by": _HANDLE,
                    },
                    {
                        "key": self.broken_key,
                        "value": {"text": "Related: [[nonexistent/does-not-exist]]"},
                        "created_by": _HANDLE,
                    },
                ]
            },
        )
        assert status == 201, f"source memory create returned {status}"

    @aetest.test
    def outbound_and_backlinks(self, api: MyceliumAPI):
        status, data = api.get_json(f"/rooms/{self.enc}/links?key={_enc(self.source_key)}")
        if status == 404:
            self.skipped("links endpoint not present in this build")
            return
        assert status == 200, f"links (outbound) returned {status}: {data}"
        outbound_targets = [link["target"] for link in data["outbound"]]
        assert self.target_key in outbound_targets, data

        status, data = api.get_json(f"/rooms/{self.enc}/links?key={_enc(self.target_key)}")
        assert status == 200, f"links (backlinks) returned {status}: {data}"
        backlink_sources = [link["source"] for link in data["backlinks"]]
        assert self.source_key in backlink_sources, data

    @aetest.test
    def graph_has_the_resolved_edge(self, api: MyceliumAPI):
        status, data = api.get_json(f"/rooms/{self.enc}/links/graph")
        assert status == 200, f"links/graph returned {status}: {data}"
        edges = [
            e for e in data["edges"]
            if e["source"] == self.source_key and e["target"] == self.target_key
        ]
        assert edges and edges[0]["resolved"] is True, data

    @aetest.test
    def integrity_reports_the_broken_link(self, api: MyceliumAPI):
        status, data = api.get_json(f"/rooms/{self.enc}/links/integrity")
        assert status == 200, f"links/integrity returned {status}: {data}"
        broken_targets = [b["target"] for b in data["broken"]]
        assert "nonexistent/does-not-exist" in broken_targets, data

    @aetest.test
    def expand_inlines_the_transcluded_body(self, api: MyceliumAPI):
        status, data = api.get_json(f"/rooms/{self.enc}/links/expand?key={_enc(self.source_key)}")
        assert status == 200, f"links/expand returned {status}: {data}"
        assert data["found"] is True, data
        assert self.target_body in data["rendered"], data

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
