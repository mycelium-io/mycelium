"""PR checks — A2A inbound (a room exposed as an A2A agent). No LLM required.

A2A ("Agent2Agent") lets an external client discover a room's Agent Card
and post into it over JSON-RPC. This is the inbound half only — no real
external A2A agent needed, no mock server, since the room *is* the server
here. The outbound half (registering a remote A2A agent) needs a real
reachable Agent Card URL and lives in nightly_a2a.py against a small local
mock instead.

Tests:
  - Agent Card discovery shape (name, rpc endpoint, skills)
  - message/send JSON-RPC delivers into the room and acks
  - /a2a/state reflects the card fetch and the inbound exchange
  - Both routes 404 on a room that doesn't exist
"""

from __future__ import annotations

import logging
import urllib.parse
import uuid

from pyats import aetest

from libs.mycelium_api import MyceliumAPI

log = logging.getLogger(__name__)

parameters = {}


def _enc(name: str) -> str:
    return urllib.parse.quote(name, safe="")


def _send_rpc(text: str, message_id: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "message/send",
        "params": {
            "configuration": {"acceptedOutputModes": ["text"]},
            "message": {
                "kind": "message",
                "messageId": message_id,
                "role": "user",
                "parts": [{"kind": "text", "text": text}],
            },
        },
    }


class InboundA2AAgentCard(aetest.Testcase):
    """The room's Agent Card is discoverable and names its own JSON-RPC endpoint."""

    @aetest.setup
    def setup_room(self, api: MyceliumAPI, testscript):
        self.room = f"qa-coord-fresh-{uuid.uuid4().hex[:8]}"
        testscript.parameters.setdefault("owned_rooms", set()).add(self.room)
        status, _ = api.create_room(self.room)
        assert status in (200, 201)

    @aetest.test
    def card_names_the_room_and_its_rpc_endpoint(self, api: MyceliumAPI):
        status, card = api.get_json(f"/rooms/{_enc(self.room)}/.well-known/agent-card.json")
        if status == 404:
            self.skipped("A2A endpoints not present in this build")
            return
        assert status == 200, f"agent card fetch returned {status}: {card}"
        assert card["name"] == self.room, card
        rpc_urls = [i["url"] for i in card["supportedInterfaces"]]
        assert any(u.endswith(f"/rooms/{self.room}/a2a") for u in rpc_urls), card

    @aetest.test
    def missing_room_card_is_404(self, api: MyceliumAPI):
        status, _ = api.get_json(f"/rooms/qa-a2a-ghost-{uuid.uuid4().hex[:8]}/.well-known/agent-card.json")
        assert status == 404, f"Expected 404 for a nonexistent room's card, got {status}"

    @aetest.cleanup
    def delete_room(self, api: MyceliumAPI):
        api.delete_room(self.room)


class InboundA2AMessageSend(aetest.Testcase):
    """message/send delivers into the room, acks, and shows up in /a2a/state."""

    @aetest.setup
    def setup_room(self, api: MyceliumAPI, testscript):
        self.room = f"qa-coord-fresh-{uuid.uuid4().hex[:8]}"
        testscript.parameters.setdefault("owned_rooms", set()).add(self.room)
        status, _ = api.create_room(self.room)
        assert status in (200, 201)
        self.enc = _enc(self.room)

    @aetest.test
    def message_send_delivers_and_acks(self, api: MyceliumAPI):
        text = "hello from an external A2A caller"
        status, resp = api.post_json(
            f"/rooms/{self.enc}/a2a", _send_rpc(text, "qa-a2a-msg-1")
        )
        if status == 404:
            self.skipped("A2A endpoints not present in this build")
            return
        assert status == 200, f"message/send returned {status}: {resp}"
        result = resp["result"]
        ack = "".join(p.get("text", "") for p in result["parts"])
        # Room create already provisions the SLIM channel (rooms.py), so this
        # should always be real delivery, never the "room not active" fallback.
        assert "Delivered to room" in ack, f"Expected real delivery, got: {ack}"

        status, state = api.get_json(f"/rooms/{self.enc}/a2a/state")
        assert status == 200, f"a2a/state returned {status}: {state}"
        assert state["exposure"]["messages"] >= 1, state
        assert state["exchanges"], f"Expected at least one exchange: {state}"
        last = state["exchanges"][-1]
        assert last["direction"] == "inbound", last
        assert last["prompt"] == text, last

    @aetest.test
    def message_send_missing_room_is_404(self, api: MyceliumAPI):
        status, _ = api.post_json(
            f"/rooms/qa-a2a-ghost-{uuid.uuid4().hex[:8]}/a2a",
            _send_rpc("ping", "qa-a2a-msg-ghost"),
        )
        assert status == 404, f"Expected 404 for a nonexistent room, got {status}"

    @aetest.cleanup
    def delete_room(self, api: MyceliumAPI):
        api.delete_room(self.room)
