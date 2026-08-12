# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for the daemon-side lean L9 helpers (``mycelium.slim.l9``).

These pin the wire contract the connector shares with the backend moderator: an
``exchange`` envelope under the additive ``l9`` key, sender first / recipients
after, parents threading causality. The *shape parity* with the backend's
``l9.envelope_to_dict`` is proven cross-package in the live integration slice;
here we pin the accessors and the round trip.
"""

from __future__ import annotations

from mycelium.slim import l9


def _inbound(**kw):
    return l9.build_reply_content(
        sender=kw.get("sender", "human"),
        recipients=kw.get("recipients", ["agent-a"]),
        episode=kw.get("episode", "urn:ioc:mycelium:episode:r:live"),
        parents=kw.get("parents", []),
        topic=kw.get("topic", "urn:concept:mycelium:r"),
        text=kw.get("text", "hello"),
        message_id=kw.get("message_id", "m-1"),
    )


def test_build_reply_content_has_exchange_envelope() -> None:
    content = _inbound(sender="agent-a", recipients=["human"], parents=["woke-1"])
    assert l9.kind_of(content) == "exchange"
    assert l9.sender_of(content) == "agent-a"
    assert l9.recipients_of(content) == ["human"]
    assert content["l9"]["header"]["message"]["parents"] == ["woke-1"]
    # subkind is omitted (never emitted) — always-valid exchange.
    assert "subkind" not in content["l9"]["header"]


def test_participants_groups_is_explicit_null() -> None:
    # The backend restores an explicit null after exclude_none; a member must
    # emit the same or re-validation drops the key.
    content = _inbound()
    assert content["l9"]["header"]["participants"]["groups"] is None


def test_accessors_read_id_episode_topic() -> None:
    content = _inbound(message_id="m-9", episode="ep-9", topic="topic-9")
    assert l9.message_id_of(content) == "m-9"
    assert l9.episode_of(content) == "ep-9"
    assert l9.topic_of(content) == "topic-9"


def test_serialize_parse_round_trip() -> None:
    content = _inbound(text="ping")
    restored = l9.parse(l9.serialize(content))
    assert restored == content


def test_parse_rejects_non_json_and_non_object() -> None:
    assert l9.parse(b"\xff\xfe not json") is None
    assert l9.parse(b"[1, 2, 3]") is None


def test_human_text_prefers_content_field() -> None:
    content = _inbound(text="the body")
    assert l9.human_text_of(content) == "the body"


def test_human_text_falls_back_to_string_leaves() -> None:
    # A message whose text landed outside the canonical field still reaches the
    # agent (every non-``l9`` string leaf, joined).
    content = _inbound(text="")
    content["note"] = "surfaced anyway"
    assert "surfaced anyway" in l9.human_text_of(content)


def test_no_topic_omits_context() -> None:
    content = l9.build_reply_content(
        sender="a", recipients=[], episode="ep", parents=[], topic=None, text="x"
    )
    assert "context" not in content["l9"]["header"]
    assert l9.topic_of(content) is None
