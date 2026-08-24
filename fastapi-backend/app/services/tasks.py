# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A task, and the thread it is worked in.

A ``work/`` row is the task: one board row, one thing to do, with its own
custody and status.  This module binds that row to an **episode URN** — a tag
over the room's existing channel, not a new one — so the same row is also the
thread the coordination about it happens in.  Nothing new is stored to make that
true: the URN is one frontmatter key on the memory the row already is.

Two properties everything downstream reads off this module:

**The container outlives what happens inside it.**  A task's episode is minted
when the task is created, not when someone argues about it.  A negotiation
inside a task is its own, later episode with its own lifecycle
(:class:`~app.services.l9_slim.EpisodeLifecycle`), and closing or aborting one
touches neither the row's custody nor its status.  A task can be created,
claimed, worked and resolved with no negotiation ever opened.

**Binding happens once.**  The URN is minted on the write that creates the task
and carried forward by every later write
(:data:`~app.services.filesystem.SYSTEM_META`), so a row's thread is stable for
the row's life.  Re-negotiating inside a task opens a *new* negotiation episode;
it does not re-mint the task's own.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.services import l9
from app.services.filesystem import (
    EPISODE_META,
    get_room_dir,
    list_memory_files,
    read_memory_file,
    serialize_memory,
    system_meta,
)

if TYPE_CHECKING:
    from app.schemas import MemoryRead

logger = logging.getLogger(__name__)

#: The namespace a task lives in — the one the board leases against.
WORK_NAMESPACE = "work"

#: What a board row calls a task.  Written explicitly because the
#: projection's default for this namespace is "concern" — a task is an action.
TASK_KIND = "action"

#: Who a task is *meant for*, which is not who holds it.
#:
#: Deliberately not ``owner``: that is the lease's, and a lease is something an
#: actor takes under rules a compiler or a creation call cannot satisfy — no
#: claim window, no renewal, and nobody on the other end who has agreed to hold
#: anything.  An assignment written as custody would be a claim on behalf of an
#: agent that never made one, and it would drain to "expired" the moment its TTL
#: passed.
ASSIGNEE_FIELD = "assignee"

#: Longest slug taken from a task's title, before any de-duplicating suffix.
SLUG_MAX = 48

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")

#: Frontmatter :func:`serialize_memory` writes from its own arguments; passing
#: it through ``extra_meta`` as well would write each of those keys twice.
_REWRITTEN_META = frozenset({"key", "created_by", "updated_by", "version", "tags"})


def _norm(handle: str) -> str:
    """A handle as it compares: the roster and the caller may spell it differently."""
    return handle.strip().lstrip("@").casefold()


def slugify(title: str) -> str:
    """A stable, readable key fragment for a task's title.

    Deterministic, so re-compiling an unchanged task lands on the row it already
    has rather than opening a second one beside it.
    """
    slug = _SLUG_STRIP.sub("-", title.casefold()).strip("-")[:SLUG_MAX].strip("-")
    return slug or "task"


def mint_episode_id() -> str:
    """A fresh episode id: the short half of a URN, and what a reader types."""
    return uuid.uuid4().hex[:8]


def mint_episode_urn(room: str) -> str:
    """A fresh episode URN over ``room``'s own channel."""
    return l9.episode_urn(room, mint_episode_id())


def short_id_of(episode: str) -> str:
    """The trailing short id of an episode URN."""
    return episode.rsplit(":", 1)[-1]


def episode_of(room: str, key: str) -> str | None:
    """The episode URN bound to a row, or ``None`` when it has no thread."""
    found = read_memory_file(get_room_dir(room), key)
    if found is None:
        return None
    return system_meta(found[0]).get(EPISODE_META)


def bound_episodes(room: str) -> set[str]:
    """Every episode URN some row in the room already carries.

    What tells a task's thread from an *orphaned* episode — one no row is bound
    to, which stays a row of its own rather than being hidden or deleted.
    """
    urns: set[str] = set()
    for _key, meta, _content in list_memory_files(get_room_dir(room)):
        urn = system_meta(meta).get(EPISODE_META)
        if isinstance(urn, str) and urn:
            urns.add(urn)
    return urns


@dataclass(frozen=True)
class ThreadRefusal:
    """Why a write into a named thread was refused, and how to answer it."""

    status: int
    detail: str


def known_episode(room: str, episode: str, *, transcript: Iterable[str] = ()) -> bool:
    """Whether ``episode`` is a thread this room actually has.

    Checked cheapest-first, because it runs on the write path: the URNs already
    on the room's in-memory transcript settle every thread that has ever been
    spoken in (a negotiation's, and an orphaned episode's, as well as a task's),
    and only a *first* write into a thread that is still silent falls through to
    the store scan — once per thread, not once per message. ``transcript`` is
    read newest-first and short-circuits, so recognising an active thread costs
    a handful of records rather than the whole history.
    """
    if episode in transcript:
        return True
    return episode in bound_episodes(room)


