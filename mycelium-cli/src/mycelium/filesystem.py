# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Memory file operations for the CLI.

Reads and writes markdown files in .mycelium/ directories.
Mirrors the backend's filesystem service for local access.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml


def get_mycelium_dir() -> Path:
    """Get the .mycelium data directory.

    Uses ~/.mycelium/, the same location the backend defaults to,
    so CLI and backend always share the same filesystem.
    """
    data_dir = Path.home() / ".mycelium"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_room_dir(room_name: str) -> Path:
    room_dir = get_mycelium_dir() / "rooms" / room_name
    room_dir.mkdir(parents=True, exist_ok=True)
    return room_dir


def get_users_dir() -> Path:
    """Get the global users store directory.

    People span rooms, so the user store is global (a sibling of ``rooms/``)
    rather than room-scoped like ``agents/``. Records live at
    ``~/.mycelium/users/<handle>.md``, same markdown+frontmatter format as any
    other memory entry.
    """
    users_dir = get_mycelium_dir() / "users"
    users_dir.mkdir(parents=True, exist_ok=True)
    return users_dir


def list_room_names() -> list[str]:
    rooms_root = get_mycelium_dir() / "rooms"
    if not rooms_root.is_dir():
        return []
    return sorted(p.name for p in rooms_root.iterdir() if p.is_dir())


def ensure_room_structure(room_dir: Path) -> None:
    for subdir in ("decisions", "failed", "status", "context", "work", "procedures", "log"):
        (room_dir / subdir).mkdir(parents=True, exist_ok=True)


# ── Markdown format ──────────────────────────────────────────────────────────


def serialize_memory(
    content: str,
    *,
    key: str,
    created_by: str,
    updated_by: str | None = None,
    version: int = 1,
    tags: list[str] | None = None,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
    extra_meta: dict[str, Any] | None = None,
) -> str:
    """Serialize a memory to markdown with YAML frontmatter."""
    now = datetime.now(UTC)
    meta: dict[str, Any] = {
        "key": key,
        "created_by": created_by,
        "version": version,
        "created_at": (created_at or now).isoformat(),
        "updated_at": (updated_at or now).isoformat(),
    }
    if updated_by:
        meta["updated_by"] = updated_by
    if tags:
        meta["tags"] = tags
    if extra_meta:
        meta.update(extra_meta)

    frontmatter = yaml.dump(meta, default_flow_style=False, sort_keys=False).strip()
    return f"---\n{frontmatter}\n---\n{content}\n"


def parse_timestamp(value: object) -> datetime | None:
    """Read a frontmatter timestamp back as a datetime, or ``None``.

    ``serialize_memory`` writes ``.isoformat()``, so YAML quotes the value and
    hands back a string; a hand-written or older file may carry a bare timestamp
    YAML parses as a datetime. A naive value is read as UTC so every stamp
    returned here is comparable with every other one.
    """
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def recover_updated_at(meta: dict[str, Any], path: Path) -> datetime:
    """When a memory was last written — from frontmatter, else the file's mtime.

    Read time is deliberately not a candidate, and neither is an empty sort key:
    the first re-dates the memory every time it is looked at, the second parks
    every unstamped memory at the bottom of the list regardless of its age.

    The CLI's counterpart to the backend's ``recover_timestamps``, holding the
    same never-read-time rule over a narrower surface: this store only orders
    memories, so it resolves one stamp where the backend resolves the
    ``(created_at, updated_at)`` pair a read model needs. Keep the rule in step
    across the two; the shapes differ on purpose.
    """
    stamp = parse_timestamp(meta.get("updated_at")) or parse_timestamp(meta.get("created_at"))
    if stamp is not None:
        return stamp
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    except OSError:
        return datetime(1970, 1, 1, tzinfo=UTC)


def parse_memory(text: str) -> tuple[dict[str, Any], str]:
    """Parse a markdown file into (frontmatter_dict, content_body)."""
    match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
    if not match:
        return {}, text.strip()
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        meta = {}
    return meta, match.group(2).strip()


# ── File operations ──────────────────────────────────────────────────────────


