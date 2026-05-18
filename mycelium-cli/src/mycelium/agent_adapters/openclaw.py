# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""OpenClawAdapter — agent runs in the OpenClaw gateway.

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
from typing import TYPE_CHECKING

from rich.console import Console

from mycelium.agent_adapters.base import AddOptions, AgentAdapter
from mycelium.sstp import AgentManifest

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig

console = Console()

_CHANNEL_ID = "mycelium-room"


class OpenClawError(RuntimeError):
    """Raised when an `openclaw` CLI invocation or config write fails."""


class OpenClawAdapter(AgentAdapter):
    name = "openclaw"

    def __init__(
        self,
        *,
        openclaw_agent: str | None = None,
        model: str | None = None,
        openclaw_profile: str | None = None,
    ) -> None:
        # These are openclaw-only `agent add` flags, threaded in at
        # construction so build_manifest/register stay uniform across adapters.
        self._explicit_agent = openclaw_agent
        self._model = model
        self._profile = openclaw_profile

    # ── path + process helpers ──────────────────────────────────────────────

    def _paths(self) -> tuple[Path, Path]:
        """(state_dir, openclaw.json) — reuses the adapter command's resolver."""
        from mycelium.commands.adapter import _openclaw_state_dir

        state_dir = _openclaw_state_dir(self._profile)
        return state_dir, state_dir / "openclaw.json"

    def _oc_cmd(self, args: list[str]) -> list[str]:
        from mycelium.commands.adapter import _openclaw_cmd

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
        state_dir, oc_json = self._paths()
        workspace = state_dir / "workspaces" / agent_id

        model = self._model
        if not model and oc_json.exists():
            try:
                oc = json.loads(oc_json.read_text())
                model = oc.get("agents", {}).get("defaults", {}).get("model") or None
            except (OSError, ValueError):
                model = None
        if not model:
            raise OpenClawError(
                "No model for the new OpenClaw agent. Pass --model "
                "(e.g. anthropic/claude-haiku-4-5-20251001) or set "
                "agents.defaults.model in openclaw.json."
            )

        result = subprocess.run(
            self._oc_cmd(
                [
                    "openclaw",
                    "agents",
                    "add",
                    agent_id,
                    "--non-interactive",
                    "--workspace",
                    str(workspace),
                    "--model",
                    model,
                ]
            ),
            text=True,
            capture_output=True,
        )
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

        console.print(
            f"  [green]created[/green] OpenClaw agent [cyan]{agent_id}[/cyan] "
            f"(model {model}, workspace {workspace})"
        )

    # ── channel config (rooms[] fan-out) ────────────────────────────────────

    def _read_block(self) -> tuple[dict, Path]:
        _state_dir, oc_json = self._paths()
        oc = {}
        if oc_json.exists():
            try:
                oc = json.loads(oc_json.read_text())
            except ValueError as exc:
                raise OpenClawError(f"{oc_json} is not valid JSON: {exc}") from exc
        return oc, oc_json

    @staticmethod
    def _normalize_rooms(block: dict) -> list[dict]:
        """Fold a legacy top-level room/agents into rooms[]; return rooms[]."""
        rooms: list[dict] = []
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
        target = next((r for r in rooms if r["room"] == room), None)
        if target is None:
            target = {"room": room, "agents": []}
            rooms.append(target)
        if agent_id not in target["agents"]:
            target["agents"].append(agent_id)

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
        result = subprocess.run(
            self._oc_cmd(["openclaw", "agents", "remove", agent_id, "--non-interactive"]),
            text=True,
            capture_output=True,
        )
        combined = ((result.stderr or "") + (result.stdout or "")).lower()
        if result.returncode != 0 and "not found" not in combined and "no such" not in combined:
            console.print(
                f"  [yellow]openclaw agents remove {agent_id} returned "
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
