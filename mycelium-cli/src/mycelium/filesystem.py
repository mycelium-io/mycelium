"""
Memory file operations for the CLI.

Reads and writes markdown files in .mycelium/ directories.
Mirrors the backend's filesystem service for local access.
"""

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml


def get_mycelium_dir() -> Path:
    """Get the .mycelium data directory.

    Uses ~/.mycelium/ — the same location the backend defaults to,
    so CLI and backend always share the same filesystem.
    """
    data_dir = Path.home() / ".mycelium"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_room_dir(room_name: str) -> Path:
    """Get the directory for a room."""
    room_dir = get_mycelium_dir() / "rooms" / room_name
    room_dir.mkdir(parents=True, exist_ok=True)
    return room_dir


def get_notebook_dir(handle: str) -> Path:
    """Get the directory for an agent's notebook."""
    nb_dir = get_mycelium_dir() / "notebooks" / handle
    nb_dir.mkdir(parents=True, exist_ok=True)
    return nb_dir


def ensure_room_structure(room_dir: Path) -> None:
    """Create standard namespace subdirectories."""
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

    frontmatter = yaml.dump(meta, default_flow_style=False, sort_keys=False).strip()
    return f"---\n{frontmatter}\n---\n{content}\n"


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


def delete_memory(base_dir: Path, key: str) -> bool:
    """Delete a memory file. Returns True if existed."""
    filename = key + ".md" if not key.endswith(".md") else key
    file_path = base_dir / filename
    if file_path.exists():
        file_path.unlink()
        return True
    return False


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

    results = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
            meta, content = parse_memory(text)
            key = str(f.relative_to(base_dir))
            if key.endswith(".md"):
                key = key[:-3]
            results.append((key, meta, content))
        except Exception:
            pass

    # Sort by updated_at descending
    results.sort(key=lambda x: x[1].get("updated_at", ""), reverse=True)
    return results[:limit]
