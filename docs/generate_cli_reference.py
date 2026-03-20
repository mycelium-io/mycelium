#!/usr/bin/env python3
"""
Generate the CLI Reference HTML section for docs/index.html.

Reads @doc_ref decorators from the CLI codebase and replaces the
CLI Reference section in index.html with the generated HTML.

Run from repo root:
    cd mycelium-cli && uv run python ../docs/generate_cli_reference.py
"""

from __future__ import annotations

import html
import re
from collections import defaultdict
from pathlib import Path

# Group display config — controls section headings and sidebar labels.
# Order here = order in the docs page.
GROUP_CONFIG: list[tuple[str, str, str]] = [
    # (group_key, heading_text, sidebar_label)
    ("room", "room", "room"),
    ("memory", "memory", "memory"),
    ("notebook", "notebook", "notebook"),
    ("message", "message", "message"),
    ("other", "synthesize / catchup / watch", "synthesize / catchup / watch"),
]


def _generate_html() -> tuple[str, str]:
    """Generate CLI Reference HTML section and sidebar nav.

    Returns (section_html, sidebar_html).
    """
    # Import triggers all @doc_ref decorators to register
    from mycelium.doc_ref import get_registry

    # Force-import all command modules so decorators run
    import mycelium.commands.memory  # noqa: F401
    import mycelium.commands.message  # noqa: F401
    import mycelium.commands.notebook  # noqa: F401
    import mycelium.commands.room  # noqa: F401

    entries = get_registry()

    # Group entries by group key, preserving registration order
    groups: dict[str, list] = defaultdict(list)
    for entry in entries:
        groups[entry.group].append(entry)

    # Build section HTML
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
            escaped_usage = html.escape(entry.usage)
            section_lines.append("")
            section_lines.append('      <div class="cmd-ref">')
            section_lines.append('        <div class="cmd-ref-header">')
            section_lines.append(f"          <code>{escaped_usage}</code>")
            section_lines.append("        </div>")
            # desc may contain intentional HTML (<code> tags), don't escape it
            section_lines.append(f'        <div class="cmd-ref-body">{entry.desc}</div>')
            section_lines.append("      </div>")

    section_html = "\n".join(section_lines)

    sidebar_html = "\n".join(
        [
            '    <div class="nav-section">',
            '      <div class="nav-section-label">CLI Reference</div>',
            *sidebar_links,
            "    </div>",
        ]
    )

    return section_html, sidebar_html


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
    return content[: match.start(1)] + match.group(1) + "\n" + replacement + "\n" + match.group(2) + content[match.end(2) :]


def _update_index_html(section_html: str, sidebar_html: str) -> None:
    """Replace the CLI Reference section and sidebar nav in docs/index.html."""
    index_path = Path(__file__).parent / "index.html"
    content = index_path.read_text()

    content = _replace_between_markers(content, "codegen:cli-reference", section_html)
    content = _replace_between_markers(content, "codegen:cli-sidebar", sidebar_html)

    index_path.write_text(content)


def main() -> None:
    section_html, sidebar_html = _generate_html()
    _update_index_html(section_html, sidebar_html)

    # Count commands
    from mycelium.doc_ref import get_registry

    entries = get_registry()
    groups = defaultdict(list)
    for e in entries:
        groups[e.group].append(e)

    print(f"Updated docs/index.html with {len(entries)} commands:")
    for group_key, heading, _ in GROUP_CONFIG:
        if group_key in groups:
            print(f"  {heading}: {len(groups[group_key])} commands")


if __name__ == "__main__":
    main()