def episode_write_rejection(
    room: str,
    handle: str,
    episode: str | None,
    *,
    frozen_episode: str | None = None,
    frozen_members: Iterable[str] = (),
    transcript: Iterable[str] = (),
) -> ThreadRefusal | None:
    """Why ``handle`` may not write into ``episode``, or ``None`` if it may.

    Two refusals, and the difference between them is the whole model:

    A thread the room does not have is refused (404) — naming a URN must not be
    how one comes into being, or the transcript grows threads nobody opened.

    A thread that is a **frozen negotiation** is refused to anyone outside the
    roster it froze on (403). That is L9's stable-membership rule: an
    offer/counter exchange scored across a set of participants means nothing if
    an outsider can drop a position into it.

    A **container** — a task's thread — refuses neither, and that is
    deliberate rather than unfinished. Freezing membership is a negotiation's
    policy, not an episode's (:class:`~app.services.l9_slim.EpisodeLifecycle`):
    a task outlives what happens inside it, so an agent that claims a row after
    the thread opened must be able to speak in it.  The honest boundary: a task's
    thread is scoped to the room, not narrower.  Everyone who may write in the
    room may write in its threads — threads separate *attention*, not access, and
    the room's own guards (membership, principal, delegation) are what a write
    still has to pass.
    """
    if episode is None or l9.is_live_episode(room, episode):
        return None
    if not known_episode(room, episode, transcript=transcript):
        return ThreadRefusal(404, f"No thread {short_id_of(episode)!r} in room {room!r}")
    if episode == frozen_episode and _norm(handle) not in {_norm(m) for m in frozen_members}:
        return ThreadRefusal(
            403,
            f"@{handle} is not a member of the negotiation in thread {short_id_of(episode)!r}",
        )
    return None


def thread_write_refusal(room: str, handle: str, episode: str | None) -> ThreadRefusal | None:
    """:func:`episode_write_rejection`, read against the room's live channel state.

    The one call both write routes make, so ``/messages`` and ``/reply`` cannot
    grow separate ideas of who may speak in a thread. A room with no live channel
    has no negotiation to be outside of and no transcript to recognise a thread
    by, so the rule falls back to what the store knows.
    """
    if episode is None or l9.is_live_episode(room, episode):
        return None

    from app.services.room_channels import manager

    managed = manager.get(room)
    lifecycle = managed.lifecycle if managed is not None else None
    persister = managed.persister if managed is not None else None
    spoken: Iterable[str] = ()
    if persister is not None:
        from app.services.persister import record_episode

        # Newest-first and lazy: a thread being written into was almost certainly
        # spoken in recently, so the membership test stops within a few records.
        spoken = (urn for r in reversed(persister.log.records) if (urn := record_episode(r)))
    return episode_write_rejection(
        room,
        handle,
        episode,
        frozen_episode=(lifecycle.episode if lifecycle is not None and lifecycle.frozen else None),
        frozen_members=lifecycle.members if lifecycle is not None else (),
        transcript=spoken,
    )


async def bind_episode(room: str, key: str, *, episode: str | None = None) -> str:
    """Bind ``key`` to a thread, minting one unless it already has one.

    Idempotent: a row that is already bound keeps the URN it has, so a
    coordination step that binds on its way in is safe however often it is
    retried, and a second negotiation never moves a task's thread.
    """
    existing = episode_of(room, key)
    if existing:
        return existing
    found = read_memory_file(get_room_dir(room), key)
    if found is None:
        raise KeyError(key)
    meta, content = found
    urn = episode or mint_episode_urn(room)

    from app.routes.memory import _reconstruct_value, upsert_memories
    from app.schemas import MemoryBatchCreate, MemoryCreate

    await upsert_memories(
        room,
        MemoryBatchCreate(
            items=[
                MemoryCreate(
                    key=key,
                    value=_reconstruct_value(meta, content),
                    content_text=content or None,
                    # The prose is untouched, so the stored vector is carried
                    # forward rather than paying for an identical re-embed.
                    embed=False,
                    created_by=meta.get("updated_by")
                    or meta.get("created_by")
                    or l9.SYSTEM_ACTOR_ID,
                )
            ]
        ),
        system={EPISODE_META: urn},
    )
    return urn


async def create_task(
    room: str,
    title: str,
    *,
    created_by: str,
    key: str | None = None,
    meta: dict[str, Any] | None = None,
) -> MemoryRead:
    """Create a task board-first, with its thread already minted.

    The row comes first and any coordination inside it is optional, so putting
    something on the board takes no negotiation to converge first.
    """
    from app.routes.memory import upsert_memories
    from app.schemas import MemoryBatchCreate, MemoryCreate

    row_key = key or f"{WORK_NAMESPACE}/{slugify(title)}"
    fields: dict[str, Any] = {"kind": TASK_KIND, "status": "open", **(meta or {})}
    written = await upsert_memories(
        room,
        MemoryBatchCreate(
            items=[MemoryCreate(key=row_key, value=title, created_by=created_by, meta=fields)]
        ),
        system={EPISODE_META: mint_episode_urn(room)},
    )
    return written[0]


def backfill_room(room: str) -> int:
    """Mint a thread for every ``work/`` row that carries none, in place.

    Written straight to the file: minting a URN records where a row's thread
    *is*, so it must not bump the version, re-date ``updated_at`` or broadcast a
    write, which is what the upsert would do — announcing a change nobody made
    and shuffling every stale row to the top of a time-ordered board.  Returns
    how many rows were bound.
    """
    base = get_room_dir(room)
    bound = 0
    for key, meta, content in list_memory_files(base, prefix=f"{WORK_NAMESPACE}/"):
        if system_meta(meta).get(EPISODE_META):
            continue
        # Everything serialize_memory does not write from its own arguments,
        # timestamps included, so the URN is the only thing that changes.
        extra = {k: v for k, v in meta.items() if k not in _REWRITTEN_META}
        extra[EPISODE_META] = mint_episode_urn(room)
        (base / f"{key}.md").write_text(
            serialize_memory(
                content,
                key=meta.get("key", key),
                created_by=meta.get("created_by", l9.SYSTEM_ACTOR_ID),
                updated_by=meta.get("updated_by"),
                version=meta.get("version", 1),
                tags=meta.get("tags"),
                extra_meta=extra,
            ),
            encoding="utf-8",
        )
        bound += 1
    if bound:
        logger.info("bound %d pre-existing work row(s) in %s to a thread", bound, room)
    return bound
