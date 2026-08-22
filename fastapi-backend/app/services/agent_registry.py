# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Reading a room's agent manifests.

Agents are registered as ``agents/<handle>`` memories whose body is a YAML
manifest. This projects those files into the typed :class:`AgentRead` the
agents route serves and cross-entity search matches against, so both read the
manifests through one parser.
"""

from __future__ import annotations

import logging

import yaml

from app.schemas import AgentRead
from app.services.filesystem import get_room_dir, list_memory_files

logger = logging.getLogger(__name__)

AGENTS_PREFIX = "agents/"


def _norm(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lstrip("@").lower()
    return cleaned or None


def room_agents(room_name: str) -> list[AgentRead]:
    """Every agent registered in ``room_name``, sorted by handle.

    Sub-keys like ``agents/<handle>/notes`` are skipped: only the manifest
    itself describes an agent. A manifest that isn't a YAML mapping is skipped
    with a warning rather than failing the whole listing.
    """
    room_dir = get_room_dir(room_name)
    agents: list[AgentRead] = []

    for key, _meta, content in list_memory_files(room_dir, prefix=AGENTS_PREFIX, limit=1000):
        handle = key.removeprefix(AGENTS_PREFIX)
        if "/" in handle:
            continue
        try:
            data = yaml.safe_load(content) or {}
        except yaml.YAMLError:
            logger.warning("room %s: skipping agent %r — invalid YAML", room_name, handle)
            continue
        if not isinstance(data, dict):
            continue

        allow_from = data.get("allow_from") or []
        if not isinstance(allow_from, list):
            allow_from = []

        skills = data.get("a2a_skills") or []
        if not isinstance(skills, list):
            skills = []

        agents.append(
            AgentRead(
                handle=handle,
                adapter=str(data.get("adapter") or "claude_code"),
                kind=str(data["kind"]) if data.get("kind") else None,
                description=str(data.get("description") or ""),
                cwd=str(data["cwd"]) if data.get("cwd") else None,
                owner=_norm(data.get("owner")),
                team=_norm(data.get("team")),
                allow_from=[str(h) for h in allow_from if h],
                a2a_card=str(data["a2a_card"]) if data.get("a2a_card") else None,
                a2a_endpoint=str(data["a2a_endpoint"]) if data.get("a2a_endpoint") else None,
                a2a_skills=[str(s) for s in skills if s],
            )
        )

    agents.sort(key=lambda a: a.handle)
    return agents
