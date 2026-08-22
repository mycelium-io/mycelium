# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Memory storage — markdown files with YAML frontmatter.

File format:
    ---
    key: decisions/db
    created_by: agent-a
    updated_by: agent-b
    version: 2
    tags: [backend, database]
    created_at: 2026-03-22T10:00:00Z
    updated_at: 2026-03-22T11:00:00Z
    ---
    PostgreSQL chosen for graph+SQL+vector support.
"""

import json
import logging
import re
import zlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Room metadata sidecar. Rooms are folders; this file holds room attributes
# (description, visibility, creation time) not derivable from memory files.
# read_room_meta synthesizes defaults when the sidecar is missing.
ROOM_META_FILENAME = ".room.json"

# Sentinel for "no default" so we can distinguish None from missing
_MISSING = object()

# Last-resort stamp for a memory with no recoverable time (see recover_timestamps).
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def get_data_dir() -> Path:
    """Get the .mycelium data directory, creating it if needed."""
    from app.config import settings

    data_dir = Path(settings.MYCELIUM_DATA_DIR)
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_room_dir(room_name: str) -> Path:
    """Get the directory for a room, creating it if needed."""
    room_dir = get_data_dir() / "rooms" / room_name
    room_dir.mkdir(parents=True, exist_ok=True)
    return room_dir


def get_users_dir() -> Path:
    """Get the global users store directory, creating it if needed.

    People span rooms, so the user store is global (a sibling of ``rooms/``)
    rather than room-scoped like ``agents/``. Records are the same
    markdown+frontmatter format as any memory, at ``users/<handle>.md``.
    """
    users_dir = get_data_dir() / "users"
    users_dir.mkdir(parents=True, exist_ok=True)
    return users_dir


def _sanitize_filename(key: str) -> str:
    """Convert a memory key to a safe filename.

    Keys like 'decisions/db' become 'decisions/db.md'.
    Keys already ending in .md are left as-is.
    """
    if not key.endswith(".md"):
        key = key + ".md"
    return key


def _key_from_path(file_path: Path, base_dir: Path) -> str:
    """Extract a memory key from a file path relative to the base directory."""
    rel = file_path.relative_to(base_dir)
    key = str(rel)
    if key.endswith(".md"):
        key = key[:-3]
    return key


# ── Markdown format ──────────────────────────────────────────────────────────


def parse_timestamp(value: object) -> datetime | None:
    """Read a frontmatter timestamp back as a datetime, or ``None``.

    ``serialize_memory`` writes timestamps with ``.isoformat()``, so YAML quotes
    them and returns a string on the next read. Hand-written or older files may
    carry a bare timestamp that YAML parses as a datetime, hence both branches.
    A naive value is read as UTC, so every stamp this returns is comparable with
    every other one — a mixed list of aware and naive stamps raises on sort.
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


def _file_mtime(path: Path | None) -> datetime | None:
    """``path``'s modification time as an aware UTC datetime, or ``None``."""
    if path is None:
        return None
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    except OSError:
        return None


def recover_timestamps(meta: dict[str, Any], path: Path | None = None) -> tuple[datetime, datetime]:
    """A memory's ``(created_at, updated_at)``, recovered — never invented.

    Frontmatter first; then the other stamp; then the file's mtime; only an
    unreadable file with no stamps at all falls back to the epoch. Read time is
    not a candidate: "now" is always the newest value there is, so substituting
    it re-dates the memory on every read and pins it to whichever end of a
    time-sorted list "newest" lands on.
    """
    created = parse_timestamp(meta.get("created_at"))
    updated = parse_timestamp(meta.get("updated_at"))
    if created is None or updated is None:
        mtime = _file_mtime(path)
        created = created or updated or mtime or _EPOCH
        if updated is None:
            # A restore or `cp -p` can leave an mtime behind the created stamp;
            # never report a memory as last updated before it existed.
            updated = max(mtime, created) if mtime else created
    return created, updated


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


