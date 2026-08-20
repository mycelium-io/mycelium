# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Memory linking — ``myc://`` / ``[[…]]`` / ``![[…]]`` parsing, JSONL link index,
resolution, and transclusion (depth 1, ``expandable: true`` only).

Four link forms, all resolved through one parser::

    myc://decisions/db              canonical URI (also inside [label](myc://…))
    [[decisions/db]]                shorthand, equivalent to the URI form
    [[decisions/db#tradeoffs|why]]  section anchor + display label
    ![[glossary/vector-store]]      transclusion — embeds the target inline

plus typed frontmatter relations (``supersedes:``, ``depends-on:``,
``part-of:``, ``relates-to:``).

Transclusion requires ``expandable: true`` on the target; expansion is depth 1.

The ``.link-index.jsonl`` sits beside the embedding index: derived from the
markdown, rebuildable, upserted on every write. Persisted so inbound lookups
need not reparse the room.

Links are room-local. ``myc://rooms/{other}/{key}`` parses, but resolves to a
``cross_room`` error.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.filesystem import get_data_dir, list_memory_files

logger = logging.getLogger(__name__)

INDEX_FILENAME = ".link-index.jsonl"

# Frontmatter flag gating whether a memory may be pulled into other pages.
EXPANDABLE_FLAG = "expandable"

# Frontmatter keys read as typed ontology edges. Each value is a key, a
# myc:// URI, or a list of either.
RELATION_KEYS = ("supersedes", "superseded-by", "depends-on", "part-of", "relates-to")

# Link kinds, in the `kind` field of a stored edge.
KIND_URI = "uri"
KIND_WIKILINK = "wikilink"
KIND_TRANSCLUSION = "transclusion"
KIND_RELATION = "relation"

# Integrity error codes carried on a resolved link.
ERR_CROSS_ROOM = "cross_room"
ERR_NOT_FOUND = "not_found"
ERR_NO_ANCHOR = "no_anchor"
ERR_NOT_EXPANDABLE = "not_expandable"

_TRANSCLUSION_RE = re.compile(r"!\[\[([^\]\n]+)\]\]")
_WIKILINK_RE = re.compile(r"(?<!!)\[\[([^\]\n]+)\]\]")
# A bare URI in prose ends at sentence punctuation: `see myc://decisions/db.`
# targets `decisions/db`, not `decisions/db.`.
_URI_RE = re.compile(r"myc://([^\s)\]>\"'`]*[^\s)\]>\"'`.,;:!?])")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)

# `[[mycelium: confidence=0.85 stance=accept]]` is an existing directive syntax in
# the agent skill, not a link. A word followed by a colon *and whitespace* is a
# directive; memory keys never contain ": ".
_DIRECTIVE_RE = re.compile(r"^[A-Za-z][\w-]*:\s")

# Fenced code blocks and inline code are prose about links, not links.
_FENCE_RE = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")


@dataclass(frozen=True)
class Link:
    """One outbound edge from a memory."""

    target: str
    kind: str
    anchor: str | None = None
    label: str | None = None
    relation: str | None = None
    raw: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ResolvedLink:
    """An edge plus what it resolves to right now."""

    target: str
    kind: str
    anchor: str | None = None
    label: str | None = None
    relation: str | None = None
    raw: str = ""
    source: str | None = None
    resolved: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Expansion:
    """The outcome of one ``![[…]]`` marker in a body."""

    target: str
    anchor: str | None = None
    raw: str = ""
    expanded: bool = False
    error: str | None = None


@dataclass
class MemoryLinks:
    """A memory's parsed link state, as stored on one index line."""

    key: str
    links: list[Link] = field(default_factory=list)
    headings: list[str] = field(default_factory=list)
    expandable: bool = False


# ── Parsing ──────────────────────────────────────────────────────────────────


def slugify_heading(text: str) -> str:
    """Slugify a markdown heading into an anchor (GitHub-style)."""
    slug = re.sub(r"[^\w\s-]", "", text.strip().lower())
    return re.sub(r"[\s_]+", "-", slug).strip("-")


def headings_of(body: str) -> list[str]:
    """Anchor slugs for every heading in a markdown body, in document order."""
    return [slugify_heading(match.group(2)) for match in _HEADING_RE.finditer(body)]


def normalize_key(target: str) -> str:
    """Normalize a link target to a memory key.

    Strips a ``myc://`` scheme, leading ``./`` or ``/``, and a trailing ``.md``
    so ``myc://decisions/db.md`` and ``decisions/db`` are one key.
    """
    target = target.strip()
    if target.startswith("myc://"):
        target = target[len("myc://") :]
    target = target.lstrip("/")
    if target.startswith("./"):
        target = target[2:]
    if target.endswith(".md"):
        target = target[: -len(".md")]
    return target.rstrip("/")


def _split_target(inner: str) -> tuple[str, str | None, str | None]:
    """Split ``key#anchor|label`` into its three parts."""
    label: str | None = None
    if "|" in inner:
        inner, _, label_part = inner.partition("|")
        label = label_part.strip() or None
    anchor: str | None = None
    if "#" in inner:
        inner, _, anchor_part = inner.partition("#")
        anchor = slugify_heading(anchor_part) or None
    return inner.strip(), anchor, label


def _make_link(inner: str, *, kind: str, raw: str, relation: str | None = None) -> Link | None:
    """Build a Link from a link body, or None if it isn't one."""
    if not inner.strip() or _DIRECTIVE_RE.match(inner.strip()):
        return None
    target, anchor, label = _split_target(inner)
    key = normalize_key(target)
    if not key:
        return None
    # Same-room only: the cross-room form parses so it can be reported, not resolved.
    error = ERR_CROSS_ROOM if key == "rooms" or key.startswith("rooms/") else None
    return Link(
        target=key, kind=kind, anchor=anchor, label=label, relation=relation, raw=raw, error=error
    )


def _strip_code(body: str) -> str:
    """Blank out code spans/blocks, preserving offsets so nothing else shifts."""
    body = _FENCE_RE.sub(lambda m: " " * len(m.group(0)), body)
    return _INLINE_CODE_RE.sub(lambda m: " " * len(m.group(0)), body)


def _code_span_ranges(body: str) -> list[tuple[int, int]]:
    """Start/end offsets of fenced code blocks and inline code spans.

    Code-span ranges so ``expand`` skips markers inside fenced or inline code,
    like ``parse_body_links`` does via ``_strip_code``.
    """
    ranges = [m.span() for m in _FENCE_RE.finditer(body)]
    ranges += [m.span() for m in _INLINE_CODE_RE.finditer(body)]
    return ranges


def _in_code_span(pos: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= pos < end for start, end in ranges)


def parse_body_links(body: str) -> list[Link]:
    """Extract every link in a markdown body, in document order."""
    scannable = _strip_code(body)
    found: list[tuple[int, Link]] = []
    seen_spans: list[tuple[int, int]] = []

    for match in _TRANSCLUSION_RE.finditer(scannable):
        link = _make_link(match.group(1), kind=KIND_TRANSCLUSION, raw=match.group(0))
        if link is not None:
            found.append((match.start(), link))
        seen_spans.append(match.span())

    for match in _WIKILINK_RE.finditer(scannable):
        link = _make_link(match.group(1), kind=KIND_WIKILINK, raw=match.group(0))
        if link is not None:
            found.append((match.start(), link))
        seen_spans.append(match.span())

    # A myc:// URI inside a wikilink we already captured isn't a second edge.
    for match in _URI_RE.finditer(scannable):
        if any(start <= match.start() < end for start, end in seen_spans):
            continue
        link = _make_link(match.group(1), kind=KIND_URI, raw=match.group(0))
        if link is not None:
            found.append((match.start(), link))

    found.sort(key=lambda item: item[0])
    return [link for _, link in found]


def parse_relation_links(meta: dict[str, Any]) -> list[Link]:
    """Extract typed ontology edges from frontmatter relation keys."""
    links: list[Link] = []
    for relation in RELATION_KEYS:
        raw_value = meta.get(relation)
        if raw_value is None:
            continue
        values = raw_value if isinstance(raw_value, list) else [raw_value]
        for value in values:
            if not isinstance(value, str):
                continue
            link = _make_link(
                value, kind=KIND_RELATION, raw=f"{relation}: {value}", relation=relation
            )
            if link is not None:
                links.append(link)
    return links


def is_expandable(meta: dict[str, Any]) -> bool:
    """True when a memory opts in to being pulled into other pages."""
    return meta.get(EXPANDABLE_FLAG) is True


def parse_memory_links(key: str, meta: dict[str, Any], body: str) -> MemoryLinks:
    """Parse one memory's full link state from its frontmatter and body."""
    return MemoryLinks(
        key=key,
        links=parse_body_links(body) + parse_relation_links(meta),
        headings=headings_of(body),
        expandable=is_expandable(meta),
    )


# ── Index ────────────────────────────────────────────────────────────────────


def index_path(room_name: str) -> Path:
    """Path to a room's JSONL link index (not created here)."""
    return get_data_dir() / "rooms" / room_name / INDEX_FILENAME


def _record(entry: MemoryLinks) -> dict[str, Any]:
    return {
        "key": entry.key,
        "links": [link.to_dict() for link in entry.links],
        "headings": entry.headings,
        "expandable": entry.expandable,
        "updated_at": datetime.now(UTC).isoformat(),
    }


def _entry(record: dict[str, Any]) -> MemoryLinks:
    links = []
    for raw in record.get("links") or []:
        if not isinstance(raw, dict) or not raw.get("target"):
            continue
        links.append(
            Link(
                target=str(raw["target"]),
                kind=str(raw.get("kind", KIND_WIKILINK)),
                anchor=raw.get("anchor"),
                label=raw.get("label"),
                relation=raw.get("relation"),
                raw=str(raw.get("raw", "")),
                error=raw.get("error"),
            )
        )
    return MemoryLinks(
        key=str(record.get("key", "")),
        links=links,
        headings=list(record.get("headings") or []),
        expandable=bool(record.get("expandable")),
    )


def load_index(room_name: str) -> list[MemoryLinks]:
    """Load a room's link index. Returns [] when absent — it rebuilds on write."""
    path = index_path(room_name)
    if not path.exists():
        return []
    entries: list[MemoryLinks] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(_entry(json.loads(line)))
        except json.JSONDecodeError:
            logger.warning("Skipping malformed link-index line in %s", path)
    return entries


def write_index(room_name: str, entries: list[MemoryLinks]) -> None:
    """Atomically rewrite a room's link index."""
    path = index_path(room_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(json.dumps(_record(entry), default=str))
            fh.write("\n")
    os.replace(tmp, path)


def upsert(room_name: str, key: str, meta: dict[str, Any], body: str) -> None:
    """Reparse one memory's links and replace its line in the index."""
    entries = [e for e in load_index(room_name) if e.key != key]
    entries.append(parse_memory_links(key, meta, body))
    entries.sort(key=lambda e: e.key)
    write_index(room_name, entries)


def remove(room_name: str, key: str) -> bool:
    """Drop a memory's line from the index. True if one was removed."""
    entries = load_index(room_name)
    kept = [e for e in entries if e.key != key]
    if len(kept) == len(entries):
        return False
    write_index(room_name, kept)
    return True


def rebuild(room_name: str) -> int:
    """Rebuild a room's whole link index from its markdown. Returns entry count."""
    room_dir = get_data_dir() / "rooms" / room_name
    if not room_dir.exists():
        return 0
    entries = [
        parse_memory_links(key, meta, content)
        for key, meta, content in list_memory_files(room_dir, limit=10000)
    ]
    entries.sort(key=lambda e: e.key)
    write_index(room_name, entries)
    return len(entries)


# ── Resolution ───────────────────────────────────────────────────────────────


def _resolve(
    link: Link, targets: dict[str, MemoryLinks], *, source: str | None = None
) -> ResolvedLink:
    """Resolve one edge against the room's index."""
    resolved = ResolvedLink(
        target=link.target,
        kind=link.kind,
        anchor=link.anchor,
        label=link.label,
        relation=link.relation,
        raw=link.raw,
        source=source,
        error=link.error,
    )
    if resolved.error:
        return resolved

    target = targets.get(link.target)
    if target is None:
        resolved.error = ERR_NOT_FOUND
        return resolved
    if link.anchor and link.anchor not in target.headings:
        resolved.error = ERR_NO_ANCHOR
        return resolved
    if link.kind == KIND_TRANSCLUSION and not target.expandable:
        resolved.error = ERR_NOT_EXPANDABLE
        return resolved

    resolved.resolved = True
    return resolved


def outbound(room_name: str, key: str) -> list[ResolvedLink]:
    """Every edge leaving ``key``, each resolved against the room."""
    entries = load_index(room_name)
    targets = {e.key: e for e in entries}
    entry = targets.get(key)
    if entry is None:
        return []
    return [_resolve(link, targets) for link in entry.links]


def backlinks(room_name: str, key: str) -> list[ResolvedLink]:
    """Every edge pointing at ``key``, tagged with the source memory."""
    entries = load_index(room_name)
    targets = {e.key: e for e in entries}
    inbound: list[ResolvedLink] = []
    for entry in entries:
        if entry.key == key:
            continue
        inbound.extend(
            _resolve(link, targets, source=entry.key)
            for link in entry.links
            if link.target == key and not link.error
        )
    return inbound


def graph(room_name: str) -> dict[str, Any]:
    """The room's whole link graph as nodes + edges."""
    entries = load_index(room_name)
    targets = {e.key: e for e in entries}
    inbound_counts: dict[str, int] = {}
    edges: list[dict[str, Any]] = []

    for entry in entries:
        for link in entry.links:
            resolved = _resolve(link, targets, source=entry.key)
            edges.append(
                {
                    "source": entry.key,
                    "target": resolved.target,
                    "kind": resolved.kind,
                    "relation": resolved.relation,
                    "resolved": resolved.resolved,
                    "error": resolved.error,
                }
            )
            if resolved.resolved:
                inbound_counts[resolved.target] = inbound_counts.get(resolved.target, 0) + 1

    nodes = [
        {
            "key": entry.key,
            "expandable": entry.expandable,
            "outbound": sum(1 for link in entry.links if not link.error),
            "inbound": inbound_counts.get(entry.key, 0),
        }
        for entry in entries
    ]
    return {"nodes": nodes, "edges": edges}


def integrity(room_name: str) -> dict[str, Any]:
    """Broken links, orphans, roots, and leaves across a room.

    Terminology (graph theory):
    - orphan: inbound == 0 AND outbound == 0 — completely isolated, no connections.
    - root:   inbound == 0 AND outbound > 0  — entry point, nothing links here yet.
    - leaf:   inbound > 0  AND outbound == 0 — dead end, links arrive but don't continue.
    """
    entries = load_index(room_name)
    targets = {e.key: e for e in entries}
    broken: list[dict[str, Any]] = []
    linked_to: set[str] = set()
    total_links = 0

    for entry in entries:
        for link in entry.links:
            total_links += 1
            resolved = _resolve(link, targets, source=entry.key)
            if resolved.resolved:
                linked_to.add(resolved.target)
            else:
                broken.append(resolved.to_dict())

    outbound_counts = {e.key: len(e.links) for e in entries}

    return {
        "broken": broken,
        "orphans": sorted(
            e.key for e in entries if e.key not in linked_to and outbound_counts[e.key] == 0
        ),
        "roots": sorted(
            e.key for e in entries if e.key not in linked_to and outbound_counts[e.key] > 0
        ),
        "leaves": sorted(
            e.key for e in entries if e.key in linked_to and outbound_counts[e.key] == 0
        ),
        "total_memories": len(entries),
        "total_links": total_links,
    }


# ── Transclusion ─────────────────────────────────────────────────────────────


def section_of(body: str, anchor: str | None) -> str:
    """The slice of ``body`` under ``anchor``, or the whole body when None.

    A section runs from its heading to the next heading of the same or higher
    level. The heading line itself is dropped — the embedding page supplies its
    own framing.
    """
    if not anchor:
        return body.strip()

    matches = list(_HEADING_RE.finditer(body))
    for i, match in enumerate(matches):
        if slugify_heading(match.group(2)) != anchor:
            continue
        level = len(match.group(1))
        end = len(body)
        for later in matches[i + 1 :]:
            if len(later.group(1)) <= level:
                end = later.start()
                break
        return body[match.end() : end].strip()
    return ""


def expand(room_name: str, key: str) -> dict[str, Any]:
    """Expand a memory's ``![[…]]`` markers against its room.

    Depth 1: pulled text is inserted verbatim, so a marker inside an expanded
    page stays literal. A marker that can't be expanded is left exactly as
    written and reported — never silently blanked, so a reader can't mistake a
    failed embed for an empty definition.
    """
    from app.services.filesystem import read_memory_file

    room_dir = get_data_dir() / "rooms" / room_name
    source = read_memory_file(room_dir, key)
    if source is None:
        return {"key": key, "rendered": "", "expansions": [], "found": False}

    body = source[1]
    targets = {e.key: e for e in load_index(room_name)}
    expansions: list[Expansion] = []
    code_ranges = _code_span_ranges(body)

    def replace(match: re.Match[str]) -> str:
        if _in_code_span(match.start(), code_ranges):
            return match.group(0)
        link = _make_link(match.group(1), kind=KIND_TRANSCLUSION, raw=match.group(0))
        if link is None:
            return match.group(0)
        resolved = _resolve(link, targets)
        if not resolved.resolved:
            expansions.append(
                Expansion(
                    target=link.target, anchor=link.anchor, raw=match.group(0), error=resolved.error
                )
            )
            return match.group(0)

        target_file = read_memory_file(room_dir, link.target)
        if target_file is None:
            expansions.append(
                Expansion(
                    target=link.target,
                    anchor=link.anchor,
                    raw=match.group(0),
                    error=ERR_NOT_FOUND,
                )
            )
            return match.group(0)

        text = section_of(target_file[1], link.anchor)
        expansions.append(
            Expansion(target=link.target, anchor=link.anchor, raw=match.group(0), expanded=True)
        )
        return text

    rendered = _TRANSCLUSION_RE.sub(replace, body)
    return {
        "key": key,
        "rendered": rendered,
        "expansions": [asdict(e) for e in expansions],
        "found": True,
    }
