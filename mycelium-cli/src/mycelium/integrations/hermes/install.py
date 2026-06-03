# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Hermes install facet — stage the hermes-side plugin into ``~/.hermes/``.

The work this module does for a ``mycelium adapter add hermes`` is:

1. ``shutil.copytree`` the bundled plugin tree from
   ``integrations/hermes/assets/mycelium/plugin/`` into
   ``~/.hermes/plugins/mycelium/``.  Hermes auto-discovers user-installed
   plugins from that directory (``hermes_cli/plugins.py:_scan_directory``
   second pass).
2. Patch ``~/.hermes/config.yaml`` in three places:
   - ``plugins.enabled`` allow-list — add ``mycelium`` (user plugins are
     opt-in by default).
   - ``platforms.mycelium-room.enabled: true``
   - ``platforms.mycelium-room.extra.backend_url`` = configured Mycelium
     api_url; ``rooms: []`` empty fan-out, populated by ``register()``.
3. ``hermes gateway restart`` so the gateway re-reads the plugin manifest.

Uninstall reverses all three.  ``register()`` (in ``dispatch.py``) appends
per-room ``{room, agents}`` entries to ``platforms.mycelium-room.extra.rooms``
the same way OpenClaw's ``_register_channel`` writes to
``channels.mycelium-room.rooms[]`` in ``openclaw.json``.

Helpers live here so ``dispatch.py`` can import the small surface it needs
(``_hermes_home``, ``_read_config_yaml``, ``_write_config_yaml``,
``_restart_gateway``) without dragging in the install banner code.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Any

import typer

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig


# ── constants ────────────────────────────────────────────────────────────────

_HERMES_PLUGIN_NAME = "mycelium"
_HERMES_PLATFORM_ID = "mycelium-room"

# Subpath under integrations/hermes/assets/ that holds the plugin tree.
_MYCELIUM_ASSET_ROOT = "mycelium"
_MYCELIUM_PLUGIN_SRC = f"{_MYCELIUM_ASSET_ROOT}/plugin"

# v1 ships no follow-up steps; OTEL/profile/container come in later releases.
_HERMES_STEPS: dict[str, str] = {}


# ── paths ────────────────────────────────────────────────────────────────────


def _hermes_home(profile: str | None = None) -> Path:
    """Return the hermes home directory for *profile* (default ``~/.hermes``).

    Mirrors hermes's own resolution (``hermes_constants.get_hermes_home()``):
    honour the ``HERMES_HOME`` env var first so containerised / test setups
    can redirect, otherwise fall back to ``~/.hermes`` or the per-profile
    ``~/.hermes/profiles/<name>/`` shape.
    """
    env_home = os.environ.get("HERMES_HOME")
    if env_home:
        return Path(env_home)
    if profile and profile.lower() != "default":
        return Path.home() / ".hermes" / "profiles" / profile
    return Path.home() / ".hermes"


def _hermes_plugin_dst(profile: str | None = None) -> Path:
    return _hermes_home(profile) / "plugins" / _HERMES_PLUGIN_NAME


def _hermes_config_yaml(profile: str | None = None) -> Path:
    return _hermes_home(profile) / "config.yaml"


def _hermes_gateway_pid(profile: str | None = None) -> Path:
    return _hermes_home(profile) / "gateway.pid"


# ── YAML config helpers ──────────────────────────────────────────────────────


def _read_config_yaml(profile: str | None = None) -> dict[str, Any]:
    """Return the parsed ``config.yaml`` (empty dict if missing/empty)."""
    import yaml

    cfg_path = _hermes_config_yaml(profile)
    if not cfg_path.exists():
        return {}
    try:
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise HermesConfigError(f"{cfg_path} is not valid YAML: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise HermesConfigError(
            f"{cfg_path} top-level must be a mapping, got {type(data).__name__}"
        )
    return data


