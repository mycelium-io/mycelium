"""
Auto-generate CLI reference documentation by introspecting the Typer/Click command tree.

Usage:
    from mycelium.generate_cli_docs import generate_all
    generate_all()            # writes markdown into mycelium/docs/commands/
    generate_all(output_dir)  # writes to a custom directory
"""

from __future__ import annotations

from pathlib import Path

import click


def _docs_dir() -> Path:
    """Default output directory — bundled docs/commands/ inside the package."""
    return Path(__file__).parent / "docs" / "commands"


# ── Click introspection helpers ──────────────────────────────────────────────


def _format_param(param: click.Parameter) -> str:
    """Format a single Click parameter as a markdown table row."""
    names = ", ".join(f"`{n}`" for n in param.opts) if param.opts else f"`{param.name}`"
    if param.secondary_opts:
        names += ", " + ", ".join(f"`{s}`" for s in param.secondary_opts)

    required = "Yes" if param.required else ""
    default = ""
    if param.default is not None and param.default != () and not param.required:
        default = f"`{param.default}`"

    help_text = ""
    if isinstance(param, click.Option) and param.help:
        help_text = param.help
    elif isinstance(param, click.Argument):
        # Typer stores argument help in the type's metavar or in custom attrs
        help_text = getattr(param, "help", "") or ""
        if not help_text and hasattr(param.type, "name"):
            help_text = ""

    kind = "argument" if isinstance(param, click.Argument) else "option"

    return f"| {names} | {kind} | {required} | {default} | {help_text} |"


def _extract_command_doc(cmd: click.Command, prefix: str = "") -> str:
    """Generate markdown documentation for a single command."""
    full_name = f"{prefix} {cmd.name}".strip() if cmd.name else prefix
    lines: list[str] = []

    # Heading
    lines.append(f"### `{full_name}`")
    lines.append("")

    # Help text (first paragraph = short, rest = long description)
    help_text = (cmd.help or "").strip()
    if help_text:
        # Strip Rich markup tags for docs
        import re

        clean = re.sub(r"\[/?[^\]]+\]", "", help_text)
        lines.append(clean)
        lines.append("")

    # Parameters table
    params = [p for p in cmd.params if p.name not in ("ctx", "help")]
    if params:
        lines.append("| Parameter | Type | Required | Default | Description |")
        lines.append("|-----------|------|----------|---------|-------------|")
        for param in params:
            lines.append(_format_param(param))
        lines.append("")

    return "\n".join(lines)


def _walk_group(group: click.Group, prefix: str = "mycelium") -> list[tuple[str, str]]:
    """Recursively walk a Click group and collect (section_key, markdown) pairs."""
    results: list[tuple[str, str]] = []

    for name in sorted(group.commands):
        cmd = group.commands[name]
        full_prefix = f"{prefix} {name}"

        if isinstance(cmd, click.Group):
            # It's a subgroup — generate a page for the whole group
            section_md = _generate_group_page(cmd, full_prefix)
            results.append((name, section_md))
        else:
            # Top-level command — collected into the "top-level" bucket
            doc = _extract_command_doc(cmd, prefix)
            results.append(("_top", doc))

    return results


def _generate_group_page(group: click.Group, prefix: str) -> str:
    """Generate a full markdown page for a command group."""
    group_name = prefix.split()[-1]
    lines: list[str] = []

    lines.append(f"# mycelium {group_name}")
    lines.append("")

    # Group help
    help_text = (group.help or "").strip()
    if help_text:
        import re

        clean = re.sub(r"\[/?[^\]]+\]", "", help_text)
        lines.append(clean)
        lines.append("")

    lines.append("## Commands")
    lines.append("")

    for name in sorted(group.commands):
        cmd = group.commands[name]
        if name == group_name:
            continue  # skip self-referencing callback
        lines.append(_extract_command_doc(cmd, prefix))

    return "\n".join(lines)


def _generate_top_level_page(app_group: click.Group, top_level_docs: list[str]) -> str:
    """Generate the top-level commands reference page."""
    lines: list[str] = []

    lines.append("# CLI Reference")
    lines.append("")
    lines.append("Auto-generated from CLI source. Run `mycelium docs generate` to regenerate.")
    lines.append("")

    # Global options
    callback = app_group
    if hasattr(callback, "params"):
        global_params = [
            p for p in callback.params if p.name not in ("help",) and isinstance(p, click.Option)
        ]
        if global_params:
            lines.append("## Global Options")
            lines.append("")
            lines.append("| Parameter | Type | Required | Default | Description |")
            lines.append("|-----------|------|----------|---------|-------------|")
            for param in global_params:
                lines.append(_format_param(param))
            lines.append("")

    # Top-level commands
    lines.append("## Top-Level Commands")
    lines.append("")
    for doc in top_level_docs:
        lines.append(doc)

    # Command groups index
    groups = [
        name
        for name in sorted(app_group.commands)
        if isinstance(app_group.commands[name], click.Group)
    ]
    if groups:
        lines.append("## Command Groups")
        lines.append("")
        for g in groups:
            group_cmd = app_group.commands[g]
            short_help = (group_cmd.help or "").split("\n")[0].strip()
            import re

            short_help = re.sub(r"\[/?[^\]]+\]", "", short_help)
            lines.append(f"- [`mycelium {g}`](commands/{g}.md) — {short_help}")
        lines.append("")

    return "\n".join(lines)


# ── Public API ───────────────────────────────────────────────────────────────


def generate_all(output_dir: Path | None = None) -> list[Path]:
    """
    Introspect the Typer app and write CLI reference docs.

    Returns a list of generated file paths.
    """
    from mycelium.cli import app as typer_app

    # Convert Typer app → Click group
    click_app: click.Group = typer.main.get_group(typer_app)  # type: ignore[attr-defined]

    out = output_dir or _docs_dir()
    out.mkdir(parents=True, exist_ok=True)

    entries = _walk_group(click_app)

    top_level_docs: list[str] = []
    written: list[Path] = []

    for key, markdown in entries:
        if key == "_top":
            top_level_docs.append(markdown)
        else:
            dest = out / f"{key}.md"
            dest.write_text(markdown)
            written.append(dest)

    # Write the index page
    index = _generate_top_level_page(click_app, top_level_docs)
    index_path = out.parent / "cli-reference.md"
    index_path.write_text(index)
    written.append(index_path)

    return written


# Need typer imported for get_group
import typer  # noqa: E402
