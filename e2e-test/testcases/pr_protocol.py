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


class MessageAmendment(aetest.Testcase):
    """Amending a message is additive: the room folds to the newest text,
    edited_at gets set, and only the original sender may amend."""

    @aetest.setup
    def setup_room(self, api: MyceliumAPI, testscript):
        self.room = f"qa-coord-fresh-{uuid.uuid4().hex[:8]}"
        testscript.parameters.setdefault("owned_rooms", set()).add(self.room)
        status, _ = api.create_room(self.room)
        assert status in (200, 201)
        self.enc = urllib.parse.quote(self.room, safe="")

    @aetest.test
    def amend_folds_to_newest_text(self, api: MyceliumAPI):
        status, created = api.post_json(
            f"/rooms/{self.enc}/messages",
            {
                "sender_handle": "qa-human",
                "message_type": "broadcast",
                "content": "Ship on Friday.",
            },
        )
        assert status == 201, f"message post returned {status}: {created}"
        message_id = created["id"]

        status, amended = api.post_json(
            f"/rooms/{self.enc}/messages/{message_id}/amend",
            {"content": "Ship on Monday instead.", "sender_handle": "qa-human"},
        )
        assert status == 201, f"amend returned {status}: {amended}"
        assert amended["content"] == "Ship on Monday instead.", amended
        assert amended["edited_at"] is not None, f"Expected edited_at to be set: {amended}"

        status, other = api.post_json(
            f"/rooms/{self.enc}/messages/{message_id}/amend",
            {"content": "I get to change this too?", "sender_handle": "qa-impostor"},
        )
        assert status == 403, (
            f"Expected 403 amending someone else's message, got {status}: {other}"
        )

    @aetest.cleanup
    def delete_room(self, api: MyceliumAPI):
        api.delete_room(self.room)


class EventStatusTransition(aetest.Testcase):
    """A stateful event (kind=action) opens "open" and transitions through
    PATCH — in_progress, then resolved."""

    @aetest.setup
    def setup_room(self, api: MyceliumAPI, testscript):
        self.room = f"qa-coord-fresh-{uuid.uuid4().hex[:8]}"
        testscript.parameters.setdefault("owned_rooms", set()).add(self.room)
        status, _ = api.create_room(self.room)
        assert status in (200, 201)
        self.enc = urllib.parse.quote(self.room, safe="")

    @aetest.test
    def stateful_event_transitions_through_patch(self, api: MyceliumAPI):
        status, created = api.post_json(
            f"/rooms/{self.enc}/messages",
            {
                "sender_handle": "qa-human",
                "message_type": "event",
                "content": "Follow up on the flaky test.",
                "metadata": {"kind": "action"},
            },
        )
        assert status == 201, f"event post returned {status}: {created}"
        assert created["metadata"]["status"] == "open", created
        message_id = created["id"]

        status, updated = api.patch_json(
            f"/rooms/{self.enc}/messages/{message_id}", {"status": "in_progress"}
        )
        assert status == 200, f"PATCH status returned {status}: {updated}"
        assert updated["metadata"]["status"] == "in_progress", updated

        status, resolved = api.patch_json(
            f"/rooms/{self.enc}/messages/{message_id}", {"status": "resolved"}
        )
        assert status == 200, f"PATCH status returned {status}: {resolved}"
        assert resolved["metadata"]["status"] == "resolved", resolved

    @aetest.cleanup
    def delete_room(self, api: MyceliumAPI):
        api.delete_room(self.room)


class AssignmentLifecycle(aetest.Testcase):
    """work/ row custody: claim -> (conflict) -> release -> re-claim -> resolve.

    claim/release/resolve/renew and the read/await shapes had zero coverage.
    No CLI wrapper exists yet, so this is straight HTTP.
    """

    @aetest.setup
    def setup_room(self, api: MyceliumAPI, testscript):
        self.room = f"qa-coord-fresh-{uuid.uuid4().hex[:8]}"
        testscript.parameters.setdefault("owned_rooms", set()).add(self.room)
        status, _ = api.create_room(self.room)
        assert status in (200, 201)
        self.enc = urllib.parse.quote(self.room, safe="")
        self.key = f"work/ship-feature-{uuid.uuid4().hex[:6]}"

        status, _ = api.post_json(
            f"/rooms/{self.enc}/memory",
            {
                "items": [
                    {
                        "key": self.key,
                        "value": {"text": "Ship the new export feature."},
                        "created_by": "qa-tester",
                    }
                ]
            },
        )
        assert status == 201, f"work row create returned {status}"

    @aetest.test
    def claim_conflict_release_reclaim_resolve(self, api: MyceliumAPI):
        status, unclaimed = api.get_json(f"/rooms/{self.enc}/assignments/{self.key}")
        if status == 404:
            self.skipped("assignments endpoint not present in this build")
            return
        assert status == 200, f"assignment read returned {status}: {unclaimed}"
        assert unclaimed["assignment"] == "unclaimed", unclaimed

        status, held = api.post_json(
            f"/rooms/{self.enc}/assignments/claim",
            {"key": self.key, "handle": "qa-alice", "ttl_minutes": 30},
        )
        assert status == 200, f"claim returned {status}: {held}"
        assert held["assignment"] == "held", held
        assert held["owner"] == "qa-alice", held

        status, conflict = api.post_json(
            f"/rooms/{self.enc}/assignments/claim",
            {"key": self.key, "handle": "qa-bob"},
        )
        assert status == 409, f"Expected 409 claiming an already-held row, got {status}: {conflict}"

        status, released = api.post_json(
            f"/rooms/{self.enc}/assignments/release",
            {"key": self.key, "handle": "qa-alice", "note": "handing off"},
        )
        assert status == 200, f"release returned {status}: {released}"
        assert released["assignment"] == "released", released
        assert released["owner"] is None, released

        status, reclaimed = api.post_json(
            f"/rooms/{self.enc}/assignments/claim",
            {"key": self.key, "handle": "qa-bob"},
        )
        assert status == 200, f"re-claim after release returned {status}: {reclaimed}"
        assert reclaimed["owner"] == "qa-bob", reclaimed

        status, resolved = api.post_json(
            f"/rooms/{self.enc}/assignments/resolve",
            {"key": self.key, "handle": "qa-bob"},
        )
        assert status == 200, f"resolve returned {status}: {resolved}"
        assert resolved["assignment"] == "resolved", resolved

        status, renewal = api.post_json(
            f"/rooms/{self.enc}/assignments/renew", {"handle": "qa-bob"}
        )
        assert status == 200, f"renew returned {status}: {renewal}"
        assert "renewed" in renewal, renewal

        status, oriented = api.get_json(
            f"/rooms/{self.enc}/assignments/await?key={urllib.parse.quote(self.key, safe='')}"
        )
        assert status == 200, f"await (orientation) returned {status}: {oriented}"
        assert oriented["assignment"] == "resolved", oriented

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
