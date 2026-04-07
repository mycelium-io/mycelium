# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
Adapter commands — connect agent frameworks to Mycelium.

Supported adapters:
  openclaw    — runs `openclaw plugins install` with the bundled mycelium plugin

Planned:
  cursor      — SDK harness (next sprint)
  claude-code — SDK harness (next sprint)
"""

import importlib.resources
import json as json_module
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import typer

from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref
from mycelium.error_handler import print_error

app = typer.Typer(
    help="Connect agent frameworks (OpenClaw, Claude Code) to Mycelium. Install hooks, skills, and plugins.",
    no_args_is_help=True,
)

ADAPTER_TYPES = {
    "openclaw": "plugin-based — installs mycelium via `openclaw plugins install`",
    "claude-code": "skill + hooks — copies SKILL.md and lifecycle hooks into ~/.claude/",
    "cursor": "sdk-based — generates CFN harness for Cursor agents (planned)",
}

_OPENCLAW_PLUGIN_NAME = "mycelium"
_OPENCLAW_HOOK_NAME = "mycelium-bootstrap"
_OPENCLAW_EXTRACTOR_HOOK_NAME = "mycelium-knowledge-extract"
_OPENCLAW_SKILL_NAME = "mycelium"

_CLAUDE_CODE_SKILL_NAME = "mycelium"
_CLAUDE_CODE_HOOKS = [
    "mycelium-session-start.sh",
    "mycelium-session-end.sh",
    "mycelium-post-tool-use.sh",
    "mycelium-pre-compact.sh",
    "mycelium-stop.sh",
]


@app.callback()
def adapter_main(ctx: typer.Context) -> None:
    """Manage agent framework adapters (openclaw, cursor, claude-code, …)."""


_OPENCLAW_STEPS = {
    "docker-env": "show env vars for Docker-based experiment agents",
}


def _openclaw_state_dir(profile: str | None) -> Path:
    """Return ~/.openclaw-<profile>/ or ~/.openclaw/ for default."""
    if profile and profile.lower() != "default":
        return Path.home() / f".openclaw-{profile}"
    return Path.home() / ".openclaw"


def _openclaw_cmd(args: list[str], profile: str | None) -> list[str]:
    """Prefix openclaw subcommand with --profile <name> when non-default."""
    if profile and profile.lower() != "default":
        return ["openclaw", "--profile", profile, *args[1:]]
    return args


# Assets that go into each agent's ~/.openclaw/ directory
_OPENCLAW_SCAFFOLD_ASSETS = [
    # (source subpath in mycelium package, dest subpath in target .openclaw dir)
    (f"extensions/{_OPENCLAW_PLUGIN_NAME}", f"extensions/{_OPENCLAW_PLUGIN_NAME}"),
    (f"hooks/{_OPENCLAW_HOOK_NAME}", f"hooks/{_OPENCLAW_HOOK_NAME}"),
    (f"hooks/{_OPENCLAW_EXTRACTOR_HOOK_NAME}", f"hooks/{_OPENCLAW_EXTRACTOR_HOOK_NAME}"),
    (f"skills/{_OPENCLAW_SKILL_NAME}", f"workspace/skills/{_OPENCLAW_SKILL_NAME}"),
]


@doc_ref(
    usage="mycelium adapter add <type> [--openclaw-profile NAME] [--dry-run] [--force]",
    desc="Install an agent framework adapter (openclaw, claude-code).",
    group="adapter",
)
@app.command("add")
def add(
    ctx: typer.Context,
    adapter_type: str = typer.Argument(..., help="Adapter type: openclaw, cursor, claude-code"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be installed without doing it"
    ),
    step: str | None = typer.Option(
        None, "--step", help=f"Run a follow-up setup step: {', '.join(_OPENCLAW_STEPS)}"
    ),
    reinstall: bool = typer.Option(
        False, "--reinstall", help="Reinstall assets even if adapter is already registered"
    ),
    scaffold_only: Path | None = typer.Option(
        None,
        "--scaffold-only",
        help="Copy adapter assets to a directory without running install commands (for Docker/experiment setups)",
    ),
    force: bool = typer.Option(
        False, "--force", "-f", help="Overwrite existing assets when using --scaffold-only"
    ),
    openclaw_profile: str | None = typer.Option(
        None,
        "--openclaw-profile",
        help="Target a named OpenClaw profile (e.g. 'work' → ~/.openclaw-work/). Omit for default gateway.",
    ),
) -> None:
    """
    Register and install an agent framework adapter, then optionally wire it into your environment.

    Examples:
        mycelium adapter add openclaw
        mycelium adapter add openclaw --reinstall
        mycelium adapter add openclaw --openclaw-profile work
        mycelium adapter add openclaw --step=local-gateway
        mycelium adapter add openclaw --step=docker-env
    """
    try:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        json_output = ctx.obj.get("json", False) if ctx.obj else False

        if adapter_type not in ADAPTER_TYPES:
            known = ", ".join(ADAPTER_TYPES.keys())
            typer.secho(
                f"Unknown adapter type '{adapter_type}'. Known types: {known}", fg=typer.colors.RED
            )
            raise typer.Exit(1)

        # ── Scaffold-only: copy assets to a directory without install commands ─
        if scaffold_only is not None:
            target = scaffold_only.resolve()
            installed: list[str] = []
            skipped_: list[str] = []
            for src_subpath, dst_subpath in _OPENCLAW_SCAFFOLD_ASSETS:
                src = _resolve_asset(src_subpath)
                dst = target / dst_subpath
                if dst.exists() and not force:
                    skipped_.append(dst_subpath)
                    continue
                dst.mkdir(parents=True, exist_ok=True)
                for item in src.iterdir():
                    dest_file = dst / item.name
                    if item.is_file():
                        dest_file.write_bytes(item.read_bytes())
                    elif item.is_dir():
                        shutil.copytree(str(item), str(dest_file), dirs_exist_ok=True)
                installed.append(dst_subpath)
            for path in installed:
                typer.secho(f"  ✓ {path}", fg=typer.colors.GREEN)
            for path in skipped_:
                typer.secho(f"  - {path} (exists, use --force to overwrite)", dim=True)
            return

        config = MyceliumConfig.load()

        # ── Follow-up steps run independently of the base install ────────────
        if step is not None:
            if adapter_type != "openclaw":
                typer.secho(
                    "--step is only supported for the 'openclaw' adapter.", fg=typer.colors.RED
                )
                raise typer.Exit(1)
            if step not in _OPENCLAW_STEPS:
                known_steps = ", ".join(_OPENCLAW_STEPS)
                typer.secho(
                    f"Unknown step '{step}'. Known steps: {known_steps}", fg=typer.colors.RED
                )
                raise typer.Exit(1)
            if step == "docker-env":
                _step_docker_env(config)
            return

        # ── Base install ──────────────────────────────────────────────────────
        if adapter_type in config.adapters and not reinstall:
            typer.secho(
                f"Adapter '{adapter_type}' already registered. Use 'mycelium adapter status {adapter_type}' to check it, or pass --reinstall to redeploy assets.",
                fg=typer.colors.YELLOW,
            )
            raise typer.Exit(0)

        if dry_run:
            typer.secho(f"[dry-run] Would install adapter: {adapter_type}", fg=typer.colors.CYAN)
            if adapter_type == "claude-code":
                claude_dir = Path.home() / ".claude"
                typer.echo(f"  skill → {claude_dir}/skills/{_CLAUDE_CODE_SKILL_NAME}/SKILL.md")
                for hook in _CLAUDE_CODE_HOOKS:
                    typer.echo(f"  hook  → {claude_dir}/hooks/{hook}")
            else:
                plugin_src = _resolve_asset(f"extensions/{_OPENCLAW_PLUGIN_NAME}")
                hook_src = _resolve_asset(f"hooks/{_OPENCLAW_HOOK_NAME}")
                prefix = (
                    f"openclaw --profile {openclaw_profile}"
                    if openclaw_profile and openclaw_profile.lower() != "default"
                    else "openclaw"
                )
                typer.echo(f"  {prefix} plugins install {plugin_src}")
                typer.echo(f"  {prefix} hooks install   {hook_src}")
                typer.echo(f"  state dir: {_openclaw_state_dir(openclaw_profile)}")
            typer.echo(f"  api_url: {config.server.api_url}")
            return

        if adapter_type == "openclaw":
            _install_openclaw(verbose=verbose, profile=openclaw_profile)
        elif adapter_type == "claude-code":
            _install_claude_code(verbose=verbose)
        else:
            typer.secho(
                f"Adapter '{adapter_type}' is planned but not yet implemented.",
                fg=typer.colors.YELLOW,
            )
            raise typer.Exit(1)

        if not reinstall:
            adapter_record: dict = {
                "type": adapter_type,
                "installed_at": datetime.now(UTC).isoformat(),
                "api_url": config.server.api_url,
            }
            if openclaw_profile:
                adapter_record["openclaw_profile"] = openclaw_profile
            config.adapters[adapter_type] = adapter_record
            config.save()

        if json_output:
            typer.echo(json_module.dumps(config.adapters.get(adapter_type, {}), indent=2))
        elif adapter_type == "claude-code":
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
        else:
            verb = "reinstalled" if reinstall else "installed"
            typer.secho(f"Adapter '{adapter_type}' {verb}.", fg=typer.colors.GREEN)
            typer.echo(f"  plugin:  {_OPENCLAW_PLUGIN_NAME}")
            typer.echo(f"  hook:    {_OPENCLAW_HOOK_NAME}")
            typer.echo(f"  hook:    {_OPENCLAW_EXTRACTOR_HOOK_NAME}")
            typer.echo(f"  skill:   {_OPENCLAW_SKILL_NAME}")
            typer.echo("")
            typer.secho("  Next steps:", bold=True)
            typer.echo("")
            typer.echo(
                "  1. Allow mycelium CLI execution (required for agents to run mycelium commands):"
            )
            typer.echo("")
            typer.echo("     For specific agents (recommended):")
            typer.secho(
                '       $ openclaw approvals allowlist add --agent "<agent-id>" "~/.local/bin/mycelium"',
                fg=typer.colors.CYAN,
            )
            typer.echo("")
            typer.echo("     Or for all agents (convenient but less restrictive):")
            typer.secho(
                '       $ openclaw approvals allowlist add --agent "*" "~/.local/bin/mycelium"',
                fg=typer.colors.CYAN,
            )
            typer.echo("")
            typer.echo("  2. Restart the openclaw gateway to pick up the updated plugin:")
            typer.secho("    $ openclaw gateway restart", fg=typer.colors.CYAN)
            typer.echo("")
            typer.echo("  For Docker-based experiment agents, get required env vars:")
            typer.secho(
                "    $ mycelium adapter add openclaw --step=docker-env", fg=typer.colors.CYAN
            )

    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None


@doc_ref(
    usage="mycelium adapter remove <type> [--force]",
    desc="Unregister and uninstall an adapter.",
    group="adapter",
)
@app.command("remove")
def remove(
    ctx: typer.Context,
    adapter_type: str = typer.Argument(..., help="Adapter type to remove"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
) -> None:
    """Unregister and uninstall an adapter."""
    try:
        config = MyceliumConfig.load()

        if adapter_type not in config.adapters:
            typer.secho(f"Adapter '{adapter_type}' is not registered.", fg=typer.colors.YELLOW)
            raise typer.Exit(0)

        if not force:
            confirm = typer.confirm(f"Remove adapter '{adapter_type}'?")
            if not confirm:
                typer.echo("Cancelled.")
                raise typer.Exit(0)

        if adapter_type == "openclaw":
            _uninstall_openclaw(
                config.adapters[adapter_type],
                profile=config.adapters[adapter_type].get("openclaw_profile"),
            )

        del config.adapters[adapter_type]
        config.save()

        typer.secho(f"Adapter '{adapter_type}' removed.", fg=typer.colors.GREEN)

    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None


@doc_ref(
    usage="mycelium adapter ls",
    desc="List available and registered adapters.",
    group="adapter",
)
@app.command("ls")
def list_adapters(ctx: typer.Context) -> None:
    """List registered adapters."""
    try:
        json_output = ctx.obj.get("json", False) if ctx.obj else False
        config = MyceliumConfig.load()

        if json_output:
            typer.echo(json_module.dumps(config.adapters, indent=2, default=str))
            return

        if not config.adapters:
            typer.echo("No adapters registered.")
            typer.echo("  Add one with: mycelium adapter add <type>")
            typer.echo(f"  Known types: {', '.join(ADAPTER_TYPES.keys())}")
            return

        typer.secho(f"Adapters ({len(config.adapters)})", bold=True)
        typer.echo("")
        for name, info in config.adapters.items():
            installed_at = info.get("installed_at", "unknown")[:10]
            typer.echo(f"  {name:<16} installed {installed_at}")

    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


@doc_ref(
    usage="mycelium adapter status [type]",
    desc="Check adapter health and installation status.",
    group="adapter",
)
@app.command("status")
def status(
    ctx: typer.Context,
    adapter_type: str | None = typer.Argument(None, help="Adapter type to check (all if omitted)"),
) -> None:
    """Check adapter health."""
    try:
        json_output = ctx.obj.get("json", False) if ctx.obj else False
        config = MyceliumConfig.load()

        if adapter_type and adapter_type not in config.adapters:
            typer.secho(f"Adapter '{adapter_type}' is not registered.", fg=typer.colors.YELLOW)
            raise typer.Exit(1)

        targets = {adapter_type: config.adapters[adapter_type]} if adapter_type else config.adapters

        if not targets:
            typer.echo("No adapters registered.")
            return

        results = {name: _check_adapter_status(name, info) for name, info in targets.items()}

        if json_output:
            typer.echo(json_module.dumps(results, indent=2, default=str))
            return

        for name, check in results.items():
            ok = check.get("ok", False)
            color = typer.colors.GREEN if ok else typer.colors.RED
            symbol = "✓" if ok else "✗"
            typer.secho(f"  {symbol} {name}", fg=color)
            for detail in check.get("details", []):
                typer.echo(f"      {detail}")

    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)


# ── Adapter-specific install / uninstall ──────────────────────────────────────


def _resolve_asset(subpath: str, adapter: str = "openclaw") -> Path:
    """
    Return a real filesystem path to a bundled adapter asset.

    For non-editable installs where the package lives inside a zip, extract
    the entire directory tree to a temp dir first.
    """
    pkg = importlib.resources.files(f"mycelium.adapters.{adapter}")
    parts = subpath.split("/")
    src = Path(str(pkg))
    for part in parts:
        src = src / part

    if src.exists():
        return src

    # Non-editable install: extract to a temp dir
    tmp = Path(tempfile.mkdtemp(prefix="mycelium-asset-"))
    dst = tmp / parts[-1]
    dst.mkdir(parents=True, exist_ok=True)
    ref = pkg
    for part in parts:
        ref = ref / part
    for entry in ref.iterdir():
        (dst / entry.name).write_bytes(entry.read_bytes())
    return dst


def _install_openclaw(verbose: bool = False, profile: str | None = None) -> None:
    """
    Install the bundled openclaw plugin and hook.

    - Plugin (mycelium): handles session lifecycle + message forwarding
    - Hook (mycelium-inject): injects MYCELIUM_API_URL + MYCELIUM_ROOM_ID + coordination
      instructions into every agent bootstrap
    """

    def _run(cmd: list[str], allow_already_exists: bool = False) -> None:
        cmd = _openclaw_cmd(cmd, profile)
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
            raise RuntimeError(
                f"`{' '.join(cmd[:3])}` failed (exit {result.returncode})"
                + (f": {stderr}" if stderr else "")
            )

    plugin_src = _resolve_asset(f"extensions/{_OPENCLAW_PLUGIN_NAME}")
    _run(["openclaw", "plugins", "install", str(plugin_src)], allow_already_exists=True)

    # Add plugin to plugins.allow so openclaw doesn't warn on every command
    _allow_plugin(_OPENCLAW_PLUGIN_NAME, profile=profile)

    hook_src = _resolve_asset(f"hooks/{_OPENCLAW_HOOK_NAME}")
    _run(["openclaw", "hooks", "install", str(hook_src)], allow_already_exists=True)

    extractor_src = _resolve_asset(f"hooks/{_OPENCLAW_EXTRACTOR_HOOK_NAME}")
    _run(["openclaw", "hooks", "install", str(extractor_src)], allow_already_exists=True)

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
    skill_src_dir = _resolve_asset(
        f"extensions/{_OPENCLAW_PLUGIN_NAME}/skills/{_OPENCLAW_SKILL_NAME}"
    )
    for workspace in _resolve_agent_workspaces(profile=profile):
        dest_dir = workspace / "skills" / _OPENCLAW_SKILL_NAME
        dest_dir.mkdir(parents=True, exist_ok=True)
        for f in skill_src_dir.iterdir():
            (dest_dir / f.name).write_bytes(f.read_bytes())


def _install_claude_code(verbose: bool = False) -> None:
    """
    Install the bundled Claude Code adapter assets into ~/.claude/.

    - Skill (SKILL.md): copied to ~/.claude/skills/mycelium/
    - Hooks (*.sh): copied to ~/.claude/hooks/  (made executable)
    - Scripts (*.sh): copied to ~/.claude/scripts/ (support files for hooks)
    - settings.json: registers Stop hook for git sync
    """
    claude_dir = Path.home() / ".claude"

    # Install skill
    skill_src = _resolve_asset(f"skills/{_CLAUDE_CODE_SKILL_NAME}", adapter="claude-code")
    skill_dst = claude_dir / "skills" / _CLAUDE_CODE_SKILL_NAME
    skill_dst.mkdir(parents=True, exist_ok=True)
    for f in skill_src.iterdir():
        dest = skill_dst / f.name
        dest.write_bytes(f.read_bytes())
        if verbose:
            typer.echo(f"  skill: {dest}")

    # Install hooks
    hooks_src = _resolve_asset("hooks", adapter="claude-code")
    hooks_dst = claude_dir / "hooks"
    hooks_dst.mkdir(parents=True, exist_ok=True)
    for hook_name in _CLAUDE_CODE_HOOKS:
        src_file = hooks_src / hook_name
        if not src_file.exists():
            if verbose:
                typer.echo(f"  skip (not found): {hook_name}")
            continue
        dst_file = hooks_dst / hook_name
        dst_file.write_bytes(src_file.read_bytes())
        dst_file.chmod(0o755)
        if verbose:
            typer.echo(f"  hook: {dst_file}")

    # Install scripts (support files used by hooks)
    scripts_src = _resolve_asset("scripts", adapter="claude-code")
    scripts_dst = claude_dir / "scripts"
    scripts_dst.mkdir(parents=True, exist_ok=True)
    if scripts_src.exists():
        for f in scripts_src.iterdir():
            if f.is_file():
                dest = scripts_dst / f.name
                dest.write_bytes(f.read_bytes())
                dest.chmod(0o755)
                if verbose:
                    typer.echo(f"  script: {dest}")

    # Register Stop hook in settings.json for git sync
    _register_claude_code_stop_hook(claude_dir, verbose=verbose)


def _register_claude_code_stop_hook(claude_dir: Path, verbose: bool = False) -> None:
    """Add mycelium-stop.sh to the Stop hooks in Claude Code settings.json."""
    settings_path = claude_dir / "settings.json"
    hook_command = str(claude_dir / "hooks" / "mycelium-stop.sh")

    try:
        if settings_path.exists():
            settings = json_module.loads(settings_path.read_text())
        else:
            settings = {}

        hooks = settings.setdefault("hooks", {})
        stop_hooks = hooks.setdefault("Stop", [])

        # Check if already registered
        for entry in stop_hooks:
            for h in entry.get("hooks", []):
                if h.get("command", "") == hook_command:
                    if verbose:
                        typer.echo("  Stop hook already registered")
                    return

        # Add the hook
        stop_hooks.append(
            {
                "matcher": "",
                "hooks": [
                    {
                        "type": "command",
                        "command": hook_command,
                        "timeout": 15,
                    }
                ],
            }
        )

        settings_path.write_text(json_module.dumps(settings, indent=2) + "\n")
        if verbose:
            typer.echo(f"  registered Stop hook: {hook_command}")
    except Exception as e:
        if verbose:
            typer.echo(f"  warning: could not register Stop hook: {e}")


def _allow_plugin(plugin_id: str, profile: str | None = None) -> None:
    """Register plugin_id in openclaw.json: allow list, load path, and entries."""
    state_dir = _openclaw_state_dir(profile)
    config_path = state_dir / "openclaw.json"
    if not config_path.exists():
        return
    try:
        import json as _json

        cfg = _json.loads(config_path.read_text())
        plugins_section = cfg.setdefault("plugins", {})

        # Allow list (suppresses security warning)
        allow_list: list = plugins_section.setdefault("allow", [])
        if plugin_id not in allow_list:
            allow_list.append(plugin_id)

        # Load path — tells openclaw where to find the extension
        ext_path = str(state_dir / "extensions" / plugin_id)
        load_section = plugins_section.setdefault("load", {})
        paths: list = load_section.setdefault("paths", [])
        if ext_path not in paths:
            paths.append(ext_path)

        # Entries — enables the plugin
        entries: dict = plugins_section.setdefault("entries", {})
        if plugin_id not in entries:
            entries[plugin_id] = {"enabled": True}

        config_path.write_text(_json.dumps(cfg, indent=2))
    except Exception:
        pass  # Non-fatal; install succeeds even if openclaw.json can't be updated


def _uninstall_openclaw(adapter_record: dict, profile: str | None = None) -> None:
    """Uninstall the mycelium plugin and hook (non-interactively)."""
    for cmd in [
        _openclaw_cmd(
            ["openclaw", "plugins", "uninstall", _OPENCLAW_PLUGIN_NAME, "--force"], profile
        ),
        _openclaw_cmd(["openclaw", "hooks", "uninstall", _OPENCLAW_HOOK_NAME, "--force"], profile),
        _openclaw_cmd(
            ["openclaw", "hooks", "uninstall", _OPENCLAW_EXTRACTOR_HOOK_NAME, "--force"], profile
        ),
    ]:
        result = subprocess.run(cmd, text=True, capture_output=True)
        # Non-zero is acceptable if already removed manually
        if result.returncode != 0 and "not found" not in (result.stderr or "").lower():
            typer.secho(
                f"  warning: {' '.join(cmd[:3])} exited {result.returncode}",
                fg=typer.colors.YELLOW,
            )
    _allow_plugin_remove(_OPENCLAW_PLUGIN_NAME, profile=profile)
    skill_dir = _openclaw_state_dir(profile) / "workspace" / "skills" / _OPENCLAW_SKILL_NAME
    if skill_dir.exists():
        shutil.rmtree(skill_dir, ignore_errors=True)


def _allow_plugin_remove(plugin_id: str, profile: str | None = None) -> None:
    """Remove plugin_id from plugins.allow, load.paths, and entries in openclaw.json."""
    state_dir = _openclaw_state_dir(profile)
    config_path = state_dir / "openclaw.json"
    if not config_path.exists():
        return
    try:
        import json as _json

        cfg = _json.loads(config_path.read_text())
        plugins_section = cfg.get("plugins", {})

        allow_list: list = plugins_section.get("allow", [])
        if plugin_id in allow_list:
            allow_list.remove(plugin_id)

        ext_path = str(state_dir / "extensions" / plugin_id)
        paths: list = plugins_section.get("load", {}).get("paths", [])
        if ext_path in paths:
            paths.remove(ext_path)

        entries: dict = plugins_section.get("entries", {})
        entries.pop(plugin_id, None)

        config_path.write_text(_json.dumps(cfg, indent=2))
    except Exception:
        pass


def _step_docker_env(config: "MyceliumConfig") -> None:
    """Print env vars needed for Docker-based experiment agent containers."""
    typer.secho("Docker agent env vars", bold=True)
    typer.echo("")
    typer.echo("  Add to your docker-compose environment block or experiment .env:")
    typer.echo("")
    typer.secho("  # .env", dim=True)
    typer.echo("  MYCELIUM_API_URL=http://host.docker.internal:8000")
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


def _check_adapter_status(name: str, info: dict) -> dict:
    """Run health checks for a registered adapter."""
    details: list[str] = []
    ok = True

    if name == "claude-code":
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

    elif name == "openclaw":
        profile = info.get("openclaw_profile")
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

        extractor_dir = state_dir / "hooks" / _OPENCLAW_EXTRACTOR_HOOK_NAME
        extractor_ok = (extractor_dir / "HOOK.md").exists()
        details.append(f"  {'✓' if extractor_ok else '✗'} hook:{_OPENCLAW_EXTRACTOR_HOOK_NAME}")
        if not extractor_ok:
            ok = False

        # Check plugin via openclaw plugins list (names don't truncate)
        result = subprocess.run(
            _openclaw_cmd(["openclaw", "plugins", "list"], profile),
            text=True,
            capture_output=True,
        )
        plugin_ok = result.returncode == 0 and _OPENCLAW_PLUGIN_NAME in (result.stdout or "")
        details.append(f"  {'✓' if plugin_ok else '✗'} plugin:{_OPENCLAW_PLUGIN_NAME}")
        if not plugin_ok:
            ok = False

    details.append(f"api_url: {info.get('api_url', '')}")

    return {"ok": ok, "details": details}
