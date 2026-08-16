# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Skills — a promoted view over the ``skills/`` memory namespace (#617).

A skill is just a memory: markdown + frontmatter at
``.mycelium/rooms/{room}/skills/{name}.md``. The store is uniform — the same way
``agents/<handle>`` memories are promoted into an Agents panel and ``decisions/``
memories into a category view, the ``skills/`` namespace is promoted into a
skills surface (``mycelium skill``, ``/api/rooms/{room}/skills``, the Skills
rail). There is no separate store: a skill is reachable as a memory too, by
design.

The only skill-specific bit is the frontmatter ``description`` (a one-line
summary), which rides in the memory's user-managed meta. The skill *body* is the
memory content; the skill *name* is the memory key with the ``skills/`` prefix
stripped.
"""

from typing import Any

from app.services.filesystem import (
    get_room_dir,
    list_memory_files,
    read_memory_file,
)

# The memory namespace promoted into skills. A slash-terminated prefix so it
# matches list_memory_files' subdirectory search.
SKILLS_PREFIX = "skills/"


def skill_key(name: str) -> str:
    """The memory key backing a skill (``summarize`` → ``skills/summarize``)."""
    return f"{SKILLS_PREFIX}{name}"


def name_from_key(key: str) -> str:
    """The skill name from its memory key (``skills/summarize`` → ``summarize``)."""
    return key[len(SKILLS_PREFIX) :] if key.startswith(SKILLS_PREFIX) else key


def list_room_skills(room_name: str) -> list[tuple[str, dict[str, Any], str]]:
    """List a room's skills as (name, frontmatter, body), newest-updated first."""
    room_dir = get_room_dir(room_name)
    entries = list_memory_files(room_dir, prefix=SKILLS_PREFIX)
    return [(name_from_key(key), meta, body) for key, meta, body in entries]


def read_room_skill(room_name: str, name: str) -> tuple[dict[str, Any], str] | None:
    """Read one skill by name. Returns (frontmatter, body) or None if absent."""
    return read_memory_file(get_room_dir(room_name), skill_key(name))
