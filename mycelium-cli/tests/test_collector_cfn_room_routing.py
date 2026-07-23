# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Regression tests for the CFN forwarder's room -> mas_id resolution.

``openclaw.session.key`` is pinned to the channel's static home room
(``mycelium_room``) for every dispatch, regardless of which coordination
room a tick is actually about (see mycelium-cli's
``integrations/openclaw/.../channel/session-key.ts``). Left unfixed, every
e2e test room's knowledge extraction gets misattributed to mycelium_room's
one shared mas_id/graph instead of each test's own isolated one — this is
what concentrated the AgensGraph TM_Deleted write-conflict race onto a
single graph during the 2026-07-22 incident.

The fix: dispatch.ts prepends a ``[[mycelium-room:<room>]]`` marker to every
tick/consensus/broadcast dispatch, captured verbatim in span content when
InsightClaw's captureContent is enabled. These tests cover the collector-side
half: extracting that marker and preferring it over the session-key-derived
room, and correctly resolving a session sub-room's mas_id via its parent
room (coordination_sessions.mas_id is always copied from the parent at
spawn time — see fastapi-backend's routes/sessions.py — so /api/rooms/{room}
only understands the parent name, not the session-suffixed one).
"""

from __future__ import annotations

from mycelium.collector import (
    _CfnForwarder,
    _room_from_captured_content,
    _room_from_session_key,
)


# ── _room_from_captured_content ─────────────────────────────────────────────


class TestRoomFromCapturedContent:
    def test_extracts_marker_from_entity_input(self):
        attrs = {"openclaw.entity.input": "[[mycelium-room:e2e-test-4753254-cfn-neg:session:f9b72633]]\nYou are in a structured negotiation..."}
        assert _room_from_captured_content(attrs) == "e2e-test-4753254-cfn-neg:session:f9b72633"

    def test_extracts_marker_from_gen_ai_input_messages_when_entity_input_absent(self):
        attrs = {"gen_ai.input.messages": "[[mycelium-room:test-room]]\nhello"}
        assert _room_from_captured_content(attrs) == "test-room"

    def test_returns_empty_string_when_no_marker_present(self):
        # e.g. real human chat in mycelium_room, or a span with no dispatch
        # content at all.
        attrs = {"openclaw.entity.input": "just a normal chat message, no marker"}
        assert _room_from_captured_content(attrs) == ""

    def test_returns_empty_string_when_captured_content_missing(self):
        # captureContent disabled — none of the content attributes are set.
        attrs = {"openclaw.session.key": "agent:agent-alpha:mycelium-room:group:mycelium_room"}
        assert _room_from_captured_content(attrs) == ""

    def test_survives_truncated_content_since_marker_is_prepended(self):
        # dispatch.ts places the marker first specifically so it survives
        # InsightClaw's truncateCapturedContent (which slices from the end).
        long_tail = "x" * 10_000
        attrs = {"openclaw.entity.input": f"[[mycelium-room:test-room]]\n{long_tail}"}
        assert _room_from_captured_content(attrs) == "test-room"

    def test_empty_attrs_dict(self):
        assert _room_from_captured_content({}) == ""


# ── _room_from_session_key (existing behavior, unchanged) ──────────────────


class TestRoomFromSessionKeyUnaffected:
    def test_still_parses_the_static_home_room(self):
        # Confirms the fallback path this module relies on is untouched.
        key = "agent:agent-alpha:mycelium-room:group:mycelium_room"
        assert _room_from_session_key(key) == "mycelium_room"


# ── _resolve_room: session sub-room -> parent room stripping ───────────────


class TestResolveRoomStripsSessionSuffix:
    def _make_forwarder(self, monkeypatch):
        fwd = _CfnForwarder("http://backend", "http://cfn-svc")
        calls: list[str] = []

        def fake_fetch_room(room: str):
            calls.append(room)
            return ("ws-123", "mas-456")

        monkeypatch.setattr(fwd, "_fetch_room", fake_fetch_room)
        return fwd, calls

    def test_strips_session_suffix_before_backend_lookup(self, monkeypatch):
        fwd, calls = self._make_forwarder(monkeypatch)
        fwd._resolve_room("e2e-test-4753254-cfn-neg:session:f9b72633")
        assert calls == ["e2e-test-4753254-cfn-neg"]

    def test_top_level_room_passes_through_unchanged(self, monkeypatch):
        fwd, calls = self._make_forwarder(monkeypatch)
        fwd._resolve_room("mycelium_room")
        assert calls == ["mycelium_room"]

    def test_session_sub_room_and_parent_share_one_cache_entry(self, monkeypatch):
        # Every session under the same parent room should hit the backend
        # exactly once, not once per distinct session id.
        fwd, calls = self._make_forwarder(monkeypatch)
        fwd._resolve_room("e2e-test-4753254-cfn-neg:session:aaa111")
        fwd._resolve_room("e2e-test-4753254-cfn-neg:session:bbb222")
        fwd._resolve_room("e2e-test-4753254-cfn-neg")
        assert calls == ["e2e-test-4753254-cfn-neg"]

    def test_returns_the_resolved_ids(self, monkeypatch):
        fwd, _ = self._make_forwarder(monkeypatch)
        workspace_id, mas_id = fwd._resolve_room("some-room:session:xyz")
        assert (workspace_id, mas_id) == ("ws-123", "mas-456")
