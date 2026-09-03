#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Generate per-section docs HTML pages from markdown sources + CLI/config schemas.

Markdown files in mycelium-cli/src/mycelium/docs/ are the single source of truth.
Each output page shares chrome (head, topnav, section nav, sidebar shell, footer)
and gets its own sidebar entries derived from its sections.

Run from repo root:
    cd mycelium-cli && uv run python ../docs/generate_docs.py

Write one page only (all three are still assembled, since the persistent nav and
the search index span the whole site):
    cd mycelium-cli && uv run python ../docs/generate_docs.py --page reference
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import tomllib
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path

# ── Page layout ──
# 3 pages, each a long doc with a grouped sidebar.
# (page_id, file_name, page_title, top_nav_label, sheet_no, plate_title, meta_description)
PAGES: list[tuple[str, str, str, str, str, str, str]] = [
    ("start", "index.html", "mycelium Docs", "Guide",
     "GET-001", "OVERVIEW · QUICK START · CONCEPTS",
     "A shared space for humans and agents. Install Mycelium and learn the core concepts: rooms, memory, the board, episodes, and the L9 protocol."),
    ("adapters", "adapters.html", "Adapters · mycelium", "Adapters",
     "ADP-001", "ADAPTERS · CLAUDE CODE · CURSOR · A2A BRIDGE · REST API · ENGINES",
     "Connect Claude Code, Cursor, any A2A agent, or any HTTP client to the Mycelium coordination layer, and summon the first-party engines: the aligner, the synthesizer, hello and the conductor."),
    ("reference", "reference.html", "Reference · mycelium", "Reference",
     "REF-001", "REFERENCE · ARCHITECTURE · CLI · CONFIG · DEPENDENCIES · GUIDES · HELP",
     "Architecture, CLI reference, configuration, dependencies and compatibility, guides, and troubleshooting for Mycelium."),
]

# Sections, in render order per page.
# (md_file_or_None, section_id, page_id, sidebar_group, sidebar_label)
# md_file=None means the section is hand-coded (kept verbatim from source HTML).
# If md_file is set AND a kept section with the same id exists, the kept HTML wins.
SECTION_CONFIG: list[tuple[str | None, str, str, str, str]] = [
    # ── start (index.html), overview + quickstart ──
    ("overview.md",                   "overview",           "start",       "Get Started",  "Overview"),
    ("guides/quickstart.md",          "quickstart",         "start",       "Get Started",  "Quick Start"),
    # ── concepts (now on the start page, grouped in the sidebar) ──
    ("concepts/rooms.md",             "rooms",              "start",       "Concepts",     "Rooms"),
    ("concepts/slim.md",              "slim",               "start",       "Concepts",     "SLIM"),
    ("concepts/board.md",             "board",              "start",       "Concepts",     "Board"),
    ("concepts/episodes.md",          "episodes",           "start",       "Concepts",     "Episodes"),
    ("concepts/memory.md",            "memory",             "start",       "Concepts",     "Memory"),
    ("concepts/principals.md",        "users",              "start",       "Concepts",     "Users & Teams"),
    ("concepts/l9-protocol.md",       "l9-protocol",        "start",       "Concepts",     "L9 Protocol"),
    # ── adapters (adapters.html), the adapter blocks hand-coded ──
    (None,                            "adapters",           "adapters",  "Adapters",     "Overview"),
    (None,                            "adapter-claude-code","adapters",  "Adapters",     "Claude Code"),
    (None,                            "adapter-cursor",     "adapters",  "Adapters",     "Cursor"),
    ("a2a-bridge.md",                 "adapter-a2a",        "adapters",  "Adapters",     "A2A Bridge"),
    (None,                            "adapter-api",        "adapters",  "Adapters",     "REST API"),
    # Engines sit alongside the adapters: an adapter connects an outside runtime
    # to a room, an engine is cognition the room already owns. Nested group —
    # the overview, then one page per kind.
    ("concepts/engines.md",           "engines",            "adapters",  "Engines",      "Overview"),
    ("concepts/aligner.md",           "aligner",            "adapters",  "Engines",      "Aligner"),
    ("concepts/synthesizer.md",       "synthesizer",        "adapters",  "Engines",      "Synthesizer"),
    ("concepts/hello.md",             "hello",              "adapters",  "Engines",      "Hello"),
    ("concepts/conductor.md",         "conductor",          "adapters",  "Engines",      "Conductor"),
    # ── reference (reference.html) ──
    ("reference/architecture.md",     "architecture",       "reference", "Architecture", "Architecture"),
    # CLI + Config blocks injected after architecture, before guides/troubleshooting.
    ("guides/structured-memory.md",   "structured-memory",  "reference", "Guides",       "Structured Memory"),
    ("guides/hub-and-spoke.md",       "hub-and-spoke",      "reference", "Guides",       "Hub & Spoke"),
    ("guides/ephemeral-agents.md",    "ephemeral-agents",   "reference", "Guides",       "Ephemeral Agents"),
    ("guides/herdr.md",               "herdr",              "reference", "Guides",       "Persistent Agents (herdr)"),
    ("guides/security-planes.md",     "security-planes",    "reference", "Guides",       "Security Planes"),
    ("guides/auth.md",                "auth",               "reference", "Guides",       "Authentication"),
    ("guides/keycloak-oidc.md",       "keycloak-oidc",      "reference", "Guides",       "Keycloak / OIDC Setup"),
    ("guides/troubleshooting.md",     "troubleshooting",    "reference", "Help",         "Troubleshooting"),
]

# The CLI/config/dependency blocks are generated rather than listed in
# SECTION_CONFIG, so their section ids carry no sidebar label to borrow. The
# search index reads its breadcrumbs from here instead.
GENERATED_SECTION_LABELS: dict[str, tuple[str, str]] = {
    "cli-reference": ("CLI Reference", "CLI Reference"),
    "configuration": ("Configuration", "Configuration"),
    "dependencies": ("Dependencies", "Dependencies"),
}

# One entry per page in the persistent nav:
# (page_id, file_name, top_nav_label, [(group_label, [(anchor, label), ...]), ...])
NavPage = tuple[str, str, str, list[tuple[str, list[tuple[str, str]]]]]

# IDs that should be looked up in kept HTML (have <!-- keep --> markers, or rescued by id).
_KEPT_IDS: set[str] = {
    "overview",
    "adapters", "adapter-claude-code", "adapter-cursor", "adapter-api",
}

# CLI groups for the cli-reference page.
GROUP_CONFIG: list[tuple[str, str, str]] = [
    ("setup", "setup", "setup"),
    ("room", "room", "room"),
    ("board", "board", "board"),
    ("session", "session", "session"),
    ("agent", "agent", "agent"),
    ("memory", "memory", "memory"),
    ("skill", "skill", "skill"),
    ("negotiate", "negotiate", "negotiate"),
    ("cfn", "cfn", "cfn"),
    ("adapter", "adapter", "adapter"),
    ("config", "config", "config"),
    ("other", "watch", "watch"),
]

# Configuration namespace order.
CONFIG_NAMESPACE_ORDER: list[str] = [
    "identity", "server", "llm", "runtime", "negotiation", "rooms", "knowledge_ingest",
]
CONFIG_NAMESPACE_SKIP: set[str] = {"adapters"}

REPO_ROOT = Path(__file__).parent.parent
DOCS_DIR = REPO_ROOT / "mycelium-cli" / "src" / "mycelium" / "docs"
OUT_DIR = Path(__file__).parent
LEGACY_INDEX = OUT_DIR / "index.html"  # for kept-section migration

