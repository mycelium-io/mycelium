# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Anonymous product analytics event emitter (#937/#938).

Purpose
-------
Measure two adoption signals that tell us whether Mycelium's coordination
value actually lands:

  - ``time-to-first-session`` — from install to a completed coordinated session
  - ``repeat-session-rate``   — do teams come back for a second session

Both signals are derived from three events emitted here.  Events fire only
when ``TELEMETRY_SEND_PRODUCT_ANALYTICS=true`` (set by the user after seeing
the install-path disclosure) **and** ``TELEMETRY_ANALYTICS_DESTINATION`` names
a live endpoint.  Absent either, ``emit()`` is a documented no-op.

Privacy contract (#937)
-----------------------
* Every event is identified by a random ``install_id`` (UUID4, generated at
  first interactive install, stored in config.toml, never rotated).
* **Prohibited fields** — never included in any event:
    - names, usernames, handles, email addresses
    - room names, task bodies, prompt text, reply text
    - IP addresses, hostnames, machine identifiers
    - any content from a coordinated session
* ``adapter_class`` is the *kind* string ("claude_code", "cursor", etc.) —
  never the agent's name or handle.
* ``outcome`` is an aggregate status word ("converged", "resolved",
  "rejected") — never session content.

Event schema
------------
All events share a common envelope:

    {
      "event":        <event_name>,
      "install_id":   "<uuid4>",
      "release":      "<semver>",
      "ts":           "<iso8601 UTC>",
      ... event-specific fields ...
    }

``mycelium.install``
    Fired once at the end of the first successful interactive install.
    Fields: release, platform (os.uname sysname, no hostname).

``mycelium.session``
    Fired when a coordinated session (aligner episode with a terminal outcome
    of ``converged`` or ``rejected``) completes.
    Fields: release, adapter_class, outcome, session_count.
    ``session_count`` is the cumulative number of sessions on this
    installation — 1 means first session, 2+ means repeat. This lets callers
    compute time-to-first (count=1), repeat rate (count>1), and retention
    curves without separate event types per retention bucket.

Destination (go/no-go: #937)
-----------------------------
The ``TELEMETRY_ANALYTICS_DESTINATION`` env var holds the destination URL.
Until #937 is resolved this is an empty string and ``emit()`` silently skips
all events.  A non-empty destination must be an HTTPS URL; plain HTTP is
rejected so credentials-in-URL attacks can't redirect telemetry to a plain
HTTP listener.
"""

from __future__ import annotations

import json
import logging
import threading as _threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

_log = logging.getLogger(__name__)

# ── Session counter ───────────────────────────────────────────────────────────
# Tracks how many coordinated sessions (aligner runs with a terminal outcome)
# have completed in this backend process. Used to distinguish the first session
# event from repeat ones. Persisted across backend restarts via a flat file in
# MYCELIUM_DATA_DIR so the first/repeat distinction survives a container recreate.
# Protected by a threading.Lock because _run_and_release runs in an asyncio
# worker thread, not the event loop.

_session_lock = _threading.Lock()


def _session_count_path():
    """Return the path to the session count file, or None if DATA_DIR is unset."""
    import os
    from pathlib import Path

    data_dir = os.environ.get("MYCELIUM_DATA_DIR", "")
    if not data_dir:
        return None
    return Path(data_dir) / ".analytics_sessions"


def increment_session_count() -> int:
    """Atomically increment and return the new session count.

    Returns the count *after* this session, so 1 means this was the first
    session (``first=True``), 2+ means repeat (``first=False``).
    Writes through to a flat file in MYCELIUM_DATA_DIR for persistence across
    restarts. Falls back to an in-memory counter if the file is unavailable.
    """
    with _session_lock:
        path = _session_count_path()
        count = 0
        if path is not None:
            try:
                if path.exists():
                    count = int(path.read_text().strip() or "0")
            except Exception:
                pass
        count += 1
        if path is not None:
            try:
                path.write_text(str(count))
            except Exception:
                pass
        return count


EventName = Literal[
    "mycelium.install",
    "mycelium.session",
]

# Fields that are NEVER allowed in any analytics event.
# This set is asserted in tests so a future field addition can't silently slip through.
PROHIBITED_FIELDS: frozenset[str] = frozenset(
    {
        "name",
        "handle",
        "email",
        "username",
        "room",
        "room_name",
        "task",
        "task_body",
        "prompt",
        "reply",
        "content",
        "ip",
        "ip_address",
        "hostname",
        "machine_id",
    }
)


@dataclass
class AnalyticsEvent:
    """A single anonymous adoption-metric event.

    Construct with one of the factory helpers below; never pass prohibited
    fields to the ``extra`` dict.
    """

    event: EventName
    install_id: str
    release: str
    extra: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        payload = {
            "event": self.event,
            "install_id": self.install_id,
            "release": self.release,
            "ts": datetime.now(UTC).isoformat(),
            **self.extra,
        }
        # Safety: strip any prohibited field that slipped in via ``extra``.
        stripped = {k: v for k, v in payload.items() if k not in PROHIBITED_FIELDS}
        if len(stripped) != len(payload):
            _log.warning(
                "analytics: stripped prohibited field(s) %s from event %s",
                set(payload) - set(stripped),
                self.event,
            )
        return stripped


# ── Event factories ───────────────────────────────────────────────────────────


def install_event(*, install_id: str, release: str, platform: str) -> AnalyticsEvent:
    """``mycelium.install`` — fired once at the end of the first interactive install."""
    return AnalyticsEvent(
        event="mycelium.install",
        install_id=install_id,
        release=release,
        extra={"platform": platform},
    )


def session_event(
    *,
    install_id: str,
    release: str,
    adapter_class: str,
    outcome: str,
    session_count: int,
) -> AnalyticsEvent:
    """``mycelium.session`` — fired when an aligner run reaches a terminal outcome.

    ``session_count`` is the cumulative number of coordinated sessions on this
    installation (1 = first, 2+ = repeat). Keeping it as a field rather than
    splitting into ``session.first`` / ``session.repeat`` event types lets
    callers compute time-to-first (count=1), repeat rate (count>1), and any
    deeper retention curve from the same event stream without a separate event
    name per retention bucket.
    """
    return AnalyticsEvent(
        event="mycelium.session",
        install_id=install_id,
        release=release,
        extra={
            "adapter_class": adapter_class,
            "outcome": outcome,
            "session_count": str(session_count),
        },
    )


# ── Emitter ───────────────────────────────────────────────────────────────────


def emit(event: AnalyticsEvent) -> None:
    """Fire an analytics event if opt-in is active and a destination is configured.

    Silently no-ops when:
    - ``TELEMETRY_SEND_PRODUCT_ANALYTICS`` is false (the default)
    - ``TELEMETRY_ANALYTICS_DESTINATION`` is empty (pending #937 go/no-go)
    - The destination is not HTTPS (plain HTTP rejected as a safeguard)

    Never raises — analytics failures are logged at DEBUG and swallowed so they
    never disrupt coordination or the install flow.
    """
    try:
        _emit_inner(event)
    except Exception as exc:
        _log.debug("analytics emit failed (non-fatal): %s", exc)


def _emit_inner(event: AnalyticsEvent) -> None:
    """Internal emitter; callers must use :func:`emit` for safe wrapping."""
    from app.config import settings

    if not settings.TELEMETRY_SEND_PRODUCT_ANALYTICS:
        return

    destination = settings.TELEMETRY_ANALYTICS_DESTINATION.strip()
    if not destination:
        # #937 destination not yet decided — silent no-op.
        _log.debug("analytics: destination not configured (pending #937); skipping %s", event.event)
        return

    if not destination.startswith("https://"):
        # Security note: plain HTTP is refused for remote destinations because
        # an event POST over plain HTTP could expose the install_id (a UUID,
        # not a secret, but still a persistent identifier) to a network observer
        # or be silently redirected to a different host.
        #
        # Local-address exception (Option A, documented): localhost,
        # 127.0.0.1, and host.docker.internal are only reachable from the
        # current machine, so the interception risk does not apply.  This lets
        # developers point the destination at a local Loki/Grafana instance
        # (e.g. http://host.docker.internal:3100/loki/api/v1/push) without
        # needing a TLS terminator.  Production deployments MUST use HTTPS.
        _LOCAL_HOSTS = ("localhost", "127.0.0.1", "host.docker.internal")
        is_local = any(h in destination for h in _LOCAL_HOSTS)
        if not (destination.startswith("http://") and is_local):
            _log.warning(
                "analytics: destination %r is not HTTPS (and not a local address); "
                "refusing to send event %s",
                destination,
                event.event,
            )
            return

    payload = event.to_dict()
    _post(destination, payload)


def _post(url: str, payload: dict) -> None:
    """HTTP POST the event payload as JSON.  Uses the stdlib so no extra deps.

    When the URL path contains ``/loki/`` (e.g. a local Grafana LGTM Loki push
    endpoint), the payload is wrapped in the Loki push stream format so events
    appear in Grafana Explore as structured log entries labelled by
    ``{service="mycelium-analytics", event="<event_name>"}``.

    All other destinations receive a plain ``application/json`` POST.
    """
    import time
    import urllib.request

    if "/loki/" in url:
        # Loki push format: stream labels + a single log line (the JSON payload).
        loki_body = {
            "streams": [
                {
                    "stream": {
                        "service": "mycelium-analytics",
                        "event": payload.get("event", "unknown"),
                    },
                    "values": [
                        [
                            str(int(time.time() * 1e9)),  # nanosecond Unix timestamp
                            json.dumps(payload),
                        ]
                    ],
                }
            ]
        }
        data = json.dumps(loki_body).encode()
    else:
        data = json.dumps(payload).encode()

    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        status = resp.status
    _log.debug("analytics: %s → %s (%d)", payload["event"], url, status)


# ── CLI-side helpers (called from install.py) ─────────────────────────────────


def ensure_install_id(config) -> str:
    """Return the install_id for this machine, generating + persisting one if absent.

    ``config`` is a :class:`~mycelium.config.MyceliumConfig` instance.
    Writes back to config if a new ID is generated.
    """
    if config.telemetry.install_id:
        return config.telemetry.install_id

    import uuid

    new_id = str(uuid.uuid4())
    config.telemetry.install_id = new_id
    config.save()
    return new_id


def _platform_token() -> str:
    """A coarse, non-identifying OS kind (e.g. 'Darwin', 'Linux')."""
    import platform

    return platform.system() or "unknown"


def _release_token() -> str:
    """Best-effort release version from the CLI package metadata."""
    try:
        from importlib.metadata import version

        return version("mycelium")
    except Exception:
        return "unknown"
