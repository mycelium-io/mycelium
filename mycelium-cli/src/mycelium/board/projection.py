# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Project what the room already has into board rows.

Nothing here is a new store: plan tasks, episodes, memories and presence are
read where they live and flattened into one row shape.  The board is a lens on
the room, so a row can't be stale relative to the thing it describes.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from mycelium.board.model import LIVE_NAMESPACES, ItemSource, LiveItem

_OWNER = re.compile(r"@([a-z0-9][a-z0-9._-]*)", re.IGNORECASE)
_ISSUE = re.compile(r"#(\d+)")


def _priority_from_text(text: str) -> str:
    lowered = text.lower()
    if re.search(r"\b(urgent|asap|blocker|critical)\b", lowered):
        return "urgent"
    if re.search(r"\b(important|high|soon)\b", lowered):
        return "high"
    if re.search(r"\b(nit|minor|someday)\b", lowered):
        return "low"
    return "normal"


def _plan_item(task: dict, plan: dict, now: str) -> LiveItem:
    owner_match = _OWNER.search(task.get("text", ""))
    owner = owner_match.group(1) if owner_match else None
    issue_match = _ISSUE.search(task.get("text", ""))
    slug = task.get("slug", "tasks")
    plan_file = next((f for f in plan.get("files", []) if f.get("slug") == slug), None)
    title = _OWNER.sub("", task.get("text", "")).strip()
    return LiveItem(
        id=f"plan:{task['id']}",
        title=title or task.get("text", ""),
        source=ItemSource("plan", f"plan/{slug}.md:{task.get('line', 0)}"),
        fields={
            "status": "resolved" if task.get("done") else ("in_progress" if owner else "open"),
            "kind": "action",
            "owner": f"@{owner}" if owner else None,
            "priority": _priority_from_text(task.get("text", "")),
            "issue": issue_match.group(0) if issue_match else None,
            "updated": (plan_file or {}).get("updated_at") or now,
            # A compiled plan task is the room's durable commitment, so it is the
            # one row kind with no TTL — it leaves by being done, not by expiring.
            "ttl_minutes": None,
        },
    )


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
            "status": ("blocked" if subkind == "rejected" else "resolved")
            if settled
            else "in_review",
            "kind": "decision",
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

    derived = {"failed": "blocked", "decisions": "resolved"}.get(namespace, "open")
    fields: dict[str, Any] = {
        "status": custom.get("status") if isinstance(custom.get("status"), str) else derived,
        "kind": {"decisions": "decision", "failed": "blocked"}.get(namespace, "concern"),
        "owner": f"@{memory.get('updated_by') or memory.get('created_by')}",
        "priority": "normal",
        "namespace": namespace,
        "tags": memory.get("tags") or [],
        "updated": memory.get("updated_at"),
        "ttl_minutes": None,
    }
    fields.update(custom)
    return LiveItem(
        id=f"memory:{key}", title=title or key, source=ItemSource("memory", key), fields=fields
    )


def _agent_item(agent: dict, presence: dict, now: str) -> LiveItem:
    handle = agent.get("handle", "")
    return LiveItem(
        id=f"agent:{handle}",
        title=f"@{handle} is resident and awaiting work",
        source=ItemSource(
            "agent", f"{agent.get('adapter', 'agent')} · {presence.get('kind', 'slim')}"
        ),
        fields={
            "status": "claimed",
            "kind": "signal",
            "owner": f"@{handle}",
            "priority": "low",
            "adapter": agent.get("adapter"),
            "live": True,
            "updated": now,
            # Presence is a lease: the row drains unless the runtime renews it.
            "ttl_minutes": 30,
        },
    )


