# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Cursor dispatch facet — manifest IS the registration (same shape as claude_code).

Cursor agents are cold-spawned by the daemon: every ``@handle`` mention
fires a fresh ``cursor-agent -p`` in the manifest's ``cwd`` (Cursor's workspace
root). So register/destroy have no external runtime to wire up — they only
claim/release the handle in ``daemon.toml`` so two daemons subscribed to
the same room don't both dispatch.

The install facet methods land in :mod:`mycelium.integrations.cursor.install`
(cursor-pkg milestone). The actual ``cursor-agent -p`` invocation lands in
:mod:`mycelium.integrations.cursor.spawn` (cursor-cli milestone). This module
exists at the protocol milestone so the registry has a real :class:`Integration`
to return for ``adapter == "cursor"`` — without it, every
:func:`get_integration("cursor")` call would crash and the contract test
couldn't be parametrised over the family.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import typer

from mycelium.integrations._spawn_common import SpawnRequest, SpawnResult
from mycelium.integrations.base import AddOptions, Integration
from mycelium.integrations.cursor.install import (
    _AGENTS_SECTION_END,
    _AGENTS_SECTION_START,
    _CURSOR_RULE_FILENAME,
    _CURSOR_STEPS,
    _step_cursor_daemon_install,
    _step_cursor_daemon_uninstall,
    install_workspace_assets,
    uninstall_workspace_assets,
)
from mycelium.integrations.cursor.spawn import spawn_cursor
from mycelium.protocol import AgentManifest

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig


class CursorIntegration(Integration):
    name = "cursor"
    lifecycle = "cold_spawn"

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
        budget: float,
        allow_from: list[str],
        owner: str | None = None,
        team: str | None = None,
    ) -> AgentManifest:
        return AgentManifest(
            handle=handle,
            adapter="cursor",
            cwd=self._cwd,
            description=description,
            budget_usd_per_month=budget,
            allow_from=allow_from,
            owner=owner,
            team=team,
        )

    def register(
        self, *, manifest: AgentManifest, config: MyceliumConfig, opts: AddOptions
    ) -> None:
        # Order matters here. ``install_workspace_assets`` raises
        # ``NotADirectoryError`` when ``manifest.cwd`` doesn't exist, and we
        # surface that to the command layer as a clean validation error. If
        # we claimed the daemon handle *before* the cwd check, a failed
        # ``mycelium agent create`` would still persist the handle into
        # ``~/.mycelium/daemon.toml`` — leaking ownership of a name that
        # never materialised as an agent. So: drop the workspace-local Cursor
        # rule + AGENTS.md section first (this validates cwd as a side
        # effect), THEN claim ownership.
        if manifest.cwd:
            install_workspace_assets(Path(manifest.cwd), verbose=False)

        # Same handle-ownership semantics as claude_code: a cursor agent is
        # cold-spawned by THIS machine's daemon (its cwd is local). Claim
        # the handle in daemon.toml so a sibling daemon syncing this room
        # via git does NOT also dispatch — without ownership two
        # cursor-agent processes would race over the same cwd.
        from mycelium.daemon.config import DaemonConfig

        daemon_cfg = DaemonConfig.load()
        if daemon_cfg.own_handle(manifest.handle):
            daemon_cfg.save()

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

        # Release the daemon ownership claimed in :meth:`register`.
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
        """Cold-spawn ``cursor-agent -p`` for one ``@handle`` mention.

        Pass-through to :func:`mycelium.integrations.cursor.spawn.spawn_cursor`
        — kept here as a method so the daemon dispatch loop's
        ``integration.spawn(...)`` call resolves through one consistent
        surface across families (claude_code does the same).
        """
        return await spawn_cursor(request=request)

    # ── install facet ───────────────────────────────────────────────────────
    #
    # Cursor differs from claude_code: the per-workspace assets
    # (``.cursor/rules/mycelium.mdc``, AGENTS.md section) drop at agent-create
    # time inside :meth:`register`, NOT at host install. So
    # ``mycelium adapter add cursor`` itself is essentially a banner pointing
    # the user at ``mycelium agent create --adapter cursor`` and surfacing
    # the ``--step=daemon`` follow-up.

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
        # The daemon, if installed via ``--step=daemon``, is removed via
        # ``mycelium adapter add cursor --step=daemon --remove-step`` (or the
        # claude_code equivalent — they share one service).
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
        typer.echo("  1) Install the daemon (one per host, shared with claude_code):")
        typer.secho(
            "       $ mycelium adapter add cursor --step=daemon",
            fg=typer.colors.CYAN,
        )
        typer.echo("")
        typer.echo("  2) Make sure cursor-agent is logged in (the daemon runs without a")
        typer.echo("     login shell, so auth must be set up interactively first):")
        typer.secho("       $ cursor-agent login", fg=typer.colors.CYAN)
        typer.echo("")
        typer.echo("  3) Create a cursor agent (drops .cursor/rules/mycelium.mdc + the")
        typer.echo("     mycelium section of AGENTS.md into the agent's workspace cwd):")
        typer.secho(
            "       $ mycelium agent create <handle> --adapter cursor "
            "--cwd <workspace-path> --room <room>",
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
        if step == "daemon":
            if remove:
                _step_cursor_daemon_uninstall(verbose=verbose)
            else:
                _step_cursor_daemon_install(verbose=verbose)

    def status_check(self, *, name: str, info: dict) -> dict:
        # No host-level files to probe — the only meaningful per-host check
        # is whether ``cursor-agent`` is on PATH; the daemon is a separate
        # adapter status (shared with claude_code). Returning ``ok=True``
        # here lets ``mycelium adapter status`` list cursor as registered
        # without a misleading red ✗.
        #
        # Why no pre-flight auth check: the daemon runs without a login
        # shell, and ``cursor-agent``'s login flow is interactive only
        # (``cursor-agent login`` opens a browser tab). Probing here would
        # either spawn an LLM call (cost) or rely on parsing internal cache
        # paths that the cursor team is free to change between releases.
        # Same posture as claude_code (which never pre-flight-checks
        # Claude's auth either). Auth failures are detected on the first
        # ``@handle`` dispatch — :func:`_detect_auth_required` in
        # ``cursor/spawn.py`` parses stderr and surfaces a friendlier
        # ``daemon error`` reply plus a ``log.warning`` daemon-log line
        # pointing at ``cursor-agent login``. The detail line below
        # documents the prerequisite so the operator sees it before they
        # even hit a failure.
        import shutil

        details: list[str] = []
        binary_ok = shutil.which("cursor-agent") is not None
        details.append(
            f"  {'✓' if binary_ok else '✗'} cursor-agent on PATH "
            f"(install via https://cursor.com/cli)"
        )
        details.append(
            "  ℹ login prerequisite: run `cursor-agent login` once interactively "
            "under the user the daemon runs as (no pre-flight check; first "
            "@handle dispatch surfaces the auth error if it's missing)"
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
