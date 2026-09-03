# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Reading and writing a room's agent manifests.

Agents are registered as ``agents/<handle>`` memories whose body is a YAML
manifest. This module:

- Projects those files into the typed :class:`AgentRead` the agents route
  serves and cross-entity search matches against, so both read the manifests
  through one parser.
- Provides :func:`norm_handle`, the canonical handle normaliser used by every
  route or service that touches agent handles, so the rule lives in one place.
- Provides :func:`write_agent_manifest`, the single path that turns a manifest
  dict into the tagged, non-embedded memory used as the agent contract. Both
  :mod:`app.routes.a2a_agents` and :mod:`app.routes.engines` write through it.
"""

from __future__ import annotations

import logging

import yaml

from app.schemas import AgentRead
from app.services.filesystem import get_room_dir, list_memory_files

logger = logging.getLogger(__name__)

AGENTS_PREFIX = "agents/"


def norm_handle(value: object) -> str | None:
    """Normalise an agent handle to a lowercase slug, or ``None`` if blank.

    Strips whitespace, removes a leading ``@``, lowercases, and returns
    ``None`` when the result is empty. This is the canonical normaliser for
    every place in the stack that reads or writes agent handle fields.
    """
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lstrip("@").lower()
    return cleaned or None


# Alias for internal use.
_norm = norm_handle


async def write_agent_manifest(room_name: str, handle: str, body: dict, *, created_by: str) -> None:
    """Write (or overwrite) an agent manifest memory for *handle* in *room_name*.

    The memory is stored as ``agents/<handle>`` with ``embed=False`` and
    ``tags=["agent-manifest"]`` — the single canonical shape every read path
    expects. Routes that build different manifests (engine vs. A2A) call this
    with their respective ``body`` dict so the YAML serialisation, tag constant,
    and embed flag are not duplicated.

    Uses a lazy import of :func:`app.routes.memory.upsert_memories` to avoid
    a services → routes circular dependency, following the same pattern as
    :mod:`app.services.task_sync` and :mod:`app.services.synthesizer`.
    """
    from app.routes.memory import upsert_memories  # lazy — routes import services
    from app.schemas import MemoryBatchCreate, MemoryCreate

    key = f"agents/{handle}"
    yaml_body = yaml.safe_dump(body, sort_keys=False, default_flow_style=False).strip()
    batch = MemoryBatchCreate(
        items=[
            MemoryCreate(
                key=key,
                value=yaml_body,
                created_by=created_by,
                embed=False,
                tags=["agent-manifest"],
            )
        ]
    )
    await upsert_memories(room_name, batch)


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
                owner=norm_handle(data.get("owner")),
                team=norm_handle(data.get("team")),
                allow_from=[str(h) for h in allow_from if h],
                a2a_card=str(data["a2a_card"]) if data.get("a2a_card") else None,
                a2a_endpoint=str(data["a2a_endpoint"]) if data.get("a2a_endpoint") else None,
                a2a_skills=[str(s) for s in skills if s],
            )
        )

    agents.sort(key=lambda a: a.handle)
    return agents
