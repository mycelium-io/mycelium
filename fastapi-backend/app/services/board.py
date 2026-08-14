# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Coordination board — a live projection over the room's event ledger (issue #493).

The board is not a store of its own. It projects three sources into one uniform
row list:

  * **the event ledger** — stateful ``action`` / ``concern`` events (#392), the
    board's canonical, agent-writable surface. Full verb support (claim / block /
    resolve / promote / dismiss) via in-place payload + status mutation.
  * **plan tasks** — the compiled ``plan/tasks.md`` checklist, projected read-mostly
    for continuity with rooms that predate the ledger. ``resolve`` maps to a task
    toggle; the richer verbs don't apply.
  * **the live episode** — a negotiation in flight, surfaced as one "needs you"
    review row pointing at the aligner. Read-only; it resolves when consensus lands.

Richer board state (claimed / in_review / blocked) and the display fields the raw
``EventStatus`` doesn't carry (owner, work-links, GitHub back-ref, decision choices)
live in the event ``payload``, so the shared #392 primitive is untouched — the board
is purely a consumer view over it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.bus import bus, room_channel
from app.schemas import MessageType
from app.services import l9, local_state
from app.services import plan as plan_service
from app.services.room_channels import BACKEND_AGENT
from app.services.room_channels import manager as channel_manager

# The ledger kinds the board projects. Other event kinds (e.g. stateless
# ``source_event`` feed items) are intentionally left off the board.
BOARD_LEDGER_KINDS = frozenset({"action", "concern"})

# Display states beyond the coarse EventStatus (open / in_progress / resolved).
# These live in payload["state"]; the projection falls back to event_status.
_STATUS_TO_STATE = {"open": "open", "in_progress": "in_progress", "resolved": "resolved"}


def _humanize_age(created: datetime, now: datetime) -> str:
    secs = max(0.0, (now - created).total_seconds())
    if secs < 60:
        return f"{int(secs)}s"
    if secs < 3600:
        return f"{int(secs // 60)}m"
    if secs < 86400:
        return f"{int(secs // 3600)}h"
    return f"{int(secs // 86400)}d"


def _needs_you(kind: str, state: str, explicit: bool | None) -> bool:
    """Whether a row demands human attention (drives the default "Needs you" lens).

    An explicit ``payload.needs_you`` wins; otherwise decisions, blocks, reviews,
    and freshly-opened concerns steer the human, while in-flight actions don't.
    """
    if explicit is not None:
        return explicit
    if state == "blocked":
        return True
    return kind in ("decision", "review", "concern") and state != "resolved"


def _lens(state: str, needs_you: bool) -> str:
    if state == "resolved":
        return "resolved"
    if needs_you:
        return "needs"
    return "flight"


def _owner_out(raw: Any, present: set[str]) -> dict[str, Any] | None:
    """Normalize a payload owner into the row's owner shape, stamping presence."""
    if not raw:
        return None
    if isinstance(raw, str):
        raw = {"handle": raw}
    if not isinstance(raw, dict):
        return None
    handle = str(raw.get("handle") or "").strip()
    if not handle:
        return None
    kind = raw.get("kind")
    if kind not in ("agent", "human"):
        # Registered agents wear the accent; anyone else reads as human.
        kind = "agent" if handle in present else "human"
    return {"handle": handle, "kind": kind, "present": handle in present}


def _ledger_item(
    msg: local_state.StoredMessage, present: set[str], now: datetime
) -> dict[str, Any] | None:
    """Project one stateful ledger event into a board row (or None if dismissed)."""
    payload = dict((msg.event_metadata or {}).get("payload") or {})
    if payload.get("dismissed"):
        return None

    state = str(payload.get("state") or _STATUS_TO_STATE.get(msg.event_status or "open", "open"))
    kind = str(payload.get("kind") or msg.event_kind or "action")
    needs = _needs_you(kind, state, payload.get("needs_you"))
    title = str(payload.get("title") or msg.content or "").strip() or "(untitled)"

    return {
        "id": str(msg.id),
        "source": "ledger",
        "kind": kind,
        "state": state,
        "title": title,
        "detail": payload.get("detail"),
        "owner": _owner_out(payload.get("owner"), present),
        "work": payload.get("work"),
        "github": payload.get("github"),
        "choices": payload.get("choices"),
        "blocks": payload.get("blocks"),
        "waiting_on": payload.get("waiting_on"),
        "provenance": payload.get("provenance") or f"from {msg.sender_handle}",
        "age": _humanize_age(msg.created_at, now),
        "needs_you": needs,
        "note": payload.get("note"),
        "created_at": msg.created_at.isoformat(),
    }