def project_items(
    *,
    plan: dict | None,
    episodes: list[dict],
    memories: list[dict],
    agents: list[dict],
    members: list[dict],
    now: datetime,
    demo: bool = False,
) -> list[LiveItem]:
    stamp = now.isoformat()
    items: list[LiveItem] = []

    for task in (plan or {}).get("tasks", []):
        items.append(_plan_item(task, plan or {}, stamp))
    for episode in episodes:
        items.append(_episode_item(episode))
    for memory in memories:
        namespace = memory.get("key", "").split("/")[0]
        if namespace in LIVE_NAMESPACES:
            items.append(_memory_item(memory))

    # A resident agent is a peer, so it holds a row like anyone else.  A merely
    # registered one doesn't: a board of things that need steering shouldn't
    # carry a line per manifest.
    presence = {str(m.get("handle", "")).lower(): m for m in members}
    for agent in agents:
        seen = presence.get(str(agent.get("handle", "")).lower())
        if seen:
            items.append(_agent_item(agent, seen, stamp))

    if demo:
        items.extend(demo_items(now))
    return items


def demo_items(now: datetime) -> list[LiveItem]:
    """Rows for the sources a live board would fill itself from — herdr presence,
    CI, PRs — which this proof of concept has no reader for yet.  Every row is
    stamped ``demo`` so what the room holds is never confused with what the
    surface is illustrating."""

    def ago(minutes: int) -> str:
        return (now - timedelta(minutes=minutes)).isoformat()

    return [
        LiveItem(
            id="demo:d3f",
            title="JWT access-token TTL: 15m or 60m?",
            source=ItemSource("episode", "@agent-y · episode d3f"),
            demo=True,
            fields={
                "status": "open",
                "kind": "decision",
                "owner": None,
                "priority": "urgent",
                "choices": ["15m", "60m"],
                "updated": ago(6),
                "ttl_minutes": 120,
            },
        ),
        LiveItem(
            id="demo:a91",
            title="Enable thin-spoke join without a local replica",
            source=ItemSource("github", "linked to #502"),
            demo=True,
            fields={
                "status": "blocked",
                "kind": "blocked",
                "owner": "@julia",
                "priority": "high",
                "blocked_by": ["#502"],
                "issue": "#502",
                "updated": ago(40),
                "ttl_minutes": None,
            },
        ),
        LiveItem(
            id="demo:7c2",
            title="@agent-z opened PR #504 and wants eyes on the custody seam",
            source=ItemSource("github", "PR #504"),
            demo=True,
            fields={
                "status": "open",
                "kind": "review",
                "owner": "@agent-z",
                "priority": "high",
                "pr": "#504",
                "ci": "green",
                "branch": "feat/custody-seam",
                "updated": ago(12),
                "ttl_minutes": 720,
            },
        ),
        LiveItem(
            id="demo:b12",
            title="Migrate auth → JWT",
            source=ItemSource("agent", "@agent-y · claude_code"),
            demo=True,
            fields={
                "status": "in_progress",
                "kind": "action",
                "owner": "@agent-y",
                "priority": "high",
                "branch": "feat/jwt-auth",
                "pr": "#502",
                "ci": "green",
                "live": True,
                "blocks": ["Enable thin-spoke join"],
                "updated": ago(12),
                "ttl_minutes": None,
            },
        ),
        LiveItem(
            id="demo:e45",
            title="Cache TTL sweep across the memory index",
            source=ItemSource("agent", "@julia · human"),
            demo=True,
            fields={
                "status": "in_progress",
                "kind": "action",
                "owner": "@julia",
                "priority": "normal",
                "branch": "feat/cache",
                "ci": "running",
                "live": True,
                "updated": ago(3),
                "ttl_minutes": None,
            },
        ),
        LiveItem(
            id="demo:c01",
            title="Fix path traversal in the memory key encoder",
            source=ItemSource("github", "PR #499 merged"),
            demo=True,
            fields={
                "status": "resolved",
                "kind": "action",
                "owner": "@agent-z",
                "priority": "urgent",
                "pr": "#499",
                "ci": "green",
                "updated": ago(62),
                "ttl_minutes": 1440,
            },
        ),
    ]
