# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Documentation commands for Mycelium CLI.

Provides built-in, agent-friendly documentation accessible from the command line.
Section files mirror the GUI docs at mycelium-io.github.io/mycelium/; markdown
is the single source of truth for both.
"""

import re
from importlib import resources
from pathlib import Path

import typer

app = typer.Typer(
    help="Browse and search built-in documentation for Mycelium concepts, protocols, and API reference.",
    invoke_without_command=True,
)

# Ordered list of doc sections (topic → display name). Order matches the GUI
# sidebar. A topic is the stem alone regardless of which subdirectory holds the
# file, so "mycelium docs rooms" is stable across a source reorganisation.
SECTIONS: list[tuple[str, str]] = [
    ("overview", "Overview"),
    ("quickstart", "Quick Start"),
    ("rooms", "Rooms"),
    ("principals", "Users & Teams"),
    ("episodes", "Episodes"),
    ("memory", "Memory"),
    ("plan", "Plan"),
    ("l9-protocol", "L9 Protocol"),
    ("engines", "Engines"),
    ("aligner", "The Aligner"),
    ("synthesizer", "The Synthesizer"),
    ("hello", "Hello"),
    ("architecture", "Architecture"),
    ("structured-memory", "Structured Memory"),
    ("hub-and-spoke", "Hub & Spoke"),
    ("ephemeral-agents", "Ephemeral Agents"),
    ("security-planes", "Security Planes"),
    ("auth", "Authentication"),
    ("keycloak-oidc", "Keycloak / OIDC Setup"),
    ("metrics", "Metrics"),
    ("troubleshooting", "Troubleshooting"),
]

# Subdirectories the docs tree is organised into, in lookup order. "commands"
# and "examples" are older layouts that some installs may still carry.
_DOC_DIRS = ("concepts", "guides", "reference", "adapters", "commands", "examples")


def _resolve_topic(docs_root: Path, topic: str) -> Path | None:
    """Find a topic's markdown file, wherever the tree currently keeps it."""
    direct = docs_root / f"{topic}.md"
    if direct.exists():
        return direct
    for dir_name in _DOC_DIRS:
        candidate = docs_root / dir_name / f"{topic}.md"
        if candidate.exists():
            return candidate
    return None


def _get_docs_root() -> Path:
    """Get the path to the bundled docs directory."""
    try:
        with resources.as_file(resources.files("mycelium").joinpath("docs")) as docs_path:
            return docs_path
    except (TypeError, FileNotFoundError):
        return Path(__file__).parent.parent / "docs"


def _extract_title(path: Path) -> str:
    """Extract the first markdown heading as the title."""
    try:
        content = path.read_text()
        for line in content.split("\n"):
            if line.startswith("# "):
                return line[2:].strip()
        return path.stem.replace("-", " ").title()
    except Exception:
        return path.stem.replace("-", " ").title()


def _list_docs(docs_root: Path, section: str | None = None) -> list[tuple[str, str, str]]:
    """List available documentation files."""
    results = []
    if section:
        # List files in a legacy subdirectory
        section_path = docs_root / section
        if section_path.is_dir():
            for f in sorted(section_path.glob("*.md")):
                results.append((section, f.stem, _extract_title(f)))
        return results

    named = {stem for stem, _ in SECTIONS}
    for stem, display_name in SECTIONS:
        if _resolve_topic(docs_root, stem):
            results.append(("", stem, display_name))

    # Anything in the tree that SECTIONS does not name, so nothing is invisible.
    for dir_name in _DOC_DIRS:
        section_path = docs_root / dir_name
        if not section_path.is_dir():
            continue
        for f in sorted(section_path.glob("*.md")):
            if f.stem not in named:
                results.append((dir_name, f.stem, _extract_title(f)))

    return results


def _find_doc(docs_root: Path, section: str, topic: str) -> Path | None:
    """Find a documentation file by section and topic."""
    doc_path = docs_root / section / f"{topic}.md"
    if doc_path.exists():
        return doc_path
    if section == "index" or topic == "index":
        index_path = docs_root / "index.md"
        if index_path.exists():
            return index_path
    # A stale section name should not hide a topic that simply moved.
    return _resolve_topic(docs_root, topic)


