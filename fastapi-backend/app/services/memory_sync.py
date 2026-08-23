# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Memory sync over SLIM — the L9 ``knowledge`` write path.

Memory content is canonical markdown; the JSONL index is derived. Cross-machine
sync is **not** git: an L9 ``knowledge`` message **carries the content** so a
running agent's working set updates mid-task (the one thing git can't stream).
This module owns both halves of that seam:

1. **Emit** — :func:`build_knowledge_envelope` wraps a :class:`KnowledgeWrite`
   (key + markdown body + version metadata) as a ``knowledge`` envelope
   broadcast on the room channel. Converged content (the compiled plan) flows
   out ``knowledge:distillation`` (see :mod:`app.services.task_sync`); a direct
   ``memory set`` write flows out ``knowledge:extraction`` (see
   ``app.routes.memory.create_memories``) — same shape, distinct subkind.

2. **Apply** — :func:`apply_knowledge` writes the carried markdown into a local
   store and reindexes the JSONL. It is the receiver half every connector runs
   (:mod:`mycelium.daemon.connector` mirrors it CLI-side) and the backend runs
   for knowledge authored elsewhere.

**Conflict policy: last-write-wins, no merge handler.**
Order by ``version``. An arriving write is *idempotent* when the local file is
already at its version (the same-machine loopback of a write the backend just
made). A write built on a **stale base** — its version is behind the local
file — **fails with details** (current content + ``updated_by`` + ``updated_at``)
and moves on; no reconciliation is attempted.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.services import l9
from app.services.l9_models import Kind

if TYPE_CHECKING:
    from app.services.l9_models import L9

logger = logging.getLogger(__name__)

# The ``knowledge`` subkinds a memory-sync write rides as (both from the
# SLIM-native subkind table, l9.VALID_SUBKINDS). ``distillation`` is converged
# content distilled to a shareable artifact — the compiled plan
# (:mod:`app.services.task_sync`). ``extraction`` is a raw ``memory set`` write
# broadcast as-is, with no negotiation behind it — kept distinct so a reader
# can tell "the room agreed to this" from "someone just wrote this".
KNOWLEDGE_SUBKIND = "distillation"
MEMORY_WRITE_SUBKIND = "extraction"


@dataclass
class KnowledgeWrite:
    """One memory write carried on a ``knowledge`` message (push-with-content).

    ``version`` is this write's new version; ``base_version`` is the version the
    writer read before editing (``None`` for a create). The receiver compares
    ``version`` against its own file to order writes and detect a stale base.
    """

    key: str
    content: str
    version: int
    created_by: str
    updated_by: str
    updated_at: str
    base_version: int | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "content": self.content,
            "version": self.version,
            "base_version": self.base_version,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> KnowledgeWrite | None:
        """Parse a ``knowledge`` payload into a write, or ``None`` if malformed."""
        key = data.get("key")
        content = data.get("content")
        if not isinstance(key, str) or not key or not isinstance(content, str):
            return None
        try:
            version = int(data.get("version", 1))
        except (TypeError, ValueError):
            version = 1
        base_version_raw = data.get("base_version")
        base_version: int | None
        try:
            base_version = int(base_version_raw) if base_version_raw is not None else None
        except (TypeError, ValueError):
            base_version = None
        actor = str(data.get("updated_by") or data.get("created_by") or l9.SYSTEM_ACTOR_ID)
        return cls(
            key=key,
            content=content,
            version=version,
            created_by=str(data.get("created_by") or actor),
            updated_by=actor,
            updated_at=str(data.get("updated_at") or datetime.now(UTC).isoformat()),
            base_version=base_version,
        )


def knowledge_write_from_envelope(envelope: L9) -> KnowledgeWrite | None:
    """Extract the :class:`KnowledgeWrite` an envelope carries, or ``None``."""
    payload = envelope.payload
    if payload is None or not isinstance(payload.data, dict):
        return None
    return KnowledgeWrite.from_payload(payload.data)


def is_knowledge(envelope: L9) -> bool:
    """True for a ``knowledge`` envelope (the memory-sync write trigger)."""
    return envelope.header.kind == Kind.knowledge


