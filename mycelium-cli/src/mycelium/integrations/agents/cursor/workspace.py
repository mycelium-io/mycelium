# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Clearing the Cursor workspace files older versions of Mycelium dropped.

``mycelium agent create --adapter cursor`` used to write a Cursor rule,
``<cwd>/.cursor/rules/mycelium.mdc``, and a section of ``<cwd>/AGENTS.md``
between ``<!-- mycelium:start -->`` and ``<!-- mycelium:end -->``: a second,
hand-kept copy of the agent skill. It no longer does: a Cursor agent learns
how to take part from ``mycelium skill print``, like every other agent. A
workspace set up before that still holds the files, so
``mycelium agent rm --full`` clears them.
"""

from __future__ import annotations

import re
from pathlib import Path

import typer

#: The rule file an earlier ``agent create`` wrote under ``<cwd>/.cursor/rules/``.
_CURSOR_RULE_FILENAME = "mycelium.mdc"

#: The markers around the section an earlier ``agent create`` wrote into AGENTS.md.
_AGENTS_SECTION_START = "<!-- mycelium:start -->"
_AGENTS_SECTION_END = "<!-- mycelium:end -->"


def uninstall_workspace_assets(cwd: Path, *, verbose: bool = False) -> list[Path]:
    """Remove the Cursor rule and the AGENTS.md section from *cwd*.

    Removes ``.cursor/rules/mycelium.mdc`` outright and strips just the
    mycelium-marker section from AGENTS.md (preserving any other content
    in the file). Returns the list of paths that were modified or
    removed. Silent on missing files; it is idempotent.
    """
    cwd = Path(cwd).expanduser()
    modified: list[Path] = []

    rule_path = cwd / ".cursor" / "rules" / _CURSOR_RULE_FILENAME
    if rule_path.exists():
        rule_path.unlink()
        modified.append(rule_path)
        if verbose:
            typer.echo(f"  removed: {rule_path}")
        # Clean up the now-empty parent dirs IFF we created them; the user
        # may have other rules under .cursor/rules. ``rmdir`` only succeeds
        # on empty dirs, so this is safe regardless.
        for parent in (rule_path.parent, rule_path.parent.parent):
            try:
                parent.rmdir()
            except OSError:
                break  # not empty; stop walking up.

    agents_path = cwd / "AGENTS.md"
    if agents_path.exists():
        new_content = _strip_agents_md_section(agents_path.read_text(encoding="utf-8"))
        if new_content is None:
            if verbose:
                typer.echo(f"  AGENTS.md: no mycelium section to remove ({agents_path})")
        elif new_content.strip() == "":
            # The file was ONLY our section. Remove the file rather than
            # leaving an empty AGENTS.md the user didn't ask for.
            agents_path.unlink()
            modified.append(agents_path)
            if verbose:
                typer.echo(f"  removed: {agents_path}")
        else:
            agents_path.write_text(new_content, encoding="utf-8")
            modified.append(agents_path)
            if verbose:
                typer.echo(f"  pruned:  {agents_path}")

    return modified


def _strip_agents_md_section(content: str) -> str | None:
    """Return *content* with the mycelium section removed.

    Returns ``None`` if no mycelium section was found, so the caller can
    distinguish "nothing to do" from "removed". Strips one surrounding
    blank line on each side to avoid leaving double-blank gaps where the
    section used to be.
    """
    pattern = re.compile(
        r"\n?\n?"
        + re.escape(_AGENTS_SECTION_START)
        + r".*?"
        + re.escape(_AGENTS_SECTION_END)
        + r"\n?",
        re.DOTALL,
    )
    if not pattern.search(content):
        return None
    return pattern.sub("", content)