def _write_config_yaml(data: dict[str, Any], profile: str | None = None) -> Path:
    """Write *data* back to ``config.yaml`` atomically.

    Uses ``yaml.safe_dump`` with ``sort_keys=False`` so we preserve key order
    on round-trip as much as PyYAML allows (it doesn't preserve original
    formatting, but mycelium-owned blocks live at the bottom anyway).
    """
    import yaml

    cfg_path = _hermes_config_yaml(profile)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cfg_path.with_suffix(cfg_path.suffix + ".tmp")
    tmp.write_text(
        yaml.safe_dump(data, sort_keys=False, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )
    tmp.replace(cfg_path)
    return cfg_path


def _enable_plugin(data: dict[str, Any]) -> bool:
    """Ensure ``plugins.enabled`` contains ``mycelium``. Returns True on change."""
    plugins = data.setdefault("plugins", {})
    if not isinstance(plugins, dict):
        # Refuse to clobber an unexpected structure
        raise HermesConfigError("config.yaml plugins: section is not a mapping")
    enabled = plugins.get("enabled")
    if not isinstance(enabled, list):
        plugins["enabled"] = [_HERMES_PLUGIN_NAME]
        return True
    if _HERMES_PLUGIN_NAME in enabled:
        return False
    enabled.append(_HERMES_PLUGIN_NAME)
    return True


def _disable_plugin(data: dict[str, Any]) -> bool:
    """Strip ``mycelium`` from ``plugins.enabled``. Returns True on change."""
    plugins = data.get("plugins")
    if not isinstance(plugins, dict):
        return False
    enabled = plugins.get("enabled")
    if not isinstance(enabled, list) or _HERMES_PLUGIN_NAME not in enabled:
        return False
    plugins["enabled"] = [p for p in enabled if p != _HERMES_PLUGIN_NAME]
    return True


def _ensure_platform_block(
    data: dict[str, Any], *, backend_url: str, api_token: str | None
) -> bool:
    """Ensure ``platforms.mycelium-room`` is enabled and configured.

    Idempotent: doesn't clobber an existing ``rooms`` list. Returns True if
    any field changed.
    """
    platforms = data.setdefault("platforms", {})
    if not isinstance(platforms, dict):
        raise HermesConfigError("config.yaml platforms: section is not a mapping")
    block = platforms.get(_HERMES_PLATFORM_ID)
    if not isinstance(block, dict):
        block = {}
    changed = False
    if block.get("enabled") is not True:
        block["enabled"] = True
        changed = True
    extra = block.setdefault("extra", {})
    if not isinstance(extra, dict):
        extra = {}
        block["extra"] = extra
        changed = True
    if extra.get("backend_url") != backend_url:
        extra["backend_url"] = backend_url
        changed = True
    if api_token and extra.get("api_token") != api_token:
        # api_token is optional. Only persist when explicitly provided.
        extra["api_token"] = api_token
        changed = True
    if "rooms" not in extra or not isinstance(extra.get("rooms"), list):
        extra["rooms"] = []
        changed = True
    if extra.get("require_mention") is None:
        extra["require_mention"] = True
        changed = True
    platforms[_HERMES_PLATFORM_ID] = block
    return changed


def _disable_platform_block(data: dict[str, Any]) -> bool:
    """Set ``platforms.mycelium-room.enabled = false`` (keep config for re-add)."""
    platforms = data.get("platforms")
    if not isinstance(platforms, dict):
        return False
    block = platforms.get(_HERMES_PLATFORM_ID)
    if not isinstance(block, dict):
        return False
    if block.get("enabled") is False:
        return False
    block["enabled"] = False
    return True


# ── hermes binary / gateway lifecycle ────────────────────────────────────────


class HermesConfigError(RuntimeError):
    """Raised when ``~/.hermes/config.yaml`` is malformed or unsafe to patch."""


def _check_hermes_binary() -> None:
    """Warn (don't fail) if ``hermes`` isn't on PATH."""
    if shutil.which("hermes") is None:
        typer.secho(
            "  warning: 'hermes' is not on PATH. Install hermes-agent before"
            " starting the gateway. The plugin will be staged regardless.",
            fg=typer.colors.YELLOW,
        )


def _gateway_service_installed(env: dict[str, str]) -> bool:
    """Probe whether a systemd unit for the hermes gateway exists.

    ``hermes gateway restart`` is overloaded: when a systemd (user or system)
    service is installed it nudges the service; when no service exists it
    falls back to running the gateway *in the foreground* until killed —
    which makes ``subprocess.run(...)`` hang the installer indefinitely
    (we hit this on first install in a fresh ``~/.hermes/``). Detect the
    service presence up front so we can skip the (foreground) restart and
    just tell the user how to launch the gateway themselves.
    """
    if shutil.which("systemctl") is None:
        return False
    # Match hermes_cli/gateway.py: profile-aware service name like
    # ``hermes-gateway`` or ``hermes-gateway-<profile>``. Probe both
    # ``--user`` and system scopes; either presence counts.
    candidates = ("hermes-gateway", "hermes-gateway.service")
    for scope in (("--user",), ()):
        for name in candidates:
            probe = subprocess.run(
                ["systemctl", *scope, "list-unit-files", name],
                text=True,
                capture_output=True,
                env=env,
                timeout=5,
            )
            if probe.returncode == 0 and name.split(".", 1)[0] in (probe.stdout or ""):
                return True
    return False


def _foreground_banner() -> None:
    typer.echo("  Plugin and config are written. The hermes gateway is not")
    typer.echo("  installed as a systemd service on this host, so 'hermes gateway")
    typer.echo("  restart' would run it in the foreground forever. Start it")
    typer.echo("  yourself in a separate terminal:")
    typer.echo("    hermes gateway run            # foreground")
    typer.echo("    hermes gateway install        # ... or install as a service")


class _GatewayCmdResult:
    """Tiny result tuple from :func:`_run_hermes_gateway_cmd`.

    Carrying the merged ``output`` instead of separate ``stdout``/``stderr``
    is enough for this caller — we only show a snippet on failure.
    """

    __slots__ = ("output", "returncode", "timed_out")

    def __init__(self, *, returncode: int, output: str, timed_out: bool) -> None:
        self.returncode = returncode
        self.output = output
        self.timed_out = timed_out


def _run_hermes_gateway_cmd(
    args: list[str], *, env: dict[str, str], timeout: float = 30.0
) -> _GatewayCmdResult:
    """Run a ``hermes gateway …`` subcommand without the daemon-handoff hang.

    ``hermes gateway restart`` (on a host with the gateway installed as a
    systemd service) spawns a detached "planned-restart helper" that
    inherits the CLI's stdout/stderr fds. The CLI itself exits promptly,
    but the helper keeps the pipe write-ends open — which means a plain
    ``subprocess.run(..., capture_output=True, timeout=…)`` deadlocks:
    ``Popen.communicate()`` blocks on EOF that never comes, and the
    ``TimeoutExpired`` cleanup re-enters ``communicate()`` *without* a
    timeout under the (here-false) assumption that "the child is dead so
    reads should EOF immediately."

    Fix: redirect to a temp file instead of capturing through pipes. The
    detached helper inherits the *file fd*, which closes cleanly when we
    do, and we still get the diagnostic output for failure messages.
    """
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as buf:
        try:
            proc = subprocess.run(
                args,
                stdin=subprocess.DEVNULL,
                stdout=buf,
                stderr=subprocess.STDOUT,
                env=env,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            buf.seek(0)
            return _GatewayCmdResult(
                returncode=-1,
                output=buf.read(),
                timed_out=True,
            )
        buf.seek(0)
        return _GatewayCmdResult(
            returncode=proc.returncode,
            output=buf.read(),
            timed_out=False,
        )


def _restart_gateway(profile: str | None = None) -> None:
    """``hermes gateway restart`` — service-only, with a foreground banner.

    Best-effort: a non-zero exit code or a missing service is a warning,
    not a fail. The plugin files and config patches are already on disk;
    the user can restart manually.
    """
    env = os.environ.copy()
    home = _hermes_home(profile)
    env["HERMES_HOME"] = str(home)

    if not _gateway_service_installed(env):
        _foreground_banner()
        return

    # Service exists — restart it. Cap the call so a misbehaving systemd
    # unit can't wedge the installer.
    result = _run_hermes_gateway_cmd(["hermes", "gateway", "restart"], env=env, timeout=30.0)
    if result.timed_out:
        typer.secho(
            "  hermes gateway restart timed out after 30s — restart manually:",
            fg=typer.colors.YELLOW,
        )
        typer.echo("    hermes gateway restart")
        return

    if result.returncode == 0:
        return

    output_low = result.output.lower()
    if "not running" in output_low or "no gateway" in output_low:
        start = _run_hermes_gateway_cmd(["hermes", "gateway", "start"], env=env, timeout=30.0)
        if start.timed_out:
            typer.secho(
                "  hermes gateway start timed out after 30s — start manually:",
                fg=typer.colors.YELLOW,
            )
            typer.echo("    hermes gateway start")
            return
        if start.returncode == 0:
            return
        typer.secho(
            f"  hermes gateway start returned {start.returncode}: {start.output.strip()[:160]}",
            fg=typer.colors.YELLOW,
        )
        typer.echo("  Plugin and config are written; start the gateway manually:")
        typer.echo("    hermes gateway start")
        return

    typer.secho(
        f"  hermes gateway restart returned {result.returncode}: {result.output.strip()[:160]}",
        fg=typer.colors.YELLOW,
    )
    typer.echo("  Plugin and config are written; restart the gateway manually:")
    typer.echo("    hermes gateway restart")


def _probe_hub_reachable(api_url: str, timeout: float = 3.0) -> tuple[bool, str]:
    """Best-effort probe of the configured Mycelium backend ``/health``.

    Mirrored from the openclaw installer — same intent (issue #139): catch
    the obvious misconfigurations at install time rather than silently
    failing once the gateway is running.
    """
    if not api_url:
        return False, "no api_url configured"
    health_url = api_url.rstrip("/") + "/health"
    try:
        req = urllib.request.Request(health_url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - trusted user-config URL
            if 200 <= resp.status < 300:
                return True, f"reachable ({resp.status})"
            return False, f"unexpected HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        return False, f"{type(exc).__name__}: {reason}"


# ── install / uninstall core ─────────────────────────────────────────────────


def _install_hermes(
    *,
    verbose: bool,
    profile: str | None,
    config: MyceliumConfig,
    reinstall: bool,
) -> None:
    """Stage the plugin, patch ``config.yaml``, restart the gateway."""
    from mycelium.integrations._resources import _resolve_asset

    _check_hermes_binary()

    plugin_src = _resolve_asset(_MYCELIUM_PLUGIN_SRC, family="hermes")
    plugin_dst = _hermes_plugin_dst(profile)

    if reinstall and plugin_dst.exists():
        shutil.rmtree(plugin_dst)

    plugin_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(plugin_src, plugin_dst, dirs_exist_ok=True)
    if verbose:
        typer.echo(f"  staged plugin: {plugin_src} → {plugin_dst}")

    # Patch config.yaml
    data = _read_config_yaml(profile)
    plugin_changed = _enable_plugin(data)
    platform_changed = _ensure_platform_block(
        data,
        backend_url=config.server.api_url.rstrip("/"),
        api_token=None,
    )
    if plugin_changed or platform_changed:
        path = _write_config_yaml(data, profile)
        if verbose:
            typer.echo(f"  patched: {path}")
            if plugin_changed:
                typer.echo(f"    plugins.enabled += {_HERMES_PLUGIN_NAME}")
            if platform_changed:
                typer.echo(f"    platforms.{_HERMES_PLATFORM_ID}.enabled = true")
    elif verbose:
        typer.echo(f"  config.yaml already configured: {_hermes_config_yaml(profile)}")

    _restart_gateway(profile)


def _uninstall_hermes(
    record: dict,  # noqa: ARG001 - record is the persisted adapter info; unused for hermes today
    *,
    profile: str | None,
) -> None:
    """Reverse :func:`_install_hermes` — remove plugin tree, disable in config."""
    plugin_dst = _hermes_plugin_dst(profile)
    if plugin_dst.exists():
        shutil.rmtree(plugin_dst, ignore_errors=True)

    try:
        data = _read_config_yaml(profile)
    except HermesConfigError:
        return  # malformed config, nothing safe to do here
    plugin_changed = _disable_plugin(data)
    platform_changed = _disable_platform_block(data)
    if plugin_changed or platform_changed:
        _write_config_yaml(data, profile)

    _restart_gateway(profile)
