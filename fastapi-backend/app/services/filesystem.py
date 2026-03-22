"""
Filesystem-native memory storage.

Rooms are folders. Memories are markdown files with YAML frontmatter.
The .mycelium/ directory is the source of truth for all shared context.
AgensGraph becomes the semantic search index, not the primary storage layer.

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

import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Sentinel for "no default" so we can distinguish None from missing
_MISSING = object()


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


def get_notebook_dir(handle: str) -> Path:
    """Get the directory for an agent's notebook, creating it if needed."""
    nb_dir = get_data_dir() / "notebooks" / handle
    nb_dir.mkdir(parents=True, exist_ok=True)
    return nb_dir


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
    scope: str = "namespace",
    owner_handle: str | None = None,
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
    if scope != "namespace":
        meta["scope"] = scope
    if owner_handle:
        meta["owner_handle"] = owner_handle
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
    scope: str = "namespace",
    owner_handle: str | None = None,
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
        scope=scope,
        owner_handle=owner_handle,
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

    results = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
            meta, content = parse_memory(text)
            key = _key_from_path(f, base_dir)
            results.append((key, meta, content))
        except Exception:
            logger.warning("Failed to read memory file: %s", f)

    # Sort by updated_at descending (newest first)
    def sort_key(item: tuple[str, dict[str, Any], str]) -> str:
        return item[1].get("updated_at", "")

    results.sort(key=sort_key, reverse=True)
    return results[:limit]


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
    """Ensure standard namespace subdirectories exist for a room."""
    for subdir in ("decisions", "failed", "status", "context", "work", "procedures", "log"):
        (room_dir / subdir).mkdir(parents=True, exist_ok=True)


def remove_room_dir(room_name: str) -> bool:
    """Remove a room's directory tree. Returns True if it existed."""
    import shutil

    room_dir = get_data_dir() / "rooms" / room_name
    if room_dir.exists():
        shutil.rmtree(room_dir)
        return True
    return False


def value_to_content(value: dict | str) -> str:
    """Convert a memory value (dict or string) to markdown content text."""
    if isinstance(value, str):
        return value
    # For dicts, extract "text" field if present, otherwise dump as YAML
    if "text" in value:
        return str(value["text"])
    return yaml.dump(value, default_flow_style=False, sort_keys=False).strip()
