# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Principal layer — the global user store plus owner/team roll-ups.

A user is one record at ``users/<handle>`` (global, markdown+frontmatter). An
agent manifest at ``rooms/<room>/agents/<handle>`` may carry ``owner`` (a user
handle) and ``team`` (a slug). This service reads both and derives the
per-user / per-team views the CLI and UI surface.

Trust is self-asserted: handles are consistent, not cryptographic.
"""

from __future__ import annotations

import logging
from typing import Any

import yaml

from app.services.filesystem import (
    get_room_dir,
    get_users_dir,
    list_memory_files,
    list_room_names,
    read_memory_file,
    write_memory_file,
)

logger = logging.getLogger(__name__)


#: Manifest adapter marking a first-party cognition engine (aligner, synthesizer).
#: Engines speak only through their own runtime, never an external participation call.
ENGINE_ADAPTER = "engine"


def _norm(handle: str | None) -> str | None:
    if not handle:
        return None
    cleaned = handle.strip().lstrip("@").lower()
    return cleaned or None


def _read_agent_manifest(room: str, handle: str) -> dict[str, Any] | None:
    """Parse the `agents/<handle>` manifest in a room, or None if absent/unreadable."""
    result = read_memory_file(get_room_dir(room), f"agents/{handle}")
    if result is None:
        return None
    try:
        data = yaml.safe_load(result[1]) or {}
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def classify_sender(room: str, handle: str) -> str:
    """Resolve a handle to what it actually is in this room.

    ``"agent"`` (a registered non-engine manifest), ``"engine"`` (an
    ``adapter: engine`` manifest), ``"user"`` (a record in the global store), or
    ``"unknown"`` (a phantom handle that resolves to neither).
    """
    h = _norm(handle)
    if not h:
        return "unknown"
    manifest = _read_agent_manifest(room, h)
    if manifest is not None:
        return "engine" if manifest.get("adapter") == ENGINE_ADAPTER else "agent"
    if load_user(h) is not None:
        return "user"
    return "unknown"


def post_rejection_reason(room: str, handle: str, *, allow_unregistered: bool) -> str | None:
    """Why ``handle`` may not post in ``room``, or None if it may.

    An **engine** is never impersonable through a participation call (drive it
    with ``engine invoke``). A **phantom** handle (neither agent nor user) is
    rejected on the agent path; the human/broadcast path passes
    ``allow_unregistered=True`` so an anonymous chat handle still works.
    """
    kind = classify_sender(room, handle)
    if kind == "engine":
        return (
            f"'{_norm(handle)}' is an engine and can't be posted as; "
            "drive it with `mycelium engine invoke`."
        )
    if kind == "unknown" and not allow_unregistered:
        return (
            f"'{_norm(handle)}' is not a registered agent or user; register it first "
            "(`mycelium agent create` or `mycelium user create`)."
        )
    return None


def load_user(handle: str) -> dict[str, Any] | None:
    """Read a user record and return its normalized fields, or None."""
    key = _norm(handle)
    if not key:
        return None
    result = read_memory_file(get_users_dir(), key)
    if result is None:
        return None
    _meta, content = result
    try:
        data = yaml.safe_load(content) or {}
    except yaml.YAMLError:
        logger.warning("user %s: invalid YAML", key)
        return None
    if not isinstance(data, dict):
        return None
    teams = data.get("teams") or []
    return {
        "handle": key,
        "display_name": data.get("display_name", "") or "",
        "teams": [t for t in (_norm(t) for t in teams) if t],
        "notify": data.get("notify"),
    }


def list_users() -> list[dict[str, Any]]:
    """Every user record in the global store."""
    out: list[dict[str, Any]] = []
    for key, _meta, _content in list_memory_files(get_users_dir(), limit=1000):
        # The store is flat: one record per handle, no nested keys.
        if "/" in key:
            continue
        user = load_user(key)
        if user is not None:
            out.append(user)
    return out


def write_user(payload: dict[str, Any]) -> dict[str, Any]:
    """Create or upsert a user record. Returns the normalized user."""
    handle = _norm(payload.get("handle"))
    if not handle:
        msg = "user handle is required"
        raise ValueError(msg)
    teams = [t for t in (_norm(t) for t in payload.get("teams") or []) if t]
    body = {
        "display_name": payload.get("display_name", "") or "",
        "teams": teams,
        "notify": payload.get("notify"),
    }
    yaml_body = yaml.safe_dump(body, sort_keys=False, default_flow_style=False).strip()

    existing = read_memory_file(get_users_dir(), handle)
    version = 1
    if existing is not None:
        # Content-idempotent: re-writing the same record is a no-op (no version
        # bump), so repeated upserts converge instead of counting up forever.
        if existing[1].strip() == yaml_body:
            return {"handle": handle, **body}
        try:
            version = int(existing[0].get("version", 1)) + 1
        except (TypeError, ValueError):
            version = 1
    write_memory_file(
        get_users_dir(),
        handle,
        yaml_body,
        created_by=payload.get("created_by", "system"),
        version=version,
        tags=["user-manifest"],
    )
    return {"handle": handle, **body}


def iter_agent_manifests() -> list[dict[str, Any]]:
    """Every agent manifest across all rooms, with room + parsed principal fields.

    Each entry: ``{room, handle, adapter, owner, team}``.
    """
    out: list[dict[str, Any]] = []
    for room_name in list_room_names():
        room_dir = get_room_dir(room_name)
        for key, _meta, content in list_memory_files(room_dir, prefix="agents/", limit=1000):
            handle = key.removeprefix("agents/")
            # Manifests live at agents/<handle>; skip notes + log children.
            if "/" in handle:
                continue
            try:
                data = yaml.safe_load(content) or {}
            except yaml.YAMLError:
                continue
            if not isinstance(data, dict):
                continue
            out.append(
                {
                    "room": room_name,
                    "handle": handle,
                    "adapter": data.get("adapter", "claude_code"),
                    "owner": _norm(data.get("owner")),
                    "team": _norm(data.get("team")),
                }
            )
    return out


def _apply_rollup(user: dict[str, Any], manifests: list[dict[str, Any]]) -> dict[str, Any]:
    """Attach the owned-agent list to a user record in place."""
    owned = [m for m in manifests if m["owner"] == user["handle"]]
    user["owns"] = [
        {
            "room": m["room"],
            "handle": m["handle"],
            "adapter": m["adapter"],
            "team": m["team"],
        }
        for m in owned
    ]
    return user


def user_with_rollup(handle: str) -> dict[str, Any] | None:
    """A user record enriched with the agents they own."""
    user = load_user(handle)
    if user is None:
        return None
    return _apply_rollup(user, iter_agent_manifests())


def list_users_with_rollup() -> list[dict[str, Any]]:
    """All users, each enriched with their owned-agent roll-up (one manifest scan)."""
    manifests = iter_agent_manifests()
    return [_apply_rollup(user, manifests) for user in list_users()]


def list_teams() -> list[dict[str, Any]]:
    """Teams rolled up from agent manifests and user records.

    A team's members are the users who claim it.
    """
    manifests = iter_agent_manifests()
    users = list_users()

    teams: dict[str, dict[str, Any]] = {}

    def _slot(name: str) -> dict[str, Any]:
        return teams.setdefault(name, {"team": name, "members": set(), "agent_count": 0})

    for m in manifests:
        if m["team"]:
            slot = _slot(m["team"])
            slot["agent_count"] += 1
    for u in users:
        for team in u["teams"]:
            _slot(team)["members"].add(u["handle"])

    return [
        {
            "team": name,
            "members": sorted(slot["members"]),
            "agent_count": slot["agent_count"],
        }
        for name, slot in sorted(teams.items())
    ]
