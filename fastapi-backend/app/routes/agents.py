# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""GET /rooms/{room_name}/agents — structured agent manifest listing."""

import logging

import yaml
from fastapi import APIRouter, HTTPException

from app.schemas import AgentRead
from app.services.filesystem import get_room_dir, list_memory_files, room_exists

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rooms/{room_name}/agents", tags=["agents"])


def _norm(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lstrip("@").lower()
    return cleaned or None


@router.get("", response_model=list[AgentRead])
async def list_agents(room_name: str) -> list[AgentRead]:
    """Return every agent registered in the room as structured JSON.

    Reads ``agents/<handle>`` memory entries, parses the YAML body through
    the manifest fields, and returns a typed list. Sub-keys like
    ``agents/<handle>/notes`` are skipped.
    """
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")

    room_dir = get_room_dir(room_name)
    agents: list[AgentRead] = []

    for key, _meta, content in list_memory_files(room_dir, prefix="agents/", limit=1000):
        handle = key.removeprefix("agents/")
        if "/" in handle:
            continue
        try:
            data = yaml.safe_load(content) or {}
        except yaml.YAMLError:
            logger.warning("room %s: skipping agent %r — invalid YAML", room_name, handle)
            continue
        if not isinstance(data, dict):
            continue

        try:
            budget = float(data.get("budget_usd_per_month", 0.0) or 0.0)
        except (TypeError, ValueError):
            budget = 0.0

        allow_from = data.get("allow_from") or []
        if not isinstance(allow_from, list):
            allow_from = []

        agents.append(
            AgentRead(
                handle=handle,
                adapter=str(data.get("adapter") or "claude_code"),
                kind=str(data["kind"]) if data.get("kind") else None,
                description=str(data.get("description") or ""),
                cwd=str(data["cwd"]) if data.get("cwd") else None,
                owner=_norm(data.get("owner")),
                team=_norm(data.get("team")),
                budget_usd_per_month=budget,
                allow_from=[str(h) for h in allow_from if h],
            )
        )

    agents.sort(key=lambda a: a.handle)
    return agents
