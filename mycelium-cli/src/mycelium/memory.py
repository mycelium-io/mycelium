# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A room's memory on the hub: writing, reading, listing, searching, its links
and its knowledge graph.

``mycelium memory ...`` and :class:`mycelium.Room`'s ``memory`` send these.
Each request takes a generated client, so the CLI keeps its own session and
the library its own. A refusal raises :class:`~mycelium.exceptions.HubError`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from mycelium.exceptions import HubError

if TYPE_CHECKING:
    from mycelium_backend_client import Client
    from mycelium_backend_client.models import (
        ExpandedMemoryRead,
        KnowledgeGraphRead,
        KnowledgeRead,
        LinkIntegrityRead,
        MemoryLinksRead,
        MemoryRead,
        MemorySearchResult,
        SubscriptionRead,
    )


def check_key(key: str) -> None:
    """Raise ``ValueError``, saying why, for a key the room won't take.

    The hub's path safety is the one rule on a key, and a key is stored as
    typed. The exception: every key under a board namespace is a row, so a
    nested one there would file a row nobody asked for.
    """
    from mycelium.board.model import LIVE_NAMESPACES

    if not key.strip() or "\\" in key or key.endswith("/"):
        msg = f"{key!r} isn't a memory key. Use `/` between its parts, like context/goal."
        raise ValueError(msg)
    category, _, name = key.partition("/")
    if category in LIVE_NAMESPACES and "/" in name:
        joined = "-".join(p for p in name.split("/") if p)
        msg = (
            f"{key} can't have folders: every {category}/ key is a row on the board, "
            f"so it takes one name. Try {category}/{joined}."
        )
        if category == "work":
            msg += " For a part of a task, use `mycelium board new <title> --parent <row>`."
        raise ValueError(msg)


def memory_item(
    key: str,
    value: str,
    *,
    handle: str,
    embed: bool = True,
    tags: list[str] | None = None,
    meta: dict[str, Any] | None = None,
) -> Any:
    """The ``MemoryCreate`` for one write, or ``ValueError`` for a key the room won't take."""
    from mycelium.protocol import MEMORY_CATEGORIES
    from mycelium_backend_client.models import MemoryCreate, MemoryCreateValueType0

    check_key(key)
    category, _, name = key.partition("/")
    if name and category in MEMORY_CATEGORIES:
        # A category key is recorded with when it was written.
        timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        structured = MemoryCreateValueType0()
        structured["text"] = value
        structured["logged_at"] = timestamp
        structured["category"] = category
        item = MemoryCreate(
            key=key,
            value=structured,
            created_by=handle,
            embed=embed,
            content_text=f"[{timestamp}] {value}",
            tags=tags,
        )
    else:
        try:
            parsed: Any = json.loads(value)
        except json.JSONDecodeError:
            parsed = value
        item = MemoryCreate(key=key, value=parsed, created_by=handle, embed=embed, tags=tags)
    if meta:
        # Frontmatter rides as an additional property, which the client passes through.
        item["meta"] = meta
    return item


def learned(
    kind: str | None = None,
    task: str | None = None,
    derived_from: list[str] | None = None,
    *,
    still_open: bool = False,
) -> dict[str, Any]:
    """The frontmatter that files a memory in a task's graph of what was learned."""
    meta: dict[str, Any] = {}
    if kind:
        meta["kind"] = kind
    if task:
        meta["task"] = task
    if derived_from:
        meta["derived-from"] = derived_from
    if still_open:
        meta["open"] = True
    return meta


def save_memory(client: Client, room: str, item: Any) -> MemoryRead:
    """Write one memory (an upsert) and return what the hub saved."""
    from mycelium.client import answered
    from mycelium_backend_client.api.memory import (
        create_memories_api_rooms_room_name_memory_post as create_api,
    )
    from mycelium_backend_client.models import MemoryBatchCreate

    resp = create_api.sync_detailed(
        room_name=room, client=client, body=MemoryBatchCreate(items=[item])
    )
    saved = [] if resp.status_code == 422 else answered(resp, list)  # noqa: PLR2004
    if not saved:
        raise HubError(resp.status_code, resp.content)
    return saved[0]


def read_memory(client: Client, room: str, key: str) -> MemoryRead:
    """One memory by key. A key the room doesn't have raises a 404 :class:`HubError`."""
    from mycelium.client import answered
    from mycelium_backend_client.api.memory import (
        get_memory_api_rooms_room_name_memory_key_get as get_api,
    )
    from mycelium_backend_client.models import MemoryRead

    return answered(get_api.sync_detailed(room_name=room, key=key, client=client), MemoryRead)


def search_memories(
    client: Client, room: str, query: str, limit: int = 5
) -> list[MemorySearchResult]:
    """The room's memories closest in meaning to ``query``, best first."""
    from mycelium.client import answered
    from mycelium_backend_client.api.memory import (
        search_memories_api_rooms_room_name_memory_search_post as search_api,
    )
    from mycelium_backend_client.models import MemorySearchRequest, MemorySearchResponse

    body = MemorySearchRequest(query=query, limit=limit)
    found = answered(
        search_api.sync_detailed(room_name=room, client=client, body=body), MemorySearchResponse
    )
    return list(found.results)


