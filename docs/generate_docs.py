#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
Generate docs/index.html from markdown source files + CLI @doc_ref decorators.

Markdown files in mycelium-cli/src/mycelium/docs/ are the single source of truth.
This script converts them to HTML and injects them into the index.html template.

Run from repo root:
    cd mycelium-cli && uv run python ../docs/generate_docs.py
"""

from __future__ import annotations

import html
import re
from collections import defaultdict
from pathlib import Path

# ── Section config ──
# (md_filename, section_id, sidebar_section, sidebar_label)
# sidebar_section groups items under a nav-section-label.
SECTION_CONFIG: list[tuple[str, str, str, str]] = [
    ("overview.md", "overview", "Start here", "Overview"),
    ("quickstart.md", "quickstart", "Start here", "Quick Start"),
    ("rooms.md", "rooms", "Concepts", "Rooms"),
    ("sessions.md", "sessions", "Concepts", "Sessions"),
    ("memory.md", "memory", "Concepts", "Memory"),
    ("notebook.md", "notebook", "Concepts", "Notebook"),
    ("cognitive-engine.md", "cognitive-engine", "Concepts", "CognitiveEngine"),
    ("knowledge-graph.md", "knowledge-graph", "Concepts", "Knowledge Graph"),
    # cli-reference is handled separately by generate_cli_reference
    ("architecture.md", "architecture", "Architecture", "Architecture"),
    ("troubleshooting.md", "troubleshooting", "Help", "Troubleshooting"),
]

DOCS_DIR = Path(__file__).parent.parent / "mycelium-cli" / "src" / "mycelium" / "docs"
INDEX_PATH = Path(__file__).parent / "index.html"


# ── Markdown to HTML conversion (minimal, no dependencies) ──

def _md_to_html(md: str, section_id: str) -> str:
    """Convert markdown to HTML matching the docs site styling.

    Handles: headings, paragraphs, code blocks, tables, blockquotes,
    ordered/unordered lists, inline code, bold, links.
    """
    lines = md.split("\n")
    out: list[str] = []
    i = 0
    first_h1 = True

    while i < len(lines):
        line = lines[i]

        # Horizontal rule
        if line.strip() == "---":
            out.append('      <hr class="divider">')
            i += 1
            continue

        # Fenced code block
        if line.startswith("```"):
            lang = line[3:].strip()
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1  # skip closing ```
            code_content = _highlight_code("\n".join(code_lines), lang)
            out.append(f"      <pre><code>{code_content}</code></pre>")
            continue

        # Table
        if "|" in line and i + 1 < len(lines) and re.match(r"\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            table_html = _parse_table(lines, i)
            out.append(table_html)
            # Skip past table
            i += 2  # header + separator
            while i < len(lines) and "|" in lines[i] and lines[i].strip().startswith("|"):
                i += 1
            continue

        # Headings
        if line.startswith("# "):
            text = line[2:].strip()
            if first_h1:
                # First h1 becomes the section eyebrow + h1
                first_h1 = False
                i += 1
                # Collect lead paragraph (next non-empty line)
                lead_lines = []
                while i < len(lines) and lines[i].strip() and not lines[i].startswith("#") and not lines[i].startswith("```") and not lines[i].startswith("|") and not lines[i].startswith(">") and not lines[i].startswith("- ") and not lines[i].startswith("1."):
                    lead_lines.append(lines[i].strip())
                    i += 1
                lead = " ".join(lead_lines)
                if lead:
                    out.append(f'      <h1>{_inline(text)}</h1>')
                    out.append(f'      <p class="lead">{_inline(lead)}</p>')
                else:
                    out.append(f'      <h1>{_inline(text)}</h1>')
                continue
            out.append(f'      <h1>{_inline(text)}</h1>')
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

        # Blockquote → callout
        if line.startswith("> "):
            quote_lines = []
            while i < len(lines) and lines[i].startswith("> "):
                quote_lines.append(lines[i][2:])
                i += 1
            quote_text = " ".join(l.strip() for l in quote_lines)
            out.append('      <div class="callout callout-note">')
            out.append('        <div class="callout-bar"></div>')
            out.append(f'        <div class="callout-body">{_inline(quote_text)}</div>')
            out.append("      </div>")
            continue

        # Ordered list → steps
        if re.match(r"^\d+\.\s", line):
            out.append('      <ol class="steps">')
            while i < len(lines) and re.match(r"^\d+\.\s", lines[i]):
                item_text = re.sub(r"^\d+\.\s+", "", lines[i])
                out.append(f"        <li>{_inline(item_text)}</li>")
                i += 1
            out.append("      </ol>")
            continue

        # Unordered list
        if line.startswith("- "):
            out.append("      <ul>")
            while i < len(lines) and lines[i].startswith("- "):
                item_text = lines[i][2:]
                out.append(f"        <li>{_inline(item_text)}</li>")
                i += 1
            out.append("      </ul>")
            continue

        # Empty line
        if not line.strip():
            i += 1
            continue

        # Paragraph — collect consecutive non-empty, non-special lines
        para_lines = []
        while i < len(lines) and lines[i].strip() and not lines[i].startswith("#") and not lines[i].startswith("```") and not lines[i].startswith("|") and not lines[i].startswith(">") and not lines[i].startswith("- ") and not re.match(r"^\d+\.\s", lines[i]):
            para_lines.append(lines[i].strip())
            i += 1
        if para_lines:
            out.append(f"      <p>{_inline(' '.join(para_lines))}</p>")
        continue

    return "\n".join(out)


def _slugify(text: str) -> str:
    """Convert heading text to URL-friendly anchor slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s]+", "-", text)
    return text.strip("-")


