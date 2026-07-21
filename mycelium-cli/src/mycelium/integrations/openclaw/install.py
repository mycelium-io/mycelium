# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""OpenClaw install facet — host-level install/uninstall/steps/status core.

Relocated verbatim from ``commands/adapter.py`` so the single ``Integration``
contract (see ``integrations/base.py``) owns both the dispatch and install
facets per runtime family — closing #173. The typer command layer is now a
thin dispatcher over ``get_integration(...)``; nothing here changed behaviour.

``_openclaw_state_dir`` / ``_openclaw_cmd`` are the two pure boundary helpers
the dispatch facet also imports (inverting the old commands→core back-import).
"""

from __future__ import annotations

import json as json_module
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import typer

from mycelium.integrations._resources import _resolve_asset

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig


def _openclaw_state_dir(profile: str | None) -> Path:
    """Return ~/.openclaw-<profile>/ or ~/.openclaw/ for default."""
    if profile and profile.lower() != "default":
        return Path.home() / f".openclaw-{profile}"
    return Path.home() / ".openclaw"


def _openclaw_cmd(args: list[str], profile: str | None, container: str | None = None) -> list[str]:
    """Build an openclaw command, routing through `docker exec` when containerized.

    When `container` is set we bypass OpenClaw's own `--container` flag (which
    uses `docker inspect` name resolution that fails for many Compose-generated
    names) and shell out via `docker exec` directly — the same strategy already
    used by `_stage_assets_in_container`.
    """
    profile_args: list[str] = []
    if profile and profile.lower() != "default":
        profile_args = ["--profile", profile]

    # Strip the leading "openclaw" from args so we can rebuild cleanly
    subcmd = args[1:] if args and args[0] == "openclaw" else args

    if container:
        return ["docker", "exec", container, "openclaw", *profile_args, *subcmd]

    if profile_args:
        return ["openclaw", *profile_args, *subcmd]
    return args


# ── constants (relocated verbatim from commands/adapter.py) ───────────────────

_OPENCLAW_PLUGIN_NAME = "mycelium"
_OPENCLAW_HOOK_NAME = "mycelium-bootstrap"
_OPENCLAW_SKILL_NAME = "mycelium"
# OpenClaw hooks that earlier versions installed but no longer do. On
# reinstall we remove them so upgraders don't keep the silent path running.
_OPENCLAW_STALE_HOOKS: list[str] = ["mycelium-knowledge-extract"]

# >= 2026.5.3: plugins must ship compiled dist/ (TS source-only rejected at install time)
# >= 2026.5.7: hooks install/uninstall removed; hooks are managed by the plugin system
_OPENCLAW_MIN_VERSION = (2026, 5, 7)

_OPENCLAW_STEPS = {
    "otel": "configure OpenClaw diagnostics-otel plugin to export to the OTLP receiver",
    "docker-env": "show env vars for Docker-based experiment agents",
}

_MYCELIUM_ASSET_ROOT = "mycelium"  # subdir under integrations/openclaw/assets/
_MYCELIUM_PLUGIN_SRC = f"{_MYCELIUM_ASSET_ROOT}/plugin"
_MYCELIUM_BOOTSTRAP_HOOK_SRC = f"{_MYCELIUM_ASSET_ROOT}/hooks/{_OPENCLAW_HOOK_NAME}"
_MYCELIUM_SKILL_SRC = f"{_MYCELIUM_PLUGIN_SRC}/skills/{_OPENCLAW_SKILL_NAME}"

# Assets that go into each agent's ~/.openclaw/ directory
_OPENCLAW_SCAFFOLD_ASSETS = [
    # (source subpath in mycelium package, dest subpath in target .openclaw dir)
    (_MYCELIUM_PLUGIN_SRC, f"extensions/{_OPENCLAW_PLUGIN_NAME}"),
    (_MYCELIUM_BOOTSTRAP_HOOK_SRC, f"hooks/{_OPENCLAW_HOOK_NAME}"),
    (_MYCELIUM_SKILL_SRC, f"workspace/skills/{_OPENCLAW_SKILL_NAME}"),
]


# ── install / uninstall / step / status core (relocated verbatim) ────────────


def _check_openclaw_version(container: str | None = None) -> None:
    """Warn if the detected openclaw version is below _OPENCLAW_MIN_VERSION."""
    cmd = (
        ["docker", "exec", container, "openclaw", "--version"]
        if container
        else ["openclaw", "--version"]
    )
    result = subprocess.run(cmd, text=True, capture_output=True)
    raw = (result.stdout + result.stderr).strip()
    # Version string is expected to be "YYYY.M.P" or "openclaw/YYYY.M.P ..."
    m = re.search(r"(\d{4})\.(\d+)\.(\d+)", raw)
    if not m:
        typer.secho(
            f"  warning: could not detect openclaw version (got: {raw[:60]!r})"
            " — mycelium v1.0.10+ requires openclaw >= 2026.5.7",
            fg=typer.colors.YELLOW,
        )
        return
    detected = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if detected < _OPENCLAW_MIN_VERSION:
        min_str = ".".join(str(x) for x in _OPENCLAW_MIN_VERSION)
        det_str = ".".join(str(x) for x in detected)
        typer.secho(
            f"  warning: openclaw {det_str} is below the required {min_str}."
            " Run `npm install -g openclaw@latest` to upgrade.",
            fg=typer.colors.YELLOW,
        )


def _openclaw_container_home(container: str) -> str:
    """Return the $HOME path inside the container (defaults to /root)."""
    result = subprocess.run(
        ["docker", "exec", container, "sh", "-c", "echo $HOME"],
        text=True,
        capture_output=True,
    )
    home = result.stdout.strip()
    return home if home else "/root"


def _stage_assets_in_container(container: str, src: Path, container_dest: str) -> None:
    """
    docker cp src into container at container_dest, then chown to root (UID 0).

    OpenClaw rejects plugins owned by non-root UIDs when running containerized,
    so the chown is required for the plugin to load cleanly.

    The destination is wiped first so re-runs replace rather than nest: ``docker
    cp <dir> container:<existing-dir>`` copies *into* the existing dir (creating
    ``<dir>/<basename>``), which on a reinstall would produce ``dist/dist`` /
    ``mycelium/plugin``. The wipe runs as root because a prior stage chowned the
    tree to 0:0 — the default container user can't remove a root-owned subtree.
    """
    parent = container_dest.rsplit("/", 1)[0]
    subprocess.run(
        ["docker", "exec", "-u", "0", container, "rm", "-rf", container_dest],
        text=True,
        capture_output=True,
    )
    # Ensure the parent directory exists inside the container
    subprocess.run(
        ["docker", "exec", container, "mkdir", "-p", parent],
        text=True,
        capture_output=True,
    )
    result = subprocess.run(
        ["docker", "cp", str(src), f"{container}:{container_dest}"],
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"docker cp to {container}:{container_dest} failed: {result.stderr.strip()}"
        )
    result = subprocess.run(
        ["docker", "exec", "-u", "0", container, "chown", "-R", "0:0", container_dest],
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"chown in container {container} failed: {result.stderr.strip()}")


def _wait_container_healthy(container: str, timeout: int = 30) -> None:
    """Block until a container is running after a gateway restart.

    ``openclaw plugins/hooks install`` writes to ``openclaw.json`` which
    triggers an async gateway restart.  Any ``docker exec`` issued while the
    restart is in-flight is killed (exit 137).  This helper polls until the
    container is back and accepting exec calls.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["docker", "exec", container, "true"],
            capture_output=True,
        )
        if result.returncode == 0:
            return
        time.sleep(1)
    raise RuntimeError(f"Container {container} did not become healthy within {timeout}s")


