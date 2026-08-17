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

Regenerate one page only:
    cd mycelium-cli && uv run python ../docs/generate_docs.py --page concepts
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from collections import defaultdict
from pathlib import Path

# ── Page layout ──
# 3 pages, each a long doc with a grouped sidebar.
# (page_id, file_name, page_title, top_nav_label, sheet_no, plate_title, meta_description)
PAGES: list[tuple[str, str, str, str, str, str, str]] = [
    ("start", "index.html", "mycelium Docs", "Get Started",
     "GET-001", "OVERVIEW · INSTALL · FIRST ROOM · COORDINATE",
     "Coordination layer for multi-agent systems. Install and run your first multi-agent coordination flow: room, agents, negotiation, plan."),
    ("concepts", "concepts.html", "Concepts · mycelium", "Concepts",
     "CON-001", "CONCEPTS · ROOMS · EPISODES · MEMORY · PLAN",
     "The core concepts behind Mycelium: rooms, episodes, memory, plan, engines (the aligner and synthesizer), and the L9 protocol."),
    ("adapters", "adapters.html", "Adapters · mycelium", "Adapters",
     "ADP-001", "ADAPTERS · CLAUDE CODE · CURSOR · REST API",
     "Connect Claude Code, Cursor, or any HTTP client to the Mycelium coordination layer."),
    ("reference", "reference.html", "Reference · mycelium", "Reference",
     "REF-001", "REFERENCE · ARCHITECTURE · CLI · CONFIG · GUIDES · HELP",
     "Architecture, CLI reference, configuration, guides, and troubleshooting for Mycelium."),
]

# Sections, in render order per page.
# (md_file_or_None, section_id, page_id, sidebar_group, sidebar_label)
# md_file=None means the section is hand-coded (kept verbatim from source HTML).
# If md_file is set AND a kept section with the same id exists, the kept HTML wins.
SECTION_CONFIG: list[tuple[str | None, str, str, str, str]] = [
    # ── start (index.html) — overview + quickstart ──
    ("overview.md",                 "overview",           "start",       "Get Started",  "Overview"),
    ("quickstart.md",               "quickstart",         "start",       "Get Started",  "Quick Start"),
    # ── concepts (concepts.html) ──
    ("rooms.md",                    "rooms",              "concepts",    "Concepts",     "Rooms"),
    ("principals.md",               "users",              "concepts",    "Concepts",     "Users & Teams"),
    ("episodes.md",                 "episodes",           "concepts",    "Concepts",     "Episodes"),
    ("memory.md",                   "memory",             "concepts",    "Concepts",     "Memory"),
    ("plan.md",                     "plan",               "concepts",    "Concepts",     "Plan"),
    ("l9-protocol.md",              "l9-protocol",        "concepts",    "Concepts",     "L9 Protocol"),
    # Engines are a nested group: the overview, then one page per kind.
    ("engines.md",                  "engines",            "concepts",    "Engines",      "Overview"),
    ("aligner.md",                  "aligner",            "concepts",    "Engines",      "Aligner"),
    ("synthesizer.md",              "synthesizer",        "concepts",    "Engines",      "Synthesizer"),
    # ── adapters (adapters.html) — all hand-coded ──
    (None,                          "adapters",           "adapters",  "Adapters",     "Overview"),
    (None,                          "adapter-claude-code","adapters",  "Adapters",     "Claude Code"),
    (None,                          "adapter-cursor",     "adapters",  "Adapters",     "Cursor"),
    (None,                          "adapter-api",        "adapters",  "Adapters",     "REST API"),
    # ── reference (reference.html) ──
    ("architecture.md",             "architecture",       "reference", "Architecture", "Architecture"),
    # CLI + Config blocks injected after architecture, before guides/troubleshooting.
    ("guides/structured-memory.md", "structured-memory",  "reference", "Guides",       "Structured Memory"),
    ("guides/hub-and-spoke.md",     "hub-and-spoke",      "reference", "Guides",       "Hub & Spoke"),
    ("guides/auth.md",              "auth",               "reference", "Guides",       "Authentication"),
    ("guides/keycloak-oidc.md",     "keycloak-oidc",      "reference", "Guides",       "Keycloak / OIDC Setup"),
    ("guides/spire-identity.md",    "spire-identity",     "reference", "Guides",       "Attested Identity (SPIRE)"),
    ("troubleshooting.md",          "troubleshooting",    "reference", "Help",         "Troubleshooting"),
]

