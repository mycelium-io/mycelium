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

import pytest

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


# ── build_envelope_content — the generic builder behind `l9 send` ───────────


def test_build_envelope_content_sets_kind_and_subkind() -> None:
    content = l9.build_envelope_content(
        kind="commit",
        subkind="resolved",
        sender="julia",
        recipients=["bob"],
        episode="ep-1",
        parents=["p-1"],
        payload_data={"assignments": {"cap": "30"}},
    )
    assert content["l9"]["header"]["kind"] == "commit"
    assert content["l9"]["header"]["subkind"] == "resolved"
    assert content["l9"]["header"]["message"]["parents"] == ["p-1"]
    assert content["l9"]["payload"]["data"] == {"assignments": {"cap": "30"}}


def test_build_envelope_content_omits_subkind_when_absent() -> None:
    content = l9.build_envelope_content(kind="exchange", sender="julia", episode="ep-1")
    assert "subkind" not in content["l9"]["header"]


def test_build_envelope_content_rejects_invalid_subkind() -> None:
    with pytest.raises(l9.L9ValidationError):
        l9.build_envelope_content(
            kind="exchange", subkind="not-a-real-subkind", sender="julia", episode="ep-1"
        )


def test_build_reply_content_matches_generic_builder_for_exchange() -> None:
    """build_reply_content is exactly the exchange-kind specialization."""
    via_generic = l9.build_envelope_content(
        kind=l9.EXCHANGE_KIND,
        sender="a",
        recipients=["b"],
        episode="ep",
        parents=["p"],
        topic="t",
        text="hi",
        message_id="m-1",
        payload_type="reply",
    )
    via_reply = l9.build_reply_content(
        sender="a",
        recipients=["b"],
        episode="ep",
        parents=["p"],
        topic="t",
        text="hi",
        message_id="m-1",
        payload_type="reply",
    )
    assert via_generic == via_reply


# ── kind/subkind validation ──────────────────────────────────────────────────


def test_validate_kind_accepts_known_kinds() -> None:
    for kind in l9.VALID_KINDS:
        l9.validate_kind(kind)  # must not raise


def test_validate_kind_rejects_unknown_kind() -> None:
    with pytest.raises(l9.L9ValidationError):
        l9.validate_kind("not-a-kind")


def test_validate_subkind_none_always_valid() -> None:
    for kind in l9.VALID_KINDS:
        l9.validate_subkind(kind, None)  # must not raise


def test_validate_subkind_accepts_allowed_pairs() -> None:
    for kind, subkinds in l9.VALID_SUBKINDS.items():
        for subkind in subkinds:
            l9.validate_subkind(kind, subkind)  # must not raise


def test_validate_subkind_rejects_mismatched_pair() -> None:
    with pytest.raises(l9.L9ValidationError):
        l9.validate_subkind("exchange", "converged")  # "converged" belongs to commit
