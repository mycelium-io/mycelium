# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for the CLI's lean message helpers (``mycelium.message_format``).

These pin the envelope shape the CLI shares with the backend: an ``exchange``
envelope under the additive ``envelope`` key, sender first / recipients after,
parents threading causality.
"""

from __future__ import annotations

import pytest

from mycelium import message_format


def _inbound(**kw):
    return message_format.build_reply_content(
        sender=kw.get("sender", "human"),
        recipients=kw.get("recipients", ["agent-a"]),
        episode=kw.get("episode", "urn:mycelium:episode:r:live"),
        parents=kw.get("parents", []),
        topic=kw.get("topic", "urn:mycelium:topic:r"),
        text=kw.get("text", "hello"),
        message_id=kw.get("message_id", "m-1"),
    )


def test_build_reply_content_has_exchange_envelope() -> None:
    content = _inbound(sender="agent-a", recipients=["human"], parents=["woke-1"])
    assert message_format.kind_of(content) == "exchange"
    assert message_format.sender_of(content) == "agent-a"
    assert message_format.recipients_of(content) == ["human"]
    assert content["envelope"]["header"]["message"]["parents"] == ["woke-1"]
    # subkind is omitted (never emitted) — always-valid exchange.
    assert "subkind" not in content["envelope"]["header"]


def test_participants_groups_is_explicit_null() -> None:
    # The backend restores an explicit null after exclude_none; a member must
    # emit the same or re-validation drops the key.
    content = _inbound()
    assert content["envelope"]["header"]["participants"]["groups"] is None


def test_accessors_read_id_episode_topic() -> None:
    content = _inbound(message_id="m-9", episode="ep-9", topic="topic-9")
    assert message_format.message_id_of(content) == "m-9"
    assert message_format.episode_of(content) == "ep-9"
    assert message_format.topic_of(content) == "topic-9"


def test_human_text_prefers_content_field() -> None:
    content = _inbound(text="the body")
    assert message_format.human_text_of(content) == "the body"


def test_human_text_falls_back_to_string_leaves() -> None:
    # A message whose text landed outside the canonical field still reaches the
    # agent (every string leaf outside the envelope, joined).
    content = _inbound(text="")
    content["note"] = "surfaced anyway"
    assert "surfaced anyway" in message_format.human_text_of(content)


def test_accessors_read_the_older_envelope_key() -> None:
    content = _inbound(message_id="m-9", episode="ep-9")
    legacy = {"content": content["content"], "l9": content["envelope"]}
    assert message_format.envelope_of(legacy) == content["envelope"]
    assert message_format.message_id_of(legacy) == "m-9"
    assert message_format.episode_of(legacy) == "ep-9"
    assert message_format.envelope_of({"content": "hi"}) == {}


def test_frame_kind_reads_both_spellings() -> None:
    assert message_format.frame_kind("envelope_exchange") == "exchange"
    assert message_format.frame_kind("l9_knowledge") == "knowledge"
    assert message_format.frame_kind("broadcast") is None


def test_no_topic_omits_context() -> None:
    content = message_format.build_reply_content(
        sender="a", recipients=[], episode="ep", parents=[], topic=None, text="x"
    )
    assert "context" not in content["envelope"]["header"]
    assert message_format.topic_of(content) is None


# ── build_envelope_content — the generic builder behind `message send` ───────────


def test_build_envelope_content_sets_kind_and_subkind() -> None:
    content = message_format.build_envelope_content(
        kind="commit",
        subkind="resolved",
        sender="avery",
        recipients=["bob"],
        episode="ep-1",
        parents=["p-1"],
        payload_data={"assignments": {"cap": "30"}},
    )
    assert content["envelope"]["header"]["kind"] == "commit"
    assert content["envelope"]["header"]["subkind"] == "resolved"
    assert content["envelope"]["header"]["message"]["parents"] == ["p-1"]
    assert content["envelope"]["payload"]["data"] == {"assignments": {"cap": "30"}}


def test_build_envelope_content_omits_subkind_when_absent() -> None:
    content = message_format.build_envelope_content(kind="exchange", sender="avery", episode="ep-1")
    assert "subkind" not in content["envelope"]["header"]


def test_build_envelope_content_rejects_invalid_subkind() -> None:
    with pytest.raises(message_format.MessageValidationError):
        message_format.build_envelope_content(
            kind="exchange", subkind="not-a-real-subkind", sender="avery", episode="ep-1"
        )


def test_build_reply_content_matches_generic_builder_for_exchange() -> None:
    """build_reply_content is exactly the exchange-kind specialization."""
    via_generic = message_format.build_envelope_content(
        kind=message_format.EXCHANGE_KIND,
        sender="a",
        recipients=["b"],
        episode="ep",
        parents=["p"],
        topic="t",
        text="hi",
        message_id="m-1",
        payload_type="reply",
    )
    via_reply = message_format.build_reply_content(
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
    for kind in message_format.VALID_KINDS:
        message_format.validate_kind(kind)  # must not raise


def test_validate_kind_rejects_unknown_kind() -> None:
    with pytest.raises(message_format.MessageValidationError):
        message_format.validate_kind("not-a-kind")


def test_validate_subkind_none_always_valid() -> None:
    for kind in message_format.VALID_KINDS:
        message_format.validate_subkind(kind, None)  # must not raise


def test_validate_subkind_accepts_allowed_pairs() -> None:
    for kind, subkinds in message_format.VALID_SUBKINDS.items():
        for subkind in subkinds:
            message_format.validate_subkind(kind, subkind)  # must not raise


def test_validate_subkind_rejects_mismatched_pair() -> None:
    with pytest.raises(message_format.MessageValidationError):
        message_format.validate_subkind("exchange", "converged")  # "converged" belongs to commit
