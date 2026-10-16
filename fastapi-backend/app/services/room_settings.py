# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A room's settings: memories under ``settings/``, checked against one table.

A room setting is a memory at ``settings/<id>``, its value in the frontmatter
as ``setting:`` and the reason for it in the body, so it is versioned, linked
and discussed like any memory. What may be set is :data:`TABLE`, a checked copy
of ``contracts/room-settings.json`` (the image carries only this package).

The check runs at the memory upsert (:func:`check_write`), not in a route of
its own, so the settings page, ``mycelium memory set settings/...`` and an
agent writing memory all hit the same refusal and read the same reason.

A setting with ``inherits`` takes the hub's value until the room sets its own,
and one with ``at_most_hub`` can lower the hub's value but never raise it: a
room asking for more worker turns than its hub allows gets the hub's.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import settings as hub_settings
from app.services.filesystem import get_room_dir, read_memory_file

NAMESPACE = "settings/"
VALUE_FIELD = "setting"


@dataclass(frozen=True)
class Spec:
    """One row of the table: what a room setting is and which values it takes."""

    id: str
    kind: str  # "bool" | "int" | "set"
    options: tuple[str, ...] = ()
    default: Any = None
    min: int | None = None
    inherits: str | None = None
    at_most_hub: bool = False


#: The room settings, frozen in ``contracts/room-settings.json``.
TABLE: tuple[Spec, ...] = (
    Spec(
        id="chat-board-moves",
        kind="set",
        options=("filed", "claimed", "released", "blocked", "unblocked", "expired", "resolved"),
        default=("filed", "resolved"),
    ),
    Spec(id="dependency-gate", kind="bool", inherits="board.dependency_gate"),
    Spec(
        id="worker-turns",
        kind="int",
        min=1,
        inherits="worker.max_turns_per_room",
        at_most_hub=True,
    ),
)

BY_ID: dict[str, Spec] = {s.id: s for s in TABLE}

#: Where each inherited setting's hub value comes from.
_HUB_VALUE = {
    "board.dependency_gate": lambda: hub_settings.BOARD_DEPENDENCY_GATE,
    "worker.max_turns_per_room": lambda: hub_settings.WORKER_MAX_TURNS_PER_ROOM,
}


class RoomSettingError(ValueError):
    """A write to ``settings/`` the table refuses; the message says why."""


def is_setting_key(key: str) -> bool:
    return key.startswith(NAMESPACE)


def hub_value(spec: Spec) -> Any:
    """The hub's value for an inherited setting, else the table's default."""
    if spec.inherits:
        return _HUB_VALUE[spec.inherits]()
    return list(spec.default) if spec.kind == "set" else spec.default


def _allowed(spec: Spec) -> str:
    if spec.kind == "bool":
        return "true or false"
    if spec.kind == "int":
        top = f" and at most the hub's {hub_value(spec)}" if spec.at_most_hub else ""
        return f"a whole number of at least {spec.min}{top}"
    return f"a list drawn from {', '.join(spec.options)}"


def validate(spec: Spec, value: Any) -> Any:
    """``value`` as the setting stores it, or :class:`RoomSettingError` saying what's allowed."""
    if spec.kind == "bool":
        if isinstance(value, bool):
            return value
    elif spec.kind == "int":
        if isinstance(value, int) and not isinstance(value, bool):
            ok = spec.min is None or value >= spec.min
            if spec.at_most_hub:
                ok = ok and value <= hub_value(spec)
            if ok:
                return value
    elif isinstance(value, list) and all(isinstance(v, str) for v in value):
        unknown = [v for v in value if v not in spec.options]
        if not unknown:
            # Kept in the table's order, once each, so two writes of the same
            # choice read the same on disk.
            return [o for o in spec.options if o in value]
    msg = f"settings/{spec.id} takes {_allowed(spec)}, not {value!r}"
    raise RoomSettingError(msg)


def check_write(key: str, meta: dict[str, Any] | None, existing_meta: dict[str, Any]) -> Any:
    """Refuse a ``settings/`` write the table doesn't allow; return the stored value.

    ``meta`` is what this write sets, ``existing_meta`` what's on disk, so a
    write that only changes the reason keeps the value it had.
    """
    setting_id = key[len(NAMESPACE) :]
    spec = BY_ID.get(setting_id)
    if spec is None:
        known = ", ".join(s.id for s in TABLE)
        msg = f"there is no room setting '{setting_id}'; a room has {known}"
        raise RoomSettingError(msg)
    if meta and VALUE_FIELD in meta:
        return validate(spec, meta[VALUE_FIELD])
    if VALUE_FIELD in existing_meta:
        return validate(spec, existing_meta[VALUE_FIELD])
    msg = f"settings/{spec.id} needs its value as `{VALUE_FIELD}:` in the frontmatter"
    raise RoomSettingError(msg)


def _stored(room: str, spec: Spec) -> tuple[dict[str, Any], str] | None:
    found = read_memory_file(get_room_dir(room), f"{NAMESPACE}{spec.id}")
    if found is None or VALUE_FIELD not in found[0]:
        return None
    return found


def value(room: str, setting_id: str) -> Any:
    """The value a room runs with: its own if set (within the hub's limit), else the hub's."""
    spec = BY_ID[setting_id]
    hub = hub_value(spec)
    found = _stored(room, spec)
    if found is None:
        return hub
    try:
        own = validate(spec, found[0][VALUE_FIELD])
    except RoomSettingError:
        # A hand-edited file, or a hub that has since lowered its cap below what
        # the room set: run with the hub's value rather than an unchecked one,
        # and never below the table's floor (a `setting: 0` would silence workers).
        stored = found[0][VALUE_FIELD]
        if spec.at_most_hub and isinstance(stored, int) and not isinstance(stored, bool):
            return max(spec.min or 0, min(stored, hub))
        return hub
    return own


def describe(room: str) -> list[dict[str, Any]]:
    """Every room setting with its value, where that comes from, and the room's own if set."""
    out: list[dict[str, Any]] = []
    for spec in TABLE:
        found = _stored(room, spec)
        meta, body = found if found else ({}, "")
        entry: dict[str, Any] = {
            "id": spec.id,
            "kind": spec.kind,
            "value": value(room, spec.id),
            "source": "room" if found else ("hub" if spec.inherits else "default"),
            "hub_value": hub_value(spec),
            "options": list(spec.options),
            "min": spec.min,
            "max": hub_value(spec) if spec.at_most_hub else None,
            "inherits": spec.inherits,
            "reason": body.strip() or None,
            "version": meta.get("version"),
            "updated_by": meta.get("updated_by") or meta.get("created_by"),
            "updated_at": str(meta["updated_at"]) if meta.get("updated_at") else None,
        }
        out.append(entry)
    return out
