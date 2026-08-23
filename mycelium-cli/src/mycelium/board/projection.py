# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Project what the room already has into board rows.

Nothing here is a new store: episodes, memories and presence are
read where they live and flattened into one row shape.  The board is one filter on
the room, so a row can't be stale relative to the thing it describes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from mycelium.board import assignment
from mycelium.board.model import LIVE_NAMESPACES, ItemSource, LiveItem


def _pretty_topic(topic: str) -> str:
    return topic.split(":")[-1].replace("-", " ").replace("_", " ")


def _episode_item(episode: dict) -> LiveItem:
    subkind = episode.get("subkind") or episode.get("outcome") or ""
    settled = subkind in ("converged", "resolved", "rejected")
    participants = episode.get("participants") or []
    assignments = episode.get("assignments") or {}
    topic = _pretty_topic(episode.get("topic", ""))
    return LiveItem(
        id=f"episode:{episode.get('short_id')}",
        title=(
            f"{topic}: {subkind}"
            if settled
            else f"{topic}: negotiating, {len(participants)} at the table"
        ),
        source=ItemSource("episode", f"episode {episode.get('short_id')}"),
        fields={
            # A rejected negotiation is not a stage called "blocked" — nothing is
            # blocking it, it failed and wants a human. It reads open, and the
            # kind carries what happened.
            "status": ("open" if subkind == "rejected" else "resolved") if settled else "in_review",
            "kind": "blocked" if subkind == "rejected" else "decision",
            "owner": f"@{next(iter(assignments))}" if len(assignments) == 1 else None,
            "priority": "normal" if settled else "high",
            "participants": participants,
            "rounds": episode.get("message_count"),
            "updated": episode.get("updated_at"),
            "ttl_minutes": 24 * 60 if settled else None,
        },
    )


def _first_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("---"):
            return stripped.lstrip("# ").strip()[:120]
    return ""


def _memory_item(memory: dict) -> LiveItem:
    key = memory.get("key", "")
    namespace = key.split("/")[0] if "/" in key else ""
    value = memory.get("value")
    # Frontmatter beyond the store's own keys is the room's schema — it passes
    # straight through, which is what makes a custom namespace a typed view.
    custom: dict[str, Any] = dict(value) if isinstance(value, dict) else {}
    custom.pop("text", None)
    custom.pop("content", None)

    if isinstance(custom.get("title"), str):
        title = custom["title"]
    elif isinstance(value, str):
        title = _first_line(value)
    else:
        title = _first_line(memory.get("content_text") or key)

    derived = "resolved" if namespace == "decisions" else "open"
    fields: dict[str, Any] = {
        "status": custom.get("status") if isinstance(custom.get("status"), str) else derived,
        "kind": {"decisions": "decision", "failed": "blocked"}.get(namespace, "concern"),
        # Who wrote it last is provenance, not assignment. Reading `owner` off
        # `updated_by` gave every memory in the room a holder, which is the
        # confident-lie failure this whole axis exists to stop: a holder is
        # something a claim writes, so an unclaimed row says nobody.
        "owner": None,
        "writer": f"@{memory.get('updated_by') or memory.get('created_by')}",
        "priority": "normal",
        "namespace": namespace,
        "tags": memory.get("tags") or [],
        "updated": memory.get("updated_at"),
        "ttl_minutes": None,
    }
    # `work/` is the in-flight unit, so it is the namespace that carries a lease:
    # frontmatter has somewhere to put a stamp, which is why leases live here and
    # not on rows that carry no stamp.
    if namespace in assignment.ASSIGNABLE_NAMESPACES:
        fields[assignment.FIELD] = "unclaimed"
    fields.update(custom)
    # The memory's own frontmatter, beyond the store's managed keys. This is
    # where a lease lands, and where a board action writes, so a projection that
    # read only the structured `value` would miss every field anybody actually
    # set — the GUI has read both all along.
    meta = memory.get("meta")
    if isinstance(meta, dict):
        fields.update(meta)
    return LiveItem(
        id=f"memory:{key}", title=title or key, source=ItemSource("memory", key), fields=fields
    )


def _agent_item(agent: dict, presence: dict, now: str) -> LiveItem:
    """Residency, as the lease it already is.

    A SLIM member holds a live socket, so the hub sees it now; a server-held
    member's lease is only as good as its last poll.  Stamping both with "now"
    made a dead agent's row draw a full TTL bar forever — the row asserted a
    future its holder had already stopped having.
    """
    handle = agent.get("handle", "")
    last_seen = presence.get("last_seen") or now
    return LiveItem(
        id=f"agent:{handle}",
        title=f"@{handle} is resident and awaiting work",
        source=ItemSource(
            "agent", f"{agent.get('adapter', 'agent')} · {presence.get('kind', 'slim')}"
        ),
        fields={
            "status": "open",
            "kind": "signal",
            "owner": f"@{handle}",
            "priority": "low",
            "adapter": agent.get("adapter"),
            "live": True,
            "updated": last_seen,
            # Presence is a lease: the row drains unless the runtime renews it.
            assignment.FIELD: "held",
            "claimed_at": last_seen,
            "ttl_minutes": assignment.DEFAULT_TTL_MINUTES,
        },
    )


def project_items(
    *,
    episodes: list[dict],
    memories: list[dict],
    agents: list[dict],
    members: list[dict],
    now: datetime,
) -> list[LiveItem]:
    stamp = now.isoformat()
    items: list[LiveItem] = []

    for episode in episodes:
        items.append(_episode_item(episode))
    for memory in memories:
        namespace = memory.get("key", "").split("/")[0]
        if namespace in LIVE_NAMESPACES:
            items.append(_memory_item(memory))

    # A resident agent is a peer, so it holds a row like anyone else.  A merely
    # registered one doesn't: a board of things that need steering shouldn't
    # carry a line per manifest.  Nor does one whose lease has drained — a
    # session that went quiet an hour ago is not residency, and a row saying it
    # is would be the board's most expensive lie.
    presence = {str(m.get("handle", "")).lower(): m for m in members}
    for agent in agents:
        seen = presence.get(str(agent.get("handle", "")).lower())
        if not seen:
            continue
        row = _agent_item(agent, seen, stamp)
        if assignment.assignment_of(row, now) == "held":
            items.append(row)

    return items
