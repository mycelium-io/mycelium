# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""OpenClaw dispatch facet — agent runs in the OpenClaw gateway.

OpenClaw agents aren't dispatched by the cc-daemon. They live inside the
OpenClaw gateway; the bundled ``mycelium-room`` channel plugin subscribes to
each configured room's SSE and delivers ``@handle`` mentions to the agent's
session. So registration is:

  1. ensure the OpenClaw agent exists (adopt an existing id, or create one)
  2. add it to the channel's per-room fan-out in ``~/.openclaw/openclaw.json``
  3. restart the gateway so the plugin re-reads the config

The plugin multiplexes N rooms internally under the single ``mycelium-room``
channel id (see ``plugin/src/config.ts`` ``readChannelConfigs``), so adding a
room never requires a plugin manifest regen / reinstall.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

import typer
from rich.console import Console

from mycelium.integrations._resources import _resolve_asset
from mycelium.integrations.base import AddOptions, Integration
from mycelium.integrations.openclaw.install import (
    _MYCELIUM_PLUGIN_SRC,
    _OPENCLAW_HOOK_NAME,
    _OPENCLAW_PLUGIN_NAME,
    _OPENCLAW_SKILL_NAME,
    _OPENCLAW_STALE_HOOKS,
    _OPENCLAW_STEPS,
    _configure_otel,
    _install_openclaw,
    _openclaw_cmd,
    _openclaw_state_dir,
    _probe_hub_reachable,
    _restart_gateway_if_needed,
    _step_docker_env,
    _uninstall_openclaw,
)
from mycelium.sstp import AgentManifest

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig

console = Console()

_CHANNEL_ID = "mycelium-room"


class OpenClawError(RuntimeError):
    """Raised when an `openclaw` CLI invocation or config write fails."""


