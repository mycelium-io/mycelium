# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Cross-channel "home address" tracking for consensus delivery.

When an agent first appears in a Mycelium negotiation session (either via
``coordination_join`` or the first ``coordination_tick`` they receive),
we record where the agent was active on a non-mycelium Hermes platform
(Matrix, Telegram, Slack, …) keyed by ``(session_room, agent_id)``.
When the negotiation concludes, :func:`route.NotifyHome` looks up that
stash and sends the consensus summary back through the other platform's
adapter via the live gateway runner.

Mirrors the openclaw ``return-address.ts``/``notify-home.ts`` pair. The
in-memory stash is intentionally ephemeral — a gateway restart between
join and consensus drops the proactive notification (same as openclaw).

Home discovery (no hermes core changes):

1. ``pre_gateway_dispatch`` hook writes the latest non-mycelium
   ``SessionSource`` to ``$HERMES_HOME/.mycelium-return-origin.json``.
2. At stash time we prefer that file, then fall back to scanning
   ``$HERMES_HOME/sessions/sessions.json`` for the most recently updated
   session whose platform is not ``mycelium-room`` (openclaw parity).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

MYCELIUM_PLATFORM = "mycelium-room"
_LAST_ORIGIN_FILENAME = ".mycelium-return-origin.json"
# Ignore a stale sidecar if the user hasn't spoken on a home platform lately.
_LAST_ORIGIN_MAX_AGE_S = 3600
# Only rewrite the sidecar if the home channel changed or this interval elapsed.
_SIDECAR_REFRESH_S = 300

_logger = logging.getLogger(__name__)
_last_sidecar_key: tuple[str, str] = ("", "")
_last_sidecar_write_ts: float = 0.0


@dataclass(frozen=True)
class HomeAddress:
    """A platform-agnostic pointer to where consensus should be posted."""

    platform: str  # e.g. "telegram", "matrix", "discord"
    chat_id: str
    thread_id: str | None = None
    raw_source: Any = None  # original SessionSource for diagnostics


class ReturnAddressBook:
    """Thread-safe stash: ``(session_room, agent_id) → HomeAddress``."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._addresses: dict[tuple[str, str], HomeAddress] = {}

    def stash(self, *, session_room: str, agent_id: str, address: HomeAddress) -> None:
        with self._lock:
            self._addresses[(session_room, agent_id)] = address

    def lookup(self, *, session_room: str, agent_id: str) -> HomeAddress | None:
        with self._lock:
            return self._addresses.get((session_room, agent_id))

    def has(self, *, session_room: str, agent_id: str) -> bool:
        with self._lock:
            return (session_room, agent_id) in self._addresses

    def drop_session(self, session_room: str) -> None:
        with self._lock:
            stale = [k for k in self._addresses if k[0] == session_room]
            for k in stale:
                self._addresses.pop(k, None)

    def __len__(self) -> int:
        with self._lock:
            return len(self._addresses)


def _hermes_home() -> Path:
    env_home = os.environ.get("HERMES_HOME")
    if env_home:
        return Path(env_home)
    return Path.home() / ".hermes"


def _sessions_json_path() -> Path:
    return _hermes_home() / "sessions" / "sessions.json"


def _last_origin_path() -> Path:
    return _hermes_home() / _LAST_ORIGIN_FILENAME


def _platform_name(raw: Any) -> str | None:
    if raw is None:
        return None
    value = getattr(raw, "value", raw)
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _is_mycelium_platform(platform: str | None, session_key: str | None = None) -> bool:
    if platform == MYCELIUM_PLATFORM:
        return True
    return bool(session_key and f":{MYCELIUM_PLATFORM}:" in session_key)


def _home_from_origin_dict(origin: dict[str, Any]) -> HomeAddress | None:
    platform_raw = origin.get("platform")
    chat_id_raw = origin.get("chat_id")
    if not isinstance(platform_raw, str) or not platform_raw.strip():
        return None
    if not isinstance(chat_id_raw, str) or not chat_id_raw.strip():
        return None
    platform = platform_raw.strip()
    chat_id = chat_id_raw.strip()
    if _is_mycelium_platform(platform):
        return None
    thread_id = origin.get("thread_id")
    return HomeAddress(
        platform=platform,
        chat_id=chat_id,
        thread_id=str(thread_id).strip()
        if isinstance(thread_id, str) and thread_id.strip()
        else None,
        raw_source=origin,
    )


def _parse_ts(raw: str) -> float:
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp()


def _parse_updated_at(entry: dict[str, Any]) -> float:
    raw = entry.get("updated_at")
    return _parse_ts(raw) if isinstance(raw, str) else 0.0


def read_home_address_from_sessions(log: logging.Logger | None = None) -> HomeAddress | None:
    """Scan Hermes ``sessions.json`` for the newest non-mycelium-room session."""
    path = _sessions_json_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        if log:
            log.info("return-address: no session store at %s", path)
        return None
    try:
        store = json.loads(raw)
    except json.JSONDecodeError as exc:
        if log:
            log.warning("return-address: sessions.json parse error: %s", exc)
        return None
    if not isinstance(store, dict):
        return None

    best: tuple[float, HomeAddress] | None = None
    for session_key, entry in store.items():
        if not isinstance(entry, dict):
            continue
        key = entry.get("session_key")
        if not isinstance(key, str):
            key = str(session_key) if isinstance(session_key, str) else ""
        platform = entry.get("platform")
        platform_str = platform if isinstance(platform, str) else None
        if _is_mycelium_platform(platform_str, key):
            continue
        origin = entry.get("origin")
        addr: HomeAddress | None = None
        if isinstance(origin, dict):
            addr = _home_from_origin_dict(origin)
        if addr is None:
            continue
        ts = _parse_updated_at(entry)
        if best is None or ts > best[0]:
            best = (ts, addr)
    return best[1] if best else None


def read_last_origin_sidecar(log: logging.Logger | None = None) -> HomeAddress | None:
    """Read the hook-written sidecar, if still fresh."""
    path = _last_origin_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        if log:
            log.warning("return-address: sidecar parse error: %s", exc)
        return None
    if not isinstance(data, dict):
        return None
    recorded_at = data.get("recorded_at")
    if isinstance(recorded_at, str):
        age = datetime.now(tz=UTC).timestamp() - _parse_ts(recorded_at)
        if age > _LAST_ORIGIN_MAX_AGE_S:
            return None
    origin = data.get("origin")
    if isinstance(origin, dict):
        return _home_from_origin_dict(origin)
    platform = data.get("platform")
    chat_id = data.get("chat_id")
    if isinstance(platform, str) and isinstance(chat_id, str):
        return _home_from_origin_dict(
            {
                "platform": platform,
                "chat_id": chat_id,
                "thread_id": data.get("thread_id"),
            }
        )
    return None


def read_home_address(log: logging.Logger | None = None) -> HomeAddress | None:
    """Resolve the agent's home channel for consensus postback."""
    sidecar = read_last_origin_sidecar(log)
    if sidecar is not None:
        return sidecar
    return read_home_address_from_sessions(log)


