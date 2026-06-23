# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium demo`` — guided sample-coordination walkthrough.

A self-contained onboarding command (issues #374 / #315). It replays a
recorded, realistic multi-agent negotiation end-to-end so a brand-new user
*watches Mycelium reach consensus* before assembling a coordination themselves,
then prints the exact commands to reproduce it.

Two modes:

* **replay** (default): deterministic, offline, zero-cost playback of a bundled
  transcript (``_demo_scenarios.py``). Always works — no backend, LLM, or
  daemon required. This is the first-run teaching moment.
* **``--live``**: provisions the scenario as a *real* room on the running
  backend — creates the room, registers the agents, and posts the negotiation
  and compiled plan as real messages — so you can open it in ``mycelium watch``
  or the GUI (``/room/<room>``) and in the GUI demo view (``/demo``). It reuses
  the public REST API only; it does not require LLM credits. For a fully
  autonomous LLM-driven run, see the ``persona-before-and-after`` skill.

Everything for the demo lives in this module and ``_demo_scenarios.py`` — it is
deliberately isolated and clearly labeled so it can be lifted out cleanly.
"""

from __future__ import annotations

import time
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from mycelium.commands._demo_scenarios import (
    DEFAULT_SCENARIO,
    SCENARIOS,
    list_scenarios,
)

app = typer.Typer()
console = Console()

# Per-agent accent colors, assigned in join order.
_AGENT_COLORS = ["cyan", "magenta", "green", "yellow", "blue"]

_ACTION_GLYPH = {
    "propose": ("◆", "white"),
    "counter": ("◇", "yellow"),
    "accept": ("✓", "green"),
    "reject": ("✗", "red"),
}


def _agent_color_map(scenario: dict[str, Any]) -> dict[str, str]:
    return {
        a["handle"]: _AGENT_COLORS[i % len(_AGENT_COLORS)] for i, a in enumerate(scenario["agents"])
    }


def _pause(seconds: float, fast: bool) -> None:
    if not fast and seconds > 0:
        time.sleep(seconds)


# --------------------------------------------------------------------------- #
# Replay (offline) renderer
# --------------------------------------------------------------------------- #


def _render_header(scenario: dict[str, Any]) -> None:
    body = Text()
    body.append(scenario["tagline"] + "\n\n", style="italic")
    body.append("Domain: ", style="dim")
    body.append(f"{scenario['domain']}    ", style="bold")
    body.append("Agents: ", style="dim")
    body.append(", ".join(f"@{a['handle']}" for a in scenario["agents"]) + "\n", style="bold")
    body.append("Model:  ", style="dim")
    body.append(scenario["model"], style="bold")
    console.print(
        Panel(
            body,
            title=f"[bold]Mycelium demo · {scenario['title']}[/bold]",
            subtitle="[dim]recorded sample — replaying[/dim]",
            border_style="cyan",
        )
    )

    issues = Table(
        title="Issues under negotiation", title_style="dim", show_edge=False, pad_edge=False
    )
    issues.add_column("Issue", style="bold")
    issues.add_column("Options", style="dim")
    for issue in scenario["issues"]:
        issues.add_row(issue["label"], "  ·  ".join(issue["options"]))
    console.print(issues)
    console.print()


def _render_step(step: dict[str, Any], colors: dict[str, str]) -> None:
    kind = step["kind"]

    if kind == "system":
        console.print(f"[dim]· {step['text']}[/dim]")

    elif kind == "seed":
        console.print(
            Panel(step["text"], title="[bold]seed task[/bold]", border_style="dim", padding=(0, 1))
        )

    elif kind == "join":
        color = colors.get(step["agent"], "white")
        console.print(f"[{color}]@{step['agent']}[/{color}] [dim]joined[/dim] — {step['intent']}")

    elif kind == "tick":
        color = colors.get(step["agent"], "white")
        glyph, gstyle = _ACTION_GLYPH.get(step["action"], ("•", "white"))
        line = Text()
        line.append(f"  R{step['round']} ", style="dim")
        line.append(f"{glyph} ", style=gstyle)
        line.append(f"@{step['agent']}", style=f"bold {color}")
        line.append(f"  {step['action']}  ", style=gstyle)
        line.append(step["text"], style="default")
        console.print(line)
        if step.get("offer"):
            offer = "   ".join(f"{k}={v}" for k, v in step["offer"].items())
            console.print(f"        [dim]offer: {offer}[/dim]")

    elif kind == "consensus":
        _render_consensus(step)


def _render_consensus(step: dict[str, Any]) -> None:
    console.print()
    reached = step["reached"]
    if reached:
        title = f"[bold green]✓ CONSENSUS[/bold green] · {step['rounds']} rounds"
        border = "green"
    else:
        title = f"[bold yellow]⚠ STRUCTURED IMPASSE[/bold yellow] · {step['rounds']} rounds"
        border = "yellow"

    table = Table(show_edge=False, pad_edge=False, box=None)
    table.add_column("Issue", style="dim")
    table.add_column("Agreed", style="bold")
    for key, val in step["assignments"].items():
        unresolved = isinstance(val, str) and val.startswith("UNRESOLVED")
        table.add_row(key, f"[yellow]{val}[/yellow]" if unresolved else val)

    console.print(Panel(table, title=title, border_style=border))
    console.print(f"[italic]{step['summary']}[/italic]")
    if step.get("escalation"):
        console.print(Panel(step["escalation"], border_style="yellow", padding=(0, 1)))

    console.print(f"\n[bold]Compiled plan[/bold] → [cyan]{step['plan_file']}[/cyan]")
    for task in step["tasks"]:
        console.print(f"  [dim]- [ ][/dim] {task}")


def _render_metrics(scenario: dict[str, Any]) -> None:
    m = scenario["metrics"]
    table = Table(title="Run summary", title_style="bold", show_edge=False, pad_edge=False)
    table.add_column("Metric", style="dim")
    table.add_column("Value", style="bold")
    table.add_row("Outcome", "Consensus" if m["consensus"] else "Escalated (correct impasse)")
    table.add_row("Rounds", str(m["rounds"]))
    table.add_row("Token cost", f"~{m['tokens']:,} tokens")
    table.add_row("Wall time", f"~{m['duration_s']}s")
    table.add_row("Model", m["model"])
    console.print()
    console.print(table)


def _render_reproduce(scenario: dict[str, Any]) -> None:
    room = scenario["room"]
    handles = [a["handle"] for a in scenario["agents"]]
    lines = [
        f"mycelium room create {room}",
        f"mycelium room use {room}",
    ]
    lines += [f"mycelium agent create --handle {h} -r {room}" for h in handles]
    lines.append(f"mycelium session create -r {room}")
    lines += [f'mycelium session join -H @{h} -m "<your position>" -r {room}' for h in handles]
    lines.append("mycelium watch " + room)
    body = "\n".join(lines)
    console.print()
    console.print(
        Panel(
            body,
            title="[bold]What you just watched — reproduce it yourself[/bold]",
            subtitle="[dim]or re-run with --live to provision this as a real room[/dim]",
            border_style="cyan",
        )
    )


def _replay(scenario: dict[str, Any], fast: bool) -> None:
    colors = _agent_color_map(scenario)
    _render_header(scenario)
    _pause(0.6, fast)
    for step in scenario["steps"]:
        _render_step(step, colors)
        delay = 1.1 if step["kind"] == "tick" else 0.6
        _pause(delay, fast)
    _render_metrics(scenario)
    _render_reproduce(scenario)


# --------------------------------------------------------------------------- #
# Live driver (provisions a real room via the public REST API)
# --------------------------------------------------------------------------- #


def _agent_manifest_yaml(scenario: dict[str, Any], agent: dict[str, Any]) -> str:
    return (
        f"handle: {agent['handle']}\n"
        f"adapter: demo\n"
        f"room: {scenario['room']}\n"
        f'description: "{agent["role"]} — {agent["blurb"]}"\n'
    )


def _live(scenario: dict[str, Any], room_override: str | None) -> None:
    import httpx

    from mycelium.config import MyceliumConfig

    config = MyceliumConfig.load()
    api = config.server.api_url.rstrip("/")
    room = room_override or scenario["room"]
    colors = _agent_color_map(scenario)

    console.print(
        Panel(
            f"Provisioning [bold]{scenario['title']}[/bold] as a real room: [cyan]{room}[/cyan]\n"
            f"[dim]Backend: {api}  ·  posts the recorded negotiation + compiled plan via the REST API.[/dim]",
            title="[bold]mycelium demo --live[/bold]",
            border_style="cyan",
        )
    )

    with httpx.Client(base_url=api, timeout=30.0) as client:
        # 1. Room
        try:
            r = client.post("/api/rooms", json={"name": room, "is_public": True})
            if r.status_code == 400:
                console.print(f"[yellow]Room '{room}' already exists — reusing it.[/yellow]")
            else:
                r.raise_for_status()
                console.print(f"[green]✓[/green] Created room [cyan]{room}[/cyan]")
        except httpx.HTTPError as e:
            console.print(f"[red]Failed to create room:[/red] {e}")
            console.print("[dim]Is the stack up? Try: mycelium status[/dim]")
            raise typer.Exit(1)

        # 2. Agents (registered as memory manifests so they show in the roster)
        items = [
            {"key": f"agents/{a['handle']}", "value": _agent_manifest_yaml(scenario, a)}
            for a in scenario["agents"]
        ]
        try:
            client.post(f"/api/rooms/{room}/memory", json={"items": items}).raise_for_status()
            console.print(
                "[green]✓[/green] Registered agents: "
                + ", ".join(
                    f"[{colors[a['handle']]}]@{a['handle']}[/{colors[a['handle']]}]"
                    for a in scenario["agents"]
                )
            )
        except httpx.HTTPError as e:
            console.print(f"[yellow]Could not register agent manifests ({e}); continuing.[/yellow]")

        # 3. Negotiation transcript as real messages
        def post(sender: str, content: str) -> None:
            try:
                client.post(
                    f"/api/rooms/{room}/messages",
                    json={"sender_handle": sender, "content": content, "message_type": "broadcast"},
                ).raise_for_status()
            except httpx.HTTPError as e:
                console.print(f"[yellow]post by @{sender} failed: {e}[/yellow]")

        consensus_step: dict[str, Any] | None = None
        for step in scenario["steps"]:
            kind = step["kind"]
            if kind == "seed":
                post("demo", f"[seed] {step['text']}")
            elif kind == "join":
                post(step["agent"], f"joined — {step['intent']}")
            elif kind == "tick":
                offer = step.get("offer") or {}
                offer_s = (
                    ("  ·  " + " ".join(f"{k}={v}" for k, v in offer.items())) if offer else ""
                )
                post(step["agent"], f"[R{step['round']} {step['action']}] {step['text']}{offer_s}")
            elif kind == "consensus":
                consensus_step = step

        console.print(
            f"[green]✓[/green] Posted {len([s for s in scenario['steps'] if s['kind'] in ('seed', 'join', 'tick')])} negotiation messages"
        )

        # 4. Consensus message + compiled plan
        if consensus_step is not None:
            verdict = "CONSENSUS" if consensus_step["reached"] else "STRUCTURED IMPASSE (escalated)"
            post("demo", f"[{verdict}] {consensus_step['summary']}")
            try:
                client.put(
                    f"/api/rooms/{room}/plan/title",
                    json={"text": scenario["title"]},
                ).raise_for_status()
                for task in consensus_step["tasks"]:
                    client.post(
                        f"/api/rooms/{room}/plan/tasks",
                        json={"text": task, "slug": "tasks"},
                    ).raise_for_status()
                console.print(
                    f"[green]✓[/green] Compiled plan with {len(consensus_step['tasks'])} tasks → [cyan]plan/tasks.md[/cyan]"
                )
            except httpx.HTTPError as e:
                console.print(
                    f"[yellow]Could not compile plan ({e}); messages still posted.[/yellow]"
                )

    console.print()
    console.print(
        Panel(
            f"Open it live:\n"
            f"  [bold]mycelium watch {room}[/bold]\n"
            f"  GUI room:  [cyan]/room/{room}[/cyan]\n"
            f"  GUI demo:  [cyan]/demo[/cyan]\n\n"
            f"Tear it down:\n"
            f"  [bold]mycelium room delete {room} --force[/bold]",
            title="[bold green]Live demo provisioned[/bold green]",
            border_style="green",
        )
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

    # Interactive menu when attached to a TTY; otherwise the default.
    choices = list_scenarios()
    import sys

    if not sys.stdin.isatty():
        return choices[0]

    try:
        import questionary

        answer = questionary.select(
            "Pick a sample scenario to walk through:",
            choices=[
                questionary.Choice(
                    title=f"{s['title']} — {s['tagline']}",
                    value=s["id"],
                )
                for s in choices
            ],
        ).ask()
    except Exception:
        return choices[0]

    if answer is None:
        raise typer.Exit(0)
    return SCENARIOS[answer]


@app.callback(invoke_without_command=True)
def demo(
    ctx: typer.Context,
    scenario: str | None = typer.Option(
        None,
        "--scenario",
        "-s",
        help="Scenario id (default: investment portfolio). See --list.",
    ),
    live: bool = typer.Option(
        False,
        "--live",
        help="Provision the scenario as a real room on the running backend (reuses the REST API; no LLM needed).",
    ),
    room: str | None = typer.Option(
        None,
        "--room",
        help="Override the room name used by --live.",
    ),
    fast: bool = typer.Option(
        False,
        "--fast",
        help="Replay with no pacing delays.",
    ),
    list_scenarios_flag: bool = typer.Option(
        False,
        "--list",
        help="List available sample scenarios and exit.",
    ),
) -> None:
    """Watch a sample multi-agent coordination reach consensus, end-to-end.

    By default this replays a recorded transcript offline (no backend, LLM, or
    daemon required). Pass --live to provision it as a real room you can open in
    'mycelium watch' or the GUI.
    """
    if ctx.invoked_subcommand is not None:
        return

    if list_scenarios_flag:
        table = Table(title="Mycelium demo scenarios", show_edge=False, pad_edge=False)
        table.add_column("id", style="bold cyan")
        table.add_column("title", style="bold")
        table.add_column("about", style="dim")
        for s in list_scenarios():
            marker = "  (default)" if s["id"] == DEFAULT_SCENARIO else ""
            table.add_row(s["id"] + marker, s["title"], s["tagline"])
        console.print(table)
        return

    chosen = _select_scenario(scenario)

    if live:
        _live(chosen, room)
    else:
        _replay(chosen, fast)
