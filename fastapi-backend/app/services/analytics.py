# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Usage events: what a hub is used for, counted, as product KPIs.

The unit of work is a task, so the events follow it: a task filed and
resolved, a flow run inside one, a negotiation inside one, an agent joining a
room, and the hub itself starting. Every way the app starts work (a plain
task, Review, Split, Settle, Catch up) lands as one of these, so the KPIs
cover what people actually do rather than one engine.

Two halves, deliberately separate:

* **Recorded on the hub, always.** Each event is appended to
  ``$MYCELIUM_DATA_DIR/usage/events.jsonl``, beside the hub's other state,
  and :func:`kpis` reads that file for ``GET /api/observability/usage`` and the app's
  Metrics page. It is counts and outcome words, never content, and it does
  not leave the machine.
* **Forwarded only with consent.** With ``TELEMETRY_SEND_PRODUCT_ANALYTICS``
  on and ``TELEMETRY_ANALYTICS_DESTINATION`` set, each event is also POSTed
  there. That is how a hub's usage reaches the people who build Mycelium.

Privacy contract
----------------
* An event names no person, agent, room or task. ``PROHIBITED_FIELDS`` is
  stripped from every payload, and a test asserts the set.
* Kinds, not names: ``adapter`` is ``claude_code``, never a handle; ``flow``
  is a built-in flow's name or ``custom``, since a room can name its own.
* Every event carries the hub's ``hub_id``: ``TELEMETRY_INSTALL_ID`` when the
  CLI's install set one, else a random UUID the hub mints once and keeps in
  its data directory. It identifies an installation, not a person.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import threading
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any, Literal
from urllib.parse import urlparse

_log = logging.getLogger(__name__)

EventName = Literal[
    "mycelium.hub_started",
    "mycelium.task_filed",
    "mycelium.task_resolved",
    "mycelium.flow_completed",
    "mycelium.negotiation_completed",
    "mycelium.agent_joined",
]

# Events that finish a piece of work. Their running count, carried on each as
# ``work_count``, is what first value (count 1) and repeat use (2+) read.
WORK_EVENTS: frozenset[str] = frozenset(
    {"mycelium.task_resolved", "mycelium.flow_completed", "mycelium.negotiation_completed"}
)

# Fields that never appear in an event. Asserted in tests, so a new field
# can't slip through unnoticed.
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
        "title",
        "key",
        "prompt",
        "reply",
        "content",
        "ip",
        "ip_address",
        "hostname",
        "machine_id",
    }
)

# Plain HTTP is only allowed to this machine, where nobody can listen in.
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "host.docker.internal"})

# The log is rotated once at this size, keeping one previous file.
_MAX_LOG_BYTES = 5 * 1024 * 1024

_lock = threading.Lock()


def _usage_dir() -> Path:
    from app.config import settings

    return Path(settings.MYCELIUM_DATA_DIR) / "usage"


def _log_path() -> Path:
    return _usage_dir() / "events.jsonl"


def hub_id() -> str:
    """This installation's id: the CLI's install id, else one the hub keeps."""
    from app.config import settings

    if settings.TELEMETRY_INSTALL_ID:
        return settings.TELEMETRY_INSTALL_ID
    path = _usage_dir() / "hub_id"
    try:
        existing = path.read_text().strip()
        if existing:
            return existing
    except OSError:
        pass
    minted = str(uuid.uuid4())
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(minted)
    except OSError:
        _log.debug("usage: could not persist hub_id", exc_info=True)
    return minted


def _release() -> str:
    from app.services.version import read_release

    return read_release()


def scrub(payload: dict[str, Any]) -> dict[str, Any]:
    """The payload with every prohibited field removed, warning if any were there."""
    clean = {k: v for k, v in payload.items() if k not in PROHIBITED_FIELDS}
    if len(clean) != len(payload):
        _log.warning("usage: stripped prohibited field(s) %s", sorted(set(payload) - set(clean)))
    return clean


def _work_count() -> int:
    """How many work events the log holds, before this one."""
    count = 0
    for event in _read_events():
        if event.get("event") in WORK_EVENTS:
            count += 1
    return count