def _container_config_path(container: str, profile: str | None) -> str:
    """Return the openclaw.json path inside a container."""
    home = _openclaw_container_home(container)
    suffix = f"-{profile}" if profile and profile.lower() != "default" else ""
    return f"{home}/.openclaw{suffix}/openclaw.json"


def _read_container_json(container: str, path: str) -> dict | None:
    """Read and parse a JSON file inside a container, or None if missing."""
    result = subprocess.run(
        ["docker", "exec", container, "cat", path],
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    try:
        import json as _json

        return _json.loads(result.stdout)
    except Exception:
        return None


def _write_container_json(container: str, path: str, data: dict) -> None:
    """Write a dict as JSON to a file inside a container."""
    import json as _json

    payload = _json.dumps(data, indent=2)
    subprocess.run(
        ["docker", "exec", "-i", container, "tee", path],
        input=payload,
        text=True,
        capture_output=True,
        check=True,
    )


# Source tree lives at mycelium-cli/src/mycelium/integrations/openclaw/assets/mycelium/
# (the "mycelium" umbrella directory grouping plugin + hooks + skills as one
# logical package). OpenClaw still expects each concern in its canonical


def _plugin_copy_ignore(_src: str, names: list[str]) -> list[str]:
    """shutil.copytree ignore filter for staging the plugin into an extension dir.

    Drops dev-only files but KEEPS dist/: it's the committed, compiled plugin and
    openclaw validates plugins.entries.mycelium against the extension dir on
    reinstall. Excluding dist/ here would fail that validation ("extension entry
    not found: dist/index.js") before the build/install could repopulate it.
    """
    return [n for n in names if n in ("node_modules", "test", "package-lock.json")]


def _copy_built_dist_to_extension(plugin_dir: Path, *, profile: str | None = None) -> None:
    """Copy compiled dist/ into the installed OpenClaw extension dir.

    ``openclaw plugins install`` blanket-excludes dist/, so we mirror it manually.
    """
    dist_src = plugin_dir / "dist"
    dist_dst = _openclaw_state_dir(profile) / "extensions" / _OPENCLAW_PLUGIN_NAME / "dist"
    if not dist_src.exists():
        return
    if dist_dst.exists():
        shutil.rmtree(dist_dst, ignore_errors=True)
    shutil.copytree(str(dist_src), str(dist_dst))


def _install_openclaw(
    verbose: bool = False,
    profile: str | None = None,
    container: str | None = None,
    config: MyceliumConfig | None = None,
    reinstall: bool = False,
) -> None:
    """
    Install the bundled openclaw plugin and hook.

    - Plugin (mycelium): handles session lifecycle + message forwarding
    - Hook (mycelium-inject): injects MYCELIUM_API_URL + MYCELIUM_ROOM_ID + coordination
      instructions into every agent bootstrap

    When `container` is set, assets are staged inside the container via docker cp
    (with root ownership) before install, so OpenClaw's container-side filesystem
    resolver finds them correctly.  A config.json snapshot is also written into the
    container's ~/.mycelium/ with the Docker-friendly API URL (host.docker.internal
    + published port) so the bootstrap hook and plugin resolve the correct backend.
    """

    def _run(cmd: list[str], allow_already_exists: bool = False) -> None:
        cmd = _openclaw_cmd(cmd, profile, container)
        if verbose:
            typer.echo(f"  running: {' '.join(cmd)}")
        result = subprocess.run(cmd, text=True, capture_output=not verbose)
        if result.returncode != 0:
            stderr = result.stderr.strip() if result.stderr else ""
            combined = (stderr + (result.stdout or "")).lower()
            if allow_already_exists and "already exists" in combined:
                if verbose:
                    typer.echo("  (already installed, skipping)")
                return
            # Exit 137 (SIGKILL) in container mode means the gateway restarted
            # after a config change — the install command completed but the
            # docker exec process was killed by the container restart.
            if container and result.returncode == 137:
                return
            raise RuntimeError(
                f"`{' '.join(cmd[:3])}` failed (exit {result.returncode})"
                + (f": {stderr}" if stderr else "")
            )

    def _build_plugin(plugin_dir: Path) -> None:
        """Refresh the plugin's compiled dist/ via npm install + npm run build.

        OpenClaw 2026.5+ requires a compiled dist/index.js (it rejects TypeScript
        entry points). The compiled dist/ is committed and ships in the wheel, so
        this is a best-effort *refresh* for contributors who edited the source —
        a missing npm just warns and falls back to the shipped dist/ rather than
        hard-blocking the install.

        Used by both the host-native and container install paths (the container
        gateway is just as strict about source-only plugins, so it needs the
        same compiled dist/ before staging).
        """
        for npm_cmd in (
            ["npm", "install", "--prefer-offline", "--silent"],
            ["npm", "run", "build"],
        ):
            if verbose:
                typer.echo(f"  {' '.join(npm_cmd)} (in {plugin_dir})")
            result = subprocess.run(
                npm_cmd, cwd=str(plugin_dir), text=True, capture_output=not verbose
            )
            if result.returncode != 0:
                stderr = (result.stderr or "").strip()
                typer.secho(
                    f"  warning: plugin build step '{' '.join(npm_cmd)}' failed"
                    + (f": {stderr}" if stderr else ""),
                    fg=typer.colors.YELLOW,
                )
                return

    _check_openclaw_version(container)

    if container:
        # Gateway is containerized: stage assets inside the container so install
        # paths resolve from the container filesystem, not the host-only uv path.
        container_home = _openclaw_container_home(container)
        state_suffix = f"-{profile}" if profile and profile.lower() != "default" else ""
        container_state_dir = f"{container_home}/.openclaw{state_suffix}"

        plugin_src = _resolve_asset(_MYCELIUM_PLUGIN_SRC)
        # Build before staging — the containerized gateway is just as strict as
        # the host one (OpenClaw >= 2026.5.3 rejects source-only plugins), so the
        # staged tree must carry a compiled dist/index.js. This mirrors the
        # host-native path's _build_plugin() call added in 0c5f524; the container
        # branch was left unbuilt and regressed once OpenClaw raised the bar.
        _build_plugin(plugin_src)
        container_plugin_path = f"/tmp/mycelium-stage/extensions/{_OPENCLAW_PLUGIN_NAME}"
        if verbose:
            typer.echo(f"  staging {plugin_src} → {container}:{container_plugin_path}")
        _stage_assets_in_container(container, plugin_src, container_plugin_path)
        _run(["openclaw", "plugins", "install", container_plugin_path], allow_already_exists=True)
        _wait_container_healthy(container)

        # openclaw.plugin.json's `extensions` field points at dist/index.js, so
        # the installed extension dir must carry a compiled dist/. Whether
        # `openclaw plugins install` copies dist/ along varies by OpenClaw
        # version; either way _stage_assets_in_container replaces the dest, so
        # the compiled dist/ lands cleanly (no dist/dist nesting on reinstall).
        dist_src = plugin_src / "dist"
        if dist_src.exists():
            container_dist_path = f"{container_state_dir}/extensions/{_OPENCLAW_PLUGIN_NAME}/dist"
            if verbose:
                typer.echo(f"  staging {dist_src} → {container}:{container_dist_path}")
            _stage_assets_in_container(container, dist_src, container_dist_path)
            _wait_container_healthy(container)

        # Remove stale hooks that earlier versions installed inside the container
        # (openclaw hooks uninstall was removed in 2026.5.7).
        for stale in _OPENCLAW_STALE_HOOKS:
            stale_container_path = f"{container_state_dir}/hooks/{stale}"
            subprocess.run(
                ["docker", "exec", container, "rm", "-rf", stale_container_path],
                text=True,
                capture_output=not verbose,
            )

        # Write allow list, load path, and entries into the *container's*
        # openclaw.json so OpenClaw's provenance check passes at runtime.
        _allow_plugin(
            _OPENCLAW_PLUGIN_NAME,
            profile=profile,
            extensions_base=Path(container_state_dir) / "extensions",
            container=container,
        )
        _install_openclaw_skill(profile=profile)

        # ── Write Docker-friendly config.json into the container ─────────
        # The bootstrap hook and plugin read ~/.mycelium/config.json to
        # resolve MYCELIUM_API_URL.  Without this, they fall back to
        # config.toml which contains localhost:<port> — unreachable from
        # inside the container.  We rewrite to host.docker.internal:<port>
        # using the published port from the host's config.toml.
        if config is not None:
            try:
                docker_url = _docker_api_url(config)
                snapshot = config.model_dump(mode="json", exclude_none=True)
                snapshot.setdefault("server", {})["api_url"] = docker_url
                container_config_dir = f"{container_home}/.mycelium"
                container_config_path = f"{container_config_dir}/config.json"
                with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
                    json_module.dump(snapshot, tmp, indent=2)
                    tmp.write("\n")
                    tmp_path = tmp.name
                try:
                    subprocess.run(
                        ["docker", "exec", container, "mkdir", "-p", container_config_dir],
                        text=True,
                        capture_output=True,
                    )
                    result = subprocess.run(
                        ["docker", "cp", tmp_path, f"{container}:{container_config_path}"],
                        text=True,
                        capture_output=True,
                    )
                    if result.returncode != 0:
                        raise RuntimeError(result.stderr.strip())
                    subprocess.run(
                        [
                            "docker",
                            "exec",
                            "-u",
                            "0",
                            container,
                            "chown",
                            "0:0",
                            container_config_path,
                        ],
                        text=True,
                        capture_output=True,
                    )
                    if verbose:
                        typer.echo(
                            f"  wrote {container}:{container_config_path} (api_url={docker_url})"
                        )
                finally:
                    Path(tmp_path).unlink(missing_ok=True)
            except Exception as exc:
                typer.secho(
                    f"  warning: could not write config.json to container: {exc}",
                    fg=typer.colors.YELLOW,
                )

        # The openclaw.json writes above (plugins install + _allow_plugin) each
        # trip the gateway's config watcher into an in-process restart; chained,
        # they race and the gateway can die with "config changed since last load"
        # mid-restart, leaving the container stopped. Force one clean full restart
        # so it converges to a healthy state loading the final config + plugin.
        if verbose:
            typer.echo(f"  restarting {container} to load the final config + plugin")
        restart = subprocess.run(
            ["docker", "restart", container], text=True, capture_output=not verbose
        )
        if restart.returncode == 0:
            _wait_container_healthy(container)
        else:
            typer.secho(
                f"  warning: could not restart {container}"
                f" ({(restart.stderr or '').strip()}) — restart it manually to load the plugin",
                fg=typer.colors.YELLOW,
            )

        return

    # ── Host-native install ───────────────────────────────────────────────────
    # When a profile is set, openclaw may report "already exists" if the plugin
    # is installed on the default profile — but it still needs to be installed
    # on the target profile.  Only tolerate "already exists" for the default
    # profile where a prior install is genuinely a no-op.
    tolerate_exists = not (profile and profile.lower() != "default")

    # `openclaw plugins install` / `hooks install` skip files that already exist
    # at the destination, so on reinstall a stale tree from a prior version would
    # linger even though the command reports success.  On --reinstall, wipe each
    # target dir and then copy the fresh source over it *before* shelling out to
    # openclaw — openclaw validates the running config at startup and would error
    # out ("unknown channel id: mycelium-room") if the plugin providing the
    # channel is absent when a user already has `channels.mycelium-room` set.
    # Copying into place first keeps validation happy; openclaw's own install
    # step becomes a no-op on matching files.
    if reinstall:
        state_dir = _openclaw_state_dir(profile)
        targets: list[tuple[Path, Path]] = [
            (
                _resolve_asset(_MYCELIUM_PLUGIN_SRC),
                state_dir / "extensions" / _OPENCLAW_PLUGIN_NAME,
            ),
        ]
        for src, dst in targets:
            if dst.exists():
                if verbose:
                    typer.echo(f"  refreshing {dst}")
                shutil.rmtree(dst, ignore_errors=True)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(str(src), str(dst), ignore=_plugin_copy_ignore)

        # Clean up hooks that earlier versions installed.
        for stale in _OPENCLAW_STALE_HOOKS:
            stale_path = state_dir / "hooks" / stale
            if stale_path.exists():
                if verbose:
                    typer.echo(f"  removing stale hook: {stale_path}")
                shutil.rmtree(stale_path, ignore_errors=True)

    plugin_src = _resolve_asset(_MYCELIUM_PLUGIN_SRC)
    # Refresh the compiled dist/ in the source tree before handing it to openclaw
    # (openclaw plugins install reads from this path, and 2026.5+ requires a
    # compiled dist/index.js). The committed dist/ already satisfies this, so on
    # a machine without npm the shipped artifact is used as-is.
    _build_plugin(plugin_src)

    # Stash an existing channels.mycelium-room block before install — openclaw
    # validates the existing config *before* loading the plugin that registers
    # the channel id, so a pre-existing entry causes
    # "channels.mycelium-room: unknown channel id" and aborts the install.
    openclaw_cfg_path = _openclaw_state_dir(profile) / "openclaw.json"
    stashed_channel: dict | None = None
    if openclaw_cfg_path.exists():
        try:
            oc_cfg = json_module.loads(openclaw_cfg_path.read_text())
            stashed_channel = oc_cfg.get("channels", {}).pop("mycelium-room", None)
            if stashed_channel is not None:
                openclaw_cfg_path.write_text(json_module.dumps(oc_cfg, indent=2) + "\n")
        except (OSError, json_module.JSONDecodeError):
            stashed_channel = None

    try:
        _run(
            ["openclaw", "plugins", "install", str(plugin_src)],
            allow_already_exists=tolerate_exists,
        )

        # openclaw plugins install blanket-excludes `dist/` (probably to skip
        # build output by default), but our plugin needs the compiled
        # dist/index.js — openclaw.plugin.json's `extensions` field points
        # at it. Copy it over after install so the channel actually loads.
        _copy_built_dist_to_extension(plugin_src, profile=profile)
    finally:
        # Restore the channel config so the user's room/agents/etc. survive
        # the install — the plugin is now registered, so the channel id
        # resolves cleanly on the next gateway restart.
        if stashed_channel is not None and openclaw_cfg_path.exists():
            try:
                oc_cfg = json_module.loads(openclaw_cfg_path.read_text())
                oc_cfg.setdefault("channels", {})["mycelium-room"] = stashed_channel
                openclaw_cfg_path.write_text(json_module.dumps(oc_cfg, indent=2) + "\n")
            except (OSError, json_module.JSONDecodeError):
                typer.secho(
                    "  warning: failed to restore channels.mycelium-room — "
                    "you may need to re-add it manually",
                    fg=typer.colors.YELLOW,
                )

    # Add plugin to plugins.allow so openclaw doesn't warn on every command
    _allow_plugin(_OPENCLAW_PLUGIN_NAME, profile=profile)

    # Remove stale hooks that earlier versions installed
    # (openclaw hooks uninstall was removed in 2026.5.7).
    for stale in _OPENCLAW_STALE_HOOKS:
        stale_hook_path = _openclaw_state_dir(profile) / "hooks" / stale
        if stale_hook_path.exists():
            shutil.rmtree(stale_hook_path, ignore_errors=True)

    # Install skill into the openclaw workspace skills directory
    _install_openclaw_skill(profile=profile)


def _resolve_agent_workspaces(profile: str | None = None) -> list[Path]:
    """Return the workspace directories for all configured openclaw agents."""
    import json

    state_dir = _openclaw_state_dir(profile)
    config_path = state_dir / "openclaw.json"
    if not config_path.exists():
        return [state_dir / "workspace"]

    try:
        cfg = json.loads(config_path.read_text())
    except Exception:
        return [state_dir / "workspace"]

    default_workspace = Path(
        cfg.get("agents", {}).get("defaults", {}).get("workspace", "").strip()
        or str(state_dir / "workspace")
    )

    agents = cfg.get("agents", {}).get("list", [])
    workspaces: set[Path] = set()

    for agent in agents:
        agent_id = agent.get("id", "").strip()
        if not agent_id:
            continue
        explicit = agent.get("workspace", "").strip()
        if explicit:
            workspaces.add(Path(explicit.replace("~", str(Path.home()))))
        elif agent_id == "main":
            workspaces.add(default_workspace)
        else:
            workspaces.add(state_dir / f"workspace-{agent_id}")

    workspaces.add(default_workspace)
    return list(workspaces)


def _install_openclaw_skill(profile: str | None = None) -> None:
    """Copy mycelium SKILL.md to skills/ under every configured agent workspace."""
    skill_src_dir = _resolve_asset(_MYCELIUM_SKILL_SRC)
    for workspace in _resolve_agent_workspaces(profile=profile):
        dest_dir = workspace / "skills" / _OPENCLAW_SKILL_NAME
        dest_dir.mkdir(parents=True, exist_ok=True)
        for f in skill_src_dir.iterdir():
            (dest_dir / f.name).write_bytes(f.read_bytes())


def _allow_plugin(
    plugin_id: str,
    profile: str | None = None,
    extensions_base: Path | None = None,
    container: str | None = None,
) -> None:
    """
    Register plugin_id in openclaw.json: allow list, and (container only) load path and entries.

    On host-native installs, ``openclaw plugins install`` already writes the
    install record, load path, and entries — we only add the ``plugins.allow``
    entry to suppress the security warning.

    When *container* is set, ``openclaw plugins install`` runs inside the
    container but doesn't always write the allow list or load path correctly,
    so we write all three (allow, load.paths, entries) into the container's
    openclaw.json.

    extensions_base overrides the default extensions directory — used when the
    gateway runs in a container so the load path resolves from the container
    filesystem rather than the host uv package path.
    """
    try:
        import json as _json

        if container:
            cfg_path = _container_config_path(container, profile)
            cfg = _read_container_json(container, cfg_path)
            if cfg is None:
                return
        else:
            state_dir = _openclaw_state_dir(profile)
            cfg_path = str(state_dir / "openclaw.json")
            local_path = Path(cfg_path)
            if not local_path.exists():
                return
            cfg = _json.loads(local_path.read_text())

        plugins_section = cfg.setdefault("plugins", {})

        # Allow list — suppresses security warning on all paths
        allow_list: list = plugins_section.setdefault("allow", [])
        if plugin_id not in allow_list:
            allow_list.append(plugin_id)

        # Load path and entries — only for container installs where openclaw
        # plugins install doesn't reliably write these itself.  On host-native
        # installs, openclaw manages these and writing our own guess can create
        # stale entries that block all subsequent openclaw commands.
        if container:
            ext_base = (
                extensions_base
                if extensions_base is not None
                else Path(cfg_path).parent / "extensions"
            )
            ext_path = str(ext_base / plugin_id)
            load_section = plugins_section.setdefault("load", {})
            paths: list = load_section.setdefault("paths", [])
            if ext_path not in paths:
                paths.append(ext_path)

            entries: dict = plugins_section.setdefault("entries", {})
            if plugin_id not in entries:
                entries[plugin_id] = {"enabled": True}

        if container:
            _write_container_json(container, cfg_path, cfg)
        else:
            Path(cfg_path).write_text(_json.dumps(cfg, indent=2))
    except Exception:
        pass  # Non-fatal; install succeeds even if openclaw.json can't be updated


def _uninstall_openclaw(
    adapter_record: dict, profile: str | None = None, container: str | None = None
) -> None:
    """Uninstall the mycelium plugin and hook (non-interactively)."""
    uninstall_cmd = _openclaw_cmd(
        ["openclaw", "plugins", "uninstall", _OPENCLAW_PLUGIN_NAME, "--force"],
        profile,
        container,
    )
    result = subprocess.run(uninstall_cmd, text=True, capture_output=True)
    if result.returncode == 137 and container:
        pass
    elif result.returncode != 0 and "not found" not in (result.stderr or "").lower():
        typer.secho(
            f"  warning: {' '.join(uninstall_cmd[:3])} exited {result.returncode}",
            fg=typer.colors.YELLOW,
        )
    if container:
        _wait_container_healthy(container)

    # Remove hook and stale hooks via filesystem (openclaw hooks uninstall removed in 2026.5.7).
    state_dir = _openclaw_state_dir(profile)
    for hook_name in [_OPENCLAW_HOOK_NAME, *_OPENCLAW_STALE_HOOKS]:
        if container:
            hook_state_suffix = f"-{profile}" if profile and profile.lower() != "default" else ""
            container_home = _openclaw_container_home(container)
            hook_path = f"{container_home}/.openclaw{hook_state_suffix}/hooks/{hook_name}"
            subprocess.run(
                ["docker", "exec", container, "rm", "-rf", hook_path],
                text=True,
                capture_output=True,
            )
        else:
            hook_path_fs = state_dir / "hooks" / hook_name
            if hook_path_fs.exists():
                shutil.rmtree(hook_path_fs, ignore_errors=True)

    _allow_plugin_remove(_OPENCLAW_PLUGIN_NAME, profile=profile, container=container)
    skill_dir = _openclaw_state_dir(profile) / "workspace" / "skills" / _OPENCLAW_SKILL_NAME
    if skill_dir.exists():
        shutil.rmtree(skill_dir, ignore_errors=True)


def _allow_plugin_remove(
    plugin_id: str,
    profile: str | None = None,
    container: str | None = None,
) -> None:
    """Remove plugin_id from plugins.allow (and, for containers, load.paths and entries).

    On host-native installs, ``openclaw plugins uninstall`` manages load.paths
    and entries — we only touch the allow list.

    When *container* is set, operates on the container's config instead of the host's.
    """
    try:
        import json as _json

        if container:
            cfg_path = _container_config_path(container, profile)
            cfg = _read_container_json(container, cfg_path)
            if cfg is None:
                return
        else:
            state_dir = _openclaw_state_dir(profile)
            cfg_path = str(state_dir / "openclaw.json")
            local_path = Path(cfg_path)
            if not local_path.exists():
                return
            cfg = _json.loads(local_path.read_text())

        plugins_section = cfg.get("plugins", {})

        allow_list: list = plugins_section.get("allow", [])
        if plugin_id in allow_list:
            allow_list.remove(plugin_id)

        # Load path and entries — only for container installs (see _allow_plugin)
        if container:
            ext_dir = str(Path(cfg_path).parent / "extensions" / plugin_id)
            paths: list = plugins_section.get("load", {}).get("paths", [])
            if ext_dir in paths:
                paths.remove(ext_dir)

            entries: dict = plugins_section.get("entries", {})
            entries.pop(plugin_id, None)

        if container:
            _write_container_json(container, cfg_path, cfg)
        else:
            Path(cfg_path).write_text(_json.dumps(cfg, indent=2))
    except Exception:
        pass


def _probe_hub_reachable(api_url: str, timeout: float = 3.0) -> tuple[bool, str]:
    """Best-effort probe of the configured Mycelium backend.

    Issue #139: spoke-only nodes silently archived hundreds of MB of
    conversation data because the out-of-process knowledge-extract hook
    couldn't reach the configured api_url and there was no install-time
    signal that anything was wrong. A 3-second probe at adapter add
    catches the obvious typo / wrong-port / firewall cases without
    blocking air-gapped installs (we only warn).

    Returns (ok, message). ``ok`` is False on any non-2xx response,
    timeout, DNS error, or connection refusal. ``message`` is a short
    human-readable reason suitable for stderr.
    """
    if not api_url:
        return False, "no api_url configured"
    health_url = api_url.rstrip("/") + "/health"
    try:
        req = urllib.request.Request(health_url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if 200 <= resp.status < 300:
                return True, f"reachable ({resp.status})"
            return False, f"unexpected HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        # URLError wraps refused connections, DNS failures, timeouts.
        reason = getattr(exc, "reason", exc)
        return False, f"{type(exc).__name__}: {reason}"


def _docker_api_url(config: MyceliumConfig) -> str:
    """Derive a Docker-friendly MYCELIUM_API_URL from the configured api_url.

    Rewrites localhost/127.0.0.1 to host.docker.internal so containers can
    reach the backend running on the host.
    """
    parsed = urlparse(config.server.api_url)
    hostname = parsed.hostname or "localhost"
    port = parsed.port
    if not port:
        raise ValueError(
            f"No port found in api_url '{config.server.api_url}'. "
            "Please set a full URL including port in config.toml "
            '(e.g. api_url = "http://localhost:8001").'
        )
    if hostname in ("localhost", "127.0.0.1", "0.0.0.0"):
        hostname = "host.docker.internal"
    scheme = parsed.scheme or "http"
    return f"{scheme}://{hostname}:{port}"


def _normalize_plugin_entries(plugins_section: dict) -> dict:
    """Ensure plugins.entries is a dict (record), converting from list if needed.

    OpenClaw validates entries as a record (``{plugin_id: {enabled: bool}}``).
    Mutates *plugins_section* in place and returns the dict.
    """
    entries = plugins_section.get("entries")
    if isinstance(entries, dict):
        return entries
    if isinstance(entries, list):
        converted: dict = {}
        for e in entries:
            if isinstance(e, dict):
                key = e.get("name") or e.get("id")
                if key:
                    converted[key] = {k: v for k, v in e.items() if k not in ("name", "id")}
        entries = converted
    else:
        entries = {}
    plugins_section["entries"] = entries
    return entries


def _patch_model_cost_and_compat(cfg: dict) -> list[str]:
    """Patch zero-cost model entries and add ``compat.supportsUsageInStreaming``.

    OpenClaw uses the ``cost`` block on each model to calculate ``openclaw.cost.usd``.
    If the costs are all zero (the default from ``openclaw configure``), the OTLP
    cost metric will always be $0.  This function fills in real pricing from
    Mycelium's pricing data and adds the ``compat`` flag that enables token
    usage reporting in streamed responses.

    OpenClaw cost values are **USD per 1M tokens**, while Mycelium's pricing
    data stores per-token rates.  This function converts accordingly.

    Returns a list of human-readable change descriptions (empty if nothing changed).
    """
    PER_M = 1_000_000

    changes: list[str] = []

    try:
        from mycelium.commands.metrics import _get_model_pricing
    except Exception:
        return changes

    providers = cfg.get("models", {}).get("providers", {})
    for _provider_name, provider in providers.items():
        for model in provider.get("models", []):
            model_id = model.get("id", "")
            if not model_id:
                continue

            cost = model.get("cost", {})
            all_zero = all(
                cost.get(k, 0) == 0 for k in ("input", "output", "cacheRead", "cacheWrite")
            )

            if all_zero:
                pricing, label = _get_model_pricing(model_id)
                inp = pricing["input"]
                if inp > 0:
                    cache_read_rate = inp * (1 - pricing["cache_discount"])
                    cache_write_rate = inp * (1 + pricing["cache_write_premium"])
                    model["cost"] = {
                        "input": inp * PER_M,
                        "output": pricing["output"] * PER_M,
                        "cacheRead": cache_read_rate * PER_M,
                        "cacheWrite": cache_write_rate * PER_M,
                    }
                    changes.append(f"cost for {model_id} (matched: {label})")

            compat = model.setdefault("compat", {})
            if not compat.get("supportsUsageInStreaming"):
                compat["supportsUsageInStreaming"] = True
                changes.append(f"compat.supportsUsageInStreaming for {model_id}")

    return changes


def _read_openclaw_cfg(
    profile: str | None,
    container: str | None,
    *,
    not_found_hint: str = "Run 'openclaw gateway start' first to create the config file.",
) -> tuple[dict, str] | None:
    """Read and parse openclaw.json from host or container.

    Returns (cfg_dict, path_str) on success, None on any failure (errors are
    printed to stderr via typer.secho before returning None).
    """
    if container:
        path_str = _container_config_path(container, profile)
        result = subprocess.run(
            ["docker", "exec", container, "cat", path_str],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            typer.secho(f"  ✗ {path_str} not found in container.", fg=typer.colors.RED)
            if not_found_hint:
                typer.echo(f"    {not_found_hint}")
            return None
        try:
            return json_module.loads(result.stdout), path_str
        except json_module.JSONDecodeError as exc:
            typer.secho(f"  ✗ Could not parse openclaw.json: {exc}", fg=typer.colors.RED)
            return None
    else:
        config_path = _openclaw_state_dir(profile) / "openclaw.json"
        path_str = str(config_path)
        if not config_path.exists():
            typer.secho(f"  ✗ {path_str} not found.", fg=typer.colors.RED)
            if not_found_hint:
                typer.echo(f"    {not_found_hint}")
            return None
        try:
            return json_module.loads(config_path.read_text()), path_str
        except (json_module.JSONDecodeError, OSError) as exc:
            typer.secho(f"  ✗ Could not read openclaw.json: {exc}", fg=typer.colors.RED)
            return None


def _write_openclaw_cfg(cfg: dict, path_str: str, container: str | None) -> bool:
    """Serialize and write cfg to openclaw.json on host or inside a container."""
    cfg_json = json_module.dumps(cfg, indent=2) + "\n"
    try:
        if container:
            result = subprocess.run(
                ["docker", "exec", "-i", container, "sh", "-c", f"cat > {path_str}"],
                input=cfg_json,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                typer.secho(
                    f"  ✗ Could not write openclaw.json: {result.stderr}", fg=typer.colors.RED
                )
                return False
        else:
            Path(path_str).write_text(cfg_json)
    except OSError as exc:
        typer.secho(f"  ✗ Could not write openclaw.json: {exc}", fg=typer.colors.RED)
        return False
    return True


def _configure_otel(
    port: int | None = None,
    profile: str | None = None,
    container: str | None = None,
) -> bool:
    """Configure OpenClaw's diagnostics-otel plugin in openclaw.json."""
    read = _read_openclaw_cfg(profile, container)
    if read is None:
        return False
    cfg, config_path_str = read

    try:
        resolved_port = port if port is not None else 4318
        env_port = os.environ.get("MYCELIUM_METRICS_PORT")
        if port is None and env_port:
            try:
                p = int(env_port)
                if 1 <= p <= 65535:
                    resolved_port = p
            except ValueError:
                pass
        host = "host.docker.internal" if container else "localhost"
        endpoint = f"http://{host}:{resolved_port}"

        diagnostics = cfg.setdefault("diagnostics", {})
        diagnostics["enabled"] = True
        otel = diagnostics.setdefault("otel", {})
        otel["enabled"] = True
        otel.setdefault("serviceName", "openclaw-gateway")
        otel.update(
            {
                "endpoint": endpoint,
                "protocol": "http/protobuf",
                "traces": True,
                "metrics": True,
                "logs": False,
                "flushIntervalMs": 5000,
            }
        )

        plugins = cfg.setdefault("plugins", {})
        allow_list = plugins.setdefault("allow", [])
        if "diagnostics-otel" not in allow_list:
            allow_list.append("diagnostics-otel")

        entries = _normalize_plugin_entries(plugins)
        if "diagnostics-otel" not in entries:
            entries["diagnostics-otel"] = {"enabled": True}

        model_changes = _patch_model_cost_and_compat(cfg)
        for desc in model_changes:
            typer.secho(f"  ✓ patched {desc}", fg=typer.colors.GREEN)

    except OSError as exc:
        typer.secho(f"  ✗ Could not write openclaw.json: {exc}", fg=typer.colors.RED)
        return False

    if not _write_openclaw_cfg(cfg, config_path_str, container):
        return False

    typer.secho("  ✓ diagnostics-otel enabled in openclaw.json", fg=typer.colors.GREEN)
    typer.echo(f"    endpoint: {endpoint}")
    return True


_INSIGHTCLAW_PLUGIN_ID = "insightclaw"
_INSIGHTCLAW_NPM_PACKAGE = "@outshift-open/insightclaw"


def _install_insightclaw(
    profile: str | None = None,
    container: str | None = None,
) -> bool:
    """Install the InsightClaw OpenClaw plugin from npm.

    Runs ``openclaw plugins install @outshift-open/insightclaw`` and adds the
    plugin id to ``plugins.allow``.  Returns True on success, False on failure
    (non-fatal — otel config is written regardless).
    """
    cmd = _openclaw_cmd(
        ["openclaw", "plugins", "install", _INSIGHTCLAW_NPM_PACKAGE],
        profile,
        container,
    )
    result = subprocess.run(cmd, text=True, capture_output=True)
    combined = ((result.stderr or "") + (result.stdout or "")).lower()
    if result.returncode != 0 and "already" not in combined:
        if container and result.returncode == 137:
            pass  # gateway restart after config change — install completed
        else:
            typer.secho(
                f"  ⚠ InsightClaw install returned {result.returncode}"
                + (f": {(result.stderr or '').strip()[:120]}" if result.stderr else ""),
                fg=typer.colors.YELLOW,
            )
            return False

    _allow_plugin(_INSIGHTCLAW_PLUGIN_ID, profile=profile, container=container)
    typer.secho(f"  ✓ {_INSIGHTCLAW_NPM_PACKAGE} installed", fg=typer.colors.GREEN)
    return True


def _configure_insightclaw(
    port: int = 4318,
    capture_content: bool = False,
    profile: str | None = None,
    container: str | None = None,
) -> bool:
    """Write InsightClaw plugin config into openclaw.json.

    Enables traces + metrics, sets the OTLP endpoint to the mycelium-collector.
    workspace.id / mas.id are NOT baked in — they change per room and after
    volume wipes; the collector's _CfnForwarder resolves them at forward time.
    Returns True on success.
    """
    read = _read_openclaw_cfg(profile, container, not_found_hint="")
    if read is None:
        return False
    cfg, config_path_str = read

    host = "host.docker.internal" if container else "localhost"
    endpoint = f"http://{host}:{port}"

    plugins = cfg.setdefault("plugins", {})
    allow_list: list = plugins.setdefault("allow", [])

    # plugins.allow only accepts plain strings (the zod schema is array(string())).
    # Normalise any stale object entries back to the plain ID string.
    allow_list[:] = [
        (e.get("name") or _INSIGHTCLAW_PLUGIN_ID) if isinstance(e, dict) else e for e in allow_list
    ]
    if _INSIGHTCLAW_PLUGIN_ID not in allow_list:
        allow_list.append(_INSIGHTCLAW_PLUGIN_ID)

    entries = _normalize_plugin_entries(plugins)
    entries[_INSIGHTCLAW_PLUGIN_ID] = {
        "enabled": True,
        # allowConversationAccess enables conversation-scoped hooks (before_model_resolve)
        # so InsightClaw can populate openclaw.session.key on spans for CFN routing.
        # Only granted when captureContent is true — conversation access implies the
        # runtime can observe prompt/completion payloads, which the user must opt into.
        # Must live in plugins.entries (not plugins.allow — that only accepts strings).
        "hooks": {"allowConversationAccess": capture_content},
        "config": {
            "endpoint": endpoint,
            "protocol": "http",
            "serviceName": "openclaw-gateway",
            "traces": True,
            "metrics": True,
            "captureContent": capture_content,
            "emitIoaObserveAttributes": True,
            # workspace.id / mas.id are intentionally omitted: they differ per room
            # and go stale after volume wipes. The collector's _CfnForwarder injects
            # the correct per-room values at forward time using the backend API, and
            # falls back to WORKSPACE_ID/MAS_ID from .env for unkeyed spans.
        },
    }

    if not _write_openclaw_cfg(cfg, config_path_str, container):
        return False

    typer.secho("  ✓ InsightClaw configured in openclaw.json", fg=typer.colors.GREEN)
    typer.echo(f"    endpoint: {endpoint}  captureContent: {capture_content}")
    return True


def _restart_gateway_if_needed(profile: str | None, container: str | None) -> None:
    """Restart the OpenClaw gateway service to pick up config changes."""
    typer.echo("")
    typer.secho("  Restarting gateway to apply changes...", dim=True)

    if container:
        typer.secho(
            "  ⚠ Container gateway: please restart the container manually.",
            fg=typer.colors.YELLOW,
        )
        return

    try:
        result = subprocess.run(
            ["systemctl", "--user", "restart", "openclaw-gateway.service"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        typer.secho(
            "  ⚠ systemctl not found. Restart the OpenClaw gateway manually.",
            fg=typer.colors.YELLOW,
        )
        return

    if result.returncode == 0:
        typer.secho("  ✓ openclaw-gateway.service restarted", fg=typer.colors.GREEN)
    else:
        typer.secho(
            "  ⚠ Could not restart gateway service. You may need to restart it manually.",
            fg=typer.colors.YELLOW,
        )


def _step_docker_env(config: MyceliumConfig) -> None:
    """Print env vars needed for Docker-based experiment agent containers."""
    docker_url = _docker_api_url(config)
    typer.secho("Docker agent env vars", bold=True)
    typer.echo("")
    typer.echo("  Add to your docker-compose environment block or experiment .env:")
    typer.echo("")
    typer.secho("  # .env", dim=True)
    typer.echo(f"  MYCELIUM_API_URL={docker_url}")
    if config.server.workspace_id:
        typer.echo(f"  MYCELIUM_WORKSPACE_ID={config.server.workspace_id}")
    if config.server.mas_id:
        typer.echo(f"  MYCELIUM_MAS_ID={config.server.mas_id}")
    typer.echo("  MYCELIUM_ROOM_ID=<experiment-name>      # unique per run")
    typer.echo("  MYCELIUM_AGENT_HANDLE=<agent-name>      # unique per agent")
    typer.echo("")
    typer.secho("  Notes:", bold=True)
    typer.echo("  • Use host.docker.internal (not localhost) to reach the Mycelium")
    typer.echo("    backend from inside a container. Add to docker-compose:")
    typer.secho('      extra_hosts: ["host.docker.internal:host-gateway"]', dim=True)
    typer.echo("  • MYCELIUM_ROOM_ID is the only var that changes per experiment.")
    typer.echo("    All agents sharing the same value coordinate in the same room.")
    typer.echo("  • If you use generate-compose.ts, these are injected automatically.")
