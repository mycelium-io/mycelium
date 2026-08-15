# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Cursor dispatch facet — manifest IS the registration (same shape as claude_code).

A ``cursor`` agent is a **resident** runtime: a Cursor session (kept woken with
``mycelium await --loop``) that participates via ``await``/``respond``. Registration
drops the workspace-local Cursor rule + AGENTS.md section so the session knows how
to coordinate; mycelium does not run the process. (Untested end-to-end — kept as the
resident sibling of claude_code.)
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import typer

from mycelium.integrations.base import AddOptions, Integration
from mycelium.integrations.cursor.install import (
    _AGENTS_SECTION_END,
    _AGENTS_SECTION_START,
    _CURSOR_RULE_FILENAME,
    _CURSOR_STEPS,
    install_workspace_assets,
    uninstall_workspace_assets,
)
from mycelium.protocol import AgentManifest

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig


class CursorIntegration(Integration):
    name = "cursor"
    lifecycle = "resident"

    STEPS = _CURSOR_STEPS

    def __init__(self, *, cwd: str | None = None) -> None:
        # Same shape as ClaudeCodeIntegration: cwd is the one family-specific
        # ``agent add`` flag and is threaded in at construction so
        # ``build_manifest`` keeps a uniform signature across families.
        self._cwd = cwd

    # ── dispatch facet ──────────────────────────────────────────────────────

    def build_manifest(
        self,
        *,
        handle: str,
        opts: AddOptions,
        description: str,
        allow_from: list[str],
        owner: str | None = None,
        team: str | None = None,
    ) -> AgentManifest:
        return AgentManifest(
            handle=handle,
            adapter="cursor",
            cwd=self._cwd,
            description=description,
            allow_from=allow_from,
            owner=owner,
            team=team,
        )

    def register(
        self, *, manifest: AgentManifest, config: MyceliumConfig, opts: AddOptions
    ) -> None:
        # Drop the workspace-local Cursor rule + AGENTS.md section so a resident
        # Cursor session knows how to coordinate. ``install_workspace_assets``
        # raises ``NotADirectoryError`` when ``manifest.cwd`` doesn't exist; the
        # command layer surfaces that as a clean validation error. No runtime is
        # started — the user runs the session (via ``mycelium await --loop``).
        if manifest.cwd:
            install_workspace_assets(Path(manifest.cwd), verbose=False)

    def destroy(
        self, *, manifest: AgentManifest, config: MyceliumConfig, room: str, full: bool
    ) -> None:
        # ``full`` requests destructive teardown of *this agent's runtime*
        # — for cursor that means removing the workspace assets we dropped.
        # Without ``full``, we leave them in place so a re-add picks up where
        # we left off and the user's project-rules history isn't disturbed.
        # The agent's manifest and notes/logs are owned by the command layer
        # and never touched here.
        if full and manifest.cwd:
            cwd_path = Path(manifest.cwd)
            if cwd_path.exists():
                uninstall_workspace_assets(cwd_path, verbose=False)

    def describe(self, manifest: AgentManifest, *, room: str) -> list[str]:
        lines: list[str] = [
            f"  adapter: {manifest.adapter}",
        ]
        if manifest.cwd:
            lines.append(f"  cwd:     {manifest.cwd}")
        if manifest.allow_from:
            lines.append(f"  allow:   {', '.join(manifest.allow_from)}")
        lines.append(
            "\n[dim]Seed the agent's brain (optional):[/dim]\n"
            f'  mycelium memory set {manifest.notes_key} "..." --room {room}\n'
            "[dim]Keep the agent woken so it can answer:[/dim]\n"
            f'  mycelium await --loop --room {room} --handle {manifest.handle} --exec "..."\n'
            "[dim]Or address it (it picks up on its next await):[/dim]\n"
            f'  mycelium agent invoke {manifest.handle} "..."'
        )
        return lines

    # ── install facet ───────────────────────────────────────────────────────
    #
    # Cursor differs from claude_code: the per-workspace assets
    # (``.cursor/rules/mycelium.mdc``, AGENTS.md section) drop at agent-create
    # time inside :meth:`register`, NOT at host install. So
    # ``mycelium adapter add cursor`` itself is essentially a banner pointing
    # the user at ``mycelium agent create --adapter cursor``.

    def install(
        self,
        *,
        config: MyceliumConfig,
        verbose: bool,
        profile: str | None,
        container: str | None,
        reinstall: bool,
    ) -> None:
        # No host-level work. The banner printed via :meth:`post_install_banner`
        # is what the user sees. Reinstall has nothing to refresh either —
        # the per-workspace assets are owned by the agent's :meth:`register`.
        return

    def uninstall(self, *, record: dict, profile: str | None, container: str | None) -> None:
        # No host-level assets ever installed — symmetry with :meth:`install`.
        return

    def reinstall_targets(self, *, profile: str | None, container: str | None) -> list[str]:
        # Per-workspace assets land at agent-create time; ``adapter add``
        # has no host file to overwrite. Return an empty list so the
        # confirmation prompt for ``--reinstall`` is suppressed.
        return []

    def dry_run_lines(
        self, *, config: MyceliumConfig, profile: str | None, container: str | None
    ) -> list[str]:
        return [
            "  (no host-level install for cursor — workspace assets drop at agent create)",
            "  Per agent:",
            f"    rule    → <agent-cwd>/.cursor/rules/{_CURSOR_RULE_FILENAME}",
            "    agents  → <agent-cwd>/AGENTS.md (merged inside",
            f"             {_AGENTS_SECTION_START}…{_AGENTS_SECTION_END} markers)",
        ]

    def post_install_banner(
        self,
        *,
        config: MyceliumConfig,
        reinstall: bool,
        profile: str | None,
        container: str | None,
    ) -> None:
        verb = "reinstalled" if reinstall else "installed"
        typer.secho(f"Adapter 'cursor' {verb}.", fg=typer.colors.GREEN)
        typer.echo("  (no host-level files — cursor reads workspace-local rules)")
        typer.echo("")
        typer.secho("  Next steps:", bold=True)
        typer.echo("")
        typer.echo("  1) Make sure cursor-agent is logged in:")
        typer.secho("       $ cursor-agent login", fg=typer.colors.CYAN)
        typer.echo("")
        typer.echo("  2) Create a cursor agent (drops .cursor/rules/mycelium.mdc + the")
        typer.echo("     mycelium section of AGENTS.md into the agent's workspace cwd):")
        typer.secho(
            "       $ mycelium agent create <handle> --adapter cursor "
            "--cwd <workspace-path> --room <room>",
            fg=typer.colors.CYAN,
        )
        typer.echo("")
        typer.echo("  3) Keep the session woken so it can answer:")
        typer.secho(
            "       $ mycelium await --loop --room <room> --handle <handle> --exec ...",
            fg=typer.colors.CYAN,
        )

    def run_step(
        self,
        step: str,
        *,
        config: MyceliumConfig,
        verbose: bool,
        profile: str | None,
        container: str | None,
        remove: bool,
    ) -> None:
        # No follow-up steps (_CURSOR_STEPS is empty). Kept to satisfy the
        # Integration contract.
        return

    def status_check(self, *, name: str, info: dict) -> dict:
        # No host-level files to probe — the only meaningful per-host check is
        # whether ``cursor-agent`` is on PATH. Returning ``ok`` on that lets
        # ``mycelium adapter status`` list cursor without a misleading red ✗.
        import shutil

        details: list[str] = []
        binary_ok = shutil.which("cursor-agent") is not None
        details.append(
            f"  {'✓' if binary_ok else '✗'} cursor-agent on PATH "
            f"(install via https://cursor.com/cli)"
        )
        details.append(
            "  ℹ login prerequisite: run `cursor-agent login` once interactively "
            "(no pre-flight check here)"
        )
        details.append("  ℹ workspace assets drop at `mycelium agent create --adapter cursor`")
        details.append(f"api_url: {info.get('api_url', '')}")
        return {"ok": binary_ok, "details": details}

    def will_destroy_runtime(self, manifest: AgentManifest, *, full: bool) -> bool:
        # ``full`` removes the workspace assets — confirm in the command
        # layer because users may have committed AGENTS.md and don't expect
        # ``agent rm --full`` to mutate their git working tree.
        return bool(full and manifest.cwd)


#: Back-compat alias for the historical class-name convention.
CursorAdapter = CursorIntegration
