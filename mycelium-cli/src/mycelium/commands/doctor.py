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
    config_url = cfg.server.api_url or "http://localhost:8000"
    # Extract port from config URL
    try:
        from urllib.parse import urlparse

        parsed = urlparse(config_url)
        config_port = str(parsed.port or 8000)
    except Exception:
        config_port = "8000"

    if env_port != config_port:
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


# ── Main doctor command ──────────────────────────────────────────────────────


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
