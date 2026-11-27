# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Contract drift guard for the shared message format (backend side).

The CLI carries its own copy of the message-format primitives
(``mycelium-cli/src/mycelium/message_format.py``) so the thin ``uv tool`` CLI
need not import the backend. A copy drifts silently: a diverging envelope
shape or URN form means a reply the hub can't parse, or a room message read
as a thread's.

This test freezes the shared constants in ``contracts/message-wire.json`` at
the repo root and asserts the **backend** primitives reproduce them exactly.
The CLI suite asserts its own copy against the *same* file
(``mycelium-cli/tests/test_message_wire.py``).
"""

import asyncio
import json
from pathlib import Path

from app.bus import bus
from app.services import message_format
from app.services.filesystem import ensure_room_structure, get_room_dir
from app.services.message_models import Kind
from app.services.room_channels import RoomChannelManager

_CONTRACT_PATH = Path(__file__).resolve().parent.parent.parent / "contracts" / "message-wire.json"


def _contract() -> dict:
    return json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))


def test_contract_file_present():
    assert _CONTRACT_PATH.is_file(), f"missing shared contract file at {_CONTRACT_PATH}"


def test_episode_and_topic_urns_match_contract():
    """The episode/topic URN forms the CLI and the app must mirror."""
    g = _contract()["urn"]
    assert message_format.episode_urn(g["room"], g["session"]) == g["expected_episode"]
    assert message_format.topic_urn(g["room"]) == g["expected_topic"]
    assert message_format.canonical_urn(g["legacy_episode"]) == g["expected_episode"]
    assert message_format.is_live_episode(g["room"], g["legacy_episode"])


def test_exchange_envelope_serializes_to_contract():
    """The backend's serialized exchange envelope is byte-for-byte the contract."""
    g = _contract()["envelope"]
    i = g["inputs"]
    envelope = message_format.build_envelope(
        kind=Kind.exchange,
        episode=i["episode"],
        parents=i["parents"],
        sender=i["sender"],
        sender_role="agent",
        recipients=i["recipients"],
        recipient_role="agent",
        topic=i["topic"],
        payload_type=i["payload_type"],
        payload_data={},
        message_id=i["message_id"],
    )
    content = message_format.serialize_content(envelope, extra={"content": i["text"]})
    assert content == g["expected_content"]


def test_valid_subkinds_match_contract():
    """The backend's subkind table matches the frozen contract the CLI mirrors."""
    g = {k: v for k, v in _contract()["valid_subkinds"].items() if k != "_comment"}
    assert {k.value for k in message_format.VALID_SUBKINDS} == set(g)
    for kind, allowed in g.items():
        assert message_format.VALID_SUBKINDS[Kind(kind)] == frozenset(allowed)


def _published(raise_it) -> dict:
    """The content of the first frame ``raise_it`` publishes on the bus."""
    ensure_room_structure(get_room_dir("acme"))
    published: list[dict] = []
    original = bus.publish
    bus.publish = lambda _ch, frame: published.append(frame)  # type: ignore[method-assign]
    try:
        asyncio.run(raise_it(RoomChannelManager()))
    finally:
        bus.publish = original  # type: ignore[method-assign]
    return json.loads(published[0]["content"])


def test_ping_payload_matches_contract():
    """The ping the backend raises is the one the CLI's tail knows how to draw.

    Rename it on this side alone and the CLI stops surfacing that a task moved.
    """
    g = _contract()["ping"]
    assert g["payload_type"] == message_format.PING_PAYLOAD_TYPE
    content = _published(
        lambda manager: manager.raise_ping(
            "acme",
            episode=message_format.episode_urn("acme", "t3"),
            sender="avery",
            message_id="m1",
        )
    )
    payload = content["envelope"]["payload"]
    assert payload["type"] == g["payload_type"]
    assert sorted(payload["data"]) == sorted(g["payload_fields"])
    # The whole of it: a ping names the thread and never echoes what was said.
    assert "content" not in content


def test_notice_payload_matches_contract():
    """The notice the backend raises is the one the GUI draws in the timeline.

    Same stakes as the ping: rename the type on this side and the channel stops
    showing that the board moved.
    """
    g = _contract()["notice"]
    assert g["payload_type"] == message_format.NOTICE_PAYLOAD_TYPE
    assert set(g["subkinds"]) == set(message_format.NOTICE_SUBKINDS)
    assert set(g["upstream_changes"]) == set(message_format.UPSTREAM_CHANGES)
    content = _published(
        lambda manager: manager.raise_notice(
            "acme",
            subkind="filed",
            key="work/ship-auth",
            title="ship auth",
            episode=message_format.episode_urn("acme", "t3"),
            by="avery",
            kind="action",
        )
    )
    payload = content["envelope"]["payload"]
    assert payload["type"] == g["payload_type"]
    assert payload["data"]["subkind"] in g["subkinds"]
    assert payload["data"]["key"] == "work/ship-auth"