def _inline(text: str) -> str:
    """Convert inline markdown (bold, code, links) to HTML."""
    text = html.escape(text)
    # Bold
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    # Inline code
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    # Links  [text](url)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


def _highlight_code(code: str, lang: str) -> str:
    """Apply simple syntax highlighting classes to shell code blocks."""
    if lang not in ("bash", "sh", ""):
        return html.escape(code)

    lines = code.split("\n")
    out = []
    for line in lines:
        if line.strip().startswith("#"):
            out.append(f'<span class="comment">{html.escape(line)}</span>')
        else:
            highlighted = html.escape(line)
            # Flags like --mode, -r, -H, -m
            highlighted = re.sub(
                r"(\s)(--?\w[\w-]*)",
                r'\1<span class="flag">\2</span>',
                highlighted,
            )
            # Quoted strings
            highlighted = re.sub(
                r'(&quot;[^&]*&quot;)',
                r'<span class="str">\1</span>',
                highlighted,
            )
            # mycelium commands
            highlighted = re.sub(
                r"(mycelium\s+\w+(?:\s+\w+)?)",
                r'<span class="cmd">\1</span>',
                highlighted,
            )
            out.append(highlighted)
    return "\n".join(out)


def _highlight_usage(usage: str) -> str:
    """Syntax-highlight a CLI usage string for the docs site.

    Applies .cmd to the command, .flag to flags, .arg to placeholders,
    and .str to quoted strings.
    """
    s = html.escape(usage)
    # Command prefix: "mycelium <subcommand> [<subcommand>]"
    s = re.sub(r"^(mycelium(?:\s+\w+){1,2})", r'<span class="cmd">\1</span>', s)
    # Quoted strings
    s = re.sub(r'(&quot;[^&]*&quot;)', r'<span class="str">\1</span>', s)
    # Flags: --foo, -f (after whitespace or bracket)
    s = re.sub(r"([\s\[])(-{1,2}\w[\w-]*)", r'\1<span class="flag">\2</span>', s)
    # Angle-bracket placeholders: <url>, <key>
    s = re.sub(r"(&lt;\w+&gt;)", r'<span class="arg">\1</span>', s)
    # Bare UPPER placeholders: ROOM, KEY, QUERY (only fully uppercase words 2+ chars)
    s = re.sub(r"(?<=\s)([A-Z]{2,})(?=[\s\]\)]|$)", r'<span class="arg">\1</span>', s)
    return s


