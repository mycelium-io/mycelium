# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Skills store — reusable, invokable skills as markdown with YAML frontmatter.

Same grain as memory (folders + markdown + frontmatter), but a distinct,
**global** (project-level) store: skills are reusable across rooms, so they live
at ``.mycelium/skills/<name>.md`` — a sibling of ``rooms/`` and ``users/`` — not
inside any room's memory tree. Keeping them out of the room dir is deliberate:
the memory index/listing walks a room's markdown wholesale, so a skill nested
there would leak into memory results.

A skill is prose (a SKILL.md-style body) plus frontmatter (``name``,
``description``). It is the backing store for the chat composer's ``/`` trigger
(reference a skill inline) and, later, agent-side invocation. The store does not
execute skills — that's the participation/engine layer's concern.

File format::

    ---
    name: summarize-room
    description: Condense the room's decisions into a short brief.
    created_by: julia
    version: 2
    tags: [reporting]
    created_at: 2026-08-16T10:00:00Z
    updated_at: 2026-08-16T11:00:00Z
    ---
    Read the room's decisions/ memories and produce a 5-bullet brief…
"""

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from app.services.filesystem import (
    get_data_dir,
    parse_memory,
)

logger = logging.getLogger(__name__)

# Frontmatter the store owns; everything else a caller supplies is carried
# forward as user data across rewrites (mirrors memory's MANAGED_META contract).
MANAGED_META = frozenset(
    {
        "name",
        "description",
        "created_by",
        "updated_by",
        "version",
        "created_at",
        "updated_at",
        "tags",
    }
)


def get_skills_dir() -> Path:
    """Get the global skills store directory, creating it if needed.

    Skills are reusable across rooms, so the store is global (a sibling of
    ``rooms/`` and ``users/``) rather than room-scoped.
    """
    skills_dir = get_data_dir() / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    return skills_dir


def _skill_path(name: str) -> Path:
    return get_skills_dir() / f"{name}.md"


def skill_exists(name: str) -> bool:
    """True if a skill with this name exists on disk."""
    return _skill_path(name).is_file()


def read_skill(name: str) -> tuple[dict[str, Any], str] | None:
    """Read a skill by name. Returns (frontmatter, body) or None if not found."""
    path = _skill_path(name)
    if not path.is_file():
        return None
    return parse_memory(path.read_text(encoding="utf-8"))


def list_skills() -> list[tuple[str, dict[str, Any], str]]:
    """List all skills as (name, frontmatter, body), newest-updated first."""
    skills_dir = get_skills_dir()
    results: list[tuple[str, dict[str, Any], str]] = []
    for f in skills_dir.glob("*.md"):
        try:
            meta, body = parse_memory(f.read_text(encoding="utf-8"))
            results.append((f.stem, meta, body))
        except OSError:
            logger.warning("Failed to read skill file: %s", f)
    results.sort(key=lambda item: item[1].get("updated_at", ""), reverse=True)
    return results


def write_skill(
    name: str,
    body: str,
    *,
    description: str,
    created_by: str,
    tags: list[str] | None = None,
    extra_meta: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str]:
    """Create or upsert a skill. Returns the resulting (frontmatter, body).

    Upsert semantics mirror memory: an existing skill keeps its original author
    and creation time, bumps ``version``, and preserves unmanaged frontmatter.
    """
    now = datetime.now(UTC)
    existing = read_skill(name)
    existing_meta = existing[0] if existing else {}

    if existing:
        version = existing_meta.get("version", 1) + 1
        author = existing_meta.get("created_by", created_by)
        created_at = existing_meta.get("created_at", now.isoformat())
    else:
        version = 1
        author = created_by
        created_at = now.isoformat()

    carried = {k: v for k, v in existing_meta.items() if k not in MANAGED_META}
    if extra_meta:
        carried.update({k: v for k, v in extra_meta.items() if k not in MANAGED_META})

    meta: dict[str, Any] = {
        "name": name,
        "description": description,
        "created_by": author,
        "updated_by": created_by,
        "version": version,
        "created_at": created_at if isinstance(created_at, str) else created_at.isoformat(),
        "updated_at": now.isoformat(),
    }
    if tags:
        meta["tags"] = tags
    meta.update(carried)

    frontmatter = yaml.dump(meta, default_flow_style=False, sort_keys=False).strip()
    text = f"---\n{frontmatter}\n---\n{body}\n"
    path = _skill_path(name)
    path.write_text(text, encoding="utf-8")
    logger.debug("Wrote skill file: %s", path)
    return parse_memory(text)


def delete_skill(name: str) -> bool:
    """Delete a skill by name. Returns True if it existed."""
    path = _skill_path(name)
    if path.is_file():
        path.unlink()
        return True
    return False
