# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Contract drift guard for the shared SLIM+L9 wire primitives (backend side).

The CLI daemon
(``mycelium-cli/src/mycelium/slim/*``) carries a copy of these primitives so the
thin ``uv tool`` CLI need not import the FastAPI/ML backend. A copy drifts
silently — a diverging ``mint_shared_secret`` / master secret / ``workspace/room``
scope / envelope shape / URN form means MLS group keys mismatch and connectors
**silently can't join**, or messages get dropped/misrouted (no app-level error).

This test freezes the shared wire constants in ``contracts/slim-l9-wire.json`` at the
repo root and asserts the **backend** primitives reproduce them exactly. The CLI
suite asserts its own copy against the *same* file
(``mycelium-cli/tests/test_slim_l9_contract.py``). One frozen source, two
asserters — so neither copy can move without turning this fast unit gate red
(no live SLIM node required).
"""

import json
from pathlib import Path

import pytest

from app.services import l9, slim_identity
from app.services.l9_models import Kind
from app.services.memory_sync import KnowledgeWrite, build_knowledge_envelope
from app.services.slim_client import (
    _DEV_MASTER_SECRET,
    DEFAULT_CHANNEL_TOPIC,
    DEFAULT_NODE_ENDPOINT,
    DEFAULT_NODE_PORT,
    MIN_SECRET_LEN,
    SlimIdentity,
    mint_shared_secret,
)

_CONTRACT_PATH = Path(__file__).resolve().parent.parent.parent / "contracts" / "slim-l9-wire.json"


def _contract() -> dict:
    return json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))


def test_contract_file_present():
    assert _CONTRACT_PATH.is_file(), f"missing shared contract file at {_CONTRACT_PATH}"


def test_shared_constants_match_contract():
    """The literals the shared secret + naming derive from are frozen."""
    g = _contract()
    assert g["master_secret"] == _DEV_MASTER_SECRET
    assert g["channel_topic"] == DEFAULT_CHANNEL_TOPIC
    assert g["min_secret_len"] == MIN_SECRET_LEN
    assert g["node_endpoint"] == DEFAULT_NODE_ENDPOINT
    assert g["node_port"] == DEFAULT_NODE_PORT


def test_mint_shared_secret_matches_contract_digest():
    """The exact HMAC digest a member/moderator derive for a known room."""
    g = _contract()["shared_secret"]
    identity = SlimIdentity(g["workspace"], g["room"], g["agent"])
    assert mint_shared_secret(identity) == g["expected_digest"]


def test_signerjwt_identity_constants_match_contract():
    """The SignerJwt-floor labels both members must agree on are frozen."""
    g = _contract()["identity"]
    assert g["mode_env"] == slim_identity._MODE_ENV
    assert g["require_env"] == slim_identity._REQUIRE_ENV
    assert g["mode_default"] == slim_identity.MODE_PSK
    assert list(slim_identity.VALID_MODES) == g["modes"]
    assert g["issuer"] == slim_identity.SIGNERJWT_ISSUER
    assert g["audience"] == slim_identity.SIGNERJWT_AUDIENCE
    assert g["alg"] == slim_identity.SIGNERJWT_ALG
    assert g["curve"] == slim_identity.SIGNERJWT_CURVE


def test_retired_spire_tier_is_absent_from_contract():
    """The SPIRE tier is retired: neither copy may reintroduce it (#668)."""
    identity = _contract()["identity"]
    assert "spire" not in identity
    assert "spire" not in identity["modes"]
    assert "spire" not in slim_identity.VALID_MODES


def test_episode_and_topic_urns_match_contract():
    """The episode/topic URN forms the connector must mirror."""
    g = _contract()["urn"]
    assert l9.episode_urn(g["room"], g["session"]) == g["expected_episode"]
    assert l9.topic_urn(g["room"]) == g["expected_topic"]


def test_exchange_envelope_serializes_to_contract():
    """The backend's serialized exchange envelope is byte-for-byte the contract."""
    g = _contract()["envelope"]
    i = g["inputs"]
    envelope = l9.build_envelope(
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
    content = {"content": i["text"], "l9": l9.envelope_to_dict(envelope)}
    assert content == g["expected_content"]


def test_knowledge_envelope_serializes_to_contract():
    """The backend's serialized ``knowledge:distillation`` envelope is the contract.

    The memory-sync wire shape: ``build_knowledge_envelope``
    wraps a :class:`KnowledgeWrite` as a ``knowledge:distillation`` envelope the CLI
    daemon parses and applies. ``build_knowledge_envelope`` mints a fresh random
    ``message.id`` per call (it is not part of the shared contract), so the produced
    id is normalized to the contract's placeholder before the byte-for-byte compare;
    every other field must match exactly.
    """
    g = _contract()["knowledge"]
    w = g["write"]
    write = KnowledgeWrite(
        key=w["key"],
        content=w["content"],
        version=w["version"],
        base_version=w["base_version"],
        created_by=w["created_by"],
        updated_by=w["updated_by"],
        updated_at=w["updated_at"],
    )
    envelope = build_knowledge_envelope(
        room=g["room"],
        write=write,
        recipients=g["recipients"],
    )
    produced = l9.envelope_to_dict(envelope)
    # The message id is a fresh UUID per build — freeze everything else, and check
    # the id is a non-empty string separately (not a shared-contract value).
    assert isinstance(produced["header"]["message"]["id"], str)
    assert produced["header"]["message"]["id"]
    produced["header"]["message"]["id"] = g["message_id_placeholder"]
    assert produced == g["expected_envelope"]


def test_valid_subkinds_match_contract():
    """The backend's subkind table matches the frozen contract the CLI mirrors."""
    g = {k: v for k, v in _contract()["valid_subkinds"].items() if k != "_comment"}
    assert {k.value for k in l9.VALID_SUBKINDS} == set(g)
    for kind, allowed in g.items():
        assert l9.VALID_SUBKINDS[Kind(kind)] == frozenset(allowed)


def test_ping_payload_matches_contract():
    """The ping the backend raises is the one the CLI's tail knows how to draw.

    Rename it on this side alone and two things go quiet: the CLI stops
    surfacing that a task moved, and every resident agent starts waking on every
    thread write, because the exclusion in ``participate._addressed_to`` keys off
    this same literal.
    """
    import asyncio
    import json as json_module

    from app.bus import bus
    from app.services.room_channels import RoomChannelManager

    g = _contract()["ping"]
    assert g["payload_type"] == l9.PING_PAYLOAD_TYPE

    published: list[dict] = []
    original = bus.publish
    bus.publish = lambda _ch, frame: published.append(frame)  # type: ignore[method-assign]
    try:
        manager = RoomChannelManager(
            endpoint="http://127.0.0.1:46357", default_workspace="mycelium"
        )
        asyncio.run(
            manager.raise_ping(
                "acme", episode=l9.episode_urn("acme", "t3"), sender="avery", message_id="m1"
            )
        )
    finally:
        bus.publish = original  # type: ignore[method-assign]

    content = json_module.loads(published[0]["content"])
    payload = content["l9"]["payload"]
    assert payload["type"] == g["payload_type"]
    assert sorted(payload["data"]) == sorted(g["payload_fields"])
    # The whole of it: a ping names the thread and never echoes what was said.
    assert "content" not in content


def test_notice_payload_matches_contract():
    """The notice the backend raises is the one the GUI draws in the timeline.

    Same stakes as the ping: rename the type on this side and either the channel
    stops showing that the board moved, or every resident agent starts waking on
    every board write (``participate._addressed_to`` keys off this same literal).
    """
    import asyncio
    import json as json_module

    from app.bus import bus
    from app.services.room_channels import RoomChannelManager

    g = _contract()["notice"]
    assert g["payload_type"] == l9.NOTICE_PAYLOAD_TYPE
    assert set(g["subkinds"]) == set(l9.NOTICE_SUBKINDS)

    published: list[dict] = []
    original = bus.publish
    bus.publish = lambda _ch, frame: published.append(frame)  # type: ignore[method-assign]
    try:
        manager = RoomChannelManager(
            endpoint="http://127.0.0.1:46357", default_workspace="mycelium"
        )
        asyncio.run(
            manager.raise_notice(
                "acme",
                subkind="filed",
                key="work/ship-auth",
                title="ship auth",
                episode=l9.episode_urn("acme", "t3"),
                by="avery",
                kind="action",
            )
        )
    finally:
        bus.publish = original  # type: ignore[method-assign]

    payload = json_module.loads(published[0]["content"])["l9"]["payload"]
    assert payload["type"] == g["payload_type"]
    assert payload["data"]["subkind"] in g["subkinds"]
    assert payload["data"]["key"] == "work/ship-auth"


def test_channel_name_topic_matches_contract():
    """A room channel's app segment is the frozen default topic."""
    pytest.importorskip("slim_bindings")
    from app.services.slim_client import to_channel_name

    g = _contract()
    name = to_channel_name("acme", "planning")
    assert name.components() == ["acme", "planning", g["channel_topic"]]