# Source-of-truth pin files for the Dependencies & Compatibility section. Versions
# are read live from these so the page can never drift from what ships.
CLI_PYPROJECT = REPO_ROOT / "mycelium-cli" / "pyproject.toml"
BACKEND_PYPROJECT = REPO_ROOT / "fastapi-backend" / "pyproject.toml"
COMPOSE_YML = REPO_ROOT / "mycelium-cli" / "src" / "mycelium" / "docker" / "compose.yml"


# ── Markdown to HTML conversion (minimal, no dependencies) ──


def _md_to_html(md: str, section_id: str) -> str:
    lines = md.split("\n")
    out: list[str] = []
    i = 0
    first_h1 = True

    while i < len(lines):
        line = lines[i]
        progress_i = i  # forward-progress guard (see end of loop body)

        if line.strip() == "---":
            out.append('      <hr class="divider">')
            i += 1
            continue

        # Standalone image line: ![alt](src). A block-level figure, clickable
        # into the lightbox (site.js); inline images inside prose are not
        # supported, only a line that is nothing but the image.
        img_m = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$", line.strip())
        if img_m:
            alt, src = img_m.group(1), img_m.group(2)
            out.append(
                f'      <figure class="doc-figure"><img class="doc-img" '
                f'src="{html.escape(src)}" alt="{html.escape(alt)}" loading="lazy">'
            )
            # A diagrams/*.svg is rendered from a same-named .d2 source; link
            # out to it on GitHub so a reader can see (or fix) the source.
            diagram_m = re.match(r"^diagrams/([\w-]+)\.svg$", src)
            if diagram_m:
                d2_url = f"{EDIT_BASE_URL}reference/diagrams/{diagram_m.group(1)}.d2"
                out.append(
                    f'        <figcaption><a href="{d2_url}" target="_blank" '
                    f'rel="noopener">View source on GitHub</a></figcaption>'
                )
            out.append("      </figure>")
            i += 1
            continue

        if line.startswith("```"):
            lang = line[3:].strip()
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1
            code_content = _highlight_code("\n".join(code_lines), lang)
            out.append(f"      <pre><code>{code_content}</code></pre>")
            continue

        if (
            "|" in line
            and i + 1 < len(lines)
            and re.match(r"\s*\|[\s:|-]+\|\s*$", lines[i + 1])
        ):
            table_html = _parse_table(lines, i)
            out.append(table_html)
            i += 2
            while (
                i < len(lines) and "|" in lines[i] and lines[i].strip().startswith("|")
            ):
                i += 1
            continue

        if line.startswith("# "):
            text = line[2:].strip()
            if first_h1:
                first_h1 = False
                i += 1
                lead_lines = []
                while (
                    i < len(lines)
                    and lines[i].strip()
                    and not lines[i].startswith("#")
                    and not lines[i].startswith("```")
                    and not lines[i].startswith("|")
                    and not lines[i].startswith(">")
                    and not lines[i].startswith("- ")
                    and not lines[i].startswith("1.")
                ):
                    lead_lines.append(lines[i].strip())
                    i += 1
                lead = " ".join(lead_lines)
                if lead:
                    out.append(f"      <h1>{_inline(text)}</h1>")
                    out.append(f'      <p class="lead">{_inline(lead)}</p>')
                else:
                    out.append(f"      <h1>{_inline(text)}</h1>")
                continue
            out.append(f"      <h1>{_inline(text)}</h1>")
            i += 1
            continue

        if line.startswith("## "):
            text = line[3:].strip()
            anchor = _slugify(text)
            out.append(f'      <h2 id="{section_id}-{anchor}">{_inline(text)}</h2>')
            i += 1
            continue

        if line.startswith("### "):
            text = line[4:].strip()
            anchor = _slugify(text)
            out.append(f'      <h3 id="{section_id}-{anchor}">{_inline(text)}</h3>')
            i += 1
            continue

        # H4–H6 collapse to <h4> so deeper hierarchies don't fall through to
        # the paragraph collector (which would spin since lines beginning with
        # '#' are excluded from paragraph collection).
        m = re.match(r"^(#{4,6})\s+(.*)$", line)
        if m:
            text = m.group(2).strip()
            anchor = _slugify(text)
            out.append(f'      <h4 id="{section_id}-{anchor}">{_inline(text)}</h4>')
            i += 1
            continue

        # Blockquote: collect any consecutive lines starting with '>' (with or
        # without a trailing space). A bare '>' is a paragraph separator inside
        # a blockquote in standard markdown; we render the whole run as one
        # callout.
        if line.startswith(">"):
            quote_lines = []
            while i < len(lines) and lines[i].startswith(">"):
                content = lines[i][1:]
                if content.startswith(" "):
                    content = content[1:]
                quote_lines.append(content)
                i += 1
            quote_text = " ".join(ln.strip() for ln in quote_lines if ln.strip())
            # A callout may lead with a small logo: `![alt](assets/name.svg)`. The
            # SVG is inlined (not an <img>) so it inherits `currentColor` and reads
            # on both themes; anything else stays part of the prose.
            logo_svg = ""
            logo_m = re.match(r"^!\[([^\]]*)\]\(assets/([\w-]+)\.svg\)\s*", quote_text)
            if logo_m:
                asset = DOCS_DIR / "assets" / f"{logo_m.group(2)}.svg"
                if asset.is_file():
                    logo_svg = asset.read_text(encoding="utf-8").strip()
                    quote_text = quote_text[logo_m.end():]
            cls = "callout callout-note" + (" callout--logo" if logo_svg else "")
            out.append(f'      <div class="{cls}">')
            out.append('        <div class="callout-bar"></div>')
            if logo_svg:
                out.append(f'        <span class="callout-logo">{logo_svg}</span>')
            out.append(f'        <div class="callout-body">{_inline(quote_text)}</div>')
            out.append("      </div>")
            continue

        if re.match(r"^\d+\.\s", line):
            out.append('      <ol class="steps">')
            while i < len(lines) and re.match(r"^\d+\.\s", lines[i]):
                item_text = re.sub(r"^\d+\.\s+", "", lines[i]).rstrip()
                i += 1
                # Fold indented continuation lines (wrapped prose) into this item
                # so a multi-line item stays one <li> instead of splitting into a
                # fresh single-item <ol> that restarts numbering at 1.
                while i < len(lines) and lines[i].strip() and lines[i][0].isspace():
                    item_text += " " + lines[i].strip()
                    i += 1
                out.append(f"        <li>{_inline(item_text)}</li>")
            out.append("      </ol>")
            continue

        if line.startswith("- "):
            out.append("      <ul>")
            while i < len(lines) and lines[i].startswith("- "):
                item_text = lines[i][2:].rstrip()
                i += 1
                while i < len(lines) and lines[i].strip() and lines[i][0].isspace():
                    item_text += " " + lines[i].strip()
                    i += 1
                out.append(f"        <li>{_inline(item_text)}</li>")
            out.append("      </ul>")
            continue

        if not line.strip():
            i += 1
            continue

        para_lines = []
        while (
            i < len(lines)
            and lines[i].strip()
            and not lines[i].startswith("#")
            and not lines[i].startswith("```")
            and not lines[i].startswith("|")
            and not lines[i].startswith(">")
            and not lines[i].startswith("- ")
            and not re.match(r"^\d+\.\s", lines[i])
        ):
            para_lines.append(lines[i].strip())
            i += 1
        if para_lines:
            out.append(f"      <p>{_inline(' '.join(para_lines))}</p>")
        # Forward-progress guard: if no branch advanced `i`, the line matched
        # no rule and would have spun the outer loop forever. Skip it with a
        # visible warning so the offending input is reported, not silently
        # eaten.
        if i == progress_i:
            print(
                f"WARNING: unhandled markdown line in section '{section_id}' "
                f"(line {i + 1}): {lines[i]!r}, skipping",
                file=sys.stderr,
            )
            i += 1
        continue

    return "\n".join(out)


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s]+", "-", text)
    return text.strip("-")