def build_knowledge_envelope(
    *,
    room: str,
    write: KnowledgeWrite,
    recipients: list[str],
    subkind: str = KNOWLEDGE_SUBKIND,
) -> L9:
    """Build the ``knowledge`` envelope that carries ``write``.

    Broadcast on the room channel; every connector applies it locally. Emitted
    with empty causal parents — like the aligner's terminal verdict, a broadcast
    memory push must be releasable by every member regardless of what each has
    seen (the rich causal chain stays in the episode record). ``subkind``
    defaults to the converged-plan shape (:data:`KNOWLEDGE_SUBKIND`); a raw
    ``memory set`` write passes :data:`MEMORY_WRITE_SUBKIND` instead. The
    payload's ``type`` always mirrors ``subkind`` so a reader can tell the two
    apart without unpacking ``data``.
    """
    return l9.build_envelope(
        kind=Kind.knowledge,
        subkind=subkind,
        episode=l9.episode_urn(room, "knowledge"),
        recipients=recipients,
        topic=l9.topic_urn(room),
        payload_type=subkind,
        payload_data=write.to_payload(),
    )


@dataclass
class ApplyResult:
    """The outcome of applying a :class:`KnowledgeWrite` to a local store."""

    key: str
    applied: bool
    conflict: bool
    reason: str
    version: int
    # On a conflict, the current local state that the stale write lost to.
    current: dict[str, Any] | None = None

    def format_conflict(self) -> str:
        """A one-line, log-ready description of a stale-base rejection."""
        cur = self.current or {}
        return (
            f"stale-base write to {self.key!r} rejected: local v{cur.get('version')} "
            f"by {cur.get('updated_by')!r} at {cur.get('updated_at')} "
            f"(incoming v{self.version}); {self.reason}"
        )


def apply_knowledge_to_dir(base_dir: Any, write: KnowledgeWrite) -> ApplyResult:
    """Apply ``write`` to a room dir (last-write-wins). No reindex — pure file IO.

    Split out from :func:`apply_knowledge` so the conflict logic is unit-testable
    against an arbitrary directory without touching the configured data dir or
    the (heavier) index. Returns an :class:`ApplyResult`; never raises on a
    conflict — a stale-base write is a *result*, not an error.
    """
    from app.services.filesystem import parse_timestamp, read_memory_file, write_memory_file

    existing = read_memory_file(base_dir, write.key)
    if existing is not None:
        meta, body = existing
        try:
            current_version = int(meta.get("version", 1))
        except (TypeError, ValueError):
            current_version = 1
        if write.version == current_version:
            # The write we already hold looped back (same-machine emit → apply).
            return ApplyResult(
                key=write.key,
                applied=False,
                conflict=False,
                reason="already at this version (idempotent)",
                version=write.version,
            )
        if write.version < current_version:
            # Built on a base behind the local file: last-write-wins keeps the
            # newer local content; surface the loss with details, do not merge.
            return ApplyResult(
                key=write.key,
                applied=False,
                conflict=True,
                reason="incoming version behind local",
                version=write.version,
                current={
                    "content": body,
                    "version": current_version,
                    "updated_by": meta.get("updated_by") or meta.get("created_by"),
                    "updated_at": meta.get("updated_at"),
                },
            )

    # Replicate the write's own timestamps rather than the applier's clock: a
    # knowledge message carries when the write happened, so stamping it "now"
    # re-dates every synced memory to whenever this store caught up — a restart
    # re-serving a backlog would land the lot at one instant. ``created_at``
    # stays whatever the local file already had; this is an update.
    written_at = parse_timestamp(write.updated_at)
    created_at = parse_timestamp(existing[0].get("created_at")) if existing else None
    write_memory_file(
        base_dir,
        write.key,
        write.content,
        created_by=write.created_by,
        updated_by=write.updated_by,
        version=write.version,
        created_at=created_at or written_at,
        updated_at=written_at,
    )
    return ApplyResult(
        key=write.key,
        applied=True,
        conflict=False,
        reason="applied",
        version=write.version,
    )


async def apply_knowledge(room: str, write: KnowledgeWrite, *, reindex: bool = True) -> ApplyResult:
    """Apply ``write`` to the room's local store and reindex the JSONL.

    The receiver half of the ``knowledge`` seam: writes the carried markdown into
    the configured data dir (so a *second* store is simulated by pointing
    ``MYCELIUM_DATA_DIR`` at it) and, on a real write, updates the search index
    the normal single-file way. A stale-base rejection is logged, not raised.
    """
    from app.services.filesystem import get_room_dir

    result = apply_knowledge_to_dir(get_room_dir(room), write)
    if result.conflict:
        logger.warning("%s", result.format_conflict())
        return result
    if result.applied and reindex:
        try:
            from app.services.indexer import index_single_file

            await index_single_file(room, write.key)
        except Exception:
            logger.exception("reindex after knowledge write failed for %s/%s", room, write.key)
    return result
