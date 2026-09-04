# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Projecting ``log/episodes/*`` records into the episode summary shape.

Each coordination session closes with a record written to the parent room's
memory (see :func:`app.services.l9_episode.write_episode_record`): a small
markdown header plus the full causally-linked L9 envelope chain as a ```jsonl```
block. This module turns one of those files back into structured fields — kind/
subkind, episode URN, participants, and the MPC/GAR/SCR consensus metrics — for
the episodes route and for cross-entity search.

The structured fields are derived from the envelopes themselves (the source of
truth), not the human-readable header; only ``tasks`` — which the consensus
envelope doesn't carry — is read from the markdown.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import yaml

from app.services.filesystem import get_room_dir, list_memory_files
from app.services.l9 import SYSTEM_ACTOR_ID

logger = logging.getLogger(__name__)

EPISODES_PREFIX = "log/episodes/"

# Anchored on their headings: a record with a flow carries two jsonl blocks
# (the trace, then the messages), so "the first fence" is no longer enough.
# The body ends at the closing fence itself, so an empty block (a run that
# has taken no step yet) captures nothing rather than running on into the
# next section.
_JSONL_RE = re.compile(r"## Messages\n.*?```jsonl\n(.*?)```", re.DOTALL)
_TRACE_RE = re.compile(r"## Trace\n.*?```jsonl\n(.*?)```", re.DOTALL)
_FLOW_RE = re.compile(r"## Flow\n.*?```yaml\n(.*?)```", re.DOTALL)
_TASKS_RE = re.compile(r"^- work: (.+)$", re.MULTILINE)
_WITHIN_RE = re.compile(r"^- within: `([^`]+)`$", re.MULTILINE)


def _parse_jsonl(match: re.Match[str] | None, what: str) -> list[dict[str, Any]]:
    if not match:
        return []
    rows: list[dict[str, Any]] = []
    for line in match.group(1).splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            logger.warning("skipping malformed episode %s line", what)
    return rows


def parse_envelopes(content: str) -> list[dict[str, Any]]:
    return _parse_jsonl(_JSONL_RE.search(content), "envelope")


def parse_trace(content: str) -> list[dict[str, Any]]:
    """The steps a flow episode has taken, as the record wrote them."""
    return _parse_jsonl(_TRACE_RE.search(content), "trace")


def parse_flow(content: str) -> dict[str, Any] | None:
    """The interaction flow an episode runs, or ``None`` for an episode without one."""
    match = _FLOW_RE.search(content)
    if not match:
        return None
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        logger.warning("skipping a flow block that does not parse")
        return None
    return data if isinstance(data, dict) else None


def current_step(
    flow: dict[str, Any] | None, trace: list[dict[str, Any]], outcome: str
) -> str | None:
    """Where an open run stands: the step its last trace entry led to, else its first."""
    if flow is None or outcome != "open":
        return None
    if trace:
        nxt = trace[-1].get("next")
        return str(nxt) if nxt else None
    steps = flow.get("steps")
    if isinstance(steps, list) and steps and isinstance(steps[0], dict):
        first = steps[0].get("id")
        return str(first) if first else None
    return None


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def episode_summary(key: str, meta: dict[str, Any], content: str) -> dict[str, Any]:
    """Project one episode record into the inspector's summary shape."""
    envelopes = parse_envelopes(content)
    short_id = key.rsplit("/", 1)[-1]

    episode_urn = ""
    topic = ""
    participants: list[str] = []
    outcome = "open"
    subkind: str | None = None
    metrics: dict[str, Any] | None = None
    assignments: dict[str, Any] | None = None

    for env in envelopes:
        header = _as_dict(env.get("header"))
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

    tasks_match = _TASKS_RE.search(content)
    tasks = (
        [k.strip(" `") for k in tasks_match.group(1).split(",") if k.strip(" `")]
        if tasks_match
        else []
    )
    within_match = _WITHIN_RE.search(content)
    flow = parse_flow(content)
    trace = parse_trace(content)

    return {
        "short_id": short_id,
        "episode": episode_urn,
        "topic": topic,
        "outcome": outcome,
        "subkind": subkind,
        "participants": participants,
        "metrics": metrics,
        "assignments": assignments,
        "tasks": tasks,
        "message_count": len(envelopes),
        "updated_at": meta.get("updated_at", ""),
        "updated_by": meta.get("updated_by", ""),
        "within": within_match.group(1) if within_match else None,
        "flow": flow,
        "trace": trace,
        "current_step": current_step(flow, trace, outcome),
    }


def live_episode_summary(room_name: str) -> dict[str, Any] | None:
    """Synthesize a summary for the episode currently *in progress*, if any.

    A closed episode lands as a ``log/episodes/*`` record; an open one exists only
    in the moderator's in-memory lifecycle until it converges/rejects. Surfacing it
    lets a caller show "in progress" (``outcome: "open"``) before the record is
    written, so a negotiation is visible while it runs, not only after it ends.
    """
    from app.services import l9
    from app.services.room_channels import BACKEND_AGENT, manager

    managed = manager.get(room_name)
    if managed is None or not managed.lifecycle.active or not managed.lifecycle.episode:
        return None
    urn = managed.lifecycle.episode
    drop = {BACKEND_AGENT, SYSTEM_ACTOR_ID}
    participants = sorted(m for m in managed.lifecycle.members if m not in drop)
    message_count = 0
    if managed.persister is not None:
        for record in managed.persister.log.records:
            message = record.content.get("l9", {}).get("header", {}).get("message", {})
            if message.get("episode") == urn:
                message_count += 1
    return {
        "short_id": urn.rsplit(":", 1)[-1],
        "episode": urn,
        "topic": l9.topic_urn(room_name),
        "outcome": "open",
        "subkind": None,
        "participants": participants,
        "metrics": None,
        "assignments": None,
        "tasks": [],
        "message_count": message_count,
        "updated_at": "",
        "updated_by": "",
        "within": None,
        "flow": None,
        "trace": [],
        "current_step": None,
    }


def room_episodes(room_name: str, *, limit: int = 50) -> list[dict[str, Any]]:
    """Episode summaries for a room, newest first, with an in-progress one first."""
    records = list_memory_files(get_room_dir(room_name), prefix=EPISODES_PREFIX, limit=limit)
    episodes = [episode_summary(key, meta, content) for key, meta, content in records]
    live = live_episode_summary(room_name)
    if live is not None and all(e["short_id"] != live["short_id"] for e in episodes):
        episodes.insert(0, live)
    return episodes