def write_memory(
    base_dir: Path,
    key: str,
    content: str,
    *,
    created_by: str,
    updated_by: str | None = None,
    version: int = 1,
    tags: list[str] | None = None,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> Path:
    """Write a memory as a markdown file."""
    filename = key + ".md" if not key.endswith(".md") else key
    file_path = base_dir / filename
    file_path.parent.mkdir(parents=True, exist_ok=True)

    text = serialize_memory(
        content,
        key=key,
        created_by=created_by,
        updated_by=updated_by,
        version=version,
        tags=tags,
        created_at=created_at,
        updated_at=updated_at,
    )
    file_path.write_text(text, encoding="utf-8")
    return file_path


def read_memory(base_dir: Path, key: str) -> tuple[dict[str, Any], str] | None:
    """Read a memory file. Returns (metadata, content) or None."""
    filename = key + ".md" if not key.endswith(".md") else key
    file_path = base_dir / filename
    if not file_path.exists():
        return None
    text = file_path.read_text(encoding="utf-8")
    return parse_memory(text)


# ── Knowledge sync ───────────────────────────────────────────────────────────
# The receiver half of the L9 ``knowledge`` write path: a connector applies a
# carried memory write into its local store. Mirrors the backend's
# ``app.services.memory_sync.apply_knowledge_to_dir``, kept as a tiny local copy
# because the CLI does not import the backend package. Conflict policy:
# last-write-wins by ``version``; a write on a stale base fails with
# details, no merge.


@dataclass
class KnowledgeApplyResult:
    """The outcome of applying a carried memory write to the local store."""

    key: str
    applied: bool
    conflict: bool
    reason: str
    version: int
    current: dict[str, Any] | None = None


def apply_knowledge(
    base_dir: Path,
    *,
    key: str,
    content: str,
    version: int,
    created_by: str = "system",
    updated_by: str = "system",
    updated_at: str | None = None,
) -> KnowledgeApplyResult:
    """Write a carried ``knowledge`` memory locally (last-write-wins).

    Idempotent when the local file is already at ``version`` (the same-machine
    loopback of a write the backend just made). A write whose ``version`` is
    behind the local file is a **stale base**: kept out, current state returned
    in ``current``, never merged.
    """
    existing = read_memory(base_dir, key)
    if existing is not None:
        meta, body = existing
        try:
            current_version = int(meta.get("version", 1))
        except (TypeError, ValueError):
            current_version = 1
        if version == current_version:
            return KnowledgeApplyResult(
                key=key,
                applied=False,
                conflict=False,
                reason="already at this version (idempotent)",
                version=version,
            )
        if version < current_version:
            return KnowledgeApplyResult(
                key=key,
                applied=False,
                conflict=True,
                reason="incoming version behind local",
                version=version,
                current={
                    "content": body,
                    "version": current_version,
                    "updated_by": meta.get("updated_by") or meta.get("created_by"),
                    "updated_at": meta.get("updated_at"),
                },
            )
    # Replicate the write's own ``updated_at`` where the message carries one,
    # rather than dating the memory to whenever this store caught up.
    written_at = parse_timestamp(updated_at)
    created_at = parse_timestamp(existing[0].get("created_at")) if existing else None
    write_memory(
        base_dir,
        key,
        content,
        created_by=created_by,
        updated_by=updated_by,
        version=version,
        created_at=created_at or written_at,
        updated_at=written_at,
    )
    return KnowledgeApplyResult(
        key=key, applied=True, conflict=False, reason="applied", version=version
    )


def list_memories(
    base_dir: Path,
    prefix: str | None = None,
    limit: int = 100,
) -> list[tuple[str, dict[str, Any], str]]:
    """List memory files. Returns list of (key, metadata, content)."""
    if not base_dir.exists():
        return []

    if prefix:
        search_dir = base_dir / prefix.rstrip("/")
        if search_dir.is_dir():
            files = list(search_dir.rglob("*.md"))
        else:
            files = []
    else:
        files = list(base_dir.rglob("*.md"))

    dated: list[tuple[datetime, tuple[str, dict[str, Any], str]]] = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
            meta, content = parse_memory(text)
            key = str(f.relative_to(base_dir))
            if key.endswith(".md"):
                key = key[:-3]
        except Exception:
            continue
        dated.append((recover_updated_at(meta, f), (key, meta, content)))

    dated.sort(key=lambda item: item[0], reverse=True)
    return [entry for _, entry in dated[:limit]]
