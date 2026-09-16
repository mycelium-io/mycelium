"""Nightly checks — A2A outbound (registering + calling a remote A2A agent).

No LLM required, but needs a real reachable Agent Card URL — this uses a
second mycelium room as the "remote" agent (mycelium's own A2A server,
already covered inbound in pr_a2a.py, is a fully spec-compliant A2A server),
so no separate mock process or extra networking is needed.

Prerequisite: the backend must have A2A_ALLOW_PRIVATE_HOSTS=1 set. Card
resolution has a deliberate SSRF guard that rejects any card host resolving
to a non-public address — which localhost always is — documented as an
escape hatch for exactly this kind of trusted-internal-deployment testing.
Both tests skip cleanly (rather than failing) when that flag isn't set, so
this is safe to run against a backend that hasn't opted in.

Tests:
  - Registering a remote A2A agent resolves its card and returns the
    endpoint/skills; an unreachable card 502s.
  - @-mentioning the registered handle calls it for real and posts its
    reply back into the room under that handle.
"""

from __future__ import annotations

import logging
import time
import urllib.parse
import uuid

from pyats import aetest

from libs.mycelium_api import MyceliumAPI

log = logging.getLogger(__name__)

parameters = {}

_BACKEND_BASE = "http://localhost:8000"


def _enc(name: str) -> str:
    return urllib.parse.quote(name, safe="")


def _ssrf_blocked(detail) -> bool:
    return "SSRF guard" in str(detail)


class OutboundA2ARegistration(aetest.Testcase):
    """Registering a remote A2A agent resolves the card at registration time."""

    @aetest.setup
    def setup_rooms(self, api: MyceliumAPI, testscript):
        self.room_a = f"qa-coord-fresh-{uuid.uuid4().hex[:8]}"
        self.room_b = f"qa-coord-fresh-{uuid.uuid4().hex[:8]}"
        testscript.parameters.setdefault("owned_rooms", set()).update({self.room_a, self.room_b})
        for room in (self.room_a, self.room_b):
            status, _ = api.create_room(room)
            assert status in (200, 201), f"room create ({room}) returned {status}"

    @aetest.test
    def registration_resolves_the_remote_card(self, api: MyceliumAPI):
        status, agent = api.post_json(
            f"/rooms/{_enc(self.room_a)}/a2a-agents",
            {"handle": "remote-room-b", "card": f"{_BACKEND_BASE}/api/rooms/{self.room_b}"},
        )
        if status == 404:
            self.skipped("A2A endpoints not present in this build")
            return
        if status == 502 and _ssrf_blocked(agent.get("detail") if isinstance(agent, dict) else agent):
            self.skipped(
                "Backend needs A2A_ALLOW_PRIVATE_HOSTS=1 to resolve a local card "
                "(SSRF guard) — see nightly_a2a.py's module docstring"
            )
            return
        assert status == 201, f"registration returned {status}: {agent}"
        assert agent["adapter"] == "a2a", agent
        assert agent["a2a_endpoint"] == f"{_BACKEND_BASE}/api/rooms/{self.room_b}/a2a", agent

    @aetest.test
    def unreachable_card_is_502(self, api: MyceliumAPI):
        status, resp = api.post_json(
            f"/rooms/{_enc(self.room_a)}/a2a-agents",
            {
                "handle": "unreachable-agent",
                "card": f"{_BACKEND_BASE}/api/rooms/qa-a2a-ghost-{uuid.uuid4().hex[:8]}",
            },
        )
        if status == 404:
            self.skipped("A2A endpoints not present in this build")
            return
        assert status == 502, f"Expected 502 for an unresolvable card, got {status}: {resp}"

    @aetest.cleanup
    def delete_rooms(self, api: MyceliumAPI):
        api.delete_room(self.room_a)
        api.delete_room(self.room_b)


class OutboundA2AMentionRoundTrip(aetest.Testcase):
    """@-mentioning a registered a2a agent calls it for real and replies back."""

    @aetest.setup
    def setup_rooms_and_register(self, api: MyceliumAPI, testscript):
        self.room_a = f"qa-coord-fresh-{uuid.uuid4().hex[:8]}"
        self.room_b = f"qa-coord-fresh-{uuid.uuid4().hex[:8]}"
        testscript.parameters.setdefault("owned_rooms", set()).update({self.room_a, self.room_b})
        for room in (self.room_a, self.room_b):
            status, _ = api.create_room(room)
            assert status in (200, 201), f"room create ({room}) returned {status}"

        status, agent = api.post_json(
            f"/rooms/{_enc(self.room_a)}/a2a-agents",
            {"handle": "remote-room-b", "card": f"{_BACKEND_BASE}/api/rooms/{self.room_b}"},
        )
        self._skip_reason = None
        if status == 404:
            self._skip_reason = "A2A endpoints not present in this build"
        elif status == 502 and _ssrf_blocked(agent.get("detail") if isinstance(agent, dict) else agent):
            self._skip_reason = (
                "Backend needs A2A_ALLOW_PRIVATE_HOSTS=1 to resolve a local card (SSRF guard)"
            )
        else:
            assert status == 201, f"registration returned {status}: {agent}"

    @aetest.test
    def mention_calls_the_remote_room_and_posts_its_reply(self, api: MyceliumAPI):
        if self._skip_reason:
            self.skipped(self._skip_reason)
            return

        status, _ = api.post_json(
            f"/rooms/{_enc(self.room_a)}/messages",
            {
                "sender_handle": "qa-human",
                "message_type": "broadcast",
                "content": "@remote-room-b can you check this?",
            },
        )
        assert status == 201, f"message post returned {status}"

        reply = None
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            status, data = api.get_json(f"/rooms/{_enc(self.room_a)}/messages?limit=20")
            assert status == 200, f"messages list returned {status}: {data}"
            reply = next(
                (m for m in data.get("messages", []) if m["sender_handle"] == "remote-room-b"),
                None,
            )
            if reply is not None:
                break
            time.sleep(1)

        assert reply is not None, "Expected a reply from remote-room-b within 15s"
        assert f"Delivered to room '{self.room_b}'" in reply["content"], reply

    @aetest.cleanup
    def delete_rooms(self, api: MyceliumAPI):
        api.delete_room(self.room_a)
        api.delete_room(self.room_b)