def parse_memory(text: str) -> tuple[dict[str, Any], str]:
    """Parse a markdown file into (frontmatter_dict, content_body).

    Returns ({}, content) if no frontmatter is found.
    """
    match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
    if not match:
        return {}, text.strip()
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        meta = {}
    return meta, match.group(2).strip()


# ── File operations ──────────────────────────────────────────────────────────


def write_memory_file(
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
    extra_meta: dict[str, Any] | None = None,
) -> Path:
    """Write a memory as a markdown file. Creates parent directories as needed."""
    filename = _sanitize_filename(key)
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
        extra_meta=extra_meta,
    )
    file_path.write_text(text, encoding="utf-8")
    logger.debug("Wrote memory file: %s", file_path)
    return file_path


def read_memory_file(base_dir: Path, key: str) -> tuple[dict[str, Any], str] | None:
    """Read a memory file by key. Returns (metadata, content) or None if not found."""
    filename = _sanitize_filename(key)
    file_path = base_dir / filename
    if not file_path.exists():
        return None
    text = file_path.read_text(encoding="utf-8")
    return parse_memory(text)


def delete_memory_file(base_dir: Path, key: str) -> bool:
    """Delete a memory file by key. Returns True if the file existed."""
    filename = _sanitize_filename(key)
    file_path = base_dir / filename
    if file_path.exists():
        file_path.unlink()
        # Clean up empty parent directories
        _cleanup_empty_dirs(file_path.parent, base_dir)
        return True
    return False


def list_memory_files(
    base_dir: Path,
    prefix: str | None = None,
    limit: int = 1000,
) -> list[tuple[str, dict[str, Any], str]]:
    """List memory files, optionally filtered by key prefix.

    Returns list of (key, metadata, content) tuples, sorted by updated_at desc.
    """
    if not base_dir.exists():
        return []

    if prefix:
        # Prefix might be "decisions/" — search in that subdirectory
        search_dir = base_dir / prefix.rstrip("/")
        if search_dir.is_dir():
            files = list(search_dir.rglob("*.md"))
        else:
            # Could be partial prefix like "dec" — search parent
            parent = base_dir / Path(prefix).parent if "/" in prefix else base_dir
            pattern = Path(prefix).name + "*.md"
            files = list(parent.glob(pattern)) if parent.exists() else []
    else:
        files = list(base_dir.rglob("*.md"))

    dated: list[tuple[datetime, tuple[str, dict[str, Any], str]]] = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
            meta, content = parse_memory(text)
            key = _key_from_path(f, base_dir)
        except Exception:
            logger.warning("Failed to read memory file: %s", f)
            continue
        # Normalize the stamps into the meta every caller reads, so a file
        # missing one (or carrying a bare timestamp YAML hands back as a
        # datetime rather than a string) can neither sort to an end it doesn't
        # belong at nor raise comparing a str against a datetime.
        created, updated = recover_timestamps(meta, f)
        meta["created_at"] = created.isoformat()
        meta["updated_at"] = updated.isoformat()
        dated.append((updated, (key, meta, content)))

    dated.sort(key=lambda item: item[0], reverse=True)
    return [entry for _, entry in dated[:limit]]


def _cleanup_empty_dirs(directory: Path, stop_at: Path) -> None:
    """Remove empty directories up the tree, stopping at stop_at."""
    current = directory
    while current != stop_at and current.is_dir():
        try:
            current.rmdir()  # Only succeeds if empty
            current = current.parent
        except OSError:
            break


def ensure_room_structure(room_dir: Path) -> None:
    """Ensure standard namespace subdirectories exist for a room.

    These are the structured *memory* namespaces. Note agents/ is excluded
    from embedding (it's room storage, not a knowledge surface) and created
    lazily by ``mycelium agent create`` rather than pre-seeded here.
    """
    for subdir in (
        "decisions",
        "failed",
        "status",
        "context",
        "work",
        "procedures",
        "log",
        "plan",
    ):
        (room_dir / subdir).mkdir(parents=True, exist_ok=True)