def _plan_items(room_name: str, present: set[str], now: datetime) -> list[dict[str, Any]]:
    """Project the compiled plan checklist as read-mostly action rows."""
    _files, tasks = plan_service.load_plan(room_name)
    items: list[dict[str, Any]] = []
    for t in tasks:
        resolved = t.done
        items.append(
            {
                "id": f"plan:{t.id}",
                "source": "plan",
                "kind": "action",
                "state": "resolved" if resolved else "in_progress",
                "title": t.text,
                "owner": None,
                "provenance": f"plan/{t.slug}.md",
                "needs_you": False,
                "note": "task complete" if resolved else None,
                # Plan lines have no event timestamp; keep them stable at the
                # bottom of the sort by leaving created_at unset.
                "created_at": None,
            }
        )
    return items


def _live_episode_item(room_name: str) -> dict[str, Any] | None:
    """Surface a negotiation in flight as one "needs you" review row.

    Mirrors ``routes.episodes._live_episode_summary`` but returns a board row: an
    open episode lives only in the moderator's in-memory lifecycle until it
    converges, so the board reads it there rather than from a written record.
    """
    managed = channel_manager.get(room_name)
    if managed is None or not managed.lifecycle.active or not managed.lifecycle.episode:
        return None
    urn = managed.lifecycle.episode
    drop = {BACKEND_AGENT, l9.SYSTEM_ACTOR_ID}
    participants = sorted(m for m in managed.lifecycle.members if m not in drop)
    detail = "the aligner is brokering — reply to move it"
    if participants:
        detail = f"{detail} ({', '.join(participants)})"
    return {
        "id": f"ep:{urn.rsplit(':', 1)[-1]}",
        "source": "episode",
        "kind": "review",
        "state": "in_review",
        "title": "negotiation in flight",
        "detail": detail,
        "provenance": "from @aligner",
        "needs_you": True,
        "note": None,
        "created_at": None,
    }


def project_board(room_name: str) -> dict[str, Any]:
    """Assemble the live board: rows from every source, present members, counts."""
    now = datetime.now(UTC)
    present = set(channel_manager.members(room_name))

    items: list[dict[str, Any]] = []

    live_ep = _live_episode_item(room_name)
    if live_ep is not None:
        items.append(live_ep)

    for msg in local_state.list_messages(room_name):
        if msg.message_type != MessageType.EVENT or msg.event_kind not in BOARD_LEDGER_KINDS:
            continue
        if msg.event_expires_at is not None and msg.event_expires_at <= now:
            continue
        row = _ledger_item(msg, present, now)
        if row is not None:
            items.append(row)

    items.extend(_plan_items(room_name, present, now))

    # Newest ledger events first; plan/episode rows (no timestamp) sink below.
    items.sort(key=lambda r: r.get("created_at") or "", reverse=True)

    counts = {"needs": 0, "flight": 0, "resolved": 0}
    for r in items:
        counts[_lens(r["state"], r["needs_you"])] += 1

    return {
        "room": room_name,
        "items": items,
        "members": sorted(present),
        "counts": counts,
    }


# ── Mutations (the shared verb vocabulary) ────────────────────────────────────


def _publish_update(room_name: str, item_id: str, verb: str) -> None:
    bus.publish(
        room_channel(room_name),
        {
            "room_name": room_name,
            "sender_handle": l9.SYSTEM_ACTOR_ID,
            "message_type": "board_updated",
            "content": "{}",
            "board_item": item_id,
            "board_verb": verb,
            "created_at": datetime.now(UTC).isoformat(),
        },
    )


