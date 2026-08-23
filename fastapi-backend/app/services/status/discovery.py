# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Which external things a room is already talking about, and where it says so.

A room never declares "watch this pull request". Someone writes a plan task that
says ``land the custody seam: mycelium-io/mycelium#504``, and the reference is
already there. This module reads the room's own text and asks the registered
providers what they recognise in it, so tracking is a consequence of writing
normally rather than a per-row setting somebody has to remember.

**The app still knows no syntax.** Nothing here matches ``#504`` or an issue URL;
``StatusRuntime.claims`` asks each provider what it claims, and a provider is the
only thing that knows its own shapes. Teaching the hub about Jira ticket keys is
adding a provider, not editing this file.

**Origins are board row ids.** A ref is discovered *somewhere*, and the surface
needs to put the answer on the row that mentioned it. The origin strings here are
exactly the ids the two board projections already build (``plan:{task_id}``,
``memory:{key}``), so a surface attaches an answer by matching an id it already
has rather than re-parsing the text itself. One row can mention two pull
requests, and one pull request can be mentioned by three rows; both are ordinary,
so this is a many-to-many and neither side is collapsed here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.services.filesystem import get_room_dir, list_memory_files

if TYPE_CHECKING:
    from app.services.status.runtime import StatusRuntime
    from app.services.status.types import Ref

#: Memory namespaces the board treats as live work, and so the only ones worth
#: scanning. Frozen in ``contracts/board-vocabulary.json`` as ``live_namespaces``
#: and mirrored by both board projections; a memory outside them is reference
#: material, not something anybody is waiting on.
LIVE_NAMESPACES = ("decisions", "status", "work", "failed")

#: Most memories to scan in one pass. A room with ten thousand memories should
#: cost a bounded read, and the rows a board shows are the recent ones anyway.
SCAN_LIMIT = 500


@dataclass(frozen=True, slots=True)
class Discovered:
    """One external reference, and every row in the room that mentions it."""

    ref: Ref
    origins: tuple[str, ...] = field(default=())


def discover(room_name: str, runtime: StatusRuntime) -> list[Discovered]:
    """Every ref the room's text mentions, each with the row ids that mention it.

    Ordered by first appearance so a caller that truncates keeps the plan's own
    ordering rather than a hash order.
    """
    found: dict[Ref, list[str]] = {}
    order: list[Ref] = []

    def note(text: str, origin: str) -> None:
        if not text:
            return
        for ref in runtime.claims(text):
            if ref not in found:
                found[ref] = []
                order.append(ref)
            if origin not in found[ref]:
                found[ref].append(origin)

    room_dir = get_room_dir(room_name)
    for namespace in LIVE_NAMESPACES:
        for key, _meta, content in list_memory_files(room_dir, prefix=namespace, limit=SCAN_LIMIT):
            # The key is scanned too: a memory filed as `work/pr-504` names the
            # thing it is about in its own name as often as in its body.
            note(f"{key}\n{content}", f"memory:{key}")

    return [Discovered(ref=ref, origins=tuple(found[ref])) for ref in order]
