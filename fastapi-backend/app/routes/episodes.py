# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
L9 episode read API — backs the protocol inspector.

Each coordination session closes with an episode record written to the parent
room's memory under ``log/episodes/{short_id}.md`` (see
``app.services.l9_episode.write_episode_record``): a small markdown header plus
the full causally-linked L9 envelope chain as a ```jsonl``` block. These
endpoints project those records into JSON the UI inspector renders — kind/
subkind, episode URN, causal parents, and the MPC/GAR/SCR consensus metrics.

GET /rooms/{room}/episodes            — summaries, newest first
GET /rooms/{room}/episodes/{short_id} — one episode + its envelope chain

The structured fields are derived from the envelopes themselves (the source of
truth), not the human-readable header; only ``plan_file`` — which the consensus
envelope doesn't carry — is read from the markdown.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from fastapi import APIRouter, HTTPException

from app.services.filesystem import get_room_dir, list_memory_files, read_memory_file, room_exists
from app.services.l9 import SYSTEM_ACTOR_ID

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rooms/{room_name}/episodes", tags=["episodes"])

_EPISODES_PREFIX = "log/episodes/"
_JSONL_RE = re.compile(r"```jsonl\n(.*?)\n```", re.DOTALL)
_PLAN_RE = re.compile(r"^- plan: `(.+)`$", re.MULTILINE)


def _require_room(room_name: str) -> None:
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")


def _parse_envelopes(content: str) -> list[dict[str, Any]]:
    """Pull the ``jsonl`` envelope chain out of an episode record's markdown."""
    match = _JSONL_RE.search(content)
    if not match:
        return []
    envelopes: list[dict[str, Any]] = []
    for line in match.group(1).splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            envelopes.append(json.loads(line))
        except json.JSONDecodeError:
            logger.warning("skipping malformed episode envelope line")
    return envelopes


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _header(env: dict[str, Any]) -> dict[str, Any]:
    return _as_dict(env.get("header"))


def _episode_summary(key: str, meta: dict[str, Any], content: str) -> dict[str, Any]:
    """Project one episode record into the inspector's summary shape."""
    envelopes = _parse_envelopes(content)
    short_id = key.rsplit("/", 1)[-1]

    episode_urn = ""
    topic = ""
    participants: list[str] = []
    outcome = "open"
    subkind: str | None = None
    metrics: dict[str, Any] | None = None
    assignments: dict[str, Any] | None = None

    for env in envelopes:
        header = _header(env)
        message = _as_dict(header.get("message"))
        if not episode_urn:
            episode_urn = str(message.get("episode") or "")
        context = _as_dict(header.get("context"))
        if not topic and context.get("topic"):
            topic = str(context["topic"])
        actors = _as_dict(header.get("participants")).get("actors") or []
        for actor in actors:
            if isinstance(actor, dict) and actor.get("role") == "agent":
                handle = str(actor.get("id") or "")
                if handle and handle != SYSTEM_ACTOR_ID and handle not in participants:
                    participants.append(handle)
        if header.get("kind") == "commit":
            subkind = header.get("subkind")
            outcome = str(subkind or "committed")
            data = _as_dict(_as_dict(env.get("payload")).get("data"))
            if isinstance(data.get("metrics"), dict):
                metrics = data["metrics"]
            if isinstance(data.get("assignments"), dict):
                assignments = data["assignments"]

    plan_match = _PLAN_RE.search(content)
    plan_file = plan_match.group(1) if plan_match else None

    return {
        "short_id": short_id,
        "episode": episode_urn,
        "topic": topic,
        "outcome": outcome,
        "subkind": subkind,
        "participants": participants,
        "metrics": metrics,
        "assignments": assignments,
        "plan_file": plan_file,
        "message_count": len(envelopes),
        "updated_at": meta.get("updated_at", ""),
        "updated_by": meta.get("updated_by", ""),
    }


@router.get("")
async def list_episodes(room_name: str, limit: int = 50):
    """List episode summaries for a room, newest first."""
    _require_room(room_name)
    records = list_memory_files(get_room_dir(room_name), prefix=_EPISODES_PREFIX, limit=limit)
    episodes = [_episode_summary(key, meta, content) for key, meta, content in records]
    return {"episodes": episodes}


@router.get("/{short_id}")
async def get_episode(room_name: str, short_id: str):
    """Return one episode: its summary plus the full L9 envelope chain."""
    _require_room(room_name)
    result = read_memory_file(get_room_dir(room_name), f"{_EPISODES_PREFIX}{short_id}")
    if result is None:
        raise HTTPException(status_code=404, detail="Episode not found")
    meta, content = result
    summary = _episode_summary(f"{_EPISODES_PREFIX}{short_id}", meta, content)
    summary["messages"] = _parse_envelopes(content)
    return summary
