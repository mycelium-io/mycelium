# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium demo`` — run a real sample coordination end-to-end.

A guided onboarding command (issues #374 / #315). It is pure glue over the real
system: it fetches agent personas from the public ``agent-personas`` dataset,
creates a room, runs ``mycelium agent create`` for each persona on your chosen
adapter, seeds the room with a task, and then lets the agents actually negotiate
to consensus. There is no canned transcript and nothing replayed — what you
watch is a live run.

Because it is live, it requires a working stack: an installed agent adapter
(``--adapter``), the backend up, and an LLM configured. If those aren't present
the command fails fast with the exact fix, rather than pretending.

Everything for the demo lives in this module and ``_demo_scenarios.py`` — it is
deliberately isolated and clearly labeled so it can be lifted out cleanly.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from mycelium.commands._demo_scenarios import (
    DEFAULT_SCENARIO,
    PERSONAS_RAW_BASE,
    SCENARIOS,
    list_scenarios,
)

app = typer.Typer()
console = Console()

# Adapters that can host a demo agent. Mirrors AGENT_ADAPTERS (underscore form).
_KNOWN_ADAPTERS = ("openclaw", "claude_code", "cursor", "hermes")


def _cli_prefix() -> list[str]:
    """How to invoke the mycelium CLI as a subprocess (installed script or module)."""
    exe = shutil.which("mycelium")
    if exe:
        return [exe]
    return [sys.executable, "-m", "mycelium.cli"]


def _run(args: list[str], *, capture: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a `mycelium ...` subcommand."""
    cmd = _cli_prefix() + args
    return subprocess.run(  # noqa: S603
        cmd,
        capture_output=capture,
        text=True,
        check=False,
    )


def _fetch_persona(path: str) -> str:
    """Fetch a persona's prose from the public agent-personas repo.

    Returns the ``domain:`` block (the agent's identity / red lines / goals).
    Raises on network or parse failure — the demo has no offline fallback by
    design.
    """
    import httpx
    import yaml

    url = f"{PERSONAS_RAW_BASE}/{path}"
    resp = httpx.get(url, timeout=15.0, follow_redirects=True)
    resp.raise_for_status()
    data = yaml.safe_load(resp.text) or {}
    prose = str(data.get("domain") or "").strip()
    if not prose:
        # Some persona files may carry the text under a different key; fall back
        # to the raw file so the agent still gets a persona.
        prose = resp.text.strip()
    return prose


# --------------------------------------------------------------------------- #
# Prerequisites
# --------------------------------------------------------------------------- #


def _adapter_installed(config: Any, adapter: str) -> bool:
    keys = {str(k).replace("-", "_") for k in (config.adapters or {})}
    return adapter in keys


def _check_prereqs(adapter: str) -> tuple[Any, list[str]]:
    """Load config and collect blocking problems (empty list = good to go)."""
    from mycelium.config import MyceliumConfig

    problems: list[str] = []
    try:
        config = MyceliumConfig.load()
    except Exception:
        console.print(
            "[red]No Mycelium config found.[/red] Run [bold]mycelium install[/bold] first."
        )
        raise typer.Exit(1)

    # Adapter installed?
    if not _adapter_installed(config, adapter):
        kebab = adapter.replace("_", "-")
        problems.append(
            f"Adapter '{adapter}' is not installed. Install it with: mycelium adapter add {kebab}"
        )

    # LLM configured? (agents can't negotiate without a model)
    if not getattr(config.llm, "model", None):
        problems.append(
            "No LLM configured. Set one with: "
            'mycelium config set llm.model "<provider/model>" && mycelium config apply'
        )

    # Backend reachable?
    import httpx

    api = config.server.api_url.rstrip("/")
    try:
        r = httpx.get(f"{api}/api/rooms", timeout=5.0)
        r.raise_for_status()
    except httpx.HTTPError:
        problems.append(f"Backend not reachable at {api}. Is the stack up? Try: mycelium status")

    return config, problems


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


def _provision(scenario: dict[str, Any], adapter: str, model: str | None, room: str) -> None:
    """Create the room + persona agents and seed the task. Raises typer.Exit on failure."""
    handles = [a["handle"] for a in scenario["agents"]]

    # 1. Fetch personas first — fail before we create anything if the dataset is
    #    unreachable.
    console.print("[dim]Fetching personas from agent-personas…[/dim]")
    personas: dict[str, str] = {}
    for a in scenario["agents"]:
        try:
            personas[a["handle"]] = _fetch_persona(a["persona"])
        except Exception as e:
            console.print(f"[red]Could not fetch persona[/red] {a['persona']}: {e}")
            raise typer.Exit(1)
    console.print(f"[green]✓[/green] Loaded {len(personas)} personas")

    # 2. Room
    r = _run(["room", "create", room])
    if r.returncode != 0 and "already exists" not in (r.stdout + r.stderr).lower():
        console.print(f"[red]room create failed:[/red]\n{r.stderr or r.stdout}")
        raise typer.Exit(1)
    console.print(f"[green]✓[/green] Room [cyan]{room}[/cyan]")

    # 3. Agents — one `mycelium agent create` per persona, on the chosen adapter.
    for a in scenario["agents"]:
        handle = a["handle"]
        args = [
            "agent",
            "create",
            handle,
            "--adapter",
            adapter,
            "--room",
            room,
            "--description",
            personas[handle],
        ]
        if model and adapter == "openclaw":
            args += ["--model", model]
        r = _run(args)
        if r.returncode != 0:
            console.print(f"[red]agent create {handle} failed:[/red]\n{r.stderr or r.stdout}")
            console.print(
                "[dim]Cold-spawn adapters (claude_code/cursor) need --cwd per agent and a "
                "running daemon; openclaw needs the gateway. See `mycelium adapter status`.[/dim]"
            )
            raise typer.Exit(1)
        console.print(f"[green]✓[/green] Created [bold]@{handle}[/bold] ({adapter})")

    # 4. Seed: one message mentioning every agent + the task. The adapter wakes
    #    each agent, which then runs the Mycelium coordination protocol.
    mentions = " ".join(f"@{h}" for h in handles)
    seed = f"{mentions} {scenario['task']} Coordinate via Mycelium and reach consensus."
    r = _run(["agent", "invoke", handles[0], seed, "--room", room, "-H", "demo"])
    if r.returncode != 0:
        console.print(f"[red]seeding failed:[/red]\n{r.stderr or r.stdout}")
        raise typer.Exit(1)
    console.print("[green]✓[/green] Seeded the room — agents are negotiating")


def _print_intro(scenario: dict[str, Any], adapter: str, room: str) -> None:
    body = (
        f"{scenario['tagline']}\n\n"
        f"[dim]Adapter:[/dim] [bold]{adapter}[/bold]    "
        f"[dim]Room:[/dim] [bold]{room}[/bold]    "
        f"[dim]Agents:[/dim] [bold]"
        + ", ".join(f"@{a['handle']}" for a in scenario["agents"])
        + "[/bold]\n"
        f"[dim]Task:[/dim] {scenario['task']}"
    )
    console.print(
        Panel(
            body,
            title=f"[bold]mycelium demo · {scenario['title']}[/bold]",
            subtitle="[dim]live run — real agents, real negotiation[/dim]",
            border_style="cyan",
        )
    )


def _print_outro(scenario: dict[str, Any], adapter: str, room: str) -> None:
    handles = [a["handle"] for a in scenario["agents"]]
    repro = "\n".join(
        [
            f"mycelium room create {room}",
            *[
                f'mycelium agent create {h} --adapter {adapter} --room {room} -d "<persona>"'
                for h in handles
            ],
            f'mycelium agent invoke {handles[0]} "@... <task>" -r {room}',
            f"mycelium watch {room}",
        ]
    )
    console.print()
    console.print(
        Panel(
            repro,
            title="[bold]What just happened — reproduce it yourself[/bold]",
            border_style="cyan",
        )
    )
    console.print(
        f"[dim]Open in the GUI: [/dim][cyan]/room/{room}[/cyan]    "
        f"[dim]Tear down: [/dim][bold]mycelium room delete {room} --force[/bold]"
    )


# --------------------------------------------------------------------------- #
# Command
# --------------------------------------------------------------------------- #


def _select_scenario(scenario_id: str | None) -> dict[str, Any]:
    if scenario_id:
        if scenario_id not in SCENARIOS:
            console.print(f"[red]Unknown scenario:[/red] {scenario_id}")
            console.print("[dim]Run 'mycelium demo --list' to see available scenarios.[/dim]")
            raise typer.Exit(1)
        return SCENARIOS[scenario_id]
    return SCENARIOS[DEFAULT_SCENARIO]


@app.callback(invoke_without_command=True)
def demo(
    ctx: typer.Context,
    adapter: str | None = typer.Option(
        None,
        "--adapter",
        "-a",
        help=f"Adapter to host the demo agents (required). One of: {', '.join(_KNOWN_ADAPTERS)}.",
    ),
    scenario: str | None = typer.Option(
        None, "--scenario", "-s", help="Scenario id (default: investment portfolio). See --list."
    ),
    model: str | None = typer.Option(
        None, "--model", help="openclaw: model for the demo agents (else the configured default)."
    ),
    room: str | None = typer.Option(None, "--room", help="Override the room name."),
    no_watch: bool = typer.Option(
        False, "--no-watch", help="Provision and seed, but don't stream the room afterward."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
    list_flag: bool = typer.Option(False, "--list", help="List available scenarios and exit."),
) -> None:
    """Run a real sample coordination: personas → agents → seeded room → live negotiation.

    Requires an installed adapter, the backend up, and an LLM configured. Example:

        mycelium demo --adapter openclaw
    """
    if ctx.invoked_subcommand is not None:
        return

    if list_flag:
        table = Table(title="mycelium demo scenarios", show_edge=False, pad_edge=False)
        table.add_column("id", style="bold cyan")
        table.add_column("title", style="bold")
        table.add_column("about", style="dim")
        for s in list_scenarios():
            marker = "  (default)" if s["id"] == DEFAULT_SCENARIO else ""
            table.add_row(s["id"] + marker, s["title"], s["tagline"])
        console.print(table)
        return

    if not adapter:
        console.print(
            "[red]--adapter is required.[/red] The demo runs real agents, so pick one:\n"
            f"  mycelium demo --adapter openclaw\n"
            f"[dim]Known adapters: {', '.join(_KNOWN_ADAPTERS)}[/dim]"
        )
        raise typer.Exit(1)

    adapter = adapter.replace("-", "_")
    if adapter not in _KNOWN_ADAPTERS:
        console.print(
            f"[red]Unknown adapter '{adapter}'.[/red] One of: {', '.join(_KNOWN_ADAPTERS)}."
        )
        raise typer.Exit(1)

    chosen = _select_scenario(scenario)
    room_name = room or chosen["room"]

    _print_intro(chosen, adapter, room_name)

    _config, problems = _check_prereqs(adapter)
    if problems:
        console.print("\n[red]Can't run the live demo yet:[/red]")
        for p in problems:
            console.print(f"  [yellow]•[/yellow] {p}")
        raise typer.Exit(1)

    if not yes:
        n = len(chosen["agents"])
        proceed = typer.confirm(
            f"\nThis will create room '{room_name}' and {n} live {adapter} agents, "
            f"then run a real negotiation (uses your LLM). Continue?"
        )
        if not proceed:
            raise typer.Exit(0)

    _provision(chosen, adapter, model, room_name)
    _print_outro(chosen, adapter, room_name)

    if not no_watch:
        console.print("\n[dim]Streaming the room (Ctrl-C to stop)…[/dim]\n")
        try:
            _run(["watch", room_name], capture=False)
        except KeyboardInterrupt:
            console.print("\n[dim]Stopped watching. The room keeps running.[/dim]")