def _inline(text: str) -> str:
    text = html.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


def _highlight_code(code: str, lang: str) -> str:
    if lang not in ("bash", "sh", ""):
        return html.escape(code)

    lines = code.split("\n")
    out = []
    for line in lines:
        if line.strip().startswith("#"):
            out.append(f'<span class="comment">{html.escape(line)}</span>')
            continue
        highlighted = html.escape(line)
        # URLs carry the warm secondary tone.
        highlighted = re.sub(
            r"(https?://[^\s&|]+)",
            r'<span class="url">\1</span>',
            highlighted,
        )
        highlighted = re.sub(
            r"(\s)(--?\w[\w-]*)",
            r'\1<span class="flag">\2</span>',
            highlighted,
        )
        highlighted = re.sub(
            r"(&quot;[^&]*&quot;)",
            r'<span class="str">\1</span>',
            highlighted,
        )
        # The mycelium binary is its own token; its subcommands stay cmd-toned.
        # Only when it's a standalone command, not inside a path (.mycelium/,
        # ~/.mycelium) or a hyphenated name (mycelium-io).
        highlighted = re.sub(
            r"(?<![\w./~-])mycelium(?=\s)((?:\s+[\w-]+){0,2})",
            lambda m: '<span class="bin">mycelium</span>'
            + re.sub(r"[\w-]+", r'<span class="cmd">\g<0></span>', m.group(1)),
            highlighted,
        )
        # Other leading shell commands that would otherwise render plain.
        highlighted = re.sub(
            r"^(\s*)(curl|docker|bash|cd|uv|ssh|git|open|cursor-agent|command)\b",
            r'\1<span class="cmd">\2</span>',
            highlighted,
        )
        out.append(highlighted)
    return "\n".join(out)


def _highlight_usage(usage: str) -> str:
    s = html.escape(usage)
    s = re.sub(
        r"^mycelium((?:\s+[\w-]+){1,2})",
        lambda m: '<span class="bin">mycelium</span>'
        + re.sub(r"[\w-]+", r'<span class="cmd">\g<0></span>', m.group(1)),
        s,
    )
    s = re.sub(r"(&quot;[^&]*&quot;)", r'<span class="str">\1</span>', s)
    s = re.sub(r"([\s\[])(-{1,2}\w[\w-]*)", r'\1<span class="flag">\2</span>', s)
    s = re.sub(r"(&lt;\w+&gt;)", r'<span class="arg">\1</span>', s)
    s = re.sub(r"(?<=\s)([A-Z]{2,})(?=[\s\]\)]|$)", r'<span class="arg">\1</span>', s)
    return s


def _parse_table(lines: list[str], start: int) -> str:
    header_line = lines[start].strip().strip("|")
    headers = [h.strip() for h in header_line.split("|")]
    row_start = start + 2
    rows = []
    i = row_start
    while i < len(lines) and "|" in lines[i] and lines[i].strip().startswith("|"):
        row_line = lines[i].strip().strip("|")
        cells = [c.strip() for c in row_line.split("|")]
        rows.append(cells)
        i += 1

    out = [
        '      <div class="table-wrap">',
        "        <table>",
        "          <thead>",
        "            <tr>",
    ]
    for h in headers:
        out.append(f"              <th>{_inline(h)}</th>")
    out.append("            </tr>")
    out.append("          </thead>")
    out.append("          <tbody>")
    for row in rows:
        out.append("            <tr>")
        for cell in row:
            out.append(f"              <td>{_inline(cell)}</td>")
        out.append("            </tr>")
    out.append("          </tbody>")
    out.append("        </table>")
    out.append("      </div>")
    return "\n".join(out)


# ── Kept (hand-crafted) section discovery ──


def _extract_kept_sections(html_text: str) -> dict[str, str]:
    """Return {section_id: full_section_html} for any <section> with <!-- keep -->."""
    kept: dict[str, str] = {}
    for m in re.finditer(
        r'(<section\s+class="doc-section"\s+id="([^"]+)"[^>]*>.*?</section>)',
        html_text,
        re.DOTALL,
    ):
        if "<!-- keep -->" in m.group(1):
            kept[m.group(2)] = m.group(1)
    return kept


def _extract_sections_by_id(html_text: str, ids: set[str]) -> dict[str, str]:
    """Extract any <section> whose id matches, regardless of <!-- keep --> marker."""
    found: dict[str, str] = {}
    for m in re.finditer(
        r'(<section\s+class="doc-section"\s+id="([^"]+)"[^>]*>.*?</section>)',
        html_text,
        re.DOTALL,
    ):
        sid = m.group(2)
        if sid in ids:
            block = m.group(1)
            # Inject <!-- keep --> if missing so future round-trips work.
            if "<!-- keep -->" not in block:
                block = re.sub(
                    r'(<section\s+class="doc-section"\s+id="[^"]+"[^>]*>)',
                    r"\1\n      <!-- keep -->",
                    block,
                    count=1,
                )
            found[sid] = block
    return found


def _all_kept_sections() -> dict[str, str]:
    """Read kept sections from existing HTML files.

    Falls back to legacy single-page index.html / .legacy copy and rescues
    hand-coded sections by id (injecting <!-- keep --> for future round-trips).
    """
    kept: dict[str, str] = {}

    # Legacy single-page sources (pre-split or saved .legacy copy).
    legacy_paths = [LEGACY_INDEX, OUT_DIR / "index.html.legacy"]
    for path in legacy_paths:
        if path.exists():
            text = path.read_text()
            kept.update(_extract_kept_sections(text))
            for sid, block in _extract_sections_by_id(text, _KEPT_IDS).items():
                kept.setdefault(sid, block)

    # Per-page files override legacy (post-split source of truth).
    for _, file_name, *_ in PAGES:
        path = OUT_DIR / file_name
        if path.exists():
            kept.update(_extract_kept_sections(path.read_text()))
    return kept


# ── CLI Reference + Config Reference ──


def _generate_cli_reference() -> tuple[str, list[tuple[str, str]]]:
    """Return (content_html, sidebar_entries) for the cli-reference page."""
    import mycelium.commands.adapter  # noqa: F401
    import mycelium.commands.agent  # noqa: F401
    import mycelium.commands.board  # noqa: F401
    import mycelium.commands.config  # noqa: F401
    import mycelium.commands.doctor  # noqa: F401
    import mycelium.commands.hub  # noqa: F401
    import mycelium.commands.install  # noqa: F401
    import mycelium.commands.instance  # noqa: F401
    import mycelium.commands.login  # noqa: F401
    import mycelium.commands.memory  # noqa: F401
    import mycelium.commands.participate  # noqa: F401
    import mycelium.commands.room  # noqa: F401
    import mycelium.commands.skill  # noqa: F401
    import mycelium.commands.ui  # noqa: F401
    from mycelium.doc_ref import get_registry

    entries = get_registry()
    groups: dict[str, list] = defaultdict(list)
    for entry in entries:
        groups[entry.group].append(entry)

    section_lines = ["      <h1>CLI Reference</h1>"]
    sidebar_entries: list[tuple[str, str]] = []

    for group_key, heading, sidebar_label in GROUP_CONFIG:
        if group_key not in groups:
            continue

        anchor = f"cli-{group_key}"
        section_lines.append("")
        section_lines.append(f'      <h2 id="{anchor}">{html.escape(heading)}</h2>')
        sidebar_entries.append((anchor, sidebar_label))

        for entry in groups[group_key]:
            highlighted_usage = _highlight_usage(entry.usage)
            section_lines.append("")
            section_lines.append('      <div class="cmd-ref">')
            section_lines.append('        <div class="cmd-ref-header">')
            section_lines.append(f"          <code>{highlighted_usage}</code>")
            section_lines.append("        </div>")
            section_lines.append(
                f'        <div class="cmd-ref-body">{entry.desc}</div>'
            )
            section_lines.append("      </div>")

    # Wrap in a <section> for IntersectionObserver tracking.
    body = (
        '    <section class="doc-section" id="cli-reference">\n'
        + "\n".join(section_lines)
        + "\n    </section>"
    )
    return body, sidebar_entries