# IDs that should be looked up in kept HTML (have <!-- keep --> markers, or rescued by id).
_KEPT_IDS: set[str] = {
    "overview",
    "adapters", "adapter-claude-code", "adapter-cursor", "adapter-api",
}

# CLI groups for the cli-reference page.
GROUP_CONFIG: list[tuple[str, str, str]] = [
    ("setup", "setup", "setup"),
    ("room", "room", "room"),
    ("session", "session", "session"),
    ("agent", "agent", "agent"),
    ("memory", "memory", "memory"),
    ("skill", "skill", "skill"),
    ("plan", "plan", "plan"),
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

DOCS_DIR = Path(__file__).parent.parent / "mycelium-cli" / "src" / "mycelium" / "docs"
OUT_DIR = Path(__file__).parent
LEGACY_INDEX = OUT_DIR / "index.html"  # for kept-section migration


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
            out.append('      <div class="callout callout-note">')
            out.append('        <div class="callout-bar"></div>')
            out.append(f'        <div class="callout-body">{_inline(quote_text)}</div>')
            out.append("      </div>")
            continue

        if re.match(r"^\d+\.\s", line):
            out.append('      <ol class="steps">')
            while i < len(lines) and re.match(r"^\d+\.\s", lines[i]):
                item_text = re.sub(r"^\d+\.\s+", "", lines[i])
                out.append(f"        <li>{_inline(item_text)}</li>")
                i += 1
            out.append("      </ol>")
            continue

        if line.startswith("- "):
            out.append("      <ul>")
            while i < len(lines) and lines[i].startswith("- "):
                item_text = lines[i][2:]
                out.append(f"        <li>{_inline(item_text)}</li>")
                i += 1
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
                f"(line {i + 1}): {lines[i]!r} — skipping",
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
        else:
            highlighted = html.escape(line)
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
            highlighted = re.sub(
                r"(mycelium\s+\w+(?:\s+\w+)?)",
                r'<span class="cmd">\1</span>',
                highlighted,
            )
            out.append(highlighted)
    return "\n".join(out)


def _highlight_usage(usage: str) -> str:
    s = html.escape(usage)
    s = re.sub(r"^(mycelium(?:\s+\w+){1,2})", r'<span class="cmd">\1</span>', s)
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
    import mycelium.commands.config  # noqa: F401
    import mycelium.commands.doctor  # noqa: F401
    import mycelium.commands.hub  # noqa: F401
    import mycelium.commands.install  # noqa: F401
    import mycelium.commands.instance  # noqa: F401
    import mycelium.commands.login  # noqa: F401
    import mycelium.commands.memory  # noqa: F401
    import mycelium.commands.participate  # noqa: F401
    import mycelium.commands.plan  # noqa: F401
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


def _head(title: str, description: str, file_name: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
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
    var t = localStorage.getItem('mycelium-theme') || 'system';
    var dark = t === 'dark'
      || (t === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);
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


def _topnav(active_page_id: str) -> str:
    """The app's shell header: brand over the rail, page tabs, right-hand actions.

    The brand cell is sidebar-width so the rail reads as one column, matching
    RoomsSidebar sitting under the workspace header in the app.
    """
    tabs = []
    for page_id, file_name, _, label, *_ in PAGES:
        cls = "active" if page_id == active_page_id else ""
        tabs.append(f'      <a href="{file_name}" class="{cls}">{html.escape(label)}</a>')
    return f"""<!-- TOP BAR -->
<nav class="topnav">
  <a href="https://mycelium-io.github.io" class="topnav-cell topnav-brand">
    <img src="logo.png" alt="Mycelium">
    <span class="brand-word">mycelium</span>
  </a>
  <nav class="sectionnav">
    <div class="sectionnav-inner">
{chr(10).join(tabs)}
    </div>
    <div class="sectionnav-right">
      <a href="{SKILL_MD_URL}" target="_blank" rel="noopener">SKILL.md ↗</a>
    </div>
  </nav>
  <div class="topnav-right">
    <div class="resources-dropdown">
      <button class="resources-btn" onclick="toggleResources(event)">Resources</button>
      <div class="resources-menu" id="resources-menu">
        <a href="index.html">Get Started</a>
        <a href="concepts.html">Concepts</a>
        <a href="adapters.html">Adapters</a>
        <a href="reference.html">Reference</a>
        <a href="{SKILL_MD_URL}" target="_blank" rel="noopener">SKILL.md ↗</a>
      </div>
    </div>
    <button class="copy-docs-btn" onclick="copyDocsCmd()"><i data-lucide="terminal"></i>Copy docs cmd</button>
    <button class="copy-page-btn" onclick="copyPage()"><i data-lucide="copy"></i>Copy page</button>
{_theme_toggle()}
    <a href="https://github.com/mycelium-io/mycelium" aria-label="GitHub">{GITHUB_SVG}</a>
  </div>
</nav>
"""


def _sidebar(groups: list[tuple[str, list[tuple[str, str]]]]) -> str:
    """Render a grouped sidebar: [(group_label, [(anchor, label), ...]), ...]."""
    out = ['  <nav class="sidebar">']
    for group_label, items in groups:
        out.append('    <div class="nav-section">')
        out.append(
            f'      <div class="nav-section-label">{html.escape(group_label)}</div>'
        )
        for anchor, label in items:
            out.append(
                f'      <a href="#{anchor}" class="nav-link sub">'
                f'{html.escape(label)}</a>'
            )
        out.append("    </div>")
    out.append("  </nav>")
    return "\n".join(out)


def _layout_open(sidebar_html: str) -> str:
    return f"""<div class="layout">

{sidebar_html}

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
  <span class="sheet-no">{html.escape(sheet_no)}</span>
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
    sidebar_groups: list[tuple[str, list[tuple[str, str]]]],
    sheet_no: str,
    plate_title: str,
) -> str:
    sidebar_html = _sidebar(sidebar_groups)
    return (
        _head(title, description, file_name)
        + _topnav(page_id)
        + _layout_open(sidebar_html)
        + content_html
        + "\n"
        + _layout_close(sheet_no, plate_title)
    )


# ── Page content builders ──


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
        f"    </section>"
    )


def _build_page(
    page_id: str,
    kept: dict[str, str],
    cli_block: tuple[str, list[tuple[str, str]]] | None = None,
    config_block: tuple[str, list[tuple[str, str]]] | None = None,
) -> tuple[str, list[tuple[str, list[tuple[str, str]]]]]:
    """Build (content_html, sidebar_groups) for a single page.

    sidebar_groups: list of (group_label, [(anchor, label), ...]) preserving order.
    For the reference page, cli_block + config_block (each a (html, sidebar_entries))
    are inserted between architecture and troubleshooting.
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

    content = "\n\n    <hr class=\"divider\">\n\n".join(parts)
    sidebar_groups = [(g, grouped[g]) for g in group_order]
    return content, sidebar_groups


# ── Main ──


def _render_and_write(
    page_id: str,
    file_name: str,
    title: str,
    description: str,
    content_html: str,
    sidebar_groups: list[tuple[str, list[tuple[str, str]]]],
    sheet_no: str,
    plate_title: str,
) -> None:
    page_html = _render_page(
        page_id, file_name, title, description, content_html, sidebar_groups,
        sheet_no, plate_title,
    )
    (OUT_DIR / file_name).write_text(page_html)
    n = sum(len(items) for _, items in sidebar_groups)
    print(f"  wrote {file_name} ({len(page_html):,} bytes, {n} subsections in {len(sidebar_groups)} groups)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--page",
        help="Regenerate a single page by id (start|concepts|adapters|reference).",
    )
    args = parser.parse_args()

    pages_to_build = {p[0] for p in PAGES}
    if args.page:
        if args.page not in pages_to_build:
            raise SystemExit(f"Unknown page '{args.page}'. Choices: {sorted(pages_to_build)}")
        pages_to_build = {args.page}

    print("Loading kept sections from existing HTML...")
    kept = _all_kept_sections()
    print(f"  found {len(kept)} kept section(s): {sorted(kept)}")

    cli_block: tuple[str, list[tuple[str, str]]] | None = None
    config_block: tuple[str, list[tuple[str, str]]] | None = None
    if "reference" in pages_to_build:
        print("Generating CLI reference from @doc_ref decorators...")
        cli_block = _generate_cli_reference()
        print("Generating config reference from pydantic schema...")
        config_block = _generate_config_reference()

    print("Rendering pages...")
    for page_id, file_name, title, _label, sheet_no, plate_title, description in PAGES:
        if page_id not in pages_to_build:
            continue
        content, sidebar_groups = _build_page(page_id, kept, cli_block, config_block)
        _render_and_write(
            page_id, file_name, title, description, content, sidebar_groups,
            sheet_no, plate_title,
        )

    if not args.page:
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