def record_last_origin(source: Any, log: logging.Logger | None = None) -> None:
    """Persist the latest non-mycelium inbound ``SessionSource`` (hook path)."""
    global _last_sidecar_key, _last_sidecar_write_ts
    platform = _platform_name(getattr(source, "platform", None))
    chat_id_raw = getattr(source, "chat_id", None)
    if not platform or _is_mycelium_platform(platform):
        return
    if not isinstance(chat_id_raw, str) or not chat_id_raw.strip():
        return
    chat_id = chat_id_raw.strip()
    now = datetime.now(tz=UTC)
    now_ts = now.timestamp()
    key = (platform, chat_id)
    if key == _last_sidecar_key and now_ts - _last_sidecar_write_ts < _SIDECAR_REFRESH_S:
        return
    thread_id = getattr(source, "thread_id", None)
    thread_id_str = (
        str(thread_id).strip() if isinstance(thread_id, str) and thread_id.strip() else None
    )
    payload: dict[str, Any] = {
        "platform": platform,
        "chat_id": chat_id,
        "thread_id": thread_id_str,
        "recorded_at": now.isoformat(),
    }
    if hasattr(source, "to_dict"):
        try:
            origin = source.to_dict()
            if isinstance(origin, dict):
                payload["origin"] = origin
        except Exception:  # noqa: BLE001
            pass
    else:
        payload["origin"] = {
            "platform": platform,
            "chat_id": chat_id,
            "thread_id": thread_id_str,
            "chat_type": getattr(source, "chat_type", "dm"),
            "user_id": getattr(source, "user_id", None),
            "user_name": getattr(source, "user_name", None),
        }
    path = _last_origin_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError as exc:
        if log:
            log.warning("return-address: failed to write sidecar %s: %s", path, exc)
        return
    _last_sidecar_key = key
    _last_sidecar_write_ts = now_ts


def on_pre_gateway_dispatch(event: Any, **_kwargs: Any) -> None:  # noqa: ANN401
    """Hermes hook: capture home platform on every non-mycelium inbound message."""
    if getattr(event, "internal", False):
        return
    source = getattr(event, "source", None)
    if source is None:
        return
    record_last_origin(source, log=_logger)


def stash_return_address(
    book: ReturnAddressBook,
    *,
    session_room: str,
    agent_id: str,
    log: logging.Logger,
) -> None:
    """Freeze the agent's home channel at join/first-tick time (idempotent)."""
    if book.has(session_room=session_room, agent_id=agent_id):
        return
    addr = read_home_address(log)
    if addr is None:
        log.info(
            "return-address: no home channel for %s in %s — will skip notify-home",
            agent_id,
            session_room,
        )
        return
    book.stash(session_room=session_room, agent_id=agent_id, address=addr)
    log.info(
        "return-address stashed: %s → %s:%s",
        agent_id,
        addr.platform,
        addr.chat_id,
    )