def _highlight_toml(code: str, anchors: dict[str, str] | None = None) -> str:
    anchors = anchors or {}
    out = []
    for line in code.split("\n"):
        stripped = line.strip()
        if not stripped:
            out.append("")
            continue
        if stripped.startswith("#"):
            out.append(f'<span class="comment">{html.escape(line)}</span>')
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            ns = stripped[1:-1]
            anchor = anchors.get(ns)
            id_attr = f' id="{anchor}"' if anchor else ""
            out.append(
                f'<span class="cmd"{id_attr}>{html.escape(line)}</span>'
            )
            continue
        m = re.match(r"^(\s*)([\w.-]+)(\s*=\s*)(.*)$", line)
        if m:
            indent, key, eq, value = m.groups()
            value_esc = html.escape(value)
            value_esc = re.sub(
                r"(&quot;[^&]*&quot;)",
                r'<span class="str">\1</span>',
                value_esc,
            )
            if value.strip() in ("true", "false"):
                value_esc = f'<span class="flag">{value_esc}</span>'
            out.append(
                f"{indent}<span class=\"arg\">{html.escape(key)}</span>"
                f"{html.escape(eq)}{value_esc}"
            )
            continue
        out.append(html.escape(line))
    return "\n".join(out)


def _format_toml_value(value: object) -> str:
    if value is None:
        return '""'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, (list, tuple)):
        inner = ", ".join(_format_toml_value(v) for v in value)
        return f"[{inner}]"
    if isinstance(value, dict):
        return "{}"
    return str(value)


def _generate_config_reference() -> tuple[str, list[tuple[str, str]]]:
    """Return (content_html, sidebar_entries) for the configuration page."""
    from pydantic import BaseModel

    from mycelium.config import MyceliumConfig

    declared = list(MyceliumConfig.model_fields.keys())
    ordered = [n for n in CONFIG_NAMESPACE_ORDER if n in declared]
    ordered += [
        n for n in declared if n not in ordered and n not in CONFIG_NAMESPACE_SKIP
    ]

    section_lines = ["      <h1>Configuration</h1>"]
    section_lines.append(
        "      <p>Settings live in <code>~/.mycelium/config.toml</code>. Change "
        "a value with <code>mycelium config set &lt;key&gt; &lt;value&gt;</code> "
        "(for example, <code>mycelium config set llm.model "
        "anthropic/claude-sonnet-4-6</code>), then run <code>mycelium config "
        "apply</code> to regenerate <code>~/.mycelium/.env</code>. If the "
        "change affects a service running in a container, restart with "
        "<code>mycelium up</code> for it to take effect.</p>"
    )
    sidebar_entries: list[tuple[str, str]] = []
    ns_anchors: dict[str, str] = {}

    code_lines: list[str] = []
    for ns in ordered:
        ns_field = MyceliumConfig.model_fields[ns]
        ns_type = ns_field.annotation
        if not (isinstance(ns_type, type) and issubclass(ns_type, BaseModel)):
            continue
        anchor = f"config-{ns.replace('_', '-')}"
        sidebar_entries.append((anchor, ns))
        ns_anchors[ns] = anchor

        if code_lines:
            code_lines.append("")
        ns_doc = (ns_type.__doc__ or "").strip().split("\n", 1)[0]
        if ns_doc:
            code_lines.append(f"# {ns_doc}")
        code_lines.append(f"[{ns}]")
        for fname, ff in ns_type.model_fields.items():
            desc = ff.description
            value = _format_toml_value(ff.default)
            code_lines.append("")
            if desc:
                code_lines.append(f"# {desc}")
            code_lines.append(f"{fname} = {value}")

    code_block = "\n".join(code_lines)
    highlighted = _highlight_toml(code_block, ns_anchors)
    section_lines.append(f"      <pre><code>{highlighted}</code></pre>")

    body = (
        '    <section class="doc-section" id="configuration">\n'
        + "\n".join(section_lines)
        + "\n    </section>"
    )
    return body, sidebar_entries


# ── Dependencies & Compatibility ──
#
# The version cell of every row is read live from the pin files (below), so the
# published page cannot drift from what actually ships. The editorial metadata
# (which group a dependency belongs to, what it's for, where its releases live)
# is curated here, because none of it is derivable from a pyproject entry.
#
# A version source is one of:
#   ("dep", "cli"|"backend", pkg)          # a [project.dependencies] pin
#   ("extra", "cli"|"backend", extra, pkg) # a [project.optional-dependencies] pin
#   ("image", "<image ref>")               # a container image tag from compose.yml
#   ("literal", "<text>")                  # not version-pinned in a file (e.g. Pi)
#   ("multi", [(label, source), ...])      # several pins rendered together

DEPENDENCY_GROUPS: list[dict] = [
    {
        "heading": "Messaging fabric (AGNTCY SLIM)",
        "sidebar": "Messaging (SLIM)",
        "intro": (
            "Mycelium is SLIM-native: rooms are SLIM group channels. This is the "
            "one deep coupling in the stack, so it comes first."
        ),
        "components": [
            {
                "name": "slim-bindings",
                "version": ("dep", "cli", "slim-bindings"),
                "role": "The client the CLI and backend use to join channels",
                "upstream": ("agntcy/slim releases", "https://github.com/agntcy/slim/releases"),
            },
            {
                "name": "agntcy/slim (node image)",
                "display": "`ghcr.io/agntcy/slim`",
                "version": ("image", "ghcr.io/agntcy/slim"),
                "role": "The messaging node itself, a blind ciphertext forwarder",
                "upstream": (
                    "ghcr.io/agntcy/slim",
                    "https://github.com/agntcy/slim/pkgs/container/slim",
                ),
            },
        ],
        # {slim} and {node} are filled from the resolved pins so the constraint
        # text always names the versions actually in force.
        "callout": (
            "**Version lockstep.** The node image and the `slim-bindings` wheel "
            "must move together. Today both sides pin `slim-bindings{slim}` and the "
            "node image is `{node}`. Mixing versions fails the MLS handshake with "
            "`public key length is invalid`, so bump both to the same 2.x line at "
            "once. 2.1.x is the first MLS-with-external-identity stack, which is "
            "what the identity tiers build on."
        ),
    },
    {
        "heading": "Memory and search",
        "sidebar": "Memory & Search",
        "components": [
            {
                "name": "fastembed",
                "version": ("dep", "backend", "fastembed"),
                "role": "Local ONNX embeddings (BAAI/bge-small-en-v1.5, 384-dim); no external service",
                "upstream": ("qdrant/fastembed", "https://github.com/qdrant/fastembed/releases"),
            },
            {
                "name": "tiktoken",
                "version": ("dep", "backend", "tiktoken"),
                "role": "Token counting for context budgeting",
                "upstream": ("openai/tiktoken", "https://github.com/openai/tiktoken/releases"),
            },
            {
                "name": "rapidfuzz",
                "version": ("dep", "backend", "rapidfuzz"),
                "role": "Fuzzy key matching over memory",
                "upstream": ("rapidfuzz/RapidFuzz", "https://github.com/rapidfuzz/RapidFuzz/releases"),
            },
        ],
    },
    {
        "heading": "Cognition",
        "sidebar": "Cognition",
        "components": [
            {
                "name": "negmas",
                "version": (
                    "multi",
                    [
                        ("backend", ("dep", "backend", "negmas")),
                        ("CLI engine extra", ("extra", "cli", "engine", "negmas")),
                    ],
                ),
                "role": "The Stacked Alternating Offers mechanism the aligner runs",
                "upstream": ("yasserfarouk/negmas", "https://github.com/yasserfarouk/negmas/releases"),
            },
            {
                "name": "anthropic",
                "version": ("dep", "backend", "anthropic"),
                "role": "LLM client for backend cognition stages",
                "upstream": (
                    "anthropic-sdk-python",
                    "https://github.com/anthropics/anthropic-sdk-python/releases",
                ),
            },
            {
                "name": "Pi",
                "display": "Pi (`pi` binary)",
                "version": ("literal", "shipped in the backend image"),
                "role": "The aligner's brain and every one-shot cognition turn",
                "upstream": "external binary, not a Python dependency",
            },
        ],
    },
    {
        "heading": "Identity and crypto",
        "sidebar": "Identity & Crypto",
        "components": [
            {
                "name": "pyjwt[crypto]",
                "version": ("dep", "backend", "pyjwt"),
                "role": "JWT validation for the auth gate and SignerJwt identity",
                "upstream": ("jpadilla/pyjwt", "https://github.com/jpadilla/pyjwt/releases"),
            },
            {
                "name": "cryptography",
                "version": ("dep", "cli", "cryptography"),
                "role": "ES256 keypair and JWK for SLIM channel identity",
                "upstream": ("pyca/cryptography", "https://github.com/pyca/cryptography/releases"),
            },
        ],
    },
]

