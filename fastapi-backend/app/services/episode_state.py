# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
episode tracking.

:class:`EpisodeState` is what any episode is — a tagged thread over the room's
channel, with its participants, its topic and the envelopes it has carried. The
conductor opens one for each run it walks, nested inside the task's thread, and
:func:`write_episode_record` writes the full record to the parent room's memory
under ``log/episodes/{short_id}.md``: git-shareable and indexed by the normal
memory path.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import yaml

from app.services import message_format

logger = logging.getLogger(__name__)


@dataclass
class EpisodeState:
    """What every episode is: a tagged thread over the room's own channel.

    A task is one of these; so is a run inside a task. Everything here is what
    a thread has whatever happens in it — who it is scoped to, what it is about,
    and the envelopes it has carried.
    """

    episode: str  # URN
    topic: str  # concept URN
    parent_room: str
    short_id: str
    workspace_id: str
    mas_id: str
    agents: list[str]
    # The registered engine running this episode (e.g. "conductor"). Signs the
    # engine-authored envelopes so the wire carries the engine's real identity,
    # not the generic system actor. Empty → falls back to the system actor (an
    # episode opened outside an engine context).
    engine_handle: str = ""
    intent_id: str = ""
    # Ordered record of every envelope in the episode (dicts, wire shape).
    messages: list[dict[str, Any]] = field(default_factory=list)
    # The interaction flow this episode runs, when it has one: the step graph
    # (roles, steps, edges) and who was bound to each role. An episode with a
    # flow is a run the conductor walks; the record carries the graph so a
    # reader can see the shape of the interaction, not only its messages.
    flow: dict[str, Any] | None = None
    # One entry per step taken: which step, whose turn, what they answered
    # with, and the edge followed. Written as the run walks, so an open episode
    # shows where it is.
    trace: list[dict[str, Any]] = field(default_factory=list)
    # The thread this episode was opened from, when it was opened inside a
    # task: the link back to the row a nested episode belongs to.
    within: str | None = None
    # The memory a run saved its result to (a shared summary, a decision).
    memory: str | None = None


def write_episode_record(
    ep: EpisodeState,
    *,
    outcome: str,
    metrics: dict[str, Any] | None,
) -> None:
    """Persist the episode to ``log/episodes/{short_id}.md`` in the parent
    room's memory. Best-effort: never raises into the commit path."""
    try:
        lines = [
            f"# Episode {ep.episode}",
            "",
            f"- topic: `{ep.topic}`",
            f"- outcome: **{outcome}**",
            f"- participants: {', '.join(ep.agents)}",
        ]
        if metrics and metrics.get("min_satisfaction") is not None:
            per_agent = metrics.get("satisfaction", {})
            lines.append(
                f"- satisfaction: min {metrics['min_satisfaction']:.2f} "
                f"(least-happy of {len(per_agent)} members)"
            )
        if ep.within:
            lines.append(f"- within: `{ep.within}`")
        if ep.memory:
            lines.append(f"- memory: `{ep.memory}`")
        _append_flow(lines, ep)
        _append_messages(lines, ep)
        _write_record(ep, lines)
    except Exception:
        logger.exception("episode record write failed for %s", ep.episode)


def _append_flow(lines: list[str], ep: EpisodeState) -> None:
    """The flow an episode runs and the steps it has taken, as two fenced blocks."""
    if ep.flow is None:
        return
    lines += [
        "",
        "## Flow",
        "",
        "The interaction flow this episode runs — its roles, steps and edges:",
        "",
        "```yaml",
        yaml.safe_dump(ep.flow, sort_keys=False, default_flow_style=False).strip(),
        "```",
        "",
        "## Trace",
        "",
        "Each step taken, in order (one JSON entry per line):",
        "",
        "```jsonl",
        *(json.dumps(t, sort_keys=True) for t in ep.trace),
        "```",
    ]


def _append_messages(lines: list[str], ep: EpisodeState) -> None:
    lines += [
        "",
        "## Messages",
        "",
        "The full causally-linked message record (one JSON envelope per line):",
        "",
        "```jsonl",
        *(json.dumps(m, sort_keys=True) for m in ep.messages),
        "```",
        "",
    ]


def _write_record(ep: EpisodeState, lines: list[str]) -> None:
    from app.services.filesystem import get_room_dir, write_memory_file
    from app.services.tasks import carry_thread

    base = get_room_dir(ep.parent_room)
    base.mkdir(parents=True, exist_ok=True)
    key = f"log/episodes/{ep.short_id}"
    write_memory_file(
        base,
        key,
        "\n".join(lines),
        created_by=message_format.SYSTEM_ACTOR_ID,
        updated_by=message_format.SYSTEM_ACTOR_ID,
        # This write skips the upsert that mints an episode binding; the
        # episode record is part of the conversation thread.
        extra_meta=carry_thread(ep.parent_room, key),
    )