def _write_payload(
    msg: local_state.StoredMessage, updates: dict[str, Any], *, status: str | None
) -> None:
    """Merge ``updates`` into the event's payload and (optionally) move its status."""
    meta = dict(msg.event_metadata or {})
    payload = dict(meta.get("payload") or {})
    payload.update(updates)
    meta["payload"] = payload
    if status is not None:
        meta["status"] = status
        msg.event_status = status
    meta["status_updated_at"] = datetime.now(UTC).isoformat()
    msg.event_metadata = meta


class BoardError(Exception):
    """A verb that can't apply to the given item (maps to HTTP 409)."""


def capture_concern(room_name: str, title: str, *, sender: str) -> dict[str, Any]:
    """Natural-language capture → a structured, open ``concern`` on the ledger."""
    msg = local_state.StoredMessage(
        room_name=room_name,
        sender_handle=sender,
        message_type=MessageType.EVENT,
        content=title,
        event_kind="concern",
        event_status="open",
        event_metadata={
            "kind": "concern",
            "status": "open",
            "payload": {
                "kind": "concern",
                "title": title,
                "state": "open",
                "needs_you": True,
                "provenance": f"captured by {sender}",
            },
        },
    )
    local_state.add_message(room_name, msg)
    _publish_update(room_name, str(msg.id), "capture")
    now = datetime.now(UTC)
    present = set(channel_manager.members(room_name))
    return _ledger_item(msg, present, now)  # type: ignore[return-value]


def apply_verb(
    room_name: str,
    item_id: str,
    verb: str,
    *,
    owner: str | None = None,
    waiting_on: str | None = None,
    issue: int | None = None,
) -> None:
    """Apply a triage verb to a board item. Same verbs humans and agents drive.

    Plan rows accept only ``resolve`` (a task toggle); episode rows are read-only;
    ledger rows accept the full set, mutating payload + status in place.
    """
    if item_id.startswith("ep:"):
        raise BoardError("a live negotiation is read-only — reply in the channel to move it")

    if item_id.startswith("plan:"):
        if verb != "resolve":
            raise BoardError(f"plan items support only 'resolve', not {verb!r}")
        task_id = item_id[len("plan:") :]
        try:
            plan_service.toggle_task(room_name, task_id, done=True)
        except KeyError as e:
            raise KeyError(task_id) from e
        _publish_update(room_name, item_id, verb)
        return

    try:
        msg = local_state.find_message(UUID(item_id))
    except ValueError as e:
        raise KeyError(item_id) from e
    if msg is None or msg.room_name != room_name or msg.event_kind not in BOARD_LEDGER_KINDS:
        raise KeyError(item_id)

    if verb == "claim":
        who = owner or msg.sender_handle
        present = set(channel_manager.members(room_name))
        kind = "agent" if who in present else "human"
        # Claimed work is in flight, not awaiting the human — clear needs_you so
        # the row leaves the "Needs you" lens for "In flight".
        _write_payload(
            msg,
            {"owner": {"handle": who, "kind": kind}, "state": "claimed", "needs_you": False},
            status="in_progress",
        )
    elif verb == "block":
        updates: dict[str, Any] = {"state": "blocked", "needs_you": True}
        if waiting_on:
            updates["waiting_on"] = waiting_on
        _write_payload(msg, updates, status=None)
    elif verb == "resolve":
        _write_payload(msg, {"state": "resolved", "needs_you": False}, status="resolved")
    elif verb == "promote":
        # Tie to GitHub by reference: stamp the back-link and leave the board.
        # Filing the issue itself is the CLI/gh caller's job; the board records
        # the intent + link and resolves the row.
        updates = {"state": "resolved", "needs_you": False, "promoted": True}
        if issue is not None:
            updates["github"] = {"issue": issue, "state": "open"}
            updates["note"] = f"promoted → #{issue}"
        else:
            updates["note"] = "promoted → GitHub issue"
        _write_payload(msg, updates, status="resolved")
    elif verb == "dismiss":
        _write_payload(msg, {"dismissed": True}, status="resolved")
    else:
        raise BoardError(f"unknown verb {verb!r}")

    _publish_update(room_name, item_id, verb)