def _render_markdown(content: str, full: bool = False) -> str:
    """Render markdown for terminal display."""
    if full:
        return content
    lines = []
    in_code_block = False
    for line in content.split("\n"):
        if line.startswith("```"):
            in_code_block = not in_code_block
            lines.append(line)
            continue
        if in_code_block:
            lines.append(line)
            continue
        if line.startswith("# "):
            lines.append(typer.style(line[2:], bold=True, fg=typer.colors.CYAN))
        elif line.startswith("## "):
            lines.append("")
            lines.append(typer.style(line[3:], bold=True))
        elif line.startswith("### "):
            lines.append("")
            lines.append(typer.style(line[4:], fg=typer.colors.WHITE))
        else:
            lines.append(line)
    return "\n".join(lines)


def _concat_all(docs_root: Path) -> str:
    """Concatenate all section markdown files in order."""
    parts = []
    for stem, _ in SECTIONS:
        md_path = _resolve_topic(docs_root, stem)
        if md_path:
            parts.append(md_path.read_text().rstrip())
    return "\n\n---\n\n".join(parts) + "\n"


def _search_docs(
    docs_root: Path, query: str, context_lines: int = 2
) -> list[tuple[str, str, str, list[str]]]:
    """Search documentation for a query."""
    results = []
    query_lower = query.lower()
    query_pattern = re.compile(re.escape(query), re.IGNORECASE)

    search_files: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for stem, _ in SECTIONS:
        md_path = _resolve_topic(docs_root, stem)
        if md_path:
            search_files.append(("", md_path))
            seen.add(md_path)

    for dir_name in _DOC_DIRS:
        section_path = docs_root / dir_name
        if section_path.is_dir():
            for f in sorted(section_path.glob("*.md")):
                if f not in seen:
                    search_files.append((dir_name, f))

    # Also search index
    index_path = docs_root / "index.md"
    if index_path.exists():
        search_files.append(("", index_path))

    for section_name, f in search_files:
        try:
            content = f.read_text()
        except Exception:
            continue
        if query_lower not in content.lower():
            continue
        title = _extract_title(f)
        lines = content.split("\n")
        context = []
        for i, line in enumerate(lines):
            if query_lower in line.lower():
                start = max(0, i - context_lines)
                end = min(len(lines), i + context_lines + 1)
                for j in range(start, end):
                    ctx_line = lines[j].strip()
                    if not ctx_line:
                        continue
                    highlighted = query_pattern.sub(
                        lambda m: typer.style(m.group(), fg=typer.colors.YELLOW, bold=True),
                        ctx_line[:100],
                    )
                    context.append(highlighted)
                break
        stem = f.stem
        results.append((section_name, stem, title, context))

    return results