def _parse_table(lines: list[str], start: int) -> str:
    """Parse a markdown table into HTML."""
    header_line = lines[start].strip().strip("|")
    headers = [h.strip() for h in header_line.split("|")]

    # Skip separator line
    row_start = start + 2

    rows = []
    i = row_start
    while i < len(lines) and "|" in lines[i] and lines[i].strip().startswith("|"):
        row_line = lines[i].strip().strip("|")
        cells = [c.strip() for c in row_line.split("|")]
        rows.append(cells)
        i += 1

    out = ['      <div class="table-wrap">', "        <table>", "          <thead>", "            <tr>"]
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


# ── CLI Reference generation (from @doc_ref) ──

GROUP_CONFIG: list[tuple[str, str, str]] = [
    ("setup", "setup", "setup"),
    ("room", "room", "room"),
    ("session", "session", "session"),
    ("memory", "memory", "memory"),
    ("notebook", "notebook", "notebook"),
    ("message", "message", "message"),
    ("adapter", "adapter", "adapter"),
    ("config", "config", "config"),
    ("other", "synthesize / catchup / watch", "synthesize / catchup / watch"),
]


def _generate_cli_reference() -> tuple[str, str]:
    """Generate CLI Reference HTML section and sidebar nav from @doc_ref."""
    from mycelium.doc_ref import get_registry

    # Force-import all command modules so decorators run
    import mycelium.commands.adapter  # noqa: F401
    import mycelium.commands.config  # noqa: F401
    import mycelium.commands.instance  # noqa: F401
    import mycelium.commands.install  # noqa: F401
    import mycelium.commands.memory  # noqa: F401
    import mycelium.commands.message  # noqa: F401
    import mycelium.commands.notebook  # noqa: F401
    import mycelium.commands.room  # noqa: F401
    import mycelium.commands.session  # noqa: F401

    entries = get_registry()

    groups: dict[str, list] = defaultdict(list)
    for entry in entries:
        groups[entry.group].append(entry)

    section_lines = ['      <h2>CLI Reference</h2>']
    sidebar_links = []

    for group_key, heading, sidebar_label in GROUP_CONFIG:
        if group_key not in groups:
            continue

        anchor = f"cli-{group_key}"
        section_lines.append("")
        section_lines.append(f'      <h3 id="{anchor}">{html.escape(heading)}</h3>')

        sidebar_links.append(
            f'      <a href="#{anchor}" class="nav-link sub">{html.escape(sidebar_label)}</a>'
        )

        for entry in groups[group_key]:
            highlighted_usage = _highlight_usage(entry.usage)
            section_lines.append("")
            section_lines.append('      <div class="cmd-ref">')
            section_lines.append('        <div class="cmd-ref-header">')
            section_lines.append(f"          <code>{highlighted_usage}</code>")
            section_lines.append("        </div>")
            section_lines.append(f'        <div class="cmd-ref-body">{entry.desc}</div>')
            section_lines.append("      </div>")

    section_html = "\n".join(section_lines)

    sidebar_html = "\n".join([
        '    <div class="nav-section">',
        '      <div class="nav-section-label">CLI Reference</div>',
        *sidebar_links,
        "    </div>",
    ])

    return section_html, sidebar_html


# ── Sidebar generation from markdown sections ──

def _generate_sidebar() -> str:
    """Generate the full sidebar nav HTML from section config."""
    sections_by_group: dict[str, list[tuple[str, str]]] = {}
    for _, section_id, sidebar_section, sidebar_label in SECTION_CONFIG:
        sections_by_group.setdefault(sidebar_section, []).append((section_id, sidebar_label))

    out = []
    for group_name, items in sections_by_group.items():
        out.append('    <div class="nav-section">')
        out.append(f'      <div class="nav-section-label">{html.escape(group_name)}</div>')
        for section_id, label in items:
            sub = " sub" if len(items) > 1 and group_name != "Architecture" else ""
            out.append(f'      <a href="#{section_id}" class="nav-link{sub}">{html.escape(label)}</a>')
        out.append("    </div>")

    return "\n".join(out)


