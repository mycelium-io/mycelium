"""PR checks — protocol boundary tests.

Gates: every PR. No LLM required. No agents.

Tests:
  - Session spawn via API returns a valid session object
  - Sessions list endpoint returns expected shape
  - Coordination sessions endpoint works
  - Protocol rejection: respond without an active await is rejected
  - Room delete removes the room (idempotent on repeated delete)
"""

from __future__ import annotations

import logging
import urllib.parse
import uuid

from pyats import aetest

from libs.mycelium_api import MyceliumAPI
from libs.mycelium_cli import MyceliumCLI

log = logging.getLogger(__name__)

parameters = {}


class SessionAPIShape(aetest.Testcase):
    """Session spawn and list endpoints return valid shapes."""

    @aetest.setup
    def setup_room(self, api: MyceliumAPI, testscript):
        self.room = f"qa-coord-fresh-{uuid.uuid4().hex[:8]}"
        testscript.parameters.setdefault("owned_rooms", set()).add(self.room)
        status, _ = api.create_room(self.room)
        assert status in (200, 201), f"room create failed: {status}"

    @aetest.test
    def sessions_list_empty(self, api: MyceliumAPI):
        status, data = api.list_sessions(self.room)
        assert status == 200, f"list_sessions returned {status}"
        sessions = data if isinstance(data, list) else (data or {}).get("sessions", [])
        assert isinstance(sessions, list), f"Expected list, got {type(sessions)}: {data}"

    @aetest.test
    def coordination_sessions_endpoint(self, api: MyceliumAPI):
        status, data = api.get_coordination_sessions(self.room)
        if status == 404:
            self.skipped("coordination-sessions endpoint not present in this build")
            return
        assert status == 200, f"get_coordination_sessions returned {status}"
        results = data if isinstance(data, list) else (data or {}).get("sessions", [])
        assert isinstance(results, list), f"Expected list: {data}"

    @aetest.cleanup
    def delete_room(self, api: MyceliumAPI):
        api.delete_room(self.room)


class RespondWithoutAwait(aetest.Testcase):
    """Responding without an active await turn should be rejected by the backend."""

    @aetest.setup
    def setup_room(self, api: MyceliumAPI, testscript):
        self.room = f"qa-coord-fresh-{uuid.uuid4().hex[:8]}"
        testscript.parameters.setdefault("owned_rooms", set()).add(self.room)
        status, _ = api.create_room(self.room)
        assert status in (200, 201)

    @aetest.test
    def respond_without_turn_fails(self, cli: MyceliumCLI):
        """mycelium respond with no pending turn should return non-zero."""
        r = cli.respond(
            self.room,
            "ghost-handle",
            "This should fail — no active turn. [<accept>]",
        )
        assert not r.ok, (
            "Expected respond to fail when there is no pending turn, "
            f"but got rc={r.returncode} stdout={r.stdout[:200]}"
        )

    @aetest.cleanup
    def delete_room(self, api: MyceliumAPI):
        api.delete_room(self.room)


class RoomDeleteIdempotent(aetest.Testcase):
    """Deleting a room twice should not error on the second call."""

    @aetest.test
    def double_delete(self, api: MyceliumAPI, testscript):
        room = f"qa-coord-fresh-{uuid.uuid4().hex[:8]}"
        api.create_room(room)
        st1, _ = api.delete_room(room)
        assert 200 <= st1 < 300, f"First delete failed: {st1}"

        st2, _ = api.delete_room(room)
        assert st2 in (200, 204, 404), f"Second delete should be 200/404, got {st2}"


