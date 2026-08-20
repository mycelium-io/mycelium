# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Adapter commands: connect agent frameworks to Mycelium.

Thin typer layer. All per-family install/uninstall/step/status behaviour
lives behind the single ``Integration`` contract
(``mycelium.integrations``); this module just parses arguments and dispatches
via ``get_integration(...)``; there is no ``if adapter_type ==`` branching
left.

Supported families: ``claude-code``, ``cursor``.
Every family that has an entry in ``ADAPTER_TYPES`` below is also wired
through :func:`mycelium.integrations.get_integration`.
"""

from __future__ import annotations

import json as json_module
from datetime import UTC, datetime

import typer

from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref
from mycelium.error_handler import print_error
from mycelium.integrations import Integration, get_integration

app = typer.Typer(
    help="Connect agent frameworks (Claude Code, Cursor) to Mycelium. Install hooks, skills, and plugins.",
    no_args_is_help=True,
)

ADAPTER_TYPES = {
    "claude-code": "skill + hooks: copies SKILL.md and lifecycle hooks into ~/.claude/",
    "cursor": (
        "resident: drops .cursor/rules/mycelium.mdc + AGENTS.md into each cursor "
        "agent's workspace at `mycelium agent create` time"
    ),
}


@app.callback()
def adapter_main(ctx: typer.Context) -> None:
    """Manage agent framework adapters (claude-code, cursor, …)."""


def _resolve_integration(adapter_type: str) -> Integration | None:
    """Resolve a known adapter type to its integration, or None if planned.

    ``ADAPTER_TYPES`` is the user-facing catalogue (incl. the planned
    ``cursor``); the integration registry only holds families that are
    actually implemented. ``get_integration`` normalises the hyphen spelling.
    """
    try:
        return get_integration(adapter_type)
    except ValueError:
        return None


@doc_ref(
    usage="mycelium adapter add <type> [--dry-run]",
    desc="Install an agent framework adapter (claude-code, cursor).",
    group="adapter",
)
@app.command("add")
def add(
    ctx: typer.Context,
    adapter_type: str = typer.Argument(..., help="Adapter type: cursor, claude-code"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be installed without doing it"
    ),
    step: list[str] | None = typer.Option(
        None,
        "--step",
        help="Follow-up step (repeatable). No adapters define follow-up steps today.",
    ),
    remove_step: bool = typer.Option(
        False,
        "--remove-step",
        help="Reverse the named --step instead of applying it.",
    ),
    reinstall: bool = typer.Option(
        False, "--reinstall", help="Reinstall assets even if adapter is already registered"
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip confirmation prompts (e.g. reinstall overwrite warning)"
    ),
) -> None:
    """
    Register and install an agent framework adapter, then optionally wire it into your environment.

    Examples:
        mycelium adapter add claude-code
        mycelium adapter add cursor
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

        config = MyceliumConfig.load()
        integ = _resolve_integration(adapter_type)

        # ── Follow-up steps run independently of the base install ────────────
        if step:
            if integ is None:
                typer.secho(
                    f"--step is not supported for the '{adapter_type}' adapter.",
                    fg=typer.colors.RED,
                )
                raise typer.Exit(1)
            for s in step:
                if s not in integ.STEPS:
                    known_steps = ", ".join(integ.STEPS)
                    typer.secho(
                        f"Unknown {adapter_type} step '{s}'. Known: {known_steps}",
                        fg=typer.colors.RED,
                    )
                    raise typer.Exit(1)
            for s in step:
                integ.run_step(
                    s,
                    config=config,
                    verbose=verbose,
                    profile=None,
                    container=None,
                    remove=remove_step,
                )
            return

        # ── Base install ──────────────────────────────────────────────────────
        if adapter_type in config.adapters and not reinstall:
            typer.secho(
                f"Adapter '{adapter_type}' already registered. Use 'mycelium adapter status {adapter_type}' to check it, or pass --reinstall to redeploy assets.",
                fg=typer.colors.YELLOW,
            )
            raise typer.Exit(0)

        # Confirm before destructive reinstall (local edits will be lost).
        if reinstall and not dry_run and not yes:
            targets = (
                integ.reinstall_targets(profile=None, container=None) if integ is not None else []
            )
            typer.secho(
                f"\n  Reinstalling the '{adapter_type}' adapter will overwrite:",
                fg=typer.colors.YELLOW,
            )
            for target_line in targets:
                typer.echo(target_line)
            typer.echo(
                "\n  Any local edits to these files will be lost. Pass --yes/-y to skip this prompt.\n"
            )
            if not typer.confirm("  Continue with reinstall?", default=False):
                typer.secho("  Aborted.", fg=typer.colors.YELLOW)
                raise typer.Exit(0)

        if dry_run:
            typer.secho(f"[dry-run] Would install adapter: {adapter_type}", fg=typer.colors.CYAN)
            lines = (
                integ.dry_run_lines(config=config, profile=None, container=None)
                if integ is not None
                else []
            )
            for line in lines:
                typer.echo(line)
            typer.echo(f"  api_url: {config.server.api_url}")
            return

        if integ is None:
            typer.secho(
                f"Adapter '{adapter_type}' is planned but not yet implemented.",
                fg=typer.colors.YELLOW,
            )
            raise typer.Exit(1)

        integ.install(
            config=config,
            verbose=verbose,
            profile=None,
            container=None,
            reinstall=reinstall,
        )

        if not reinstall:
            adapter_record: dict = {
                "type": adapter_type,
                "installed_at": datetime.now(UTC).isoformat(),
                "api_url": config.server.api_url,
            }
            config.adapters[adapter_type] = adapter_record
            config.save()

        if json_output:
            typer.echo(json_module.dumps(config.adapters.get(adapter_type, {}), indent=2))
        else:
            integ.post_install_banner(
                config=config,
                reinstall=reinstall,
                profile=None,
                container=None,
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

        integ = _resolve_integration(adapter_type)
        if integ is not None:
            record = config.adapters[adapter_type]
            integ.uninstall(
                record=record,
                profile=None,
                container=None,
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

        def _status_one(name: str, info: dict) -> dict:
            integ = _resolve_integration(name)
            if integ is None:
                # Unknown/planned family registered in config; report a
                # minimal status (ok, just the api_url).
                return {"ok": True, "details": [f"api_url: {info.get('api_url', '')}"]}
            return integ.status_check(name=name, info=info)

        results = {name: _status_one(name, info) for name, info in targets.items()}

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