def record(event: EventName, **fields: Any) -> dict[str, Any] | None:
    """Record one usage event on the hub, and forward it if the hub shares usage.

    Never raises: usage must never get in the way of the work it counts.
    Returns the payload written, for tests.
    """
    try:
        with _lock:
            payload: dict[str, Any] = {
                "event": event,
                "hub_id": hub_id(),
                "release": _release(),
                "ts": datetime.now(UTC).isoformat(),
                **fields,
            }
            if event in WORK_EVENTS:
                payload["work_count"] = _work_count() + 1
            payload = scrub(payload)
            _append(payload)
        _forward_in_background(payload)
        return payload
    except Exception:
        _log.debug("usage: record failed (non-fatal)", exc_info=True)
        return None


def _append(payload: dict[str, Any]) -> None:
    path = _log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if path.stat().st_size > _MAX_LOG_BYTES:
            path.replace(path.with_suffix(".1.jsonl"))
    except FileNotFoundError:
        pass
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, separators=(",", ":")) + "\n")


def _read_events() -> list[dict[str, Any]]:
    """Every event the hub has recorded, oldest first, across the rotated file."""
    events: list[dict[str, Any]] = []
    current = _log_path()
    for path in (current.with_suffix(".1.jsonl"), current):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
    return events


# ── Forwarding ────────────────────────────────────────────────────────────────


def destination() -> str | None:
    """Where events go, or None when this hub doesn't share usage."""
    from app.config import settings

    if not settings.TELEMETRY_SEND_PRODUCT_ANALYTICS:
        return None
    url = settings.TELEMETRY_ANALYTICS_DESTINATION.strip()
    if not url:
        return None
    if url.startswith("https://"):
        return url
    # Checked on the parsed host, so http://evil.example/localhost doesn't pass.
    host = urlparse(url).hostname or ""
    if url.startswith("http://") and host in _LOCAL_HOSTS:
        return url
    _log.warning("usage: destination %r is not HTTPS or local; not sending", url)
    return None


def _forward_in_background(payload: dict[str, Any]) -> None:
    url = destination()
    if url is None:
        return
    threading.Thread(target=_post_quietly, args=(url, payload), daemon=True).start()


def _post_quietly(url: str, payload: dict[str, Any]) -> None:
    try:
        _post(url, payload)
    except Exception as exc:
        _log.debug("usage: forward failed (non-fatal): %s", exc)


def _post(url: str, payload: dict[str, Any]) -> None:
    """POST one event as JSON; a Loki push URL gets Loki's stream format."""
    import time
    import urllib.request

    if "/loki/" in url:
        body = {
            "streams": [
                {
                    "stream": {
                        "service": "mycelium-usage",
                        "event": payload.get("event", "unknown"),
                    },
                    "values": [[str(int(time.time() * 1e9)), json.dumps(payload)]],
                }
            ]
        }
    else:
        body = payload
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        _log.debug("usage: %s -> %s (%d)", payload.get("event"), url, response.status)


# ── What happens on the hub, as events ───────────────────────────────────────


def hub_mode() -> str:
    """How this hub runs: the desktop app, a container, or a server someone started."""
    return os.environ.get("MYCELIUM_HUB_MODE", "").strip() or "server"


def hub_started() -> None:
    record("mycelium.hub_started", mode=hub_mode(), platform=platform.system() or "unknown")


def _actor_kind(room: str, handle: str | None) -> str:
    """Who did it, as a kind: an engine, an agent, or a person."""
    if not handle:
        return "person"
    from app.services.filesystem import get_room_dir, read_memory_file

    found = read_memory_file(get_room_dir(room), f"agents/{handle.lstrip('@')}")
    if not found:
        return "person"
    text = found[1] or ""
    return "engine" if "adapter: engine" in text else "agent"


def _hours_since_created(room: str, key: str) -> float | None:
    from app.services.filesystem import get_room_dir, read_memory_file

    found = read_memory_file(get_room_dir(room), key)
    if not found:
        return None
    raw = found[0].get("created_at")
    if not raw:
        return None
    created = raw if isinstance(raw, datetime) else datetime.fromisoformat(str(raw))
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return round((datetime.now(UTC) - created).total_seconds() / 3600, 2)