def remove_room_dir(room_name: str) -> bool:
    """Remove a room's directory tree and any session sub-room directories.

    Session sub-rooms follow the pattern ``{room_name}:session:*`` and are
    stored as sibling directories alongside the parent room directory.  They
    are orphaned when the parent is deleted, so we clean them up here too.

    Returns True if the primary room directory existed.
    """
    import shutil

    rooms_dir = get_data_dir() / "rooms"
    room_dir = rooms_dir / room_name
    existed = room_dir.exists()
    if existed:
        shutil.rmtree(room_dir)

    # Remove session sub-rooms: same-prefix directories with ":session:" suffix.
    prefix = room_name + ":session:"
    if rooms_dir.exists():
        for child in list(rooms_dir.iterdir()):
            if child.is_dir() and child.name.startswith(prefix):
                shutil.rmtree(child)

    return existed


def _is_session_dir(name: str) -> bool:
    """Coordination-session sub-rooms follow ``{parent}:session:{short}``."""
    return ":session:" in name


def room_id(room_name: str) -> int:
    """Stable positive int id for a room, derived from its name via CRC32.

    The frontend keys rooms by name, not id.
    """
    return zlib.crc32(room_name.encode()) & 0x7FFFFFFF


def room_exists(room_name: str) -> bool:
    """True if the room's directory exists on disk."""
    return (get_data_dir() / "rooms" / room_name).is_dir()


def list_room_names() -> list[str]:
    """Names of all real rooms (excludes coordination-session sub-rooms)."""
    rooms_dir = get_data_dir() / "rooms"
    if not rooms_dir.exists():
        return []
    return sorted(
        child.name
        for child in rooms_dir.iterdir()
        if child.is_dir() and not _is_session_dir(child.name)
    )


def write_room_meta(room_name: str, meta: dict[str, Any]) -> None:
    """Persist a room's metadata sidecar (``.room.json``)."""
    room_dir = get_room_dir(room_name)
    (room_dir / ROOM_META_FILENAME).write_text(
        json.dumps(meta, default=str, indent=2), encoding="utf-8"
    )


def read_room_meta(room_name: str) -> dict[str, Any] | None:
    """Read a room's metadata, or None if the room directory doesn't exist.

    Synthesizes sensible defaults when the sidecar is missing (a room dir that
    predates the sidecar): creation time from the directory mtime, public and
    persistent by default.
    """
    room_dir = get_data_dir() / "rooms" / room_name
    if not room_dir.is_dir():
        return None

    meta_path = room_dir / ROOM_META_FILENAME
    stored: dict[str, Any] = {}
    if meta_path.exists():
        try:
            stored = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("Malformed room meta for %s; using defaults", room_name)

    created_at = stored.get("created_at")
    if not created_at:
        # A room dir predating the sidecar. Prefer the sidecar's own mtime (stable
        # — written once at creation); fall back to the dir mtime only when there's
        # no sidecar at all. The dir mtime bumps whenever a child file changes (the
        # search index rewrites on startup), so on its own it drifts to "just now"
        # on every restart.
        fallback_path = meta_path if meta_path.exists() else room_dir
        created_at = datetime.fromtimestamp(fallback_path.stat().st_mtime, tz=UTC).isoformat()

    return {
        "id": room_id(room_name),
        "name": room_name,
        "description": stored.get("description"),
        "is_public": stored.get("is_public", True),
        "is_persistent": stored.get("is_persistent", True),
        "mas_id": stored.get("mas_id"),
        "workspace_id": stored.get("workspace_id"),
        "created_at": created_at,
    }


def value_to_content(value: dict | str) -> str:
    """Convert a memory value (dict or string) to markdown content text."""
    if isinstance(value, str):
        return value
    # For dicts, extract "text" field if present, otherwise dump as YAML
    if "text" in value:
        return str(value["text"])
    return yaml.dump(value, default_flow_style=False, sort_keys=False).strip()
