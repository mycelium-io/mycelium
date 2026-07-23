# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Hermes dispatch facet — agent runs in the hermes gateway.

Mirrors the OpenClaw shape almost exactly: hermes agents aren't dispatched
by the mycelium-daemon. They live inside ``hermes gateway run``; the
bundled ``mycelium-room`` platform plugin (Python, in
``assets/mycelium/plugin/``) subscribes to each configured room's SSE,
formats ticks/consensus, and dispatches to the gateway's agent loop. So
registration is:

  1. ensure ``mycelium`` is listed in ``plugins.enabled`` and
     ``platforms.mycelium-room`` is configured (the install facet does this).
  2. append ``{room, agents}`` to ``platforms.mycelium-room.extra.rooms[]``
     in ``~/.hermes/config.yaml``.
  3. ``hermes gateway restart`` so the gateway re-reads the platform config.

There is no separate "hermes agent" object to create — hermes treats a
handle exposed through a platform adapter as just another participant.
That mirrors the OpenClaw plugin's create-vs-adopt distinction in spirit:
mycelium never owns the underlying hermes-side identity; we only own the
fan-out entry that points the platform at this handle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import typer
from rich.console import Console

from mycelium.integrations._resources import _resolve_asset
from mycelium.integrations.base import AddOptions, Integration
from mycelium.integrations.hermes.install import (
    _HERMES_PLATFORM_ID,
    _HERMES_PLUGIN_NAME,
    _HERMES_STEPS,
    _MYCELIUM_PLUGIN_SRC,
    _MYCELIUM_SKILL_SRC,
    HermesConfigError,
    _hermes_config_yaml,
    _hermes_home,
    _hermes_plugin_dst,
    _hermes_skill_dst,
    _install_hermes,
    _read_config_yaml,
    _read_gateway_pid,
    _restart_gateway,
    _uninstall_hermes,
    _write_config_yaml,
)
from mycelium.protocol import AgentManifest

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig

console = Console()


class HermesError(RuntimeError):
    """Raised when a hermes config write or gateway invocation fails."""