def on_notice(room: str, notice: dict[str, str]) -> None:
    """The board moving, as usage: a task filed, and a task resolved."""
    subkind = notice.get("subkind")
    key = notice.get("key") or ""
    namespace = key.split("/", 1)[0]
    kind = notice.get("kind") or namespace or "task"
    if subkind == "filed":
        record(
            "mycelium.task_filed",
            kind=kind,
            by=_actor_kind(room, notice.get("by")),
            assigned=bool(notice.get("for")),
        )
    elif subkind == "resolved":
        record(
            "mycelium.task_resolved",
            kind=kind,
            by=_actor_kind(room, notice.get("by")),
            hours_open=_hours_since_created(room, key),
        )


def flow_completed(flow: str, outcome: str, steps: int) -> None:
    from app.services.protocols import builtin_names

    record(
        "mycelium.flow_completed",
        flow=flow if flow in builtin_names() else "custom",
        outcome=outcome,
        steps=steps,
    )


def negotiation_completed(outcome: str, rounds: int) -> None:
    record("mycelium.negotiation_completed", outcome=outcome, rounds=rounds)


def agent_joined(adapter: str | None) -> None:
    record("mycelium.agent_joined", adapter=(adapter or "unknown").strip() or "unknown")


# ── KPIs ──────────────────────────────────────────────────────────────────────


def kpis(days: int = 30, *, now: datetime | None = None) -> dict[str, Any]:
    """What this hub's usage adds up to, over the last ``days`` and overall."""
    now = now or datetime.now(UTC)
    since = now - timedelta(days=days)
    events = _read_events()

    def when(event: dict[str, Any]) -> datetime | None:
        try:
            return datetime.fromisoformat(event["ts"])
        except (KeyError, ValueError):
            return None

    recent = [e for e in events if (t := when(e)) is not None and t >= since]
    by_name: dict[str, list[dict[str, Any]]] = {}
    for event in recent:
        by_name.setdefault(event.get("event", ""), []).append(event)

    filed = by_name.get("mycelium.task_filed", [])
    resolved = by_name.get("mycelium.task_resolved", [])
    flows = by_name.get("mycelium.flow_completed", [])
    negotiations = by_name.get("mycelium.negotiation_completed", [])
    joined = by_name.get("mycelium.agent_joined", [])
    hours = [h for e in resolved if isinstance(h := e.get("hours_open"), int | float)]
    # How long tasks stay open, by who closed them: a person's task and an
    # agent's task are different clocks.
    hours_by: dict[str, list[float]] = {}
    for e in resolved:
        if isinstance(h := e.get("hours_open"), int | float):
            hours_by.setdefault(e.get("by", "person"), []).append(h)

    flow_counts: dict[str, dict[str, int]] = {}
    for e in flows:
        row = flow_counts.setdefault(e.get("flow", "custom"), {})
        row[e.get("outcome", "unknown")] = row.get(e.get("outcome", "unknown"), 0) + 1

    active_days = sorted({t.date().isoformat() for e in recent if (t := when(e)) is not None})
    daily: list[dict[str, Any]] = []
    for offset in range(days - 1, -1, -1):
        day = (now - timedelta(days=offset)).date().isoformat()
        daily.append(
            {
                "day": day,
                "filed": sum(1 for e in filed if e.get("ts", "").startswith(day)),
                "resolved": sum(1 for e in resolved if e.get("ts", "").startswith(day)),
            }
        )

    first_seen = next((when(e) for e in events if when(e) is not None), None)
    first_work = next(
        (when(e) for e in events if e.get("event") in WORK_EVENTS and when(e) is not None), None
    )
    first_value_hours = (
        round((first_work - first_seen).total_seconds() / 3600, 2)
        if first_seen is not None and first_work is not None
        else None
    )

    return {
        "days": days,
        "sharing": destination() is not None,
        "tasks": {
            "filed": len(filed),
            "resolved": len(resolved),
            "filed_by": dict(Counter(e.get("by", "person") for e in filed)),
            "median_hours_open": round(median(hours), 2) if hours else None,
            "median_hours_open_by": {k: round(median(v), 2) for k, v in hours_by.items()},
        },
        "flows": flow_counts,
        "negotiations": dict(Counter(e.get("outcome", "unknown") for e in negotiations)),
        "agents_joined": dict(Counter(e.get("adapter", "unknown") for e in joined)),
        "active_days": len(active_days),
        "daily": daily,
        "work_total": sum(1 for e in events if e.get("event") in WORK_EVENTS),
        "first_value_hours": first_value_hours,
    }
