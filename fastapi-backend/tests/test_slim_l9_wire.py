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


def test_channel_name_topic_matches_contract():
    """A room channel's app segment is the frozen default topic."""
    pytest.importorskip("slim_bindings")
    from app.services.slim_client import to_channel_name

    g = _contract()
    name = to_channel_name("acme", "planning")
    assert name.components() == ["acme", "planning", g["channel_topic"]]


def test_identity_env_names_match_contract():
    """The identity tier is selected from the same env names on both sides."""
    g = _contract()["identity"]
    assert list(g["modes"]) == list(slim_identity.IDENTITY_MODES)
    assert g["default_mode"] == slim_identity.IDENTITY_MODE_PSK
    assert g["default_algorithm"] == slim_identity.DEFAULT_ALGORITHM
    assert g["default_duration_s"] == slim_identity.DEFAULT_DURATION_S
    assert g["token_dir_name"] == slim_identity.TOKEN_DIR_NAME
    env = g["env"]
    assert env["mode"] == slim_identity.IDENTITY_ENV
    assert env["token"] == slim_identity.TOKEN_ENV
    assert env["token_file"] == slim_identity.TOKEN_FILE_ENV
    assert env["issuer"] == slim_identity.ISSUER_ENV
    assert env["audience"] == slim_identity.AUDIENCE_ENV
    assert env["jwks"] == slim_identity.JWKS_ENV
    assert env["jwks_file"] == slim_identity.JWKS_FILE_ENV
    assert env["algorithm"] == slim_identity.ALGORITHM_ENV
    assert env["duration_s"] == slim_identity.DURATION_ENV
    assert env["require"] == slim_identity.REQUIRE_ENV


def test_identity_defaults_to_the_shared_secret_tier(monkeypatch):
    """An install that configures nothing stays on the PSK."""
    monkeypatch.delenv(slim_identity.IDENTITY_ENV, raising=False)
    assert slim_identity.resolve_mode() == _contract()["identity"]["default_mode"]