def thread_of(client: Client, room: str, key: str) -> tuple[bool, str | None]:
    """Whether the room has the memory ``key``, and the thread on it if it does.

    Only its thread is read, so a memory a hub a version apart shapes
    differently is still this memory, never "not there".
    """
    from mycelium.board.model import EPISODE_FIELD
    from mycelium.client import sent_unparsed
    from mycelium_backend_client.api.memory import get_memory_api_rooms_room_name_memory_key_get

    resp = sent_unparsed(get_memory_api_rooms_room_name_memory_key_get, client, room, key)
    if resp.status_code >= 400:  # noqa: PLR2004
        return False, None
    try:
        found = resp.json()
    except ValueError:
        return True, None
    return True, (found.get(EPISODE_FIELD) if isinstance(found, dict) else None) or None


def list_memories(
    client: Client, room: str, prefix: str | None = None, limit: int = 20
) -> list[MemoryRead]:
    """The room's memories, newest first, under ``prefix`` when given."""
    from mycelium.client import answered
    from mycelium_backend_client.api.memory import (
        list_memories_api_rooms_room_name_memory_get as list_api,
    )

    return answered(
        list_api.sync_detailed(room_name=room, client=client, prefix=prefix, limit=limit), list
    )


def changed_since(
    client: Client, room: str, etag: str | None, limit: int = 1000
) -> tuple[list[MemoryRead] | None, str | None]:
    """Every memory in the room, unless nothing changed since ``etag``.

    ``(None, etag)`` when the hub says nothing changed; otherwise the memories
    and the hub's new etag.
    """
    from mycelium.client import answered
    from mycelium_backend_client.api.memory import (
        list_memories_api_rooms_room_name_memory_get as list_api,
    )

    headers = {"If-None-Match": etag} if etag else {}
    resp = list_api.sync_detailed(room, client=client.with_headers(headers), limit=limit)
    if resp.status_code == 304:  # noqa: PLR2004
        return None, etag
    return answered(resp, list), resp.headers.get("etag")


def delete_memory(client: Client, room: str, key: str) -> None:
    """Delete one memory: its file and its place in the search index."""
    from mycelium_backend_client.api.memory import (
        delete_memory_api_rooms_room_name_memory_key_delete as delete_api,
    )

    resp = delete_api.sync_detailed(room_name=room, key=key, client=client)
    if resp.status_code >= 400:  # noqa: PLR2004
        raise HubError(resp.status_code, resp.content)


def subscribe(client: Client, room: str, pattern: str, handle: str) -> SubscriptionRead:
    """Have ``handle`` told when a memory matching the glob ``pattern`` changes."""
    from mycelium.client import answered
    from mycelium_backend_client.api.memory import (
        subscribe_api_rooms_room_name_memory_subscribe_post as sub_api,
    )
    from mycelium_backend_client.models import SubscriptionCreate, SubscriptionRead

    body = SubscriptionCreate(key_pattern=pattern, subscriber=handle)
    return answered(
        sub_api.sync_detailed(room_name=room, client=client, body=body), SubscriptionRead
    )


# ── links ─────────────────────────────────────────────────────────────────────


def expanded(client: Client, room: str, key: str) -> ExpandedMemoryRead:
    """One memory with its transclusions pulled in."""
    from mycelium.client import answered
    from mycelium_backend_client.api.links import (
        get_expanded_api_rooms_room_name_links_expand_get as expand_api,
    )
    from mycelium_backend_client.models import ExpandedMemoryRead

    return answered(expand_api.sync_detailed(room, client=client, key=key), ExpandedMemoryRead)


def integrity(client: Client, room: str) -> LinkIntegrityRead:
    """Every link in the room that doesn't resolve, and every embed that can't expand."""
    from mycelium.client import answered
    from mycelium_backend_client.api.links import (
        get_integrity_api_rooms_room_name_links_integrity_get as integrity_api,
    )
    from mycelium_backend_client.models import LinkIntegrityRead

    return answered(integrity_api.sync_detailed(room, client=client), LinkIntegrityRead)


def links(client: Client, room: str, key: str) -> MemoryLinksRead:
    """What one memory links to, and what links to it."""
    from mycelium.client import answered
    from mycelium_backend_client.api.links import (
        get_links_api_rooms_room_name_links_get as links_api,
    )
    from mycelium_backend_client.models import MemoryLinksRead

    return answered(links_api.sync_detailed(room, client=client, key=key), MemoryLinksRead)


# ── what the room learned ─────────────────────────────────────────────────────


def knowledge(client: Client, room: str, task: str | None = None) -> KnowledgeGraphRead:
    """The room's graph of what was learned, or one task's part of it."""
    from mycelium.client import answered
    from mycelium_backend_client.api.knowledge import (
        read_knowledge_api_rooms_room_name_knowledge_get as read_api,
    )
    from mycelium_backend_client.models import KnowledgeGraphRead
    from mycelium_backend_client.types import UNSET

    return answered(
        read_api.sync_detailed(room_name=room, client=client, task=task or UNSET),
        KnowledgeGraphRead,
    )


def settle(client: Client, room: str, key: str, handle: str | None) -> KnowledgeRead:
    """Mark a memory as holding: it's no longer open."""
    from mycelium.client import answered
    from mycelium_backend_client.api.knowledge import (
        settle_knowledge_api_rooms_room_name_knowledge_settle_post as settle_api,
    )
    from mycelium_backend_client.models import KnowledgeRead, KnowledgeSettle

    body = KnowledgeSettle(key=key, handle=(handle or "").lstrip("@") or None)
    return answered(
        settle_api.sync_detailed(room_name=room, client=client, body=body), KnowledgeRead
    )