@app.callback(invoke_without_command=True)
def docs_main(
    ctx: typer.Context,
    section: str | None = typer.Argument(None),
    topic: str | None = typer.Argument(None),
    full: bool = typer.Option(False, "--full", "-f", is_eager=True),
    list_all: bool = typer.Option(False, "--list", "-l", is_eager=True),
) -> None:
    """
    Built-in documentation for Mycelium CLI.

    Examples:
        mycelium docs                    # Index
        mycelium docs --full             # Dump all sections as markdown
        mycelium docs overview           # Read a section
        mycelium docs rooms              # Rooms documentation
        mycelium docs --list             # List all docs
        mycelium docs search "memory"    # Search all docs
        mycelium docs concepts rooms     # Legacy: read from subdirectory
    """
    if ctx.invoked_subcommand is not None:
        return

    docs_root = _get_docs_root()

    if not docs_root.exists():
        typer.secho("Documentation not found.", fg=typer.colors.RED)
        raise typer.Exit(1)

    if list_all:
        _print_doc_list(docs_root)
        return

    if section == "search":
        if not topic:
            typer.secho("Usage: mycelium docs search QUERY", fg=typer.colors.RED)
            raise typer.Exit(1)
        _do_search(docs_root, topic)
        return

    # No section: show index or --full dump
    if not section:
        if full:
            typer.echo(_concat_all(docs_root))
            return
        doc_path = docs_root / "index.md"
        if doc_path.exists():
            typer.echo(_render_markdown(doc_path.read_text(), full=False))
        else:
            _print_doc_list(docs_root)
        return

    # A bare topic ("mycelium docs rooms") resolves wherever the file lives.
    if not topic:
        resolved = _resolve_topic(docs_root, section)
        if resolved:
            content = resolved.read_text()
            if full:
                typer.echo(content)
            else:
                typer.echo(_render_markdown(content, full=False))
            return

        # Try legacy subdirectory
        section_path = docs_root / section
        if section_path.is_dir():
            _print_section_list(docs_root, section)
            return

        typer.secho(f"Section not found: {section}", fg=typer.colors.RED)
        typer.secho(
            "Run 'mycelium docs --list' to see available docs.", fg=typer.colors.BRIGHT_BLACK
        )
        raise typer.Exit(1)

    # Section + topic (legacy path: "mycelium docs concepts rooms")
    doc_path = _find_doc(docs_root, section, topic)
    if doc_path:
        content = doc_path.read_text()
        if full:
            typer.echo(content)
        else:
            typer.secho(f"mycelium docs > {section} > {topic}", fg=typer.colors.BRIGHT_BLACK)
            typer.echo("")
            typer.echo(_render_markdown(content, full=False))
    else:
        typer.secho(f"Documentation not found: {section}/{topic}", fg=typer.colors.RED)
        raise typer.Exit(1)


def _print_doc_list(docs_root: Path) -> None:
    typer.secho("Available Documentation", bold=True)
    typer.echo("")

    typer.secho("SECTIONS", fg=typer.colors.CYAN)
    for stem, display_name in SECTIONS:
        if _resolve_topic(docs_root, stem):
            typer.echo(f"  mycelium docs {stem:<24} {display_name}")

    named = {stem for stem, _ in SECTIONS}
    for section_name in _DOC_DIRS:
        section_path = docs_root / section_name
        extra = sorted(section_path.glob("*.md")) if section_path.is_dir() else []
        if any(f.stem not in named for f in extra):
            typer.echo("")
            typer.secho(section_name.upper(), fg=typer.colors.CYAN)
            for f in extra:
                if f.stem in named:
                    continue
                title = _extract_title(f)
                cmd = f"mycelium docs {section_name} {f.stem}"
                typer.echo(f"  {cmd:<40} {title}")

    typer.echo("")
    typer.secho(
        "  mycelium docs --full                   Dump all sections as markdown",
        fg=typer.colors.BRIGHT_BLACK,
    )


def _print_section_list(docs_root: Path, section: str) -> None:
    typer.secho(f"{section.upper()}", bold=True)
    typer.echo("")
    docs = _list_docs(docs_root, section)
    for _, topic, title in docs:
        cmd = f"mycelium docs {section} {topic}"
        typer.echo(f"  {cmd:<40} {title}")


def _do_search(docs_root: Path, query: str) -> None:
    results = _search_docs(docs_root, query)
    if not results:
        typer.echo(f"No results for: {query}")
        return
    typer.secho(f"Search results for '{query}':", bold=True)
    typer.echo("")
    for section, topic, title, context_lines in results:
        cmd = f"mycelium docs {section} {topic}" if section else f"mycelium docs {topic}"
        typer.echo(f"  {cmd}")
        typer.secho(f"    {title}", fg=typer.colors.CYAN)
        if context_lines:
            typer.echo("    ---")
            for line in context_lines:
                typer.echo(f"    {line}")
            typer.echo("    ---")
        typer.echo("")


@app.command("ls")
def list_docs() -> None:
    """List all available documentation."""
    docs_root = _get_docs_root()
    _print_doc_list(docs_root)


@app.command()
def search(query: str = typer.Argument(..., help="Search query")) -> None:
    """Search documentation for a term."""
    docs_root = _get_docs_root()
    _do_search(docs_root, query)
