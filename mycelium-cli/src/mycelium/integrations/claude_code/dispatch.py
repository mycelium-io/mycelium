# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""ClaudeCode dispatch facet — the manifest IS the registration.

The daemon discovers ``agents/<handle>`` manifests off the filesystem and
dispatches ``@handle`` mentions to ``claude -p`` spawns. So register/destroy
have no runtime side effects — there's no external service to wire up. This
exists so the command layer has a uniform contract, not because it does work.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import typer

from mycelium.integrations._spawn_common import SpawnRequest, SpawnResult
from mycelium.integrations.base import AddOptions, Integration
from mycelium.integrations.claude_code.install import (
    _CLAUDE_CODE_HOOKS,
    _CLAUDE_CODE_SKILL_NAME,
    _CLAUDE_CODE_STEPS,
    _install_claude_code,
    _step_claude_daemon_install,
    _step_claude_daemon_uninstall,
)
from mycelium.integrations.claude_code.spawn import spawn_claude
from mycelium.protocol import AgentManifest

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig


class ClaudeCodeIntegration(Integration):
    name = "claude_code"
    lifecycle = "cold_spawn"

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
        budget: float,
        allow_from: list[str],
    ) -> AgentManifest:
        return AgentManifest(
            handle=handle,
            adapter="claude_code",
            cwd=self._cwd,
            description=description,
            budget_usd_per_month=budget,
            allow_from=allow_from,
        )

    def register(
        self, *, manifest: AgentManifest, config: MyceliumConfig, opts: AddOptions
    ) -> None:
        # A claude_code agent is cold-spawned by the daemon on THIS machine
        # (its cwd is a local path). Claim the handle in daemon.toml so the
        # local daemon dispatches it — and so another machine that syncs this
        # room does NOT (its daemon.toml won't list the handle). Without
        # this, two daemons subscribed to one room both spawn the agent.
        from mycelium.daemon.config import DaemonConfig

        daemon_cfg = DaemonConfig.load()
        if daemon_cfg.own_handle(manifest.handle):
            daemon_cfg.save()

    def destroy(
        self, *, manifest: AgentManifest, config: MyceliumConfig, room: str, full: bool
    ) -> None:
        # No external runtime to tear down. `full` is meaningless here — the
        # only artifacts are the manifest (deleted by the command layer) and
        # notes/logs (deliberately preserved). Release the daemon ownership
        # claimed in register().
        from mycelium.daemon.config import DaemonConfig

        daemon_cfg = DaemonConfig.load()
        if daemon_cfg.disown_handle(manifest.handle):
            daemon_cfg.save()

    def describe(self, manifest: AgentManifest, *, room: str) -> list[str]:
        lines = [
            f"  adapter: {manifest.adapter}",
            f"  cwd:     {manifest.cwd}",
        ]
        if manifest.allow_from:
            lines.append(f"  allow:   {', '.join(manifest.allow_from)}")
        lines.append(
            "\n[dim]Seed the agent's brain (optional):[/dim]\n"
            f'  mycelium memory set {manifest.notes_key} "..." --room {room}\n'
            "[dim]Make sure the daemon watches this room:[/dim]\n"
            f"  mycelium daemon subscribe {room}\n"
            "[dim]Then invoke it:[/dim]\n"
            f'  mycelium agent invoke {manifest.handle} "..."'
        )
        return lines

    # ── cold-spawn dispatch ─────────────────────────────────────────────────

    async def spawn(self, *, request: SpawnRequest) -> SpawnResult:
        """Cold-spawn ``claude -p`` for one ``@handle`` mention.

        Thin adapter from the family-agnostic :class:`SpawnRequest` /
        :class:`SpawnResult` shape into the existing ``spawn_claude(...)``
        helper. The helper still returns a plain dict (its shape is widely
        used elsewhere in the daemon log path); we convert here.

        ``request.binary`` is the resolved claude binary path (the daemon
        passes ``DaemonConfig.claude_binary``). ``RunningProc`` registration
        currently lives inside ``spawn_claude`` for backward compatibility;
        the daemon-core milestone will move it up into the dispatch loop so
        every cold-spawn family inherits abort/status uniformly.
        """
        result = await spawn_claude(
            claude_binary=request.binary or "claude",
            cwd=request.cwd,
            prompt=request.prompt,
            notes=request.notes,
            state=request.state,
            handle=request.handle,
            sender=request.sender,
            room=request.room,
            description=request.description,
            plan_block=request.plan_block,
        )
        return SpawnResult(
            ok=bool(result.get("ok")),
            final_message=result.get("final_message", ""),
            transcript=result.get("transcript", ""),
            cost_usd=float(result.get("cost_usd", 0.0)),
            duration_s=float(result.get("duration_s", 0.0)),
            aborted=bool(result.get("aborted", False)),
        )

    # ── install facet ───────────────────────────────────────────────────────
    # Behaviour relocated verbatim from the old ``commands/adapter.py`` add/
    # remove/status bodies; the command layer just dispatches here now.

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
        # claude-code has no external runtime to tear down — `remove` just
        # drops the config entry (handled by the command layer). The daemon
        # service, if installed, is removed via
        # `mycelium adapter add claude-code --step=daemon --remove-step`.
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
        verb = "reinstalled" if reinstall else "installed"
        typer.secho(f"Adapter 'claude-code' {verb}.", fg=typer.colors.GREEN)
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
        typer.echo("")
        typer.echo("  Knowledge graph ingest now fires on deliberate room writes only —")
        typer.echo("  channel messages and `mycelium memory set`. The silent per-turn")
        typer.echo("  hook has been removed. Flip the master switch in ~/.mycelium/config.toml")
        typer.echo("  to enable CFN forwarding (costs tokens):")
        typer.secho(
            "    [knowledge_ingest]\n    enabled = true",
            fg=typer.colors.CYAN,
        )
        typer.echo("  and confirm [server].mas_id is set.")

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
        if step == "daemon":
            if remove:
                _step_claude_daemon_uninstall(verbose=verbose)
            else:
                _step_claude_daemon_install(verbose=verbose)

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