# Rendered verbatim as the closing paragraph. These carry no special version
# constraint beyond their pins, so they don't earn a row each.
DEPENDENCY_FOOTER = (
    "The rest of the stack is standard, widely used building blocks with no "
    "special version constraint beyond their pins: `fastapi[standard]`, `httpx`, "
    "`pydantic` / `pydantic-settings`, `typer`, `rich`, and `questionary`. See the "
    "`pyproject.toml` in each package for exact ranges."
)


def _normalize_pkg(name: str) -> str:
    """PyPI-normalize a distribution name (case-fold, unify -/_/., drop extras)."""
    name = name.split("[", 1)[0]
    return re.sub(r"[-_.]+", "-", name).strip().lower()


def _dep_version(deps: list[str], pkg: str) -> str:
    """Return the version specifier for pkg from a dependencies list, e.g. '>=2.1,<2.2'."""
    want = _normalize_pkg(pkg)
    for entry in deps:
        m = re.match(r"^\s*([A-Za-z0-9._-]+(?:\[[^\]]*\])?)\s*(.*)$", entry)
        if m and _normalize_pkg(m.group(1)) == want:
            return m.group(2).strip()
    raise KeyError(f"dependency '{pkg}' not found; the pin was renamed or removed")


def _image_tag(compose_text: str, image: str) -> str:
    """Extract the default tag for a compose image, e.g. 'ghcr.io/agntcy/slim' -> '2.1.0'."""
    # Matches either `image:2.1.0` or `image:${VAR:-2.1.0}`.
    m = re.search(
        rf"{re.escape(image)}:(?:\$\{{[^:}}]+:-([^}}]+)\}}|([^\s${{}}]+))",
        compose_text,
    )
    if not m:
        raise KeyError(f"image '{image}' not found in compose.yml")
    return (m.group(1) or m.group(2)).strip()


def _load_pin_context() -> dict:
    """Read every pin file once into a lookup the version resolver reads from."""
    cli = tomllib.loads(CLI_PYPROJECT.read_text())
    backend = tomllib.loads(BACKEND_PYPROJECT.read_text())

    def deps(pp: dict) -> list[str]:
        return pp.get("project", {}).get("dependencies", [])

    def extras(pp: dict) -> dict:
        return pp.get("project", {}).get("optional-dependencies", {})

    return {
        "cli": {"deps": deps(cli), "extras": extras(cli)},
        "backend": {"deps": deps(backend), "extras": extras(backend)},
        "compose": COMPOSE_YML.read_text(),
    }


def _resolve_version(source: tuple, ctx: dict) -> str:
    kind = source[0]
    if kind == "dep":
        _, which, pkg = source
        return _dep_version(ctx[which]["deps"], pkg)
    if kind == "extra":
        _, which, extra, pkg = source
        return _dep_version(ctx[which]["extras"].get(extra, []), pkg)
    if kind == "image":
        return _image_tag(ctx["compose"], source[1])
    if kind == "literal":
        return source[1]
    raise ValueError(f"unknown version source: {source!r}")


def _version_cell(source: tuple, ctx: dict) -> str:
    """Render a component's version as a markdown table cell."""
    if source[0] == "literal":
        return source[1]
    if source[0] == "multi":
        return " / ".join(
            f"`{_resolve_version(sub, ctx)}` {label}" for label, sub in source[1]
        )
    return f"`{_resolve_version(source, ctx)}`"


def _upstream_cell(upstream: object) -> str:
    if isinstance(upstream, tuple):
        label, url = upstream
        return f"[{label}]({url})"
    return str(upstream)


def _generate_dependencies_reference() -> tuple[str, list[tuple[str, str]]]:
    """Return (content_html, sidebar_entries) for the Dependencies & Compatibility section.

    Versions come live from the pin files; role/upstream metadata is curated in
    DEPENDENCY_GROUPS. The section is emitted as markdown and run through the same
    renderer as every other page, so it inherits table/callout styling for free.
    """
    ctx = _load_pin_context()

    # Lockstep invariant: the CLI and backend slim-bindings pins must be identical,
    # or the shared node image can't match both. Surfacing this page while the two
    # have silently diverged would document a broken state, so fail loudly.
    cli_slim = _dep_version(ctx["cli"]["deps"], "slim-bindings")
    backend_slim = _dep_version(ctx["backend"]["deps"], "slim-bindings")
    if cli_slim != backend_slim:
        raise SystemExit(
            "slim-bindings pins have drifted: "
            f"CLI '{cli_slim}' vs backend '{backend_slim}'. They must match "
            "(see the version-lockstep note in compose.yml)."
        )
    node_tag = _image_tag(ctx["compose"], "ghcr.io/agntcy/slim")

    md: list[str] = [
        "# Dependencies & Compatibility",
        "",
        "Mycelium is assembled from a small set of upstream components. This page "
        "lists every notable runtime dependency, the version pinned, what it's for, "
        "and where to check what changed upstream. The versions are read from the "
        "pins in `pyproject.toml` and `compose.yml`, so they match what ships.",
        "",
    ]
    sidebar_entries: list[tuple[str, str]] = []

    for group in DEPENDENCY_GROUPS:
        heading = group["heading"]
        md.append(f"## {heading}")
        md.append("")
        sidebar_entries.append((f"dependencies-{_slugify(heading)}", group["sidebar"]))

        if group.get("intro"):
            md.append(group["intro"])
            md.append("")

        md.append("| Component | Pinned version | Role | Upstream |")
        md.append("| --- | --- | --- | --- |")
        for comp in group["components"]:
            name = comp.get("display", f"`{comp['name']}`")
            version = _version_cell(comp["version"], ctx)
            upstream = _upstream_cell(comp["upstream"])
            md.append(f"| {name} | {version} | {comp['role']} | {upstream} |")
        md.append("")

        if group.get("callout"):
            md.append("> " + group["callout"].format(slim=cli_slim, node=node_tag))
            md.append("")

    md.append(DEPENDENCY_FOOTER)

    body = _md_to_html("\n".join(md), "dependencies")
    section = (
        '    <section class="doc-section" id="dependencies">\n'
        + body
        + "\n    </section>"
    )
    return section, sidebar_entries


