# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium demo`` — run a real sample coordination end-to-end.

A guided onboarding command. It is pure glue over the real
system, with no mirrored data: it discovers scenarios and agent personas from
the public ``agent-personas`` dataset at run time, creates a room, runs
``mycelium agent create`` for each persona on your chosen adapter, seeds the
room with a task, and then lets the agents actually negotiate to consensus.
There is no canned transcript and nothing replayed — what you watch is a live
run.

Because it is live, it requires a working stack: an installed agent adapter
(``--adapter``), the backend up, and an LLM configured. If those aren't present
the command fails fast with the exact fix, rather than pretending.

Everything for the demo lives in this single module — it is deliberately
isolated and clearly labeled so it can be lifted out cleanly.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

app = typer.Typer()
console = Console()

# Public persona dataset (the persona-before-and-after skill runs these live).
_REPO = "mycelium-io/agent-personas"
_REF = "main"
_RAW_BASE = f"https://raw.githubusercontent.com/{_REPO}/{_REF}"
_TREE_URL = f"https://api.github.com/repos/{_REPO}/git/trees/{_REF}?recursive=1"

# Sensible default; any scenario discovered in the dataset is selectable.
DEFAULT_SCENARIO = "ex07_investment_portfolio"

# The reserved handle that summons the SIEP aligner (backend ALIGNER_HANDLE
# default). Summoning it scores the room's positions into a converged/rejected
# verdict and, on converge, compiles plan/tasks.md + syncs a knowledge memory.
ALIGNER_HANDLE = "aligner"

# Adapters that can host a demo agent. Mirrors AGENT_ADAPTERS (underscore form).
_KNOWN_ADAPTERS = ("openclaw", "claude_code", "cursor", "hermes")

# Cold-spawn families: the daemon launches a fresh CLI process per @-mention.
# They require a non-empty `cwd` per agent (protocol.py) and only get a SLIM
# connector for a room the daemon is subscribed to.
_COLD_SPAWN_ADAPTERS = ("claude_code", "cursor")


def _cli_prefix() -> list[str]:
    """How to invoke the mycelium CLI as a subprocess (installed script or module)."""
    exe = shutil.which("mycelium")
    if exe:
        return [exe]
    return [sys.executable, "-m", "mycelium.cli"]


