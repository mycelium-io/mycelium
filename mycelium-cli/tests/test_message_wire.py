# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Contract drift guard for the shared message envelope (CLI side).

The CLI carries its own copy of the message envelope helpers
(``mycelium.message_format``) so the thin ``uv tool`` CLI need not import the
FastAPI/ML backend. A diverging envelope shape or URN form means its replies
get dropped or misrouted with no app-level error.

This test freezes the shared constants in ``contracts/message-wire.json`` at the
repo root and asserts the **CLI** helpers reproduce them exactly.
"""

import json
from pathlib import Path

from mycelium import message_format
from mycelium.message_format import room_episode as _room_episode
from mycelium.message_format import room_topic as _room_topic

_CONTRACT_PATH = Path(__file__).resolve().parent.parent.parent / "contracts" / "message-wire.json"


def _contract() -> dict:
    return json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))


def test_contract_file_present():
    assert _CONTRACT_PATH.is_file(), f"missing shared contract file at {_CONTRACT_PATH}"


def test_ping_payload_matches_contract():
    """The CLI reads the ping payload type off the shared contract literal."""
    g = _contract()["ping"]
    assert g["payload_type"] == message_format.PING_PAYLOAD_TYPE

    fields = dict.fromkeys(g["payload_fields"], "x")
    ping = {"envelope": {"payload": {"type": g["payload_type"], "data": fields}}}
    assert message_format.ping_of(ping) == fields
    # Anything else on the channel is not a ping, however it is shaped.
    assert (
        message_format.ping_of({"envelope": {"payload": {"type": "message", "data": fields}}})
        is None
    )
    assert message_format.ping_of({"content": "hello"}) is None


def test_episode_and_topic_urns_match_contract():
    """The CLI's episode/topic URN forms match the backend's."""
    g = _contract()["urn"]
    assert _room_episode(g["room"]) == g["expected_episode"]
    assert _room_topic(g["room"]) == g["expected_topic"]
    assert message_format.canonical_urn(g["legacy_episode"]) == g["expected_episode"]
    assert message_format.is_room_episode(g["room"], g["legacy_episode"])


def test_exchange_reply_serializes_to_contract():
    """The connector's serialized exchange reply is byte-for-byte the contract."""
    g = _contract()["envelope"]
    i = g["inputs"]
    content = message_format.build_reply_content(
        sender=i["sender"],
        recipients=i["recipients"],
        episode=i["episode"],
        parents=i["parents"],
        topic=i["topic"],
        text=i["text"],
        message_id=i["message_id"],
        payload_type=i["payload_type"],
    )
    assert content == g["expected_content"]


def test_valid_subkinds_match_contract():
    """The CLI's kind/subkind vocabulary is byte-for-byte the backend's
    ``app.services.message_format.VALID_SUBKINDS`` table."""
    g = {k: v for k, v in _contract()["valid_subkinds"].items() if k != "_comment"}
    assert set(message_format.VALID_KINDS) == set(g)
    for kind, allowed in g.items():
        assert message_format.VALID_SUBKINDS[kind] == frozenset(allowed)