class HermesIntegration(Integration):
    name = "hermes"
    lifecycle = "long_lived_gateway"

    # ── path helpers ────────────────────────────────────────────────────────

    def _paths(self) -> tuple:
        """(state_dir, config_yaml) — shared with install facet."""
        return _hermes_home(), _hermes_config_yaml()

    # ── manifest ────────────────────────────────────────────────────────────

    def build_manifest(
        self,
        *,
        handle: str,
        opts: AddOptions,  # noqa: ARG002 - room not consumed by build_manifest yet
        description: str,
        budget: float,
        allow_from: list[str],
    ) -> AgentManifest:
        return AgentManifest(
            handle=handle,
            adapter="hermes",
            description=description,
            budget_usd_per_month=budget,
            allow_from=allow_from,
        )

    # ── room fan-out ────────────────────────────────────────────────────────
    #
    # The hermes plugin reads ``platforms.mycelium-room.extra.rooms`` on
    # gateway boot; each entry is ``{room: <name>, agents: [<handle>, ...]}``.
    # ``_register_room`` appends/merges; ``_unregister_room`` prunes.

    @staticmethod
    def _normalize_rooms(extra: dict[str, Any]) -> list[dict[str, Any]]:
        rooms_raw = extra.get("rooms")
        if not isinstance(rooms_raw, list):
            return []
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for entry in rooms_raw:
            if not isinstance(entry, dict):
                continue
            rname = entry.get("room")
            if not isinstance(rname, str) or not rname or rname in seen:
                continue
            agents_raw = entry.get("agents") or []
            agents = [str(a) for a in agents_raw if isinstance(a, (str, int))]
            out.append({"room": rname, "agents": agents})
            seen.add(rname)
        return out

    def _read_platform_extra(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """Return (full config dict, platform `extra` dict) for read-modify-write.

        Raises :class:`HermesError` if the platform block is missing — that
        means ``adapter add hermes`` has not run on this host yet.
        """
        try:
            data = _read_config_yaml()
        except HermesConfigError as exc:
            raise HermesError(str(exc)) from exc
        platforms = data.get("platforms") or {}
        block = platforms.get(_HERMES_PLATFORM_ID)
        if not isinstance(block, dict):
            raise HermesError(
                f"hermes ~/.hermes/config.yaml has no [platforms.{_HERMES_PLATFORM_ID}] block — "
                "run `mycelium adapter add hermes` first."
            )
        extra = block.setdefault("extra", {})
        if not isinstance(extra, dict):
            extra = {}
            block["extra"] = extra
        return data, extra

    def _register_room(self, *, room: str, handle: str) -> None:
        data, extra = self._read_platform_extra()
        rooms = self._normalize_rooms(extra)
        target = next((r for r in rooms if r["room"] == room), None)
        if target is None:
            target = {"room": room, "agents": []}
            rooms.append(target)
        # ``_normalize_rooms`` guarantees ``agents`` is a list[str]; the cast
        # is solely to narrow the type for ty after the dict round-trip.
        agents: list[str] = target["agents"] if isinstance(target["agents"], list) else []
        if handle not in agents:
            agents.append(handle)
        target["agents"] = agents
        extra["rooms"] = rooms
        path = _write_config_yaml(data)
        console.print(
            f"  [green]registered[/green] {path} → room [cyan]{room}[/cyan] agents={agents}"
        )

    def _unregister_room(self, *, room: str, handle: str) -> bool:
        try:
            data, extra = self._read_platform_extra()
        except HermesError:
            # Adapter not installed → nothing to unregister; treat as no-op.
            return False
        rooms = self._normalize_rooms(extra)
        changed = False
        pruned: list[dict[str, Any]] = []
        for r in rooms:
            if r["room"] == room and handle in r["agents"]:
                r["agents"].remove(handle)
                changed = True
            if r["room"] == room and not r["agents"]:
                continue  # drop empty room entry
            pruned.append(r)
        if not changed:
            return False
        extra["rooms"] = pruned
        path = _write_config_yaml(data)
        console.print(
            f"  [green]unregistered[/green] [cyan]{handle}[/cyan] "
            f"from room [cyan]{room}[/cyan] in {path}"
        )
        return True

    # ── lifecycle ───────────────────────────────────────────────────────────

    def register(
        self,
        *,
        manifest: AgentManifest,
        config: MyceliumConfig,
        opts: AddOptions,  # noqa: ARG002
    ) -> None:
        self._register_room(room=opts.room, handle=manifest.handle)
        _restart_gateway()

    def destroy(
        self,
        *,
        manifest: AgentManifest,
        config: MyceliumConfig,  # noqa: ARG002
        room: str,
        full: bool,  # noqa: ARG002 - hermes has nothing to destroy `--full`
    ) -> None:
        changed = self._unregister_room(room=room, handle=manifest.handle)
        if changed:
            _restart_gateway()

    def will_destroy_runtime(self, manifest: AgentManifest, *, full: bool) -> bool:  # noqa: ARG002
        # hermes-side identity isn't owned by mycelium — `--full` has no effect.
        return False

    def describe(self, manifest: AgentManifest, *, room: str) -> list[str]:  # noqa: ARG002
        return [
            "  adapter: hermes",
            "\n[dim]Hermes agents are dispatched by the gateway's "
            f"{_HERMES_PLATFORM_ID} platform plugin, not the mycelium-daemon.[/dim]\n"
            f'[dim]Invoke:[/dim] mycelium agent invoke {manifest.handle} "..."',
        ]

    # ── install facet ───────────────────────────────────────────────────────

    STEPS = _HERMES_STEPS

    def install(
        self,
        *,
        config: MyceliumConfig,
        verbose: bool,
        profile: str | None,  # noqa: ARG002 - hermes always uses the active profile
        container: str | None,  # noqa: ARG002 - containerised hermes is a v2 followup
        reinstall: bool,
    ) -> None:
        # Profile selection is deliberately ignored: Mycelium targets whichever
        # hermes profile is active on the host (``$HERMES_HOME`` or
        # ``~/.hermes/``). First-class multi-profile support is on hold until
        # ``hermes-agent#25660`` — once handle-level routing inside one
        # gateway lands, this whole profile-as-deployment-unit branch goes
        # away anyway.
        from mycelium.integrations.hermes.install import _probe_hub_reachable

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
                "  The hermes plugin will start once the backend is reachable. "
                "Verify [server].api_url in ~/.mycelium/config.toml."
            )
        _install_hermes(verbose=verbose, config=config, reinstall=reinstall)

    def uninstall(
        self,
        *,
        record: dict,
        profile: str | None,  # noqa: ARG002
        container: str | None,  # noqa: ARG002
    ) -> None:
        _uninstall_hermes(record)

    def reinstall_targets(
        self,
        *,
        profile: str | None,  # noqa: ARG002
        container: str | None,  # noqa: ARG002
    ) -> list[str]:
        return [
            f"  • {_hermes_plugin_dst()}",
            f"  • {_hermes_skill_dst()}",
            f"  • {_hermes_config_yaml()} (plugins.enabled, platforms.{_HERMES_PLATFORM_ID}.*)",
        ]

    def dry_run_lines(
        self,
        *,
        config: MyceliumConfig,
        profile: str | None,  # noqa: ARG002
        container: str | None,  # noqa: ARG002
    ) -> list[str]:
        plugin_src = _resolve_asset(_MYCELIUM_PLUGIN_SRC, family="hermes")
        skill_src = _resolve_asset(_MYCELIUM_SKILL_SRC, family="hermes")
        return [
            f"  stage plugin: {plugin_src} → {_hermes_plugin_dst()}",
            f"  stage skill:  {skill_src} → {_hermes_skill_dst()}",
            f"  patch:        {_hermes_config_yaml()}",
            f"                  plugins.enabled += {_HERMES_PLUGIN_NAME}",
            f"                  platforms.{_HERMES_PLATFORM_ID}.enabled = true",
            f"                  platforms.{_HERMES_PLATFORM_ID}.extra.backend_url = {config.server.api_url}",
            "  hermes gateway restart",
        ]

    def post_install_banner(
        self,
        *,
        config: MyceliumConfig,
        reinstall: bool,
        profile: str | None,  # noqa: ARG002
        container: str | None,  # noqa: ARG002
    ) -> None:
        verb = "reinstalled" if reinstall else "installed"
        typer.secho(f"Adapter 'hermes' {verb}.", fg=typer.colors.GREEN)
        typer.echo(f"  plugin: {_hermes_plugin_dst()}")
        typer.echo(f"  config: {_hermes_config_yaml()}")
        typer.echo("")
        typer.secho("  Next steps:", bold=True)
        typer.echo("")
        typer.echo("  1. Wire agents into a room with `mycelium agent add`. Each wired-in")
        typer.echo("     handle is appended to platforms.mycelium-room.extra.rooms[] in")
        typer.echo("     hermes's config.yaml.")
        typer.echo("")
        typer.echo("  2. Make sure the hermes gateway is running:")
        typer.secho("    $ hermes gateway status", fg=typer.colors.CYAN)
        typer.secho("    $ hermes gateway restart", fg=typer.colors.CYAN)
        typer.echo("")
        typer.echo("  3. (Optional) If you want HTTP-style access alongside the platform")
        typer.echo("     adapter, set API_SERVER_KEY in ~/.hermes/.env and enable the")
        typer.echo("     api_server platform — see hermes docs for details.")
        typer.echo("")
        typer.echo(f"  Mycelium backend: {config.server.api_url}")

    def run_step(
        self,
        step: str,
        *,
        config: MyceliumConfig,  # noqa: ARG002
        verbose: bool,  # noqa: ARG002
        profile: str | None,  # noqa: ARG002
        container: str | None,  # noqa: ARG002
        remove: bool,  # noqa: ARG002
    ) -> None:
        # No --step actions defined yet for hermes; the dispatcher in
        # commands/adapter.py validates against STEPS before reaching us, so
        # any value that lands here is a programmer error.
        typer.secho(
            f"Unknown hermes step '{step}' (no steps defined for this adapter yet).",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    def status_check(self, *, name: str, info: dict) -> dict:  # noqa: ARG002
        details: list[str] = []
        ok = True

        plugin_yaml = _hermes_plugin_dst() / "plugin.yaml"
        plugin_ok = plugin_yaml.exists()
        details.append(f"  {'✓' if plugin_ok else '✗'} plugin:{_HERMES_PLUGIN_NAME}")
        if not plugin_ok:
            ok = False

        # Inspect config.yaml without raising — status_check is a probe, not a write.
        config_ok = False
        platform_ok = False
        try:
            data = _read_config_yaml()
        except HermesConfigError:
            data = {}
        plugins_block = data.get("plugins") if isinstance(data, dict) else None
        if isinstance(plugins_block, dict):
            enabled = plugins_block.get("enabled")
            if isinstance(enabled, list) and _HERMES_PLUGIN_NAME in enabled:
                config_ok = True
        platforms_block = data.get("platforms") if isinstance(data, dict) else None
        if isinstance(platforms_block, dict):
            block = platforms_block.get(_HERMES_PLATFORM_ID)
            if isinstance(block, dict) and block.get("enabled") is True:
                platform_ok = True

        details.append(f"  {'✓' if config_ok else '✗'} config:plugins.enabled")
        details.append(
            f"  {'✓' if platform_ok else '✗'} config:platforms.{_HERMES_PLATFORM_ID}.enabled"
        )
        if not config_ok or not platform_ok:
            ok = False

        # Gateway alive check: PID file present *and* the PID is responsive.
        # `kill -0` (signal 0) is a permission probe; it doesn't actually
        # signal the process — POSIX-standard idiom for "is this PID alive".
        gateway_ok = False
        pid = _read_gateway_pid()
        if pid is not None:
            try:
                import os

                os.kill(pid, 0)
                gateway_ok = True
            except OSError:
                gateway_ok = False
        details.append(f"  {'✓' if gateway_ok else '✗'} gateway:hermes-gateway-pid")
        if not gateway_ok:
            ok = False

        details.append(f"api_url: {info.get('api_url', '')}")
        return {"ok": ok, "details": details}


def unregister_room_from_hermes(room_name: str) -> list[str]:
    """Remove *room_name* from the local hermes config.yaml in one shot.

    Called by ``mycelium room delete`` to keep the hermes gateway from
    re-opening an SSE connection to a room that no longer exists after the
    next ``hermes gateway restart``.

    Returns the list of agent handles that were registered in the room (may
    be empty).  Returns [] silently if hermes config is absent or unreadable.
    """
    try:
        data = _read_config_yaml()
    except (HermesConfigError, Exception):
        return []

    platforms = data.get("platforms") or {}
    block = platforms.get(_HERMES_PLATFORM_ID)
    if not isinstance(block, dict):
        return []
    extra = block.get("extra") or {}
    if not isinstance(extra, dict):
        return []
    rooms_raw = extra.get("rooms") or []
    if not isinstance(rooms_raw, list):
        return []

    removed_agents: list[str] = []
    kept: list[dict] = []
    for entry in rooms_raw:
        if not isinstance(entry, dict):
            kept.append(entry)
            continue
        if entry.get("room") == room_name:
            agents_raw = entry.get("agents") or []
            removed_agents = [str(a) for a in agents_raw if isinstance(a, (str, int))]
        else:
            kept.append(entry)

    if not removed_agents:
        return []

    extra["rooms"] = kept
    try:
        _write_config_yaml(data)
    except Exception:
        return []

    try:
        _restart_gateway()
    except Exception:
        pass

    return removed_agents


#: Back-compat alias matching the convention used by the other integrations.
HermesAdapter = HermesIntegration