class HerdrPresenceOverlay(aetest.Testcase):
    """herdr presence overlay: sync push surfaces on /sessions/members, and a
    mention of a busy herdr-present handle enqueues a wake that stays held
    until herdr reports it idle. No real herdr install needed — the backend
    only ever sees the sync bridge's HTTP push/drain, never herdr itself.
    """

    _HANDLE = "herdr-agent"

    @aetest.setup
    def setup_room(self, api: MyceliumAPI, testscript):
        self.room = f"qa-coord-fresh-{uuid.uuid4().hex[:8]}"
        testscript.parameters.setdefault("owned_rooms", set()).add(self.room)
        status, _ = api.create_room(self.room)
        assert status in (200, 201), f"room create failed: {status}"
        self.enc = urllib.parse.quote(self.room, safe="")

    @aetest.test
    def presence_push_surfaces_on_members(self, api: MyceliumAPI):
        status, _ = api.post_json(
            f"/rooms/{self.enc}/sessions/herdr-presence",
            {"statuses": {self._HANDLE: {"status": "working", "title": "refactor auth"}}},
        )
        assert status == 204, f"herdr-presence push returned {status}"

        status, data = api.get_json(f"/rooms/{self.enc}/sessions/members")
        assert status == 200, f"members endpoint returned {status}: {data}"
        members = {m["handle"]: m for m in data.get("members", [])}
        assert self._HANDLE in members, f"herdr-only handle missing from members: {data}"
        entry = members[self._HANDLE]
        assert entry["status"] == "working", entry
        assert entry["title"] == "refactor auth", entry
        assert entry["wake_pending"] is False, entry

    @aetest.test
    def mention_while_busy_holds_the_wake(self, api: MyceliumAPI):
        # herdr-agent is still "working" from the previous test's push (90s TTL).
        status, _ = api.post_json(
            f"/rooms/{self.enc}/messages",
            {
                "sender_handle": "qa-human",
                "message_type": "broadcast",
                "content": f"@{self._HANDLE} can you take a look?",
            },
        )
        assert status == 201, f"message post returned {status}"

        status, data = api.get_json(f"/rooms/{self.enc}/sessions/members")
        members = {m["handle"]: m for m in data.get("members", [])}
        assert members[self._HANDLE]["wake_pending"] is True, (
            f"Expected the mention to enqueue a held wake while busy: {data}"
        )

        status, wakes = api.get_json(f"/rooms/{self.enc}/sessions/herdr-wakes")
        assert status == 200, f"herdr-wakes returned {status}"
        assert wakes.get("wakes") == [], f"A busy handle's wake must stay held: {wakes}"

    @aetest.test
    def wake_releases_once_idle(self, api: MyceliumAPI):
        status, _ = api.post_json(
            f"/rooms/{self.enc}/sessions/herdr-presence",
            {"statuses": {self._HANDLE: "idle"}},
        )
        assert status == 204, f"herdr-presence push returned {status}"

        status, wakes = api.get_json(f"/rooms/{self.enc}/sessions/herdr-wakes")
        assert status == 200, f"herdr-wakes returned {status}"
        handles = [w.get("handle") for w in wakes.get("wakes", [])]
        assert self._HANDLE in handles, f"Expected the held wake to release once idle: {wakes}"

        # Drained: a second read is empty, and wake_pending clears on /members.
        status, wakes2 = api.get_json(f"/rooms/{self.enc}/sessions/herdr-wakes")
        assert wakes2.get("wakes") == [], f"Wake should be drained, not re-delivered: {wakes2}"
        status, data = api.get_json(f"/rooms/{self.enc}/sessions/members")
        members = {m["handle"]: m for m in data.get("members", [])}
        assert members.get(self._HANDLE, {}).get("wake_pending", False) is False, data

    @aetest.cleanup
    def delete_room(self, api: MyceliumAPI):
        api.delete_room(self.room)


class AgentContextEndpointShape(aetest.Testcase):
    """agent_context endpoint returns expected structure (or 404 in older builds)."""

    @aetest.setup
    def setup_room(self, api: MyceliumAPI, testscript):
        self.room = f"qa-memory-{uuid.uuid4().hex[:8]}"
        testscript.parameters.setdefault("owned_rooms", set()).add(self.room)
        api.create_room(self.room)

    @aetest.test
    def endpoint_returns_structured_response(self, api: MyceliumAPI):
        import urllib.parse
        enc = urllib.parse.quote(self.room, safe="")
        status, data = api.get_json(f"/rooms/{enc}/agent-context")
        if status == 404:
            self.skipped("agent_context not in this build — skipping shape check")
            return
        assert status == 200, f"agent_context returned {status}: {data}"
        # Should be a dict with at least one key, or an empty dict
        assert isinstance(data, dict), f"Expected dict, got {type(data)}: {data}"

    @aetest.cleanup
    def delete_room(self, api: MyceliumAPI):
        api.delete_room(self.room)
