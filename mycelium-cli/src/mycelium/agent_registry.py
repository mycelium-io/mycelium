# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Agent registry reads: enumerate handles and load manifests/notes from a room.

Agents are markdown manifests at ``agents/<handle>.md`` in a room dir (notes at
``agents/<handle>/notes.md``). These are pure filesystem reads over the room's
memory namespace, used by any consumer that needs to know who's registered:
agent commands, engine registration, and tests. Kept free of any runtime/dispatch
coupling so it survives independent of how agents are actually run.
"""

from __future__ import annotations

import logging

import yaml
from pydantic import ValidationError

from mycelium.filesystem import get_room_dir, list_memories, read_memory
from mycelium.protocol import AgentManifest

log = logging.getLogger("mycelium.agent_registry")


def list_agent_handles(room_name: str) -> list[str]:
    """List handles registered in *room_name* by scanning the local filesystem."""
    room_dir = get_room_dir(room_name)
    entries = list_memories(room_dir, prefix="agents/", limit=500)
    handles: list[str] = []
    for key, _meta, _content in entries:
        rest = key.removeprefix("agents/")
        if "/" in rest:
            continue
        handles.append(rest)
    return handles


def load_manifest(room_name: str, handle: str) -> AgentManifest | None:
    """Return the agent's manifest, or None if missing / unreadable.

    "Unreadable" (bad YAML, wrong shape, schema violation) is logged at WARNING
    so a corrupt manifest doesn't masquerade as "agent not registered": a
    consumer would otherwise silently ignore every @handle with no clue why.
    """
    room_dir = get_room_dir(room_name)
    path = room_dir / "agents" / f"{handle}.md"
    result = read_memory(room_dir, f"agents/{handle}")
    if result is None:
        return None
    _, content = result
    try:
        data = yaml.safe_load(content) or {}
    except yaml.YAMLError as exc:
        log.warning("manifest %s: invalid YAML: %s", path, exc)
        return None
    if not isinstance(data, dict):
        log.warning("manifest %s: expected a YAML mapping, got %s", path, type(data).__name__)
        return None
    data.setdefault("handle", handle)
    try:
        return AgentManifest(**data)
    except ValidationError as exc:
        log.warning("manifest %s: schema validation failed: %s", path, exc)
        return None


def load_notes(room_name: str, handle: str) -> str:
    """Return the agent's freeform notes (``agents/<handle>/notes``), or ''."""
    room_dir = get_room_dir(room_name)
    result = read_memory(room_dir, f"agents/{handle}/notes")
    if result is None:
        return ""
    _, content = result
    return content
