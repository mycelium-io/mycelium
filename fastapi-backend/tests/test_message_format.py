# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Tests for the message module (app/services/message_format.py)."""

import json
import uuid

import pytest

from app.services import message_format
from app.services.message_models import Kind


def test_episode_and_topic_urns():
    assert (
        message_format.episode_urn("sprint", "abc123") == "urn:ioc:mycelium:episode:sprint:abc123"
    )
    assert message_format.topic_urn("sprint") == "urn:concept:mycelium:sprint"


def test_build_minimal_envelope_defaults():
    env = message_format.build_envelope(kind=Kind.exchange, episode="urn:ioc:mycelium:episode:r:s")
    assert env.header.protocol == "SSTP"
    assert env.header.subprotocol == "mycelium"
    assert env.header.kind is Kind.exchange
    assert env.header.subkind is None
    assert env.header.participants.actors[0].id == "system"
    assert env.header.participants.groups is None
    assert env.header.message is not None
    uuid.UUID(env.header.message.id)  # valid UUID
    assert env.header.message.parents == []
    assert env.payload.type == "data"
    assert env.payload.data == {}


def test_build_envelope_full():
    env = message_format.build_envelope(
        kind=Kind.commit,
        subkind="converged",
        episode="urn:ioc:mycelium:episode:r:s",
        parents=["p1", "p2"],
        recipients=["agent-a", "agent-b"],
        topic="urn:concept:mycelium:r",
        workspace_id="ws-1",
        mas_id="mas-1",
        payload_type="consensus",
        payload_data={"assignments": {"budget": "high"}},
    )
    assert env.header.subkind == "converged"
    assert [a.id for a in env.header.participants.actors] == [
        "system",
        "agent-a",
        "agent-b",
    ]
    assert env.header.participants.groups == {"workspace_id": "ws-1", "mas_id": "mas-1"}
    assert env.header.message is not None and env.header.context is not None
    assert env.header.message.parents == ["p1", "p2"]
    assert env.header.context.topic == "urn:concept:mycelium:r"
    assert env.payload.data["assignments"] == {"budget": "high"}


# The SLIM-native table. A failed negotiation is commit:rejected;
# the Go CFN's "abort" is retired with the CFN, and "ready" was never valid.
@pytest.mark.parametrize(
    ("kind", "subkind", "ok"),
    [
        (Kind.commit, "converged", True),
        (Kind.commit, "resolved", True),
        (Kind.commit, "rejected", True),
        (Kind.commit, "abort", False),
        (Kind.commit, "ready", False),
        (Kind.exchange, "team-formation", True),
        (Kind.exchange, "ready", False),
        (Kind.intent, "mission", True),
        (Kind.intent, "coordinator-assignment", True),
        (Kind.contingency, "negotiation", True),
        (Kind.knowledge, "query", True),
        (Kind.knowledge, "distillation", True),
        (Kind.knowledge, "extraction", True),
        (Kind.knowledge, "feedback", True),
        (Kind.knowledge, "converged", False),
        (Kind.exchange, None, True),  # empty subkind always valid
        (Kind.exchange, "", True),
    ],
)
def test_subkind_validation(kind, subkind, ok):
    if ok:
        message_format.validate_subkind(kind, subkind)
    else:
        with pytest.raises(message_format.MessageValidationError):
            message_format.validate_subkind(kind, subkind)


def test_build_envelope_rejects_bad_subkind():
    with pytest.raises(message_format.MessageValidationError):
        message_format.build_envelope(kind=Kind.commit, subkind="abort", episode="e")


def test_envelope_roundtrip_via_dict():
    env = message_format.build_envelope(
        kind=Kind.knowledge,
        subkind="query",
        episode="urn:ioc:mycelium:episode:r:s",
        topic="urn:concept:mycelium:r",
        workspace_id="ws",
        mas_id="mas",
        payload_data={"intent": "prior agreements on this topic"},
    )
    as_dict = message_format.envelope_to_dict(env)
    # exclude_none keeps the wire shape lean
    assert "policy" not in as_dict["header"]
    parsed = message_format.parse_envelope(as_dict)
    assert parsed.header.message is not None and env.header.message is not None
    assert parsed.header.message.id == env.header.message.id
    assert parsed.payload.data == env.payload.data
    # also from a JSON string
    parsed2 = message_format.parse_envelope(json.dumps(as_dict))
    assert parsed2.header.kind is Kind.knowledge


def test_parse_envelope_rejects_invalid_subkind():
    env = message_format.build_envelope(kind=Kind.commit, subkind="converged", episode="e")
    as_dict = message_format.envelope_to_dict(env)
    as_dict["header"]["subkind"] = "ready"
    with pytest.raises(message_format.MessageValidationError):
        message_format.parse_envelope(as_dict)


def test_extract_parent_id():
    env = message_format.build_envelope(kind=Kind.exchange, episode="e")
    assert env.header.message is not None
    content = json.dumps({"payload": {"round": 1}, "l9": message_format.envelope_to_dict(env)})
    assert message_format.extract_parent_id(content) == env.header.message.id
    assert message_format.extract_parent_id('{"payload": {}}') is None
    assert message_format.extract_parent_id("not json") is None
    assert message_format.extract_parent_id({}) is None
