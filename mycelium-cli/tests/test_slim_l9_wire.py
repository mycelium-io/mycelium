# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Contract drift guard for the shared SLIM+L9 wire primitives (CLI side).

The CLI carries its own copy of the SLIM+L9 primitives
(``mycelium.slim.{naming,client,l9}``) so the
thin ``uv tool`` CLI need not import the FastAPI/ML backend. A diverging
``mint_shared_secret`` / master secret / ``workspace/room`` scope / envelope
shape / URN form means MLS group keys mismatch and this connector **silently
can't join** the backend moderator's group, or its replies get dropped/misrouted
(no app-level error).

This test freezes the shared wire constants in ``contracts/slim-l9-wire.json`` at the
repo root and asserts the **CLI** primitives reproduce them exactly, preventing
silent wire-contract drift (no live SLIM node required).
"""

import json
from pathlib import Path

import pytest

from mycelium.slim import identity as slim_identity
from mycelium.slim import l9
from mycelium.slim.l9 import room_episode as _room_episode
from mycelium.slim.l9 import room_topic as _room_topic
from mycelium.slim.naming import (
    _DEV_MASTER_SECRET,
    DEFAULT_CHANNEL_TOPIC,
    DEFAULT_NODE_ENDPOINT,
    DEFAULT_NODE_PORT,
    DEFAULT_WORKSPACE,
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
    assert g["workspace"] == DEFAULT_WORKSPACE
    assert g["channel_topic"] == DEFAULT_CHANNEL_TOPIC
    assert g["min_secret_len"] == MIN_SECRET_LEN
    assert g["node_endpoint"] == DEFAULT_NODE_ENDPOINT
    assert g["node_port"] == DEFAULT_NODE_PORT


def test_mint_shared_secret_matches_contract_digest():
    """The exact HMAC digest a connector derives for a known room."""
    g = _contract()["shared_secret"]
    identity = SlimIdentity(g["workspace"], g["room"], g["agent"])
    assert mint_shared_secret(identity) == g["expected_digest"]


def test_signerjwt_identity_constants_match_contract():
    """The CLI's SignerJwt-floor labels match the backend's frozen contract."""
    g = _contract()["identity"]
    assert g["mode_env"] == slim_identity._MODE_ENV
    assert g["require_env"] == slim_identity._REQUIRE_ENV
    assert g["mode_default"] == slim_identity.MODE_PSK
    assert list(slim_identity.VALID_MODES) == g["modes"]
    assert g["issuer"] == slim_identity.SIGNERJWT_ISSUER
    assert g["audience"] == slim_identity.SIGNERJWT_AUDIENCE
    assert g["alg"] == slim_identity.SIGNERJWT_ALG
    assert g["curve"] == slim_identity.SIGNERJWT_CURVE


def test_episode_and_topic_urns_match_contract():
    """The CLI's episode/topic URN forms match the backend's."""
    g = _contract()["urn"]
    assert _room_episode(g["room"]) == g["expected_episode"]
    assert _room_topic(g["room"]) == g["expected_topic"]


def test_exchange_reply_serializes_to_contract():
    """The connector's serialized exchange reply is byte-for-byte the contract."""
    g = _contract()["envelope"]
    i = g["inputs"]
    content = l9.build_reply_content(
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


def test_knowledge_envelope_parses_to_contract_write():
    """The connector parses the backend's ``knowledge:distillation`` envelope.

    Guards the *parse* half of the memory-sync contract: given
    the exact envelope the backend produces (frozen in the contract), the CLI's
    ``l9.kind_of`` / ``l9.payload_data_of`` — the two the connector's
    ``apply_knowledge_message`` reads through — must recover every carried write
    field byte-for-byte. If the backend's produced shape and this parse ever drift,
    this gate goes red instead of silently breaking cross-machine memory sync.
    """
    g = _contract()["knowledge"]
    # The content dict a connector receives on the wire: the contract envelope under
    # the additive ``l9`` key. (``content`` is empty — a knowledge push carries its
    # payload in ``l9.payload.data``, not the human-text field.)
    content = {"content": "", "l9": g["expected_envelope"]}

    assert l9.kind_of(content) == l9.KNOWLEDGE_KIND

    data = l9.payload_data_of(content)
    w = g["write"]
    assert data["key"] == w["key"]
    assert data["content"] == w["content"]
    assert data["version"] == w["version"]
    assert data["base_version"] == w["base_version"]
    assert data["created_by"] == w["created_by"]
    assert data["updated_by"] == w["updated_by"]
    assert data["updated_at"] == w["updated_at"]


def test_valid_subkinds_match_contract():
    """The CLI's kind/subkind vocabulary (used by the hidden `l9 send` plumbing)
    is byte-for-byte the backend's ``app.services.l9.VALID_SUBKINDS`` table."""
    g = {k: v for k, v in _contract()["valid_subkinds"].items() if k != "_comment"}
    assert set(l9.VALID_KINDS) == set(g)
    for kind, allowed in g.items():
        assert l9.VALID_SUBKINDS[kind] == frozenset(allowed)


def test_channel_name_topic_matches_contract():
    """A room channel's app segment is the frozen default topic."""
    pytest.importorskip("slim_bindings")
    from mycelium.slim.naming import to_channel_name

    g = _contract()
    name = to_channel_name("acme", "planning")
    assert name.components() == ["acme", "planning", g["channel_topic"]]
