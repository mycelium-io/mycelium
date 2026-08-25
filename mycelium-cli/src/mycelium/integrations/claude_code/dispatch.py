# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""ClaudeCode dispatch facet: the manifest IS the registration.

A ``claude_code`` agent is a **resident** runtime: a Claude Code session (kept
woken with ``mycelium await --loop``) that participates via ``await``/``respond``.
Mycelium names the agent (the ``agents/<handle>`` manifest) and installs the
skill; it does not run the process. So register/destroy have no runtime side
effects; this exists so the command layer has a uniform contract.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import typer

from mycelium.integrations.base import AddOptions, Integration
from mycelium.integrations.claude_code.install import (
    _CLAUDE_CODE_HOOKS,
    _CLAUDE_CODE_SKILL_NAME,
    _CLAUDE_CODE_STEPS,
    _install_claude_code,
)
from mycelium.protocol import AgentManifest

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig


class ClaudeCodeIntegration(Integration):
    name = "claude_code"
    lifecycle = "resident"

    def __init__(self, *, cwd: str | None = None) -> None:
        # cwd is collected by the command layer (it's a claude_code-only flag)
        # and threaded in at construction so build_manifest stays uniform.
        self._cwd = cwd

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
            adapter="claude_code",
            cwd=self._cwd,
            description=description,
            allow_from=allow_from,
            owner=owner,
            team=team,
        )

    def register(
        self, *, manifest: AgentManifest, config: MyceliumConfig, opts: AddOptions
    ) -> None:
        # No runtime side effects: a claude_code agent is a resident session the
        # user runs (via `mycelium await --loop`), not a process mycelium spawns.
        # The manifest (persisted by the command layer) is the whole registration.
        return

    def destroy(
        self, *, manifest: AgentManifest, config: MyceliumConfig, room: str, full: bool
    ) -> None:
        # No external runtime to tear down. `full` is meaningless here; the only
        # artifacts are the manifest (deleted by the command layer) and notes/logs
        # (deliberately preserved).
        return

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

    STEPS = _CLAUDE_CODE_STEPS

    def install(
        self,
        *,
        config: MyceliumConfig,
        verbose: bool,
        profile: str | None,
        container: str | None,
        reinstall: bool,
    ) -> None:
        _install_claude_code(verbose=verbose)

    def uninstall(self, *, record: dict, profile: str | None, container: str | None) -> None:
        # claude-code has no external runtime to tear down; `remove` just
        # drops the config entry (handled by the command layer).
        return

    def reinstall_targets(self, *, profile: str | None, container: str | None) -> list[str]:
        claude_dir = Path.home() / ".claude"
        targets = [f"  • {claude_dir}/skills/{_CLAUDE_CODE_SKILL_NAME}"]
        for hook in _CLAUDE_CODE_HOOKS:
            targets.append(f"  • {claude_dir}/hooks/{hook}")
        return targets

    def dry_run_lines(
        self, *, config: MyceliumConfig, profile: str | None, container: str | None
    ) -> list[str]:
        claude_dir = Path.home() / ".claude"
        lines = [f"  skill → {claude_dir}/skills/{_CLAUDE_CODE_SKILL_NAME}/SKILL.md"]
        for hook in _CLAUDE_CODE_HOOKS:
            lines.append(f"  hook  → {claude_dir}/hooks/{hook}")
        return lines

    def post_install_banner(
        self,
        *,
        config: MyceliumConfig,
        reinstall: bool,
        profile: str | None,
        container: str | None,
    ) -> None:
        action = "reinstalled" if reinstall else "installed"
        typer.secho(f"Adapter 'claude-code' {action}.", fg=typer.colors.GREEN)
        typer.echo(f"  skill:   ~/.claude/skills/{_CLAUDE_CODE_SKILL_NAME}/SKILL.md")
        for hook in _CLAUDE_CODE_HOOKS:
            typer.echo(f"  hook:    ~/.claude/hooks/{hook}")
        typer.echo("")
        typer.secho("  Next steps:", bold=True)
        typer.echo("")
        typer.echo("  Set your active room, then start a Claude Code session:")
        typer.secho("    $ mycelium room use <room-name>", fg=typer.colors.CYAN)
        typer.echo("")
        typer.echo("  Invoke the skill from within a session:")
        typer.secho("    /mycelium", fg=typer.colors.CYAN)

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
        # No follow-up steps (_CLAUDE_CODE_STEPS is empty). Kept to satisfy the
        # Integration contract.
        return

    def status_check(self, *, name: str, info: dict) -> dict:
        details: list[str] = []
        ok = True

        claude_dir = Path.home() / ".claude"
        skill_ok = (claude_dir / "skills" / _CLAUDE_CODE_SKILL_NAME / "SKILL.md").exists()
        details.append(f"  {'✓' if skill_ok else '✗'} skill:{_CLAUDE_CODE_SKILL_NAME}")
        if not skill_ok:
            ok = False
        for hook_name in _CLAUDE_CODE_HOOKS:
            hook_ok = (claude_dir / "hooks" / hook_name).exists()
            details.append(f"  {'✓' if hook_ok else '✗'} hook:{hook_name}")
            if not hook_ok:
                ok = False

        details.append(f"api_url: {info.get('api_url', '')}")
        return {"ok": ok, "details": details}


#: Back-compat alias for the historical class name.
ClaudeCodeAdapter = ClaudeCodeIntegration
