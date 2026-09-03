# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for app/services/analytics.py (#937/#938).

Two invariants from the #938 acceptance criteria:

1. ``emit()`` never fires before opt-in — no HTTP call when
   ``TELEMETRY_SEND_PRODUCT_ANALYTICS`` is false or destination is empty.
2. ``PROHIBITED_FIELDS`` are enforced — no prohibited key ever reaches the
   wire payload, even if passed via ``extra``.

No network, no backend process, no SLIM node required.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.analytics import (
    PROHIBITED_FIELDS,
    AnalyticsEvent,
    EventName,
    emit,
    install_event,
    session_event,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _event(name: EventName = "mycelium.install") -> AnalyticsEvent:
    return AnalyticsEvent(event=name, install_id="test-id", release="0.1.0")


# ── Invariant 1: no emit before opt-in ────────────────────────────────────────

class TestNoEmitBeforeOptIn:
    """emit() must not make any HTTP call unless the user has opted in."""

    def test_no_http_when_analytics_disabled(self):
        """Consent off → _post is never called regardless of destination."""
        with patch("app.services.analytics._post") as mock_post, \
             patch("app.config.settings") as mock_settings:
            mock_settings.TELEMETRY_SEND_PRODUCT_ANALYTICS = False
            mock_settings.TELEMETRY_ANALYTICS_DESTINATION = "https://analytics.example.com"
            emit(_event())
        mock_post.assert_not_called()

    def test_no_http_when_destination_empty(self):
        """Consent on but no destination configured → _post is never called."""
        with patch("app.services.analytics._post") as mock_post, \
             patch("app.config.settings") as mock_settings:
            mock_settings.TELEMETRY_SEND_PRODUCT_ANALYTICS = True
            mock_settings.TELEMETRY_ANALYTICS_DESTINATION = ""
            emit(_event())
        mock_post.assert_not_called()

    def test_no_http_when_destination_whitespace_only(self):
        """Whitespace-only destination is treated as empty."""
        with patch("app.services.analytics._post") as mock_post, \
             patch("app.config.settings") as mock_settings:
            mock_settings.TELEMETRY_SEND_PRODUCT_ANALYTICS = True
            mock_settings.TELEMETRY_ANALYTICS_DESTINATION = "   "
            emit(_event())
        mock_post.assert_not_called()

    def test_no_http_when_destination_not_https(self):
        """Plain HTTP destination is refused even when consent is on."""
        with patch("app.services.analytics._post") as mock_post, \
             patch("app.config.settings") as mock_settings:
            mock_settings.TELEMETRY_SEND_PRODUCT_ANALYTICS = True
            mock_settings.TELEMETRY_ANALYTICS_DESTINATION = "http://analytics.example.com"
            emit(_event())
        mock_post.assert_not_called()

    def test_http_fires_when_opted_in_and_destination_set(self):
        """Consent on + HTTPS destination → _post IS called exactly once."""
        with patch("app.services.analytics._post") as mock_post, \
             patch("app.config.settings") as mock_settings:
            mock_settings.TELEMETRY_SEND_PRODUCT_ANALYTICS = True
            mock_settings.TELEMETRY_ANALYTICS_DESTINATION = "https://analytics.example.com"
            emit(_event())
        mock_post.assert_called_once()

    def test_emit_never_raises(self):
        """emit() swallows all exceptions — analytics must never disrupt the caller."""
        with patch("app.services.analytics._emit_inner", side_effect=RuntimeError("boom")):
            emit(_event())  # must not raise


# ── Invariant 2: prohibited fields never reach the wire ───────────────────────

class TestProhibitedFields:
    """No key from PROHIBITED_FIELDS may appear in to_dict() output."""

    def test_prohibited_fields_set_is_not_empty(self):
        """Sanity: the set itself has not been accidentally cleared."""
        assert len(PROHIBITED_FIELDS) >= 10

    @pytest.mark.parametrize("bad_key", sorted(PROHIBITED_FIELDS))
    def test_prohibited_key_stripped_from_extra(self, bad_key: str):
        """A prohibited key passed via extra is silently stripped."""
        ev = AnalyticsEvent(
            event="mycelium.install",
            install_id="x",
            release="0.0.1",
            extra={bad_key: "should-be-stripped"},
        )
        payload = ev.to_dict()
        assert bad_key not in payload, (
            f"Prohibited field {bad_key!r} must never appear in the event payload"
        )

    def test_clean_event_has_no_prohibited_keys(self):
        """A normally-constructed event contains no prohibited keys."""
        ev = install_event(install_id="abc", release="1.0.0", platform="Darwin")
        payload = ev.to_dict()
        leaks = set(payload) & PROHIBITED_FIELDS
        assert not leaks, f"Prohibited fields leaked into install event: {leaks}"

    def test_session_event_has_no_prohibited_keys(self):
        ev = session_event(
            install_id="abc",
            release="1.0.0",
            adapter_class="cursor",
            outcome="converged",
            first=True,
        )
        payload = ev.to_dict()
        leaks = set(payload) & PROHIBITED_FIELDS
        assert not leaks, f"Prohibited fields leaked into session event: {leaks}"

    def test_multiple_prohibited_keys_all_stripped(self):
        """All prohibited keys are stripped, not just the first one found."""
        ev = AnalyticsEvent(
            event="mycelium.install",
            install_id="x",
            release="0.0.1",
            extra={"handle": "alice", "room": "my-room", "hostname": "devbox"},
        )
        payload = ev.to_dict()
        assert "handle" not in payload
        assert "room" not in payload
        assert "hostname" not in payload


# ── Event shape sanity ────────────────────────────────────────────────────────

class TestEventShape:
    """The mandatory envelope fields are always present."""

    @pytest.mark.parametrize("factory,kwargs", [
        (install_event, {"install_id": "i", "release": "1.0", "platform": "Linux"}),
        (session_event, {"install_id": "i", "release": "1.0", "adapter_class": "cursor",
                         "outcome": "converged", "first": True}),
        (session_event, {"install_id": "i", "release": "1.0", "adapter_class": "cursor",
                         "outcome": "rejected", "first": False}),
    ])
    def test_mandatory_envelope_fields_present(self, factory, kwargs):
        payload = factory(**kwargs).to_dict()
        for required in ("event", "install_id", "release", "ts"):
            assert required in payload, f"Missing required envelope field: {required!r}"

    def test_install_event_name(self):
        assert install_event(install_id="x", release="1.0", platform="Darwin").event \
            == "mycelium.install"

    def test_first_session_event_name(self):
        assert session_event(install_id="x", release="1.0", adapter_class="c",
                             outcome="converged", first=True).event \
            == "mycelium.session.first"

    def test_repeat_session_event_name(self):
        assert session_event(install_id="x", release="1.0", adapter_class="c",
                             outcome="converged", first=False).event \
            == "mycelium.session.repeat"