class OpenClawIntegration(Integration):
    name = "openclaw"

    def __init__(
        self,
        *,
        openclaw_agent: str | None = None,
        model: str | None = None,
        openclaw_profile: str | None = None,
        copy_auth_from: str | None = None,
    ) -> None:
        # These are openclaw-only `agent add` flags, threaded in at
        # construction so the base AddOptions stays family-agnostic.
        self._explicit_agent = openclaw_agent
        self._model = model
        self._profile = openclaw_profile
        self._copy_auth_from = copy_auth_from

    # ── path + process helpers ──────────────────────────────────────────────

    def _paths(self) -> tuple[Path, Path]:
        """(state_dir, openclaw.json) — shared with the install facet."""
        state_dir = _openclaw_state_dir(self._profile)
        return state_dir, state_dir / "openclaw.json"

    def _oc_cmd(self, args: list[str]) -> list[str]:
        return _openclaw_cmd(args, self._profile, None)

    def restart_gateway(self) -> None:
        result = subprocess.run(
            self._oc_cmd(["openclaw", "gateway", "restart"]),
            text=True,
            capture_output=True,
        )
        if result.returncode != 0:
            stderr = (result.stderr or result.stdout or "").strip()
            console.print(
                f"[yellow]gateway restart returned {result.returncode}[/yellow] "
                f"{stderr[:160]}\n"
                "  Config is written; restart manually: openclaw gateway restart"
            )

    # ── manifest ────────────────────────────────────────────────────────────

    def build_manifest(
        self,
        *,
        handle: str,
        opts: AddOptions,
        description: str,
        budget: float,
        allow_from: list[str],
    ) -> AgentManifest:
        resolved = (self._explicit_agent or handle).strip()
        return AgentManifest(
            handle=handle,
            adapter="openclaw",
            openclaw_agent=resolved,
            openclaw_created=not self._explicit_agent,  # adopt vs create
            description=description,
            budget_usd_per_month=budget,
            allow_from=allow_from,
        )

    # ── create / adopt ──────────────────────────────────────────────────────

    def _create_agent(self, *, agent_id: str, description: str) -> None:
        state_dir, _oc_json = self._paths()
        workspace = state_dir / "workspaces" / agent_id

        # Only override the model when the user explicitly asked. Otherwise
        # inherit openclaw's own `agents.defaults.model` — that default is
        # known-good for the installed openclaw version (it may be the
        # structured {primary: ...} form on newer builds; passing a bare
        # `--model <string>` writes an unresolvable record and the agent
        # session hangs in `processing` forever with no error).
        cmd = [
            "openclaw",
            "agents",
            "add",
            agent_id,
            "--non-interactive",
            "--workspace",
            str(workspace),
        ]
        if self._model:
            cmd += ["--model", self._model]

        result = subprocess.run(self._oc_cmd(cmd), text=True, capture_output=True)
        combined = ((result.stderr or "") + (result.stdout or "")).lower()
        if result.returncode != 0 and "already exists" not in combined:
            raise OpenClawError(
                f"`openclaw agents add {agent_id}` failed "
                f"(exit {result.returncode}): "
                f"{(result.stderr or result.stdout).strip()[:200]}"
            )

        if description.strip():
            workspace.mkdir(parents=True, exist_ok=True)
            (workspace / "SOUL.md").write_text(description.strip() + "\n")

        model_note = self._model or "openclaw default"
        console.print(
            f"  [green]created[/green] OpenClaw agent [cyan]{agent_id}[/cyan] "
            f"(model: {model_note}, workspace {workspace})"
        )

        if self._copy_auth_from:
            self._seed_auth(agent_id=agent_id, source_agent=self._copy_auth_from)

    def _seed_auth(self, *, agent_id: str, source_agent: str) -> None:
        """Seed the new agent's auth-profiles.json from an existing agent.

        `openclaw agents add --non-interactive` creates an agent with an
        EMPTY agent dir — no auth-profiles.json — so it can't authenticate
        its model and every dispatch hangs in `processing` (verified on
        2026.5.7). OpenClaw's own auth surface (`openclaw models auth`) is
        per-agent and interactive/one-token-at-a-time; the file format is
        stable (`{version, profiles:{...}}`), so the robust version-
        independent fix is to copy the file OpenClaw itself reads. This is
        opt-in (the user named the source) and intentionally duplicates a
        secret — log it loudly.
        """
        state_dir, _ = self._paths()
        src = state_dir / "agents" / source_agent / "agent" / "auth-profiles.json"
        dst = state_dir / "agents" / agent_id / "agent" / "auth-profiles.json"
        if not src.exists():
            raise OpenClawError(
                f"--copy-auth-from {source_agent}: no auth-profiles.json at {src}. "
                f"Pick an agent that has authed (see ~/.openclaw/agents/*/agent/)."
            )
        try:
            profiles = json.loads(src.read_text()).get("profiles", {})
        except (OSError, ValueError) as exc:
            raise OpenClawError(f"{src} is unreadable: {exc}") from exc
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        try:
            dst.chmod(0o600)
        except OSError:
            pass
        console.print(
            f"  [yellow]auth[/yellow] copied {len(profiles)} profile(s) "
            f"[{', '.join(sorted(profiles)) or '—'}] from "
            f"[cyan]{source_agent}[/cyan] → {dst} [dim](contains secrets)[/dim]"
        )

    # ── channel config (rooms[] fan-out) ────────────────────────────────────

    def _read_block(self) -> tuple[dict[str, Any], Path]:
        _state_dir, oc_json = self._paths()
        oc: dict[str, Any] = {}
        if oc_json.exists():
            try:
                oc = json.loads(oc_json.read_text())
            except ValueError as exc:
                raise OpenClawError(f"{oc_json} is not valid JSON: {exc}") from exc
        return oc, oc_json

    @staticmethod
    def _normalize_rooms(block: dict[str, Any]) -> list[dict[str, Any]]:
        """Fold a legacy top-level room/agents into rooms[]; return rooms[]."""
        rooms: list[dict[str, Any]] = []
        seen: set[str] = set()
        legacy_room = block.pop("room", None)
        legacy_agents = block.pop("agents", None)
        if isinstance(legacy_room, str) and legacy_room:
            rooms.append({"room": legacy_room, "agents": [str(a) for a in (legacy_agents or [])]})
            seen.add(legacy_room)
        for entry in block.get("rooms", []) or []:
            if not isinstance(entry, dict) or not entry.get("room"):
                continue
            rname = str(entry["room"])
            if rname in seen:
                continue
            rooms.append({"room": rname, "agents": [str(a) for a in entry.get("agents", [])]})
            seen.add(rname)
        return rooms

    def _register_channel(self, *, room: str, agent_id: str, backend_url: str) -> None:
        oc, oc_json = self._read_block()
        channels = oc.setdefault("channels", {})
        block = channels.get(_CHANNEL_ID)
        if not isinstance(block, dict):
            block = {}

        block["enabled"] = True
        block["backendUrl"] = backend_url.rstrip("/")
        block.setdefault("requireMention", True)

        rooms = self._normalize_rooms(block)
        target: dict[str, Any] | None = next((r for r in rooms if r["room"] == room), None)
        if target is None:
            target = {"room": room, "agents": []}
            rooms.append(target)
        agents: list[str] = target["agents"]
        if agent_id not in agents:
            agents.append(agent_id)

        block["rooms"] = rooms
        channels[_CHANNEL_ID] = block

        oc_json.parent.mkdir(parents=True, exist_ok=True)
        oc_json.write_text(json.dumps(oc, indent=2) + "\n")
        console.print(
            f"  [green]channel[/green] {oc_json} → "
            f"room [cyan]{room}[/cyan] agents={target['agents']}"
        )

    def _unregister_channel(self, *, room: str, agent_id: str) -> bool:
        """Drop agent from room's rooms[] entry; prune empty rooms. Returns
        True if anything changed (caller decides whether to restart)."""
        oc, oc_json = self._read_block()
        block = (oc.get("channels") or {}).get(_CHANNEL_ID)
        if not isinstance(block, dict):
            return False

        rooms = self._normalize_rooms(block)
        changed = False
        pruned: list[dict] = []
        for r in rooms:
            if r["room"] == room and agent_id in r["agents"]:
                r["agents"].remove(agent_id)
                changed = True
            if r["room"] == room and not r["agents"]:
                continue  # drop the now-empty room entry
            pruned.append(r)
        if not changed:
            return False

        block["rooms"] = pruned
        oc["channels"][_CHANNEL_ID] = block
        oc_json.write_text(json.dumps(oc, indent=2) + "\n")
        console.print(
            f"  [green]channel[/green] removed [cyan]{agent_id}[/cyan] "
            f"from room [cyan]{room}[/cyan] in {oc_json}"
        )
        return True

    def _destroy_agent(self, agent_id: str) -> None:
        # The subcommand is `agents delete <id>` on openclaw 2026.5.7
        # (verified via `openclaw agents --help`: "delete — Delete an agent
        # and prune workspace/state"). It prunes the workspace itself, so the
        # explicit rmtree below is just a belt-and-suspenders fallback for
        # custom --workspace paths openclaw might not track. `--force` is
        # required: we always run non-interactively, and without it openclaw
        # refuses with "Non-interactive session. Re-run with --force." —
        # leaving the agent record orphaned after its workspace is gone.
        result = subprocess.run(
            self._oc_cmd(["openclaw", "agents", "delete", agent_id, "--force"]),
            text=True,
            capture_output=True,
        )
        combined = ((result.stderr or "") + (result.stdout or "")).lower()
        if result.returncode != 0 and "not found" not in combined and "no such" not in combined:
            console.print(
                f"  [yellow]openclaw agents delete {agent_id} returned "
                f"{result.returncode}[/yellow]: "
                f"{(result.stderr or result.stdout).strip()[:160]}"
            )
        else:
            console.print(f"  [green]destroyed[/green] OpenClaw agent {agent_id}")

        state_dir, _ = self._paths()
        workspace = state_dir / "workspaces" / agent_id
        if workspace.exists():
            shutil.rmtree(workspace, ignore_errors=True)
            console.print(f"  [green]removed[/green] workspace {workspace}")

    # ── lifecycle ───────────────────────────────────────────────────────────

    def register(
        self, *, manifest: AgentManifest, config: MyceliumConfig, opts: AddOptions
    ) -> None:
        agent_id = manifest.openclaw_agent
        assert agent_id  # guaranteed by AgentManifest validation
        if manifest.openclaw_created:
            self._create_agent(agent_id=agent_id, description=manifest.description)
        else:
            console.print(
                f"  [green]adopting[/green] existing OpenClaw agent [cyan]{agent_id}[/cyan]"
            )
        self._register_channel(room=opts.room, agent_id=agent_id, backend_url=config.server.api_url)
        self.restart_gateway()

    def destroy(
        self, *, manifest: AgentManifest, config: MyceliumConfig, room: str, full: bool
    ) -> None:
        agent_id = manifest.openclaw_agent
        if not agent_id:
            return
        changed = self._unregister_channel(room=room, agent_id=agent_id)
        if self.will_destroy_runtime(manifest, full=full):
            self._destroy_agent(agent_id)
        if changed:
            self.restart_gateway()

    def will_destroy_runtime(self, manifest: AgentManifest, *, full: bool) -> bool:
        # Only destroy agents WE created. Adopted agents are the user's — never.
        return bool(full and manifest.openclaw_created and manifest.openclaw_agent)

    def describe(self, manifest: AgentManifest, *, room: str) -> list[str]:
        mode = "create" if manifest.openclaw_created else "adopt"
        return [
            f"  adapter:        openclaw ({mode})",
            f"  openclaw_agent: {manifest.openclaw_agent}",
            "\n[dim]OpenClaw agents are dispatched by the gateway's "
            "mycelium-room channel, not the cc-daemon.[/dim]\n"
            f'[dim]Invoke:[/dim] mycelium agent invoke {manifest.handle} "..."',
        ]

    # ── install facet ───────────────────────────────────────────────────────
    # Behaviour relocated verbatim from the old ``commands/adapter.py`` add/
    # remove/status bodies; the command layer just dispatches here now.

    STEPS = _OPENCLAW_STEPS

    def install(
        self,
        *,
        config: MyceliumConfig,
        verbose: bool,
        profile: str | None,
        container: str | None,
        reinstall: bool,
    ) -> None:
        # Probe the configured hub so a misconfigured spoke fails loudly at
        # install time rather than silently archiving conversation turns
        # forever (issue #139). Best-effort: warn-only so air-gapped or
        # not-yet-running setups still install.
        api_url = config.server.api_url
        ok, reason = _probe_hub_reachable(api_url)
        if ok:
            if verbose:
                typer.echo(f"  hub probe: {api_url}/health → {reason}")
        else:
            typer.secho(
                f"  warning: cannot reach Mycelium backend at {api_url}/health ({reason})",
                fg=typer.colors.YELLOW,
            )
            typer.echo(
                "  The knowledge-extract hook will archive locally "
                "until the backend is reachable. Verify "
                "[server].api_url in ~/.mycelium/config.toml."
            )
        _install_openclaw(
            verbose=verbose,
            profile=profile,
            container=container,
            config=config,
            reinstall=reinstall,
        )

    def uninstall(self, *, record: dict, profile: str | None, container: str | None) -> None:
        _uninstall_openclaw(record, profile=profile, container=container)

    def reinstall_targets(self, *, profile: str | None, container: str | None) -> list[str]:
        state_dir = _openclaw_state_dir(profile)
        return [
            f"  • {state_dir}/extensions/{_OPENCLAW_PLUGIN_NAME}",
            f"  • {state_dir}/hooks/{_OPENCLAW_HOOK_NAME}",
            f"  • <agent workspaces>/skills/{_OPENCLAW_SKILL_NAME}",
        ]

    def dry_run_lines(
        self, *, config: MyceliumConfig, profile: str | None, container: str | None
    ) -> list[str]:
        plugin_src = _resolve_asset(_MYCELIUM_PLUGIN_SRC)
        parts: list[str] = ["openclaw"]
        if profile and profile.lower() != "default":
            parts += ["--profile", profile]
        if container:
            parts += ["--container", container]
        prefix = " ".join(parts)
        lines = [
            f"  {prefix} plugins install {plugin_src}",
            f"  state dir: {_openclaw_state_dir(profile)}",
        ]
        if container:
            lines.append(f"  container: {container} (assets staged via docker cp)")
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
        typer.secho(f"Adapter 'openclaw' {verb}.", fg=typer.colors.GREEN)
        typer.echo(f"  plugin:  {_OPENCLAW_PLUGIN_NAME}")
        typer.echo(f"  hook:    {_OPENCLAW_HOOK_NAME}")
        typer.echo(f"  skill:   {_OPENCLAW_SKILL_NAME}")
        typer.echo("")
        typer.secho("  Next steps:", bold=True)
        typer.echo("")
        typer.echo(
            "  1. Allow mycelium CLI execution for each agent that should run mycelium commands"
        )
        typer.echo(
            "     (scope per-agent so only the agents wired into a Mycelium room can exec it):"
        )
        typer.secho(
            '       $ openclaw approvals allowlist add --agent "<agent-id>" "~/.local/bin/mycelium"',
            fg=typer.colors.CYAN,
        )
        typer.echo("")
        # Step 2: channel config guidance — only if not already configured.
        # The channel block lives under `channels.mycelium-room` in openclaw.json
        # and is how agents use Mycelium rooms as an addressed chat surface.
        channel_configured = False
        try:
            oc_json = _openclaw_state_dir(profile) / "openclaw.json"
            if oc_json.exists():
                oc_cfg = json.loads(oc_json.read_text())
                channel_configured = bool((oc_cfg.get("channels") or {}).get("mycelium-room"))
        except Exception:
            channel_configured = False

        if not channel_configured:
            typer.echo(
                "  2. (Optional) Enable the mycelium-room channel so agents can "
                "coordinate through a Mycelium room."
            )
            typer.echo(f"     Add this block to {_openclaw_state_dir(profile)}/openclaw.json:")
            typer.echo("")
            typer.secho(
                '       "channels": {\n'
                '         "mycelium-room": {\n'
                '           "enabled": true,\n'
                f'           "backendUrl": "{config.server.api_url}",\n'
                '           "room": "<room-name>",\n'
                '           "agents": ["<agent-id-1>", "<agent-id-2>"],\n'
                '           "requireMention": true\n'
                "         }\n"
                "       }",
                fg=typer.colors.CYAN,
            )
            typer.echo("")
            typer.echo(
                "     Skip this if you only want the `mycelium` skill + hooks "
                "(no channel messaging)."
            )
            typer.echo("")
            typer.echo("  3. Restart the openclaw gateway to pick up the updated plugin:")
            typer.secho("    $ openclaw gateway restart", fg=typer.colors.CYAN)
        else:
            typer.echo("  2. Restart the openclaw gateway to pick up the updated plugin:")
            typer.secho("    $ openclaw gateway restart", fg=typer.colors.CYAN)
        typer.echo("")
        typer.echo("  For Docker-based experiment agents, get required env vars:")
        typer.secho("    $ mycelium adapter add openclaw --step=docker-env", fg=typer.colors.CYAN)

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
        if remove:
            typer.secho(
                "--remove-step is not implemented for openclaw steps yet.",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)
        if step == "docker-env":
            _step_docker_env(config)
        elif step == "otel":
            if _configure_otel(profile=profile, container=container):
                _restart_gateway_if_needed(profile, container)

    def status_check(self, *, name: str, info: dict) -> dict:
        details: list[str] = []
        ok = True

        profile = info.get("openclaw_profile")
        container = info.get("openclaw_container")
        state_dir = _openclaw_state_dir(profile)

        # Check skill via filesystem (openclaw has no skills install/list CLI)
        skill_dir = state_dir / "workspace" / "skills" / _OPENCLAW_SKILL_NAME
        skill_ok = (skill_dir / "SKILL.md").exists()
        details.append(f"  {'✓' if skill_ok else '✗'} skill:{_OPENCLAW_SKILL_NAME}")
        if not skill_ok:
            ok = False

        # Check hook via filesystem (list output truncates long names)
        hook_dir = state_dir / "hooks" / _OPENCLAW_HOOK_NAME
        hook_ok = (hook_dir / "HOOK.md").exists()
        details.append(f"  {'✓' if hook_ok else '✗'} hook:{_OPENCLAW_HOOK_NAME}")
        if not hook_ok:
            ok = False

        # Stale hooks (e.g. mycelium-knowledge-extract) should not be present.
        for stale in _OPENCLAW_STALE_HOOKS:
            if (state_dir / "hooks" / stale).exists():
                details.append(
                    f"  ! stale hook still installed: {stale} (run `mycelium adapter add openclaw --force`)"
                )
                ok = False

        # Check plugin via openclaw plugins list (names don't truncate)
        result = subprocess.run(
            _openclaw_cmd(["openclaw", "plugins", "list"], profile, container),
            text=True,
            capture_output=True,
        )
        plugin_ok = result.returncode == 0 and _OPENCLAW_PLUGIN_NAME in (result.stdout or "")
        details.append(f"  {'✓' if plugin_ok else '✗'} plugin:{_OPENCLAW_PLUGIN_NAME}")
        if not plugin_ok:
            ok = False

        details.append(f"api_url: {info.get('api_url', '')}")
        return {"ok": ok, "details": details}


#: Back-compat alias for the historical class name.
OpenClawAdapter = OpenClawIntegration