# ── Main content generation ──

def _extract_kept_sections(html: str) -> dict[str, str]:
    """Extract sections marked <!-- keep --> from existing index.html.

    Sections with this comment are hand-crafted HTML (interactive components,
    card grids, etc.) that can't be expressed in markdown. The generator
    preserves them verbatim. Remove the comment to switch to markdown-generated.
    """
    kept: dict[str, str] = {}
    for m in re.finditer(
        r'(<section\s+class="doc-section"\s+id="([^"]+)"[^>]*>.*?</section>)',
        html,
        re.DOTALL,
    ):
        if "<!-- keep -->" in m.group(1):
            kept[m.group(2)] = m.group(1)
    return kept


def _generate_content_sections(existing_html: str) -> str:
    """Generate all content section HTML from markdown files.

    Sections in the existing HTML that contain <!-- keep --> are preserved
    verbatim. All others are regenerated from their markdown source.
    """
    kept = _extract_kept_sections(existing_html)
    sections = []

    for md_file, section_id, _, _ in SECTION_CONFIG:
        if section_id in kept:
            print(f"  {section_id}: kept (hand-crafted HTML)")
            sections.append(kept[section_id])
        else:
            md_path = DOCS_DIR / md_file
            if not md_path.exists():
                print(f"  WARNING: {md_path} not found, skipping")
                continue

            md_content = md_path.read_text()
            section_html = _md_to_html(md_content, section_id)

            sections.append(f'    <section class="doc-section" id="{section_id}">')
            sections.append(section_html)
            sections.append("    </section>")

        sections.append("")
        sections.append('    <hr class="divider">')
        sections.append("")

    return "\n".join(sections)


# ── Template replacement ──

def _replace_between_markers(content: str, marker: str, replacement: str) -> str:
    """Replace content between <!-- marker --> and <!-- /marker --> comments."""
    pattern = re.compile(
        rf"(<!-- {re.escape(marker)} -->).*?(<!-- /{re.escape(marker)} -->)",
        re.DOTALL,
    )
    match = pattern.search(content)
    if not match:
        msg = f"Could not find <!-- {marker} --> markers in index.html"
        raise RuntimeError(msg)
    return (
        content[: match.start(1)]
        + match.group(1) + "\n"
        + replacement + "\n"
        + match.group(2)
        + content[match.end(2) :]
    )


def main() -> None:
    content = INDEX_PATH.read_text()

    # Generate content sections from markdown
    print("Generating content sections from markdown...")
    sections_html = _generate_content_sections(content)
    content = _replace_between_markers(content, "codegen:content", sections_html)

    # Generate CLI reference from @doc_ref
    print("Generating CLI reference from @doc_ref decorators...")
    cli_html, cli_sidebar = _generate_cli_reference()
    content = _replace_between_markers(content, "codegen:cli-reference", cli_html)

    # Generate sidebar
    print("Generating sidebar navigation...")
    sidebar_html = _generate_sidebar()
    content = _replace_between_markers(content, "codegen:sidebar", sidebar_html)

    # CLI sidebar
    content = _replace_between_markers(content, "codegen:cli-sidebar", cli_sidebar)

    INDEX_PATH.write_text(content)

    from mycelium.doc_ref import get_registry
    entries = get_registry()
    groups = defaultdict(list)
    for e in entries:
        groups[e.group].append(e)

    print(f"\nUpdated docs/index.html:")
    print(f"  {len(SECTION_CONFIG)} content sections from markdown")
    print(f"  {len(entries)} CLI commands from @doc_ref:")
    for group_key, heading, _ in GROUP_CONFIG:
        if group_key in groups:
            print(f"    {heading}: {len(groups[group_key])} commands")


if __name__ == "__main__":
    main()
