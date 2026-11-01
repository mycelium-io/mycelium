# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Which engine kind, if any, a handle is in a room.

Every engine shares the one summon seam (``main._dispatch_summon``) and acts
only when the summoned handle's manifest names its kind, so they all read the
manifest the same way, here.
"""

from __future__ import annotations

from app.services.agent_registry import norm_handle


def registered_engine_kind(room: str, handle: str) -> str | None:
    """The engine kind if ``handle`` is a registered ``engine`` agent in ``room``.

    The agent manifest is stored as YAML in the body of ``agents/<handle>`` (the
    CLI's ``mycelium engine create`` writes ``adapter: engine`` + ``kind:``).
    Returns the ``kind`` for an engine manifest, else ``None``, so summoning a
    normal teammate, or a handle with a missing or broken manifest, fires no
    engine. Cheap: summons are rare and this is one small file read.
    """
    import yaml

    from app.services.filesystem import get_room_dir, read_memory_file

    result = read_memory_file(get_room_dir(room), f"agents/{handle}")
    if result is None:
        return None
    _meta, body = result
    try:
        data = yaml.safe_load(body) or {}
    except yaml.YAMLError:
        return None
    if isinstance(data, dict) and data.get("adapter") == "engine":
        kind = data.get("kind")
        return kind if isinstance(kind, str) else None
    return None


def norm(handle: str) -> str:
    """``handle`` normalized, with a blank handle as ``""``."""
    return norm_handle(handle) or ""
