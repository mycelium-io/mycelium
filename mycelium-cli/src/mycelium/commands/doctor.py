# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
Doctor command — diagnose and fix common Mycelium configuration issues.

Checks:
  1. Config files exist (~/.mycelium/.env, config.toml)
  2. LLM configuration (model + API key set)
  3. Docker containers running and healthy
  4. Backend API reachable
  5. Workspace ID in sync (CFN mgmt plane vs .env vs config.toml)
  6. .env ↔ config.toml drift (api_url / port)
  7. Room MAS IDs present (CFN-enabled installs)
"""

import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import typer

from mycelium.doc_ref import doc_ref
from mycelium.error_handler import print_error

# ── Check result model ───────────────────────────────────────────────────────


@dataclass
class CheckResult:
    name: str
    status: str  # "ok" | "warning" | "error"
    message: str
    details: list[str] = field(default_factory=list)
    fix_label: str = ""
    fix_fn: Callable[[], None] | None = None


# ── Status display ───────────────────────────────────────────────────────────

_STATUS_ICONS = {
    "ok": "\x1b[32m✓\x1b[0m",
    "warning": "\x1b[33m~\x1b[0m",
    "error": "\x1b[31m✗\x1b[0m",
}
_STATUS_COLORS = {
    "ok": typer.colors.GREEN,
    "warning": typer.colors.YELLOW,
    "error": typer.colors.RED,
}


def _print_check(result: CheckResult) -> None:
    icon = _STATUS_ICONS.get(result.status, "?")
    color = _STATUS_COLORS.get(result.status, typer.colors.WHITE)
    typer.secho(f"  {icon} {result.name:<22s} {result.message}", fg=color)
    for detail in result.details:
        typer.echo(f"  {' ' * 24}{detail}")


# ── Individual checks ────────────────────────────────────────────────────────


def _check_config_files() -> CheckResult:
    """Check that ~/.mycelium/.env and config.toml exist."""
    env_path = Path.home() / ".mycelium" / ".env"
    config_path = Path.home() / ".mycelium" / "config.toml"

    missing = []
    if not env_path.exists():
        missing.append(".env")
    if not config_path.exists():
        missing.append("config.toml")

    if missing:
        return CheckResult(
            name="Config files",
            status="error",
            message=f"Missing: {', '.join(missing)}",
            details=["Run: mycelium install"],
        )
    return CheckResult(
        name="Config files",
        status="ok",
        message="~/.mycelium/.env and config.toml present",
    )


def _check_llm_config() -> CheckResult:
    """Check that LLM model and API key are configured in .env."""
    env_path = Path.home() / ".mycelium" / ".env"
    if not env_path.exists():
        return CheckResult(
            name="LLM configuration",
            status="error",
            message="No .env file",
        )

    from dotenv import dotenv_values

    vals = dotenv_values(env_path)
    model = vals.get("LLM_MODEL", "")
    key = vals.get("LLM_API_KEY", "")

    if not model:
        return CheckResult(
            name="LLM configuration",
            status="warning",
            message="LLM_MODEL not set",
            details=["Run: mycelium install --force"],
        )

    key_hint = (
        f"(key: ...{key[-4:]})" if key and len(key) > 4 else "(no key)" if not key else "(key set)"
    )

    # Ollama and some local providers don't need API keys
    if not key and not model.startswith("ollama/"):
        return CheckResult(
            name="LLM configuration",
            status="warning",
            message=f"{model} {key_hint}",
            details=["LLM_API_KEY not set — run: mycelium install --force"],
        )

    return CheckResult(
        name="LLM configuration",
        status="ok",
        message=f"{model} {key_hint}",
    )


def _check_docker_containers() -> CheckResult:
    """Check that expected containers are running and healthy."""
    expected = ["mycelium-db", "mycelium-backend"]

    # Check if CFN is enabled
    env_path = Path.home() / ".mycelium" / ".env"
    if env_path.exists():
        from dotenv import dotenv_values

        vals = dotenv_values(env_path)
        if vals.get("CFN_MGMT_URL", ""):
            expected += ["ioc-cfn-mgmt-plane-svc", "ioc-cognition-fabric-node-svc"]

    try:
        r = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode != 0:
            return CheckResult(
                name="Docker containers",
                status="error",
                message="Docker not available",
            )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return CheckResult(
            name="Docker containers",
            status="error",
            message="Docker not available",
        )

    running = {}
    for line in r.stdout.strip().splitlines():
        parts = line.split("\t", 1)
        if len(parts) == 2:
            running[parts[0]] = parts[1]

    missing = [c for c in expected if c not in running]
    unhealthy = [c for c in expected if c in running and "unhealthy" in running.get(c, "").lower()]

    if missing:
        return CheckResult(
            name="Docker containers",
            status="error",
            message=f"Not running: {', '.join(missing)}",
            details=["Run: mycelium up"],
        )
    if unhealthy:
        return CheckResult(
            name="Docker containers",
            status="warning",
            message=f"Unhealthy: {', '.join(unhealthy)}",
            details=["Check: mycelium logs"],
        )

    healthy_list = ", ".join(f"{c} (up)" for c in expected if c in running)
    return CheckResult(
        name="Docker containers",
        status="ok",
        message=healthy_list,
    )


def _check_backend_reachable() -> CheckResult:
    """Check that the backend API responds to /health."""
    from mycelium.config import MyceliumConfig

    try:
        config = MyceliumConfig.load()
    except Exception:
        return CheckResult(
            name="Backend reachable",
            status="error",
            message="Cannot load config",
        )

    api_url = config.server.api_url

    try:
        import httpx

        resp = httpx.get(f"{api_url}/health", timeout=5)
        if resp.status_code < 500:
            data = resp.json()
            status = data.get("status", "unknown")
            version = data.get("version", "")
            label = f"{api_url} ({status})"
            if version:
                label += f" v{version}"
            return CheckResult(
                name="Backend reachable",
                status="ok" if status in ("ok", "degraded") else "warning",
                message=label,
            )
        return CheckResult(
            name="Backend reachable",
            status="error",
            message=f"{api_url} returned HTTP {resp.status_code}",
        )
    except Exception as exc:
        return CheckResult(
            name="Backend reachable",
            status="error",
            message=f"Cannot connect to {api_url}",
            details=[str(exc), "Run: mycelium up"],
        )


def _check_workspace_id() -> CheckResult:
    """Check workspace_id consistency between .env, config.toml, and CFN mgmt plane."""
    env_path = Path.home() / ".mycelium" / ".env"
    config_path = Path.home() / ".mycelium" / "config.toml"

    # Read from .env
    env_ws = ""
    cfn_enabled = False
    if env_path.exists():
        from dotenv import dotenv_values

        vals = dotenv_values(env_path)
        env_ws = vals.get("WORKSPACE_ID", "")
        cfn_enabled = bool(vals.get("CFN_MGMT_URL", ""))

    # Read from config.toml
    config_ws = ""
    if config_path.exists():
        from mycelium.config import MyceliumConfig

        try:
            cfg = MyceliumConfig.load(config_path)
            config_ws = cfg.server.workspace_id or ""
        except Exception:
            pass

    if not env_ws and not config_ws:
        return CheckResult(
            name="Workspace ID",
            status="warning",
            message="Not configured",
            details=["Run: mycelium install --force"],
        )

    # If CFN is enabled, check against the mgmt plane
    cfn_ws = None
    if cfn_enabled:
        from mycelium.commands.install import _get_cfn_workspace_id

        cfn_ws = _get_cfn_workspace_id("http://localhost:9000")

    details: list[str] = []
    mismatches: list[str] = []

    if env_ws:
        details.append(f".env: {env_ws}")
    if config_ws and config_ws != env_ws:
        details.append(f"config.toml: {config_ws}")
        mismatches.append("config.toml")

    if cfn_ws is not None:
        details.append(f"CFN mgmt plane: {cfn_ws}")
        if cfn_ws != env_ws:
            mismatches.append("CFN mgmt plane")
    elif cfn_enabled:
        details.append("CFN mgmt plane: unreachable")

    if mismatches:
        # Build a fix function that re-syncs from CFN (or from .env if no CFN)
        source_ws = cfn_ws if cfn_ws else env_ws
        fix_fn = (
            _make_workspace_fix(source_ws, env_path, config_path, cfn_enabled)
            if source_ws
            else None
        )

        return CheckResult(
            name="Workspace ID",
            status="error",
            message=f"Mismatch — {', '.join(mismatches)} differ from .env",
            details=details,
            fix_label=f"Sync all to {source_ws}",
            fix_fn=fix_fn,
        )

    # All agree (or only one source exists)
    display_ws = env_ws or config_ws
    return CheckResult(
        name="Workspace ID",
        status="ok",
        message=display_ws,
        details=details if len(details) > 1 else [],
    )


def _make_workspace_fix(
    target_ws: str,
    env_path: Path,
    config_path: Path,
    cfn_enabled: bool,
) -> Callable[[], None]:
    """Return a closure that patches workspace_id in .env and config.toml."""

    def _fix() -> None:
        from mycelium.commands.install import (
            _get_compose_path,
            _patch_env_vars,
            _restart_backend,
            _write_mycelium_config,
        )

        # Patch .env
        typer.echo(f"    Patching ~/.mycelium/.env WORKSPACE_ID={target_ws}")
        _patch_env_vars(env_path, {"WORKSPACE_ID": target_ws})

        # Patch config.toml
        from mycelium.config import MyceliumConfig

        try:
            cfg = MyceliumConfig.load(config_path) if config_path.exists() else MyceliumConfig()
        except Exception:
            cfg = MyceliumConfig()

        api_url = cfg.server.api_url or "http://localhost:8000"
        mas_id = cfg.server.mas_id or ""

        typer.echo(f"    Patching ~/.mycelium/config.toml server.workspace_id={target_ws}")
        _write_mycelium_config(api_url, target_ws, mas_id)

        # Restart backend so it picks up the new WORKSPACE_ID
        typer.echo("    Restarting backend...")
        try:
            compose_path = _get_compose_path()
            profiles = ["cfn"] if cfn_enabled else []
            _restart_backend(compose_path, env_path, profiles, api_url)
            typer.secho("  ✓ Workspace ID synced", fg=typer.colors.GREEN)
        except Exception as exc:
            typer.secho(f"  ⚠  Backend restart failed: {exc}", fg=typer.colors.YELLOW)
            typer.echo("    Run: mycelium up")

    return _fix


def _check_config_drift() -> CheckResult:
    """Check for drift between .env and config.toml (api_url / port)."""
    env_path = Path.home() / ".mycelium" / ".env"
    config_path = Path.home() / ".mycelium" / "config.toml"

    if not env_path.exists() or not config_path.exists():
        return CheckResult(
            name="Config consistency",
            status="ok",
            message="Skipped (missing files)",
        )

    from dotenv import dotenv_values

    from mycelium.config import MyceliumConfig

    vals = dotenv_values(env_path)

    try:
        cfg = MyceliumConfig.load(config_path)
    except Exception:
        return CheckResult(
            name="Config consistency",
            status="warning",
            message="Cannot parse config.toml",
        )

    issues: list[str] = []

    # Check port consistency
    env_port = vals.get("MYCELIUM_BACKEND_PORT", "8000")
    config_url = cfg.server.api_url
    # Extract port from config URL
    try:
        from urllib.parse import urlparse

        parsed = urlparse(config_url)
        config_port = str(parsed.port) if parsed.port else None
    except Exception:
        config_port = None

    if config_port is None:
        issues.append(
            f"No port found in config.toml api_url '{config_url}' — "
            "expected a full URL including port (e.g. http://localhost:8001)"
        )

    if config_port is not None and env_port != config_port:
        issues.append(f"Backend port: .env={env_port}, config.toml URL implies {config_port}")

    if issues:
        return CheckResult(
            name="Config consistency",
            status="warning",
            message="Drift detected",
            details=issues,
        )

    return CheckResult(
        name="Config consistency",
        status="ok",
        message=".env and config.toml are consistent",
    )


def _check_room_mas_ids() -> CheckResult:
    """Check that all rooms have a MAS ID (CFN-enabled installs only)."""
    env_path = Path.home() / ".mycelium" / ".env"
    if not env_path.exists():
        return CheckResult(name="Room MAS IDs", status="ok", message="Skipped (no .env)")

    from dotenv import dotenv_values

    vals = dotenv_values(env_path)
    if not vals.get("CFN_MGMT_URL"):
        return CheckResult(name="Room MAS IDs", status="ok", message="Skipped (CFN not enabled)")

    from mycelium.config import MyceliumConfig

    try:
        cfg = MyceliumConfig.load()
        api_url = cfg.server.api_url or "http://localhost:8000"
    except Exception:
        api_url = "http://localhost:8000"

    try:
        import httpx

        with httpx.Client(base_url=api_url, timeout=5) as client:
            resp = client.get("/rooms")
            resp.raise_for_status()
            rooms = resp.json()
    except Exception:
        return CheckResult(
            name="Room MAS IDs", status="ok", message="Skipped (backend unreachable)"
        )

    # Session sub-rooms (name contains ":session:") don't need MAS IDs
    top_level = [r for r in rooms if ":session:" not in r["name"]]
    missing = [r["name"] for r in top_level if not r.get("mas_id")]
    if not missing:
        return CheckResult(
            name="Room MAS IDs",
            status="ok",
            message=f"All {len(top_level)} room(s) have MAS IDs",
        )

    return CheckResult(
        name="Room MAS IDs",
        status="warning",
        message=f"{len(missing)} room(s) missing MAS ID",
        details=[f"  {name}" for name in missing]
        + ["Fix: run 'mycelium doctor --fix' after workspace ID is synced"],
    )


# ── Main doctor command ──────────────────────────────────────────────────────


def _check_openclaw_mycelium_plugin() -> CheckResult:
    """Verify the unified `mycelium` plugin is installed at ~/.openclaw/extensions/mycelium/."""
    plugin_dir = Path.home() / ".openclaw" / "extensions" / "mycelium"
    manifest = plugin_dir / "openclaw.plugin.json"
    index = plugin_dir / "index.ts"

    if not manifest.exists():
        # No OpenClaw install at all — not a failure, just skip
        openclaw_dir = Path.home() / ".openclaw"
        if not openclaw_dir.exists():
            return CheckResult(
                name="openclaw plugin",
                status="ok",
                message="no OpenClaw install detected — skipped",
            )
        return CheckResult(
            name="openclaw plugin",
            status="warning",
            message="not installed",
            details=[
                f"expected: {plugin_dir}",
                "fix: run `mycelium adapter add openclaw`",
            ],
        )

    if not index.exists():
        return CheckResult(
            name="openclaw plugin",
            status="error",
            message="manifest present but index.ts missing — corrupt install",
            details=[
                "fix: run `mycelium adapter add openclaw --reinstall`",
            ],
        )

    return CheckResult(
        name="openclaw plugin",
        status="ok",
        message=f"installed at {plugin_dir}",
    )


def _check_openclaw_channel_config() -> CheckResult:
    """Verify channels.mycelium-room is configured correctly in openclaw.json."""
    import json

    openclaw_json = Path.home() / ".openclaw" / "openclaw.json"
    if not openclaw_json.exists():
        return CheckResult(
            name="channel config",
            status="ok",
            message="no OpenClaw install detected — skipped",
        )

    try:
        with openclaw_json.open() as f:
            oc = json.load(f)
    except Exception as exc:
        return CheckResult(
            name="channel config",
            status="error",
            message=f"could not parse openclaw.json: {exc}",
        )

    channel = (oc.get("channels") or {}).get("mycelium-room")
    if not channel:
        return CheckResult(
            name="channel config",
            status="warning",
            message="channels.mycelium-room not configured",
            details=[
                "the plugin will run in session-only mode (no addressed messaging)",
                "fix: add channels.mycelium-room with backendUrl, room, agents, requireMention",
            ],
        )

    if channel.get("enabled") is False:
        return CheckResult(
            name="channel config",
            status="warning",
            message="channels.mycelium-room present but disabled",
        )

    missing = [k for k in ("backendUrl", "room", "agents") if not channel.get(k)]
    if missing:
        return CheckResult(
            name="channel config",
            status="error",
            message=f"missing required fields: {', '.join(missing)}",
            details=["fix: set backendUrl, room, and agents in channels.mycelium-room"],
        )

    # Check backendUrl matches mycelium config.toml's server.api_url
    try:
        import tomllib

        mycelium_toml = Path.home() / ".mycelium" / "config.toml"
        if mycelium_toml.exists():
            with mycelium_toml.open("rb") as f:
                mcfg = tomllib.load(f)
            expected = (mcfg.get("server") or {}).get("api_url", "").rstrip("/")
            actual = str(channel.get("backendUrl", "")).rstrip("/")
            if expected and actual and expected != actual:
                return CheckResult(
                    name="channel config",
                    status="error",
                    message="backendUrl doesn't match mycelium config.toml",
                    details=[
                        f"openclaw.json:     {actual}",
                        f"mycelium/config:   {expected}",
                        "fix: update channels.mycelium-room.backendUrl to match",
                    ],
                )
    except Exception:
        pass  # non-fatal

    agents = channel.get("agents") or []
    require_mention = channel.get("requireMention", True)
    return CheckResult(
        name="channel config",
        status="ok",
        message=f"room={channel.get('room')} agents={len(agents)} requireMention={require_mention}",
    )


def _check_openclaw_agent_sandbox() -> CheckResult:
    """Warn about agents whose sandbox mode blocks the mycelium CLI."""
    import json

    openclaw_json = Path.home() / ".openclaw" / "openclaw.json"
    if not openclaw_json.exists():
        return CheckResult(
            name="agent sandbox",
            status="ok",
            message="no OpenClaw install detected — skipped",
        )

    try:
        with openclaw_json.open() as f:
            oc = json.load(f)
    except Exception as exc:
        return CheckResult(
            name="agent sandbox",
            status="error",
            message=f"could not parse openclaw.json: {exc}",
        )

    channel = (oc.get("channels") or {}).get("mycelium-room") or {}
    channel_agents = set(channel.get("agents") or [])
    if not channel_agents:
        return CheckResult(
            name="agent sandbox",
            status="ok",
            message="no channel agents configured — skipped",
        )

    default_sandbox = (((oc.get("agents") or {}).get("defaults") or {}).get("sandbox") or {}).get(
        "mode", "all"
    )

    sandboxed: list[str] = []
    for agent in (oc.get("agents") or {}).get("list", []):
        agent_id = agent.get("id", "")
        if agent_id not in channel_agents:
            continue
        mode = (agent.get("sandbox") or {}).get("mode") or default_sandbox
        if mode != "off":
            sandboxed.append(f"{agent_id} (mode={mode})")

    if sandboxed:
        return CheckResult(
            name="agent sandbox",
            status="warning",
            message=f"{len(sandboxed)} channel agent(s) are sandboxed — mycelium CLI invisible",
            details=[
                *sandboxed,
                "sandboxed agents cannot execute `mycelium session join`, `message propose`,",
                "or `message respond` because the mycelium binary isn't in their sandbox PATH.",
                "fix: set sandbox.mode = 'off' in openclaw.json for each agent, restart gateway",
            ],
        )

    return CheckResult(
        name="agent sandbox",
        status="ok",
        message=f"all {len(channel_agents)} channel agent(s) have sandbox=off",
    )


@doc_ref(
    usage="mycelium doctor [--fix] [--json]",
    desc="Diagnose and fix common configuration issues (workspace sync, LLM, containers).",
    group="setup",
)
def doctor(
    ctx: typer.Context,
    fix: bool = typer.Option(False, "--fix", help="Auto-fix all fixable issues without prompting"),
) -> None:
    """
    Diagnose and fix common Mycelium configuration issues.

    Checks config files, LLM setup, Docker containers, backend connectivity,
    workspace ID sync, and config consistency. Offers to fix issues it finds.

    \b
    Examples:
        mycelium doctor          # interactive — asks before fixing
        mycelium doctor --fix    # auto-fix all fixable issues
    """
    try:
        json_output = ctx.obj.get("json", False) if ctx.obj else False

        typer.secho("\n  Mycelium Doctor\n", bold=True)

        # Run all checks
        results = [
            _check_config_files(),
            _check_llm_config(),
            _check_docker_containers(),
            _check_backend_reachable(),
            _check_workspace_id(),
            _check_config_drift(),
            _check_room_mas_ids(),
            _check_openclaw_mycelium_plugin(),
            _check_openclaw_channel_config(),
            _check_openclaw_agent_sandbox(),
        ]

        if json_output:
            import json

            output = [
                {
                    "name": r.name,
                    "status": r.status,
                    "message": r.message,
                    "details": r.details,
                    "fixable": r.fix_fn is not None,
                }
                for r in results
            ]
            typer.echo(json.dumps(output, indent=2))
            return

        # Display results
        for result in results:
            _print_check(result)

        # Summary
        issues = [r for r in results if r.status in ("warning", "error")]
        fixable = [r for r in issues if r.fix_fn is not None]

        typer.echo("")
        if not issues:
            typer.secho("  All checks passed.", fg=typer.colors.GREEN, bold=True)
            return

        typer.echo(
            f"  {len(issues)} issue(s) found"
            + (f", {len(fixable)} auto-fixable" if fixable else "")
            + "."
        )

        # Offer to fix
        if fixable:
            typer.echo("")
            for result in fixable:
                if fix:
                    typer.echo(f"  Fixing: {result.fix_label}")
                    assert result.fix_fn is not None
                    result.fix_fn()
                else:
                    try:
                        answer = input(f"  {result.fix_label}? [Y/n] ").strip()
                    except (EOFError, KeyboardInterrupt):
                        typer.echo("\n  Skipped.")
                        continue
                    if answer.lower() in ("y", "yes", ""):
                        assert result.fix_fn is not None
                        result.fix_fn()
                    else:
                        typer.echo("  Skipped.")

        # Exit code
        errors = [r for r in results if r.status == "error"]
        if errors:
            raise typer.Exit(1)

    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None