# ── Page assembly ──


GITHUB_SVG = (
    '<svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" '
    'style="display:block;"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 '
    '5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69'
    '-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 '
    '1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-'
    '3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 '
    '2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 '
    '1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29'
    '.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 '
    '0016 8c0-4.42-3.58-8-8-8z"/></svg>'
)

SKILL_MD_URL = (
    "https://raw.githubusercontent.com/mycelium-io/mycelium/main/"
    "mycelium-cli/src/mycelium/integrations/claude_code/assets/skills/"
    "mycelium/SKILL.md"
)

# Every markdown-backed section links back to the file it was rendered from, so
# a reader who spots a mistake can fix it where the source of truth lives.
EDIT_BASE_URL = (
    "https://github.com/mycelium-io/mycelium/blob/main/mycelium-cli/src/mycelium/docs/"
)

SEARCH_SVG = (
    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
    '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>'
)

CHEVRON_SVG = (
    '<svg class="nav-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="2.5" stroke-linecap="round" '
    'stroke-linejoin="round"><path d="m9 6 6 6-6 6"/></svg>'
)

PENCIL_SVG = (
    '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M12 20h9"/>'
    '<path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>'
)


def _head(title: str, description: str, file_name: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(description)}">
<meta property="og:title" content="{html.escape(title)}">
<meta property="og:description" content="{html.escape(description)}">
<meta property="og:image" content="https://mycelium-io.github.io/mycelium/og.png">
<meta property="og:url" content="https://mycelium-io.github.io/mycelium/{file_name}">
<meta property="og:type" content="website">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="https://mycelium-io.github.io/mycelium/og.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="mycelium.css">
<script>
// Resolve the theme before first paint so the page never flashes the wrong one.
(function () {{
  try {{
    var t = localStorage.getItem('mycelium-theme') || 'dark';
    var dark = t !== 'light'
      && (t === 'dark' || window.matchMedia('(prefers-color-scheme: dark)').matches);
    document.documentElement.classList.toggle('dark', dark);
  }} catch (e) {{
    document.documentElement.classList.add('dark');
  }}
}})();
</script>
</head>
<body>
<canvas id="mycelium-bg"></canvas>
"""


def _theme_toggle() -> str:
    """Light / dark / system menu, mirroring the app's ThemeToggle."""
    opts = [
        ("light", "Light", "sun"),
        ("dark", "Dark", "moon"),
        ("system", "System", "monitor"),
    ]
    items = "\n".join(
        f'      <button data-theme-set="{value}">'
        f'<i data-lucide="{icon}"></i>{label}</button>'
        for value, label, icon in opts
    )
    return f"""    <div class="theme-toggle">
      <button class="theme-btn" id="theme-btn" aria-label="Theme" onclick="toggleThemeMenu(event)">
        <i data-lucide="sun"></i>
      </button>
      <div class="theme-menu" id="theme-menu">
{items}
      </div>
    </div>"""


def _topnav() -> str:
    """The app's shell header: brand over the rail, search, right-hand actions.

    The brand cell is sidebar-width so the rail reads as one column, matching
    RoomsSidebar sitting under the workspace header in the app. Page navigation
    lives in the persistent rail, which carries every page at every width, so the
    bar holds only what the rail cannot: search and the page actions.
    """
    return f"""<!-- TOP BAR -->
<nav class="topnav">
  <button class="nav-toggle" aria-label="Menu" onclick="toggleDrawer(event)"><i data-lucide="menu"></i></button>
  <a href="https://mycelium-io.github.io" class="topnav-cell topnav-brand">
    <img src="logo.png" alt="Mycelium">
    <span class="brand-word">mycelium</span>
  </a>
  <div class="topnav-right">
    <div class="docsearch" id="docsearch">
      <button class="docsearch-toggle" id="docsearch-toggle" type="button"
              aria-label="Search docs" aria-expanded="false">{SEARCH_SVG}</button>
      <div class="docsearch-field">
        {SEARCH_SVG}
        <input type="search" id="docsearch-input" placeholder="Search docs"
               autocomplete="off" spellcheck="false" aria-label="Search the documentation"
               role="combobox" aria-expanded="false" aria-controls="docsearch-results">
        <kbd class="docsearch-hint">/</kbd>
      </div>
      <div class="docsearch-panel" id="docsearch-panel">
        <div class="docsearch-results" id="docsearch-results" role="listbox"></div>
        <div class="docsearch-legend">
          <span><kbd>&uarr;</kbd><kbd>&darr;</kbd> navigate</span>
          <span><kbd>&crarr;</kbd> open</span>
          <span><kbd>esc</kbd> close</span>
        </div>
      </div>
    </div>
    <button class="copy-agents-btn" onclick="copyAgentsMd()"><i data-lucide="file-text"></i>Copy agents.md</button>
    <button class="copy-page-btn" onclick="copyPage()"><i data-lucide="copy"></i>Copy page</button>
{_theme_toggle()}
    <a href="https://github.com/mycelium-io/mycelium" aria-label="GitHub">{GITHUB_SVG}</a>
  </div>
</nav>
"""


def _sidebar(nav: list[NavPage], active_page_id: str) -> str:
    """Render the persistent nav: every page's groups, on every page.

    Groups belonging to the page being read start expanded and link to bare
    anchors; the rest start collapsed and link across files. site.js layers the
    reader's own expand/collapse choices on top.
    """
    out = ['  <nav class="sidebar" id="sidebar">', '    <div class="nav-tree">']
    for page_id, file_name, label, groups in nav:
        current = page_id == active_page_id
        page_cls = "nav-page-link" + (" active" if current else "")
        out.append('    <div class="nav-page-group">')
        out.append(
            f'      <a href="{file_name}" class="{page_cls}">{html.escape(label)}</a>'
        )
        for group_label, items in groups:
            if not items:
                continue
            key = f"{page_id}:{_slugify(group_label)}"
            group_cls = "nav-group" + ("" if current else " collapsed")
            out.append(f'      <div class="{group_cls}" data-nav-group="{key}">')
            out.append(
                f'        <button class="nav-group-toggle" type="button" '
                f'aria-expanded="{"true" if current else "false"}">'
                f'{CHEVRON_SVG}<span>{html.escape(group_label)}</span></button>'
            )
            out.append('        <div class="nav-group-items">')
            for anchor, item_label in items:
                href = f"#{anchor}" if current else f"{file_name}#{anchor}"
                out.append(
                    f'          <a href="{href}" class="nav-link sub">'
                    f"{html.escape(item_label)}</a>"
                )
            out.append("        </div>")
            out.append("      </div>")
        out.append("    </div>")
    out.append("    </div>")
    out.append('    <div class="nav-external">')
    out.append(
        f'      <a href="{SKILL_MD_URL}" target="_blank" rel="noopener">SKILL.md ↗</a>'
    )
    out.append("    </div>")
    out.append("  </nav>")
    return "\n".join(out)


def _layout_open(sidebar_html: str) -> str:
    return f"""<div class="layout">

{sidebar_html}
  <div class="nav-backdrop" id="nav-backdrop" onclick="closeDrawer()"></div>

  <!-- MAIN -->
  <main class="main">
  <div class="main-inner">
"""


def _layout_close(sheet_no: str, plate_title: str) -> str:
    """Close the workspace and pin the editor-style status bar beneath it."""
    return f"""  </div>
  </main>
</div>

<!-- STATUS BAR -->
<footer class="docs-footer">
  <a href="https://github.com/mycelium-io/mycelium">mycelium-io/mycelium</a>
  <span class="sep">·</span>
  <span>Apache 2.0</span>
  <span class="tagline">Shared Intent &middot; Shared Memory &middot; Shared Context</span>
</footer>

<script src="https://unpkg.com/lucide@latest/dist/umd/lucide.min.js"></script>
<script src="site.js"></script>

</body>
</html>
"""


