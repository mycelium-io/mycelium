# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Golden drift guard for the shared SLIM+L9 wire primitives (backend side).

D2 (bible Part IV, Known debt register): the CLI daemon
(``mycelium-cli/src/mycelium/slim/*``) carries a copy of these primitives so the
thin ``uv tool`` CLI need not import the FastAPI/ML backend. A copy drifts
silently — a diverging ``mint_shared_secret`` / master secret / ``workspace/room``
scope / envelope shape / URN form means MLS group keys mismatch and connectors
**silently can't join**, or messages get dropped/misrouted (no app-level error).

This test freezes the shared wire constants in ``slim-l9-golden.json`` at the
repo root and asserts the **backend** primitives reproduce them exactly. The CLI
suite asserts its own copy against the *same* file
(``mycelium-cli/tests/test_slim_l9_golden.py``). One frozen source, two
asserters — so neither copy can move without turning this fast unit gate red
(no live SLIM node required).
"""

import json
from pathlib import Path

import pytest

from app.services import l9
from app.services.l9_models import Kind
from app.services.slim_client import (
    _DEV_MASTER_SECRET,
    DEFAULT_CHANNEL_TOPIC,
    DEFAULT_NODE_ENDPOINT,
    DEFAULT_NODE_PORT,
    MIN_SECRET_LEN,
    SlimIdentity,
    mint_shared_secret,
)

_GOLDEN_PATH = Path(__file__).resolve().parent.parent.parent / "slim-l9-golden.json"


def _golden() -> dict:
    return json.loads(_GOLDEN_PATH.read_text(encoding="utf-8"))


def test_golden_file_present():
    assert _GOLDEN_PATH.is_file(), f"missing shared golden file at {_GOLDEN_PATH}"


def test_shared_constants_match_golden():
    """The literals the shared secret + naming derive from are frozen."""
    g = _golden()
    assert g["master_secret"] == _DEV_MASTER_SECRET
    assert g["channel_topic"] == DEFAULT_CHANNEL_TOPIC
    assert g["min_secret_len"] == MIN_SECRET_LEN
    assert g["node_endpoint"] == DEFAULT_NODE_ENDPOINT
    assert g["node_port"] == DEFAULT_NODE_PORT


def test_mint_shared_secret_matches_golden_digest():
    """The exact HMAC digest a member/moderator derive for a known room."""
    g = _golden()["shared_secret"]
    identity = SlimIdentity(g["workspace"], g["room"], g["agent"])
    assert mint_shared_secret(identity) == g["expected_digest"]


def test_episode_and_topic_urns_match_golden():
    """The episode/topic URN forms the connector must mirror."""
    g = _golden()["urn"]
    assert l9.episode_urn(g["room"], g["session"]) == g["expected_episode"]
    assert l9.topic_urn(g["room"]) == g["expected_topic"]


def test_exchange_envelope_serializes_to_golden():
    """The backend's serialized exchange envelope is byte-for-byte the golden."""
    g = _golden()["envelope"]
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


def test_channel_name_topic_matches_golden():
    """A room channel's app segment is the frozen default topic."""
    pytest.importorskip("slim_bindings")
    from app.services.slim_client import to_channel_name

    g = _golden()
    name = to_channel_name("acme", "planning")
    assert name.components() == ["acme", "planning", g["channel_topic"]]
