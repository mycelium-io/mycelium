# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for the L9-over-SLIM binding (app/services/l9_slim.py).

These are node-free: they exercise serialization, causal ordering, and the
episode lifecycle as pure logic. The live round-trip over a real SLIM group is
in ``test_l9_over_slim_roundtrip.py`` (guarded on a running node).
"""

import json

import pytest

from app.services import l9, l9_slim
from app.services.l9_models import Kind


def _ids(envelopes) -> list[str]:
    """Message ids of a released batch (asserts each envelope has a message)."""
    out = []
    for env in envelopes:
        assert env.header.message is not None
        out.append(env.header.message.id)
    return out


def _exchange(message_id: str, parents: list[str] | None = None):
    """A minimal exchange envelope with a fixed id (so ordering is testable)."""
    return l9.build_envelope(
        kind=Kind.exchange,
        episode="urn:ioc:mycelium:episode:r:s",
        parents=parents or [],
        topic="urn:concept:mycelium:r",
        message_id=message_id,
        payload_type="tick",
        payload_data={"round": 1},
    )


# ── serialize / deserialize ──────────────────────────────────────────────────


def test_serialize_deserialize_round_trip_preserves_envelope():
    env = l9.build_envelope(
        kind=Kind.commit,
        subkind="converged",
        episode="urn:ioc:mycelium:episode:r:s",
        parents=["p1", "p2"],
        recipients=["agent-a", "agent-b"],
        topic="urn:concept:mycelium:r",
        payload_type="consensus",
        payload_data={"assignments": {"budget": "high"}},
    )
    data = l9_slim.serialize_envelope(env)
    parsed, content = l9_slim.deserialize_envelope(data)

    assert l9_slim.CONTENT_L9_KEY in content
    assert parsed.header.kind is Kind.commit
    assert parsed.header.subkind == "converged"
    assert parsed.header.message is not None and env.header.message is not None
    assert parsed.header.message.id == env.header.message.id
    assert parsed.header.message.parents == ["p1", "p2"]
    assert parsed.header.message.episode == env.header.message.episode
    assert parsed.payload.data == {"assignments": {"budget": "high"}}


def test_serialize_carries_extra_content_alongside_l9():
    env = _exchange("m1")
    data = l9_slim.serialize_envelope(env, extra={"human": "let's ship it"})
    _parsed, content = l9_slim.deserialize_envelope(data)
    assert content["human"] == "let's ship it"
    assert content[l9_slim.CONTENT_L9_KEY]["header"]["kind"] == "exchange"


def test_deserialize_rejects_non_json():
    with pytest.raises(l9_slim.L9SlimError):
        l9_slim.deserialize_envelope(b"\xff\xfe not json")


def test_deserialize_rejects_missing_envelope():
    with pytest.raises(l9_slim.L9SlimError):
        l9_slim.deserialize_envelope(json.dumps({"human": "no l9 here"}).encode())


def test_deserialize_rejects_invalid_subkind():
    # A tampered wire message with a subkind outside the SLIM-native table.
    env = _exchange("m1")
    content = {l9_slim.CONTENT_L9_KEY: l9.envelope_to_dict(env)}
    content[l9_slim.CONTENT_L9_KEY]["header"]["kind"] = "commit"
    content[l9_slim.CONTENT_L9_KEY]["header"]["subkind"] = "abort"
    with pytest.raises(l9.L9ValidationError):
        l9_slim.deserialize_envelope(json.dumps(content).encode())


# ── causal ordering ──────────────────────────────────────────────────────────


def test_causal_buffer_in_order_passes_through():
    buf = l9_slim.CausalOrderBuffer()
    a = _exchange("A")
    b = _exchange("B", parents=["A"])
    assert _ids(buf.add(a)) == ["A"]
    assert _ids(buf.add(b)) == ["B"]
    assert buf.pending_count == 0


def test_causal_buffer_reorders_out_of_order_arrivals():
    """A(root) → B(parent A) → C(parent B), arriving reversed, deliver A,B,C."""
    buf = l9_slim.CausalOrderBuffer()
    a = _exchange("A")
    b = _exchange("B", parents=["A"])
    c = _exchange("C", parents=["B"])

    # C then B arrive first: both held (their parents haven't been delivered).
    assert buf.add(c) == []
    assert buf.add(b) == []
    assert buf.pending_count == 2

    # A arrives and unblocks the whole chain, released in causal order.
    released = _ids(buf.add(a))
    assert released == ["A", "B", "C"]
    assert buf.pending_count == 0


def test_causal_buffer_holds_message_with_missing_parent():
    buf = l9_slim.CausalOrderBuffer()
    orphan = _exchange("X", parents=["never-arrives"])
    assert buf.add(orphan) == []
    assert buf.pending_count == 1


def test_causal_buffer_ignores_duplicate_ids():
    buf = l9_slim.CausalOrderBuffer()
    a = _exchange("A")
    assert _ids(buf.add(a)) == ["A"]
    # Re-delivery of the same id yields nothing (already released).
    assert buf.add(a) == []
    assert buf.pending_count == 0


def test_causal_buffer_multi_parent_waits_for_all():
    buf = l9_slim.CausalOrderBuffer()
    a = _exchange("A")
    b = _exchange("B")
    merge = _exchange("M", parents=["A", "B"])

    buf.add(a)
    assert buf.add(merge) == []  # B not yet delivered
    released = _ids(buf.add(b))
    assert released == ["B", "M"]


# ── episode lifecycle ────────────────────────────────────────────────────────


def test_episode_membership_change_aborts_active_episode():
    lc = l9_slim.EpisodeLifecycle()
    lc.open("urn:ioc:mycelium:episode:r:s", {"agent-a", "agent-b"})
    assert lc.active is True

    # A third agent joins mid-episode → abort.
    aborted = lc.on_membership_change({"agent-a", "agent-b", "agent-c"})
    assert aborted is True
    assert lc.active is False


def test_episode_no_change_does_not_abort():
    lc = l9_slim.EpisodeLifecycle()
    lc.open("urn:ioc:mycelium:episode:r:s", {"agent-a", "agent-b"})
    assert lc.on_membership_change({"agent-a", "agent-b"}) is False
    assert lc.active is True


def test_membership_change_with_no_active_episode_adopts_baseline():
    lc = l9_slim.EpisodeLifecycle()
    # No episode open: churn is just adopted, never an abort.
    assert lc.on_membership_change({"agent-a"}) is False
    assert lc.active is False
    # Opening now freezes the current baseline; same set doesn't abort.
    lc.open("urn:ioc:mycelium:episode:r:s", {"agent-a"})
    assert lc.on_membership_change({"agent-a"}) is False


def test_episode_abort_envelope_is_rejected_commit():
    env = l9_slim.build_episode_abort_envelope(
        "urn:ioc:mycelium:episode:r:s",
        recipients=["agent-a", "agent-b"],
        topic="urn:concept:mycelium:r",
    )
    assert env.header.kind is Kind.commit
    assert env.header.subkind == "rejected"
    assert env.payload.data == {"aborted": True, "reason": "membership_change"}
    # Round-trips cleanly through the wire form.
    parsed, _ = l9_slim.deserialize_envelope(l9_slim.serialize_envelope(env))
    assert parsed.header.subkind == "rejected"