def _render_page(
    page_id: str,
    file_name: str,
    title: str,
    description: str,
    content_html: str,
    nav: list[NavPage],
    sheet_no: str,
    plate_title: str,
) -> str:
    sidebar_html = _sidebar(nav, page_id)
    return (
        _head(title, description, file_name)
        + _topnav()
        + _layout_open(sidebar_html)
        + content_html
        + "\n"
        + _layout_close(sheet_no, plate_title)
    )


# ── Page content builders ──


def _edit_link(md_file: str) -> str:
    """Link a section back to the markdown file it was rendered from."""
    return (
        f'      <p class="edit-page"><a href="{EDIT_BASE_URL}{md_file}" '
        f'target="_blank" rel="noopener">{PENCIL_SVG}Edit this page on GitHub</a></p>'
    )


def _md_section_html(md_file: str, section_id: str) -> str:
    md_path = DOCS_DIR / md_file
    if not md_path.exists():
        print(f"  WARNING: {md_path} not found, skipping {section_id}")
        return ""
    md_content = md_path.read_text()
    body = _md_to_html(md_content, section_id)
    return (
        f'    <section class="doc-section" id="{section_id}">\n'
        f"{body}\n"
        f"{_edit_link(md_file)}\n"
        f"    </section>"
    )


def _build_page(
    page_id: str,
    kept: dict[str, str],
    cli_block: tuple[str, list[tuple[str, str]]] | None = None,
    config_block: tuple[str, list[tuple[str, str]]] | None = None,
    deps_block: tuple[str, list[tuple[str, str]]] | None = None,
) -> tuple[str, list[tuple[str, list[tuple[str, str]]]]]:
    """Build (content_html, sidebar_groups) for a single page.

    sidebar_groups: list of (group_label, [(anchor, label), ...]) preserving order.
    For the reference page, cli_block + config_block + deps_block (each a
    (html, sidebar_entries)) are inserted between architecture and troubleshooting.
    """
    parts: list[str] = []
    grouped: dict[str, list[tuple[str, str]]] = {}
    group_order: list[str] = []

    def add_group(group: str, anchor: str, label: str) -> None:
        if group not in grouped:
            grouped[group] = []
            group_order.append(group)
        grouped[group].append((anchor, label))

    inject_after_architecture = page_id == "reference"

    for md_file, sid, pid, group, label in SECTION_CONFIG:
        if pid != page_id:
            continue

        if sid in kept:
            parts.append(kept[sid])
        elif md_file:
            section_html = _md_section_html(md_file, sid)
            if not section_html:
                continue
            parts.append(section_html)
        else:
            print(f"  WARNING: section '{sid}' has no md and no kept HTML")
            continue

        add_group(group, sid, label)

        # Inject CLI + Config blocks right after the architecture section on the
        # reference page (and before troubleshooting).
        if inject_after_architecture and sid == "architecture":
            if cli_block is not None:
                cli_html, cli_entries = cli_block
                parts.append(cli_html)
                for anchor, lbl in cli_entries:
                    add_group("CLI Reference", anchor, lbl)
            if config_block is not None:
                config_html, config_entries = config_block
                parts.append(config_html)
                for anchor, lbl in config_entries:
                    add_group("Configuration", anchor, lbl)
            if deps_block is not None:
                deps_html, deps_entries = deps_block
                parts.append(deps_html)
                for anchor, lbl in deps_entries:
                    add_group("Dependencies", anchor, lbl)

    content = "\n\n    <hr class=\"divider\">\n\n".join(parts)
    sidebar_groups = [(g, grouped[g]) for g in group_order]
    return content, sidebar_groups


# ── Search index ──
#
# The index is derived from the rendered HTML rather than from the markdown, so
# it covers every source the pages are assembled from — markdown sections, the
# hand-coded adapter blocks, and the generated CLI/config/dependency reference —
# through one code path.

_INDEX_SKIP_TAGS = {"script", "style"}
_SNIPPET_CHARS = 420


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


class _SearchIndexExtractor(HTMLParser):
    """Collect one search record per anchor from a page's rendered content."""

    def __init__(self, file_name: str, labels: dict[str, tuple[str, str]]) -> None:
        super().__init__(convert_charrefs=True)
        self.file_name = file_name
        self.labels = labels
        self.records: list[dict] = []
        self._cur: dict | None = None
        self._crumb = ""
        self._heading: dict | None = None
        self._skipped: list[str] = []
        self._divs: list[str | None] = []
        self._cmd: dict | None = None
        self._cmd_part: str | None = None

    # -- record lifecycle --

    def _open(self, anchor: str, title: str, crumb: str) -> None:
        self._cur = {"u": f"{self.file_name}#{anchor}", "t": title, "s": crumb, "x": []}
        self.records.append(self._cur)

    def _flush_cmd(self) -> None:
        cmd, self._cmd = self._cmd, None
        if cmd is None or self._cur is None:
            return
        title = _collapse("".join(cmd["t"]))
        if title:
            self.records.append({
                "u": self._cur["u"],
                "t": title,
                "s": self._crumb,
                "x": [_collapse("".join(cmd["x"]))],
                "k": "cmd",
            })

    # -- parser hooks --

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k: v or "" for k, v in attrs}
        classes = attr.get("class", "").split()
        if tag in _INDEX_SKIP_TAGS or "edit-page" in classes:
            self._skipped.append(tag)
            return
        if self._skipped:
            return

        if tag == "section" and attr.get("id"):
            sid = attr["id"]
            group, label = self.labels.get(sid, ("", sid.replace("-", " ").title()))
            self._crumb = f"{group} › {label}" if group and group != label else label
            self._open(sid, label, group or "")
            return

        # An h1 names the section it opens; capturing it keeps the section's
        # own title from leading its snippet.
        if tag == "h1":
            self._heading = {"anchor": None, "text": []}
            return

        if tag in ("h2", "h3") and attr.get("id"):
            self._heading = {"anchor": attr["id"], "text": []}
            return

        if tag == "div":
            role = None
            if "cmd-ref" in classes:
                role = "cmd"
            elif "cmd-ref-header" in classes:
                role = "t"
            elif "cmd-ref-body" in classes:
                role = "x"
            self._divs.append(role)
            if role == "cmd":
                self._cmd = {"t": [], "x": []}
            elif role in ("t", "x") and self._cmd is not None:
                self._cmd_part = role

    def handle_endtag(self, tag: str) -> None:
        if self._skipped:
            if self._skipped[-1] == tag:
                self._skipped.pop()
            return

        if tag == "div":
            role = self._divs.pop() if self._divs else None
            if role == "cmd":
                self._flush_cmd()
            elif role in ("t", "x"):
                self._cmd_part = None
            return

        if tag in ("h1", "h2", "h3") and self._heading is not None:
            heading, self._heading = self._heading, None
            title = _collapse("".join(heading["text"]))
            if not title:
                return
            if heading["anchor"] is None:
                if self._cur is not None and not self._cur["t"]:
                    self._cur["t"] = title
                return
            self._open(heading["anchor"], title, self._crumb)

    def handle_data(self, data: str) -> None:
        if self._skipped:
            return
        if self._heading is not None:
            self._heading["text"].append(data)
            return
        if self._cmd is not None and self._cmd_part:
            self._cmd[self._cmd_part].append(data)
            return
        if self._cur is not None and len("".join(self._cur["x"])) < _SNIPPET_CHARS * 3:
            self._cur["x"].append(data)


