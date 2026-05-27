# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Cursor install facet — workspace assets + cc-daemon composition.

Unlike claude_code (which installs host-level skills/hooks into
``~/.claude/``), cursor's reading surfaces are workspace-local:

- ``<cwd>/.cursor/rules/mycelium.mdc`` — a Cursor project-rules file loaded
  automatically by Cursor on every session in the workspace. Owned wholly by
  Mycelium — overwritten on every refresh.
- ``<cwd>/AGENTS.md`` — an agent-readable preamble. Lives at the workspace
  root, where other tools (Cursor, Claude Code with --add-dir, etc.) may
  also read it. Idempotent and **non-destructive**: writes only a
  ``<!-- mycelium:start -->...<!-- mycelium:end -->`` section so any
  surrounding content the user or another tool has placed there is
  preserved. The marker is the contract — never grep the body to decide
  whether to write.

These drops happen per-agent in :class:`CursorIntegration.register` (called
by ``mycelium agent create``), NOT in :meth:`Integration.install`. Cursor
has no single host-level state dir, so ``mycelium adapter add cursor``
itself is informational — it points the user at the agent-create path and
optionally installs the cc-daemon via ``--step=daemon`` (composed from the
family-agnostic :mod:`mycelium.daemon.install`).
"""

from __future__ import annotations

import re
from pathlib import Path

import typer

from mycelium.daemon.install import install_daemon_service, uninstall_daemon_service
from mycelium.integrations._resources import _resolve_asset

# ── constants ────────────────────────────────────────────────────────────────

#: Bundled-asset subpath (inside ``mycelium/integrations/cursor/assets/``)
#: holding the ``mycelium.mdc`` Cursor rule file. Stored under
#: ``cursor_rules/`` rather than ``.cursor/rules/`` because setuptools +
#: ``importlib.resources`` handle dot-prefixed directories inconsistently;
#: the install translates this to ``<cwd>/.cursor/rules/mycelium.mdc`` at
#: drop time.
_CURSOR_RULE_ASSET = "cursor_rules"
_CURSOR_RULE_FILENAME = "mycelium.mdc"

#: Bundled-asset path for the workspace AGENTS.md content. The file ships
#: with the section markers already in place — the merge logic in
#: :func:`_write_agents_md_section` reads them from the asset rather than
#: hard-coding them in this module, so the marker contract has one source
#: of truth.
_CURSOR_AGENTS_ASSET = "AGENTS.md"

#: Section markers used to embed the mycelium block inside the workspace's
#: AGENTS.md without clobbering any other content the user / another tool
#: has placed there. Mirrors how OpenClaw's channel config protects per-
#: vendor regions of ``~/.openclaw/openclaw.json``.
_AGENTS_SECTION_START = "<!-- mycelium:start -->"
_AGENTS_SECTION_END = "<!-- mycelium:end -->"

#: ``mycelium adapter add cursor --step=<step>`` follow-up actions. Only
#: ``daemon`` is supported — the cc-daemon install/uninstall is family-
#: agnostic and shared with claude_code via :mod:`mycelium.daemon.install`.
_CURSOR_STEPS = {
    "daemon": "install + register the mycelium-cc-daemon user service",
}


# ── workspace asset drop / remove ────────────────────────────────────────────


def _read_bundled_rule() -> str:
    """Return the bundled ``mycelium.mdc`` content as a string.

    Reads from the relocated non-dotted asset path; the on-disk target is
    rewritten to ``.cursor/rules/`` in :func:`install_workspace_assets`.
    """
    src = _resolve_asset(_CURSOR_RULE_ASSET, family="cursor") / _CURSOR_RULE_FILENAME
    return src.read_text(encoding="utf-8")


def _read_bundled_agents_section() -> str:
    """Return the bundled AGENTS.md content (including section markers).

    The bundled file already wraps its content in
    ``<!-- mycelium:start -->`` / ``<!-- mycelium:end -->`` so the merge in
    :func:`_write_agents_md_section` has one source of truth.
    """
    src = _resolve_asset(_CURSOR_AGENTS_ASSET, family="cursor")
    # _resolve_asset returns the assets root when *subpath* is a file name
    # without intermediate directories. Read the file directly off the path.
    candidate = src if src.is_file() else src / _CURSOR_AGENTS_ASSET
    return candidate.read_text(encoding="utf-8")


def install_workspace_assets(cwd: Path, *, verbose: bool = False) -> list[Path]:
    """Drop ``.cursor/rules/mycelium.mdc`` + AGENTS.md section into *cwd*.

    Returns the list of paths created or updated. Idempotent: re-running
    refreshes the rule file in full and re-merges the AGENTS.md mycelium
    section without touching any other content.

    Raises ``NotADirectoryError`` if *cwd* doesn't exist — the command
    layer catches it and prints a friendly error rather than crashing.
    """
    cwd = Path(cwd).expanduser()
    if not cwd.is_dir():
        raise NotADirectoryError(f"cursor agent cwd '{cwd}' is not a directory — create it first")

    updated: list[Path] = []

    # 1) .cursor/rules/mycelium.mdc — owned wholly by mycelium; overwrite.
    rules_dir = cwd / ".cursor" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    rule_dst = rules_dir / _CURSOR_RULE_FILENAME
    rule_dst.write_text(_read_bundled_rule(), encoding="utf-8")
    updated.append(rule_dst)
    if verbose:
        typer.echo(f"  rule:    {rule_dst}")

    # 2) AGENTS.md — non-destructive section merge.
    agents_dst = cwd / "AGENTS.md"
    _write_agents_md_section(agents_dst, _read_bundled_agents_section())
    updated.append(agents_dst)
    if verbose:
        typer.echo(f"  agents:  {agents_dst}")

    return updated


def uninstall_workspace_assets(cwd: Path, *, verbose: bool = False) -> list[Path]:
    """Reverse :func:`install_workspace_assets` in *cwd*.

    Removes ``.cursor/rules/mycelium.mdc`` outright and strips just the
    mycelium-marker section from AGENTS.md (preserving any other content
    in the file). Returns the list of paths that were modified or
    removed. Silent on missing assets — uninstall is idempotent.
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
                break  # not empty — stop walking up.

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