def _run(args: list[str], *, capture: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a `mycelium ...` subcommand."""
    cmd = _cli_prefix() + args
    return subprocess.run(cmd, capture_output=capture, text=True, check=False)  # noqa: S603


# --------------------------------------------------------------------------- #
# Discovery from the public dataset (no local mirror)
# --------------------------------------------------------------------------- #


def _fetch_tree() -> list[str]:
    """Return every path in the agent-personas repo (one API call)."""
    import httpx

    resp = httpx.get(_TREE_URL, timeout=15.0, follow_redirects=True)
    resp.raise_for_status()
    return [t["path"] for t in resp.json().get("tree", [])]


def _list_scenarios(paths: list[str] | None = None) -> list[str]:
    """Scenario ids = the subdirectories under ``profiles/`` in the dataset."""
    paths = paths if paths is not None else _fetch_tree()
    return sorted(
        {p.split("/")[1] for p in paths if p.startswith("profiles/") and p.count("/") >= 2}
    )


def _pretty_topic(scenario_id: str) -> str:
    """ex07_investment_portfolio -> 'investment portfolio'."""
    return re.sub(r"^ex\d+_", "", scenario_id).replace("_", " ")


def _fetch_persona(path: str) -> str:
    """Fetch a persona's prose (the ``domain:`` block) from the dataset."""
    import httpx
    import yaml

    resp = httpx.get(f"{_RAW_BASE}/{path}", timeout=15.0, follow_redirects=True)
    resp.raise_for_status()
    data = yaml.safe_load(resp.text) or {}
    return str(data.get("domain") or "").strip() or resp.text.strip()


def _resolve_scenario(scenario_id: str) -> dict[str, Any]:
    """Build a scenario spec entirely from the remote dataset.

    Returns ``{id, title, topic, room, task, agents:[{handle, persona}]}``.
    Raises typer.Exit if the scenario or its personas can't be resolved.
    """
    import httpx
    import yaml

    try:
        paths = _fetch_tree()
    except httpx.HTTPError as e:
        console.print(f"[red]Could not reach agent-personas:[/red] {e}")
        raise typer.Exit(1)

    if scenario_id not in _list_scenarios(paths):
        console.print(f"[red]Unknown scenario:[/red] {scenario_id}")
        console.print("[dim]Run 'mycelium demo --list' to see available scenarios.[/dim]")
        raise typer.Exit(1)

    profile_files = sorted(
        p for p in paths if p.startswith(f"profiles/{scenario_id}/") and p.endswith(".yaml")
    )

    agents: list[dict[str, str]] = []
    for pf in profile_files:
        stem = pf.rsplit("/", 1)[1][: -len(".yaml")]
        handle = stem[: -len("_agent")] if stem.endswith("_agent") else stem
        try:
            profile = yaml.safe_load(httpx.get(f"{_RAW_BASE}/{pf}", timeout=15.0).text) or {}
        except httpx.HTTPError as e:
            console.print(f"[red]Could not read profile[/red] {pf}: {e}")
            raise typer.Exit(1)
        parts = profile.get("persona_parts", []) or []
        pref = next((x for x in parts if "preferences/" in x), None)
        if not pref:
            continue
        # persona_parts paths are repo-root-relative but prefixed `personas/`.
        persona_path = pref.split("personas/", 1)[-1]
        agents.append({"handle": handle, "persona": persona_path})

    if len(agents) < 2:
        console.print(f"[red]Scenario '{scenario_id}' has too few agents to negotiate.[/red]")
        raise typer.Exit(1)

    topic = _pretty_topic(scenario_id)
    return {
        "id": scenario_id,
        "title": topic[:1].upper() + topic[1:],
        "topic": topic,
        "room": "demo-" + topic.replace(" ", "-"),
        "task": (
            f"You are negotiating the {topic} decision. Each of you holds the position "
            f"described in your persona. Use Mycelium to propose offers, counter, and "
            f"reach consensus."
        ),
        "agents": agents,
    }


# --------------------------------------------------------------------------- #
# Prerequisites
# --------------------------------------------------------------------------- #


def _demo_workdir(room: str, handle: str) -> Path:
    """Per-agent working dir for cold-spawn adapters (claude_code/cursor).

    Cold-spawn agents require a non-empty ``cwd`` — the daemon launches the
    agent's CLI there per @-mention (Claude treats it as the project root, cursor
    as the workspace root). Give each demo agent its own stable dir under
    ``~/.mycelium/demo/`` so it survives the run and is inspectable afterward.
    """
    from mycelium.config import MyceliumConfig

    d = MyceliumConfig.get_global_config_dir() / "demo" / room / handle
    d.mkdir(parents=True, exist_ok=True)
    return d


def _daemon_running() -> bool:
    """Whether the mycelium daemon is answering its health socket."""
    from mycelium.daemon.health import read_health_blocking

    return read_health_blocking(timeout=2.0) is not None


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

    if not _adapter_installed(config, adapter):
        kebab = adapter.replace("_", "-")
        problems.append(
            f"Adapter '{adapter}' is not installed. Install it with: mycelium adapter add {kebab}"
        )

    if not getattr(config.llm, "model", None):
        problems.append(
            "No LLM configured. Set one with: "
            'mycelium config set llm.model "<provider/model>" && mycelium config apply'
        )

    import httpx

    api = config.server.api_url.rstrip("/")
    try:
        httpx.get(f"{api}/api/rooms", timeout=5.0).raise_for_status()
    except httpx.HTTPError:
        problems.append(f"Backend not reachable at {api}. Is the stack up? Try: mycelium status")

    # Cold-spawn agents wake only through a running daemon subscribed to the
    # room; without it they're created but never invoked. Fail fast with the fix.
    if adapter in _COLD_SPAWN_ADAPTERS and not _daemon_running():
        problems.append(
            f"The mycelium daemon isn't running — {adapter} agents cold-spawn through it. "
            "Start it with: mycelium daemon run --foreground "
            "(or install the service: mycelium adapter add claude-code --step=daemon)."
        )

    return config, problems


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


def _discover_openclaw_auth_source(exclude: set[str]) -> str | None:
    """Find an existing OpenClaw agent that already has model credentials.

    ``openclaw agents add --non-interactive`` (which ``agent create`` uses)
    creates an agent with an *empty* ``auth-profiles.json`` — no token — so the
    agent can't authenticate its model and every dispatch hangs in
    ``processing`` with no error. The demo's whole point is a turn that runs, so
    we copy credentials from an already-authenticated agent via
    ``--copy-auth-from``. Pick a source here: prefer one with an anthropic
    profile (matches openclaw's default model), else any non-empty profile.

    Returns the source agent id, or None if nothing on this host is
    authenticated yet (the caller warns and proceeds).
    """
    agents_dir = Path.home() / ".openclaw" / "agents"
    if not agents_dir.is_dir():
        return None
    fallback: str | None = None
    for d in sorted(agents_dir.iterdir()):
        if d.name in exclude:
            continue
        try:
            profiles = json.loads((d / "agent" / "auth-profiles.json").read_text()).get(
                "profiles", {}
            )
        except (OSError, ValueError):
            continue
        if not profiles:
            continue
        if any("anthropic" in k for k in profiles):
            return d.name  # ideal: matches the default anthropic model
        fallback = fallback or d.name
    return fallback


def _await_openclaw_ready(*, timeout: float = 30.0, settle: float = 5.0) -> None:
    """Block until the OpenClaw gateway is back up and its room channel has had
    time to (re)subscribe to SSE, before we seed.

    ``mycelium agent create --adapter openclaw`` restarts the gateway to load
    the new room into the ``mycelium-room`` channel, but that restart is
    asynchronous. The gateway then has to come up *and* the channel has to open
    a fresh SSE connection per room. Until that subscription exists, the seed
    mention is delivered to nobody — SSE is live-only, so a message posted
    before the channel connects is never replayed, and the agents simply never
    wake (the message still lands in the room, which makes the silence look
    like a hang). Wait for ``gateway status`` to report running, then settle a
    few seconds for the per-room SSE subscription to establish.

    Best-effort: if openclaw isn't on PATH or never reports ready, warn and let
    the caller seed anyway rather than blocking the demo outright.
    """
    if not shutil.which("openclaw"):
        return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = subprocess.run(  # noqa: S603
            ["openclaw", "gateway", "status"],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
        )
        if r.returncode == 0 and "running" in (r.stdout + r.stderr).lower():
            time.sleep(settle)  # let the mycelium-room channel open its SSE
            return
        time.sleep(1.0)
    console.print(
        "[yellow]⚠ gateway didn't report ready in time — seeding anyway. If the "
        "agents stay silent, run [cyan]openclaw gateway restart[/cyan] and re-seed "
        "with the invoke command shown below.[/yellow]"
    )


def _provision(
    scenario: dict[str, Any],
    adapter: str,
    model: str | None,
    room: str,
    auth_from: str | None = None,
) -> None:
    """Create the room + persona agents and seed the task. Raises typer.Exit on failure."""
    handles = [a["handle"] for a in scenario["agents"]]

    # 1. Fetch personas first — fail before we create anything if unreachable.
    console.print("[dim]Fetching personas from agent-personas…[/dim]")
    personas: dict[str, str] = {}
    for a in scenario["agents"]:
        try:
            personas[a["handle"]] = _fetch_persona(a["persona"])
        except Exception as e:
            console.print(f"[red]Could not fetch persona[/red] {a['persona']}: {e}")
            raise typer.Exit(1)
    console.print(f"[green]✓[/green] Loaded {len(personas)} personas")

    # 1b. openclaw: new agents are created with no model credentials, so their
    #     turns hang in `processing` with no error. Copy creds from an
    #     already-authenticated agent (explicit --auth-from, else discovered).
    auth_source: str | None = None
    if adapter == "openclaw":
        auth_source = auth_from or _discover_openclaw_auth_source(exclude=set(handles))
        if auth_source:
            console.print(f"[dim]Seeding agent credentials from [cyan]{auth_source}[/cyan][/dim]")
        else:
            console.print(
                "[yellow]⚠ No authenticated OpenClaw agent found to copy credentials from.[/yellow]\n"
                "[dim]  Fresh agents have no model token, so their turns will hang silently. "
                "Authenticate one agent (e.g. [cyan]openclaw models auth[/cyan]) or pass "
                "[cyan]--auth-from <agent>[/cyan].[/dim]"
            )

    # 2. Room
    r = _run(["room", "create", room])
    if r.returncode != 0 and "already exists" not in (r.stdout + r.stderr).lower():
        console.print(f"[red]room create failed:[/red]\n{r.stderr or r.stdout}")
        raise typer.Exit(1)
    console.print(f"[green]✓[/green] Room [cyan]{room}[/cyan]")

    # 2b. Cold-spawn adapters (claude_code/cursor) only get a SLIM connector for
    #     a room the daemon is subscribed to. Subscribe now — before the agents
    #     are seeded — so they actually wake on the mention.
    if adapter in _COLD_SPAWN_ADAPTERS:
        r = _run(["daemon", "subscribe", room])
        if r.returncode != 0:
            console.print(f"[red]daemon subscribe {room} failed:[/red]\n{r.stderr or r.stdout}")
            console.print(
                "[dim]Cold-spawn agents wake only through the daemon. "
                "Check it with: mycelium daemon status[/dim]"
            )
            raise typer.Exit(1)
        console.print(f"[green]✓[/green] Daemon subscribed to [cyan]{room}[/cyan]")

    # 3. Agents — one `mycelium agent create` per persona, on the chosen adapter.
    for a in scenario["agents"]:
        handle = a["handle"]
        args = [
            "agent", "create", handle,
            "--adapter", adapter,
            "--room", room,
            "--description", personas[handle],
        ]  # fmt: skip
        # Cold-spawn families require a per-agent working dir (protocol.py).
        if adapter in _COLD_SPAWN_ADAPTERS:
            args += ["--cwd", str(_demo_workdir(room, handle))]
        if model and adapter == "openclaw":
            args += ["--model", model]
        if auth_source:
            args += ["--copy-auth-from", auth_source]
        r = _run(args)
        if r.returncode != 0:
            console.print(f"[red]agent create {handle} failed:[/red]\n{r.stderr or r.stdout}")
            console.print(
                "[dim]Cold-spawn adapters (claude_code/cursor) need --cwd per agent and a "
                "running daemon; openclaw needs the gateway. See `mycelium adapter status`.[/dim]"
            )
            raise typer.Exit(1)
        console.print(f"[green]✓[/green] Created [bold]@{handle}[/bold] ({adapter})")

    # 3b. For openclaw, the gateway restart triggered by `agent create` is
    #     async — wait for it to come back and re-subscribe the room's SSE
    #     before seeding, or the wake-up mention is delivered to nobody.
    if adapter == "openclaw":
        console.print("[dim]Waiting for the OpenClaw gateway to subscribe the room…[/dim]")
        _await_openclaw_ready()

    # 4. Seed: one message mentioning every agent + the task. The adapter wakes
    #    each agent, which then runs the Mycelium coordination protocol.
    mentions = " ".join(f"@{h}" for h in handles)
    seed = f"{mentions} {scenario['task']}"
    r = _run(["agent", "invoke", handles[0], seed, "--room", room, "-H", "demo"])
    if r.returncode != 0:
        console.print(f"[red]seeding failed:[/red]\n{r.stderr or r.stdout}")
        raise typer.Exit(1)
    console.print("[green]✓[/green] Seeded the room — agents are negotiating")


def _room_senders(api: str, room: str) -> set[str]:
    """The set of handles that have posted a message to ``room`` (lowercased)."""
    import httpx

    try:
        resp = httpx.get(f"{api}/api/rooms/{room}/messages", timeout=5.0)
        resp.raise_for_status()
    except httpx.HTTPError:
        return set()
    return {
        str(m["sender_handle"]).lower()
        for m in resp.json().get("messages", [])
        if m.get("sender_handle")
    }


def _drive_consensus(
    config: Any,
    room: str,
    handles: list[str],
    *,
    timeout: float = 180.0,
    settle: float = 15.0,
) -> None:
    """Wait for the agents to state positions, then summon the aligner.

    Cold-spawn turns land asynchronously (each is a live ``claude -p``), so poll
    the room until every agent has spoken — then let a short settle window catch
    their final positions — and post ``@aligner``. That summon is what the backend
    scores into a ``commit:converged``/``rejected`` verdict and, on convergence,
    compiles into ``plan/tasks.md`` + syncs as a ``knowledge`` memory. Driving it
    here makes the payoff deterministic instead of hoping an agent remembers to.
    """
    api = config.server.api_url.rstrip("/")
    want = {h.lower() for h in handles}
    console.print("[dim]Waiting for agents to state their positions…[/dim]")
    deadline = time.monotonic() + timeout
    seen: set[str] = set()
    while time.monotonic() < deadline:
        seen = _room_senders(api, room)
        if want <= seen:
            time.sleep(settle)  # let final-round positions land before scoring
            seen = _room_senders(api, room)
            break
        time.sleep(3.0)

    posted = sorted(want & seen)
    if posted:
        console.print(f"[green]✓[/green] Positions in from {', '.join('@' + h for h in posted)}")
    else:
        console.print(
            "[yellow]⚠ No agent positions yet[/yellow] — summoning the aligner anyway; "
            "it will report no convergence."
        )

    console.print(f"[dim]Summoning [cyan]@{ALIGNER_HANDLE}[/cyan] to assess convergence…[/dim]")
    r = _run(
        [
            "room",
            "send",
            f"@{ALIGNER_HANDLE} assess whether the team has converged and compile the plan.",
            "--room",
            room,
            "--handle",
            "demo",
        ]  # fmt: skip
    )
    if r.returncode != 0:
        console.print(f"[yellow]⚠ could not summon the aligner:[/yellow]\n{r.stderr or r.stdout}")
        return
    console.print(
        f"[green]✓[/green] Summoned [bold]@{ALIGNER_HANDLE}[/bold] — on convergence the backend "
        "compiles [cyan]plan/tasks.md[/cyan] and syncs it as a knowledge memory."
    )


def _print_intro(scenario: dict[str, Any], adapter: str, room: str) -> None:
    body = (
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
    cold = adapter in _COLD_SPAWN_ADAPTERS
    cwd_flag = " --cwd <dir>" if cold else ""
    repro = "\n".join(
        [
            f"mycelium room create {room}",
            # Cold-spawn agents wake only through a daemon subscribed to the room.
            *([f"mycelium daemon subscribe {room}"] if cold else []),
            *[
                f'mycelium agent create {h} --adapter {adapter} --room {room}{cwd_flag} -d "<persona>"'
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
    auth_from: str | None = typer.Option(
        None,
        "--auth-from",
        help=(
            "openclaw: copy model credentials from this existing agent into the demo "
            "agents (else auto-discovered). Fresh agents have no token and would hang."
        ),
    ),
    room: str | None = typer.Option(None, "--room", help="Override the room name."),
    no_watch: bool = typer.Option(
        False, "--no-watch", help="Provision and seed, but don't stream the room afterward."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
    list_flag: bool = typer.Option(False, "--list", help="List available scenarios and exit."),
) -> None:
    """Run a real sample coordination: personas → agents → seeded room → live negotiation.

    Scenarios and personas are discovered from the public agent-personas dataset.
    Requires an installed adapter, the backend up, and an LLM configured:

        mycelium demo --adapter openclaw
    """
    if ctx.invoked_subcommand is not None:
        return

    if list_flag:
        try:
            ids = _list_scenarios()
        except Exception as e:
            console.print(f"[red]Could not reach agent-personas:[/red] {e}")
            raise typer.Exit(1)
        table = Table(title="mycelium demo scenarios", show_edge=False, pad_edge=False)
        table.add_column("id", style="bold cyan")
        table.add_column("about", style="dim")
        for sid in ids:
            marker = "  (default)" if sid == DEFAULT_SCENARIO else ""
            table.add_row(sid + marker, _pretty_topic(sid))
        console.print(table)
        console.print("[dim]Source: github.com/mycelium-io/agent-personas[/dim]")
        return

    if not adapter:
        console.print(
            "[red]--adapter is required.[/red] The demo runs real agents, so pick one:\n"
            "  mycelium demo --adapter openclaw\n"
            f"[dim]Known adapters: {', '.join(_KNOWN_ADAPTERS)}[/dim]"
        )
        raise typer.Exit(1)

    adapter = adapter.replace("-", "_")
    if adapter not in _KNOWN_ADAPTERS:
        console.print(
            f"[red]Unknown adapter '{adapter}'.[/red] One of: {', '.join(_KNOWN_ADAPTERS)}."
        )
        raise typer.Exit(1)

    chosen = _resolve_scenario(scenario or DEFAULT_SCENARIO)
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

    _provision(chosen, adapter, model, room_name, auth_from)

    # The payoff: once positions are in, summon the aligner so the negotiation
    # actually converges → compiles plan/tasks.md → syncs a knowledge memory.
    handles = [a["handle"] for a in chosen["agents"]]
    _drive_consensus(_config, room_name, handles)

    _print_outro(chosen, adapter, room_name)

    if not no_watch:
        console.print("\n[dim]Streaming the room (Ctrl-C to stop)…[/dim]\n")
        try:
            _run(["watch", room_name], capture=False)
        except KeyboardInterrupt:
            console.print("\n[dim]Stopped watching. The room keeps running.[/dim]")