def _build_search_index(
    file_name: str,
    page_label: str,
    content_html: str,
    sidebar_groups: list[tuple[str, list[tuple[str, str]]]],
) -> list[dict]:
    labels = dict(GENERATED_SECTION_LABELS)
    labels.update({
        anchor: (group, label)
        for group, items in sidebar_groups
        for anchor, label in items
    })
    parser = _SearchIndexExtractor(file_name, labels)
    parser.feed(content_html)
    parser.close()

    out: list[dict] = []
    for rec in parser.records:
        rec["x"] = _collapse("".join(rec["x"]))[:_SNIPPET_CHARS]
        if not rec["t"]:
            continue
        rec["p"] = page_label
        # The rendered breadcrumb is page + crumb, so a group named after its own
        # page would read "Adapters › Adapters › Cursor".
        crumb = rec["s"]
        if crumb == page_label:
            crumb = ""
        elif crumb.startswith(f"{page_label} › "):
            crumb = crumb[len(page_label) + 3 :]
        if crumb:
            rec["s"] = crumb
        else:
            rec.pop("s")
        out.append(rec)
    return out


def _write_search_index(records: list[dict]) -> None:
    """Emit the index as a script that assigns a global.

    A plain .json fetched at runtime would be blocked opening the site straight
    off disk; a script tag injected on first use works from file:// too and
    keeps the payload off the critical path.

    Indented, because every docs change regenerates this whole file and git has
    to be able to merge two of them. Minified it was one 120KB line: a single
    atom with nothing to align on, so any two docs branches conflicted across
    all of it and no one could resolve it by hand. Indented, the records and
    their fields are separate lines and git merges disjoint edits itself. The
    site pays half a kilobyte over the wire for it, after compression.
    """
    payload = json.dumps(records, indent=2, ensure_ascii=False)
    # Legal in JSON, a line break in JS source: escape them or a page with one
    # in its prose takes the whole index down.
    payload = payload.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    out = OUT_DIR / "search-index.js"
    out.write_text(f"window.MYCELIUM_SEARCH_INDEX = {payload};\n")
    print(f"  wrote {out.name} ({out.stat().st_size:,} bytes, {len(records)} records)")


# ── Main ──


_ID_ATTR = re.compile(r'\bid="([^"]+)"')
_BARE_FRAGMENT = re.compile(r'href="#([^"]+)"')


def _resolve_cross_page_anchors(
    built: list[tuple[tuple, str, list[tuple[str, list[tuple[str, str]]]]]],
) -> list[tuple[tuple, str, list[tuple[str, list[tuple[str, str]]]]]]:
    """Point body links at the page that actually holds the anchor.

    A source doc writes `[the aligner](#aligner)` without knowing which page its
    section lands on, so once split across files that link scrolls nowhere: the
    id lives on index.html, not reference.html. The sidebar already qualifies its
    hrefs with a file name; prose does it here, where every page is assembled and
    none written. An anchor on the current page stays bare.
    """
    owner: dict[str, str] = {}
    for page, content, _groups in built:
        file_name = page[1]
        for anchor in _ID_ATTR.findall(content):
            owner.setdefault(anchor, file_name)

    resolved = []
    for page, content, groups in built:
        file_name = page[1]
        here = set(_ID_ATTR.findall(content))

        def qualify(match: re.Match[str]) -> str:
            anchor = match.group(1)
            target = owner.get(anchor)
            if anchor in here or target is None or target == file_name:
                return match.group(0)
            return f'href="{target}#{anchor}"'

        resolved.append((page, _BARE_FRAGMENT.sub(qualify, content), groups))
    return resolved


def _render_and_write(
    page_id: str,
    file_name: str,
    title: str,
    description: str,
    content_html: str,
    nav: list[NavPage],
    sheet_no: str,
    plate_title: str,
) -> None:
    page_html = _render_page(
        page_id, file_name, title, description, content_html, nav,
        sheet_no, plate_title,
    )
    (OUT_DIR / file_name).write_text(page_html)
    print(f"  wrote {file_name} ({len(page_html):,} bytes)")


def _copy_diagrams() -> None:
    """Copy the rendered architecture SVGs next to the generated site.

    Source of truth is the .d2 alongside each .svg under
    docs/reference/diagrams/; only the .svg is published (the .d2 is for
    contributors re-rendering it, not for the site).
    """
    import shutil

    src_dir = DOCS_DIR / "reference" / "diagrams"
    if not src_dir.is_dir():
        return
    dst_dir = OUT_DIR / "diagrams"
    dst_dir.mkdir(exist_ok=True)
    for svg in src_dir.glob("*.svg"):
        shutil.copyfile(svg, dst_dir / svg.name)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--page",
        help="Write a single page by id (start|adapters|reference). Every page is "
             "still assembled, since the persistent nav lists them all.",
    )
    args = parser.parse_args()

    page_ids = {p[0] for p in PAGES}
    if args.page and args.page not in page_ids:
        raise SystemExit(f"Unknown page '{args.page}'. Choices: {sorted(page_ids)}")

    print("Copying diagram SVGs...")
    _copy_diagrams()

    print("Loading kept sections from existing HTML...")
    kept = _all_kept_sections()
    print(f"  found {len(kept)} kept section(s): {sorted(kept)}")

    print("Generating CLI reference from @doc_ref decorators...")
    cli_block = _generate_cli_reference()
    print("Generating config reference from pydantic schema...")
    config_block = _generate_config_reference()
    print("Generating dependency reference from pyproject + compose pins...")
    deps_block = _generate_dependencies_reference()

    # Assemble every page before writing any of them: the persistent nav and the
    # search index are both whole-site views, so a partial build would emit a
    # sidebar and an index missing the pages that were skipped.
    print("Assembling pages...")
    built: list[tuple[tuple, str, list[tuple[str, list[tuple[str, str]]]]]] = []
    nav: list[NavPage] = []
    for page in PAGES:
        page_id, file_name, _title, label, *_rest = page
        content, sidebar_groups = _build_page(
            page_id, kept, cli_block, config_block, deps_block
        )
        built.append((page, content, sidebar_groups))
        nav.append((page_id, file_name, label, sidebar_groups))
        n = sum(len(items) for _, items in sidebar_groups)
        print(f"  {file_name}: {n} subsections in {len(sidebar_groups)} groups")

    built = _resolve_cross_page_anchors(built)

    print("Rendering pages...")
    for page, content, _groups in built:
        page_id, file_name, title, _label, sheet_no, plate_title, description = page
        if args.page and page_id != args.page:
            continue
        _render_and_write(
            page_id, file_name, title, description, content, nav,
            sheet_no, plate_title,
        )

    if not args.page:
        records: list[dict] = []
        for page, content, sidebar_groups in built:
            page_id, file_name, _title, label, *_rest = page
            records.extend(
                _build_search_index(file_name, label, content, sidebar_groups)
            )
        _write_search_index(records)
        _write_llms_full()

    print("\nDone.")


def _write_llms_full() -> None:
    """Concatenate every markdown section into one file for LLM ingestion.

    The multi-page split means no single HTML page holds all the docs anymore,
    so this preserves the "feed the whole docs to an LLM" flow.
    """
    parts: list[str] = [
        "# Mycelium Documentation (full)\n",
        "Coordination layer for multi-agent systems. "
        "Concatenated from the source docs; see https://mycelium-io.github.io/mycelium/\n",
    ]
    for md_file, _section_id, _page_id, _group, _label in SECTION_CONFIG:
        if md_file is None:
            continue
        path = DOCS_DIR / md_file
        if not path.exists():
            continue
        parts.append("\n\n---\n\n" + path.read_text().rstrip() + "\n")
    out = OUT_DIR / "llms-full.txt"
    out.write_text("".join(parts))
    print(f"  wrote {out.name} ({out.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