def _write_agents_md_section(path: Path, section: str) -> None:
    """Idempotently write *section* between mycelium markers in *path*.

    Three cases:

    1. ``path`` doesn't exist → create it with just our section.
    2. ``path`` exists and contains the marker pair → replace just the
       region between them.
    3. ``path`` exists without the markers → append our section to the
       end with a blank-line separator.

    *section* is expected to already include the marker lines (the
    bundled asset does). The merge regex is anchored on the markers, not
    on the section text, so a future change to the bundled content
    propagates cleanly.
    """
    section = section.strip() + "\n"

    if not path.exists():
        path.write_text(section, encoding="utf-8")
        return

    existing = path.read_text(encoding="utf-8")
    pattern = re.compile(
        re.escape(_AGENTS_SECTION_START) + r".*?" + re.escape(_AGENTS_SECTION_END),
        re.DOTALL,
    )
    if pattern.search(existing):
        # Replace the existing region. Strip the trailing newline from
        # ``section`` first to avoid stacking blank lines on re-runs; the
        # surrounding text keeps its own whitespace.
        replaced = pattern.sub(section.rstrip("\n"), existing)
        # Idempotency guard: avoid touching mtime when the content didn't
        # change. setuptools' file-watcher and CI diffing both benefit.
        if replaced != existing:
            path.write_text(replaced, encoding="utf-8")
        return

    # No marker yet — append.
    sep = "\n\n" if existing and not existing.endswith("\n\n") else ""
    path.write_text(existing + sep + section, encoding="utf-8")


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


# ── cc-daemon user-service install / uninstall ──────────────────────────────
#
# Identical to claude_code's ``--step=daemon`` flow — the daemon is shared
# infrastructure. One service per host services every cold-spawn family.


def _step_cursor_daemon_install(verbose: bool = False) -> None:
    """Install the cc-daemon — cursor's ``--step=daemon`` entrypoint.

    Thin pass-through to the shared family-agnostic helper. Kept as a
    separate function so any future cursor-specific daemon setup (e.g.
    an ``cursor-agent login`` probe, binary discovery) lands here without
    pulling family logic into :mod:`mycelium.daemon.install`.
    """
    install_daemon_service(verbose=verbose)


def _step_cursor_daemon_uninstall(verbose: bool = False) -> None:
    """Reverse :func:`_step_cursor_daemon_install`."""
    uninstall_daemon_service(verbose=verbose)
