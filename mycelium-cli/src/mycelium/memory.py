# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Writing, reading and searching a room's memory on the hub.

``mycelium memory set|get|search`` and :class:`mycelium.Room`'s ``memory``
send these. Each request takes a generated client, so the CLI keeps its own
session and the library its own.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from mycelium.exceptions import HubError

if TYPE_CHECKING:
    from mycelium_backend_client import Client
    from mycelium_backend_client.models import MemoryRead, MemorySearchResult


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
