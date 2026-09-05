# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium onboard``: a guided first run, on a real hub, with your own coding agents.

The tour a new user would otherwise assemble by hand from six doc pages: point
the CLI at a hub, sign in if the hub asks, pick a scenario, put a task on the
board, hand two of your coding agents a briefing each, watch the aligner mediate
them to an agreement, and file the follow-up work. Every step runs the real
command and prints it first, so what the user watches is what they will type
next time.

Nothing is canned. The agents are the user's own sessions (Claude Code, Cursor,
anything with a shell): the wizard writes each one a briefing and either types
it into a herdr pane or hands it over on the clipboard, then waits for them to
turn up in the room. The scenarios (``mycelium.scenarios``) are ordinary
disagreements on a software team, written in plain language.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn
from urllib.parse import urlsplit

import httpx
import typer
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule

from mycelium.client import hub_client, probe_health
from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref
from mycelium.scenarios import (
    ALIGNER_HANDLE,
    DEFAULT_SCENARIO,
    SCENARIOS,
    DemoAgent,
    Scenario,
    briefing,
    kickoff_text,
)

console = Console()

LOCAL_HUB = "http://localhost:8000"
HERDR_URL = "https://herdr.dev"
INSTALL_URL = "https://mycelium-io.github.io/mycelium/install.sh"

#: Steps in the tour, in order, as the header names them.
STEPS = (
    "Point at a hub",
    "Sign in",
    "Pick a scenario",
    "Set up the room",
    "Bring in your coding agents",
    "Let the aligner mediate",
    "Work the board",
)

#: How often the wait loops ask the hub, and how long they wait before the
#: verdict is given up on. Agents reason at their own pace; these are generous.
POLL_S = 3.0
VERDICT_TIMEOUT_S = 20 * 60
COMPILE_TIMEOUT_S = 90

_HANDLE_STRIP = re.compile(r"[^a-z0-9._-]+")


# ── plumbing ─────────────────────────────────────────────────────────────────


def _cli_prefix() -> list[str]:
    """How to invoke the mycelium CLI as a subprocess (installed script or module)."""
    exe = shutil.which("mycelium")
    if exe:
        return [exe]
    return [sys.executable, "-m", "mycelium.cli"]


def _shell_quote(arg: str) -> str:
    return f'"{arg}"' if (" " in arg or not arg) else arg


def _run(args: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    """Run ``mycelium <args>``, printing the command first so the tour teaches it."""
    console.print(f"[dim]$[/dim] [bold]mycelium {' '.join(_shell_quote(a) for a in args)}[/bold]")
    return subprocess.run(  # noqa: S603 - args are code-built, never shell-interpolated
        _cli_prefix() + args, capture_output=capture, text=True, check=False
    )


def _interactive(yes: bool) -> bool:
    return not yes and sys.stdin.isatty() and sys.stdout.isatty()


def _pause(yes: bool, note: str = "Press Enter to continue") -> None:
    if not _interactive(yes):
        return
    try:
        console.input(f"[dim]{note}…[/dim] ")
    except (EOFError, KeyboardInterrupt):
        raise typer.Exit(0) from None


def _step(n: int, title: str | None = None) -> None:
    console.print()
    console.print(Rule(f"[bold]Step {n} of {len(STEPS)} · {title or STEPS[n - 1]}[/bold]"))
    console.print()


def _fail(message: str, *fixes: str) -> NoReturn:
    console.print(f"[red]✗[/red] {message}")
    for fix in fixes:
        console.print(f"  [dim]{fix}[/dim]")
    raise typer.Exit(1)


def _select(question: str, choices: list[str], *, default: str | None = None) -> str | None:
    import questionary

    return questionary.select(question, choices=choices, default=default).ask()


def _confirm(question: str, *, default: bool = True) -> bool:
    import questionary

    answer = questionary.confirm(question, default=default).ask()
    return bool(answer) if answer is not None else False


def _text(question: str, *, default: str = "") -> str:
    import questionary

    answer = questionary.text(question, default=default).ask()
    return (answer or "").strip()


# ── the hub ──────────────────────────────────────────────────────────────────


def normalize_hub(raw: str) -> str:
    """A hub address as people paste it, made into the origin the CLI calls.

    A bare host gets ``http://``; a trailing slash goes; a trailing ``/api`` goes
    too, because the CLI adds that prefix itself and a copied API path would
    otherwise turn every call into ``/api/api/…``.
    """
    url = raw.strip()
    if not url:
        return url
    if "://" not in url:
        url = f"http://{url}"
    url = url.rstrip("/")
    if url.endswith("/api"):
        url = url[: -len("/api")]
    return url


def is_local_hub(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1", "0.0.0.0")  # noqa: S104 - a listen address


def ui_url(config: MyceliumConfig, room: str) -> str:
    """Where the room is in a browser: the local UI port, or the hub's own origin."""
    api = config.server.api_url
    if is_local_hub(api):
        return f"http://localhost:{config.runtime.frontend_port}/room/{room}"
    parts = urlsplit(api)
    return f"{parts.scheme}://{parts.netloc}/room/{room}"


def _stack_installed() -> bool:
    return (Path.home() / ".mycelium" / ".env").exists()


def _wait_for_hub(url: str, timeout_s: float = 120.0) -> dict[str, Any] | None:
    deadline = time.monotonic() + timeout_s
    with console.status(f"[dim]waiting for {url}…[/dim]"):
        while time.monotonic() < deadline:
            body, _ = probe_health(url)
            if body is not None:
                return body
            time.sleep(POLL_S)
    return None


def _choose_hub(config: MyceliumConfig, hub_flag: str | None, yes: bool) -> str:
    current = config.server.api_url
    if hub_flag:
        return normalize_hub(hub_flag)
    if not _interactive(yes):
        return current

    local = f"This machine ({LOCAL_HUB}): run the stack here with Docker"
    hosted = "A hosted hub: I have its address (e.g. https://mycelium.outshift.io)"
    keep = f"Keep the current one: {current}"
    choices = [local, hosted]
    if not is_local_hub(current):
        choices.insert(0, keep)
    picked = _select("Which hub should this machine talk to?", choices)
    if picked is None:
        raise typer.Exit(0)
    if picked == local:
        return LOCAL_HUB
    if picked == keep:
        return current
    while True:
        url = normalize_hub(_text("Hub address:"))
        if url:
            return url


def _bring_up_local(yes: bool) -> None:
    """Get a local stack answering, with the user's say-so: ``up`` or ``install``."""
    if _stack_installed():
        console.print("[dim]Mycelium is installed here but the stack isn't answering.[/dim]")
        if _interactive(yes) and not _confirm("Start it now with `mycelium up`?"):
            _fail("The hub has to be running.", "Start it with: mycelium up")
        _run(["up"])
        return
    console.print(
        "[dim]Nothing is installed on this machine yet. `mycelium install` brings up the "
        "stack with Docker: the messaging node, the backend and the UI. It asks which LLM "
        "the aligner should use.[/dim]"
    )
    if _interactive(yes) and not _confirm("Run `mycelium install` now?"):
        _fail(
            "The tour needs a hub.",
            "Install one here: mycelium install",
            "Or re-run with --hub <url>",
        )
    _run(["install"])


def _point_at_hub(config: MyceliumConfig, hub_flag: str | None, yes: bool) -> dict[str, Any]:
    """Step 1: a hub that answers, saved as this machine's ``server.api_url``."""
    console.print(
        "Mycelium runs on a hub your team connects to. It can be this machine, or one\n"
        "someone already runs for you."
    )
    console.print()
    url = _choose_hub(config, hub_flag, yes)
    body, why = probe_health(url)
    if body is None:
        if not is_local_hub(url):
            _fail(
                f"No hub answered at {url} ({why}).",
                "Check the address, and that the hub is up.",
                "Behind a proxy the hub answers under /api; the CLI tries both.",
            )
        _bring_up_local(yes)
        body = _wait_for_hub(url)
        if body is None:
            _fail(f"The stack came up but {url} still isn't answering.", "Try: mycelium status")

    if config.server.api_url != url:
        config.server.api_url = url
        config.save()
        console.print(f"[dim]$[/dim] [bold]mycelium config set server.api_url {url}[/bold]")
    version = body.get("version") or ""
    gate = "sign-in required" if (body.get("auth") or {}).get("enabled") else "open, no sign-in"
    console.print(
        f"[green]✓[/green] Hub: [cyan]{url}[/cyan]"
        + (f" [dim](v{version})[/dim]" if version else "")
        + f" [dim]· {gate}[/dim]"
    )
    return body


# ── identity ─────────────────────────────────────────────────────────────────


def _whoami(config: MyceliumConfig) -> dict[str, Any] | None:
    """The hub's own answer for who this machine is, fresh, or None if it can't say."""
    from mycelium import identity

    identity._WHOAMI_CACHE.pop(config.server.api_url, None)
    return identity._hub_whoami(config)


def default_handle() -> str:
    """A handle to offer: the login name, made legal, or ``me``."""
    raw = (os.environ.get("USER") or os.environ.get("USERNAME") or "").lower()
    slug = _HANDLE_STRIP.sub("-", raw).strip("-._")
    return slug or "me"


def _sign_in(config: MyceliumConfig, health: dict[str, Any], yes: bool) -> str:
    """Step 2: an identity the hub will attribute the tour's writes to."""
    from mycelium.commands.user import align_identity

    gated = bool((health.get("auth") or {}).get("enabled"))
    if gated:
        who = _whoami(config) or {}
        if not who.get("handle"):
            console.print("This hub asks people to sign in. Your browser will open.")
            console.print(
                "[dim]On a machine with no browser, run `mycelium login --device` yourself.[/dim]"
            )
            _pause(yes)
            _run(["login"])
            who = _whoami(config) or {}
        handle = str(who.get("handle") or "").strip()
        if not handle:
            _fail("Signed in, but the hub didn't say who you are.", "Try: mycelium whoami")
        # The hub's answer is the one a gated hub enforces, so it is the one this
        # machine writes as; a token claim decoded locally can disagree with it.
        if (config.identity.name or "").strip().lstrip("@").lower() != handle.lower():
            config.identity.name = handle
            config.save()
        console.print(f"[green]✓[/green] Signed in as [cyan]@{handle}[/cyan]")
        return handle

    handle = (config.identity.name or "").strip().lstrip("@")
    if not handle:
        console.print(
            "This hub is open, so there is no sign-in. Pick a name the room knows you by."
        )
        suggested = default_handle()
        handle = _text("Your handle:", default=suggested) if _interactive(yes) else suggested
        handle = handle.lstrip("@") or suggested
        console.print(f"[dim]$[/dim] [bold]mycelium iam {handle}[/bold]")
        try:
            _manifest, registered = align_identity(handle, config=config)
        except Exception as exc:  # noqa: BLE001 - a bad handle is the user's to fix
            _fail(f"'{handle}' isn't a usable handle ({exc}).", "Lowercase letters, digits, - . _")
        if not registered:
            console.print("[yellow]![/yellow] The hub didn't take the user record; carrying on.")
    console.print(
        f"[green]✓[/green] You are [cyan]@{handle}[/cyan] "
        "[dim]· this machine's identity; change it with mycelium iam <handle>[/dim]"
    )
    return handle


# ── the scenario ─────────────────────────────────────────────────────────────


def _pick_scenario(scenario_flag: str | None, yes: bool) -> Scenario:
    if scenario_flag:
        if scenario_flag not in SCENARIOS:
            _fail(
                f"Unknown scenario '{scenario_flag}'.",
                "See the list with: mycelium onboard --list",
            )
        return SCENARIOS[scenario_flag]
    if not _interactive(yes):
        return SCENARIOS[DEFAULT_SCENARIO]
    labels = {f"{s.title}  —  {s.blurb}": s for s in SCENARIOS.values()}
    picked = _select("Which disagreement should the agents settle?", list(labels))
    if picked is None:
        raise typer.Exit(0)
    return labels[picked]


def _print_scenario(scenario: Scenario, room: str) -> None:
    lines = [f"[bold]{scenario.title}[/bold]", "", f"The task on the board: {scenario.task}", ""]
    lines.extend(f"  [cyan]@{a.handle}[/cyan]  {a.label}" for a in scenario.agents)
    lines.extend(["", f"What the aligner is asked to settle: {scenario.question}."])
    console.print(
        Panel("\n".join(lines), title=f"[dim]room[/dim] [cyan]{room}[/cyan]", border_style="cyan")
    )


def _list_scenarios() -> None:
    from rich.table import Table

    table = Table(title="mycelium onboard scenarios", show_edge=False, pad_edge=False)
    table.add_column("id", style="bold cyan")
    table.add_column("title")
    table.add_column("who", style="dim")
    for sid, s in SCENARIOS.items():
        marker = " (default)" if sid == DEFAULT_SCENARIO else ""
        table.add_row(sid + marker, s.title, " vs ".join(f"@{a.handle}" for a in s.agents))
    console.print(table)


# ── the room ─────────────────────────────────────────────────────────────────


def _agent_workdir(room: str, handle: str) -> Path:
    """A stable per-agent directory, so a coding agent has somewhere to sit."""
    d = MyceliumConfig.get_global_config_dir() / "onboard" / room / handle
    d.mkdir(parents=True, exist_ok=True)
    return d


def _state_path(room: str) -> Path:
    return MyceliumConfig.get_global_config_dir() / "onboard" / room / "state.json"


def _save_state(room: str, state: dict[str, Any]) -> None:
    path = _state_path(room)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n")


def _load_state(room: str) -> dict[str, Any] | None:
    try:
        return json.loads(_state_path(room).read_text())
    except (OSError, ValueError):
        return None


def _create_task(config: MyceliumConfig, room: str, title: str, me: str) -> tuple[str, str]:
    """Put the scenario's task on the board; return its row key and thread URN."""
    from mycelium.board.model import EPISODE_FIELD

    console.print(f'[dim]$[/dim] [bold]mycelium board new "{title}" --room {room}[/bold]')
    try:
        with hub_client(config, timeout=30) as client:
            resp = client.post(f"/api/rooms/{room}/tasks", json={"title": title, "handle": me})
    except httpx.HTTPError as exc:
        _fail(f"Couldn't reach the hub to create the task: {exc}")
    if resp.status_code >= 400:
        _fail(f"The hub refused the task: {resp.text}")
    task = resp.json()
    key = str(task.get("key") or "")
    thread = str(task.get(EPISODE_FIELD) or "")
    if not key or not thread:
        _fail("The hub created the task without a thread; is the backend current?")
    console.print(
        f"[green]✓[/green] [bold]{key}[/bold] [dim]· thread {thread.rsplit(':', 1)[-1]}[/dim]"
    )
    return key, thread


def _set_up_room(config: MyceliumConfig, scenario: Scenario, room: str, me: str) -> tuple[str, str]:
    """Step 4: the room, the aligner, the two agents, and the task, in that order."""
    console.print(
        "A room is where a team's work lives: a board of tasks, a thread inside each task,\n"
        "and shared memory. This creates one and registers the mediator and two agents."
    )
    console.print()
    r = _run(["room", "create", room], capture=True)
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0 and "already exists" not in out.lower():
        _fail(f"Couldn't create the room:\n{out.strip()}")
    console.print(
        f"[green]✓[/green] Room [cyan]{room}[/cyan]"
        + (" [dim](already there; reusing it)[/dim]" if "already exists" in out.lower() else "")
    )
    r = _run(["room", "use", room], capture=True)
    if r.returncode != 0:
        _fail(f"Couldn't switch to the room:\n{(r.stdout or '') + (r.stderr or '')}")

    r = _run(
        ["engine", "create", ALIGNER_HANDLE, "--kind", "aligner", "--room", room], capture=True
    )
    if r.returncode != 0:
        _fail(f"Couldn't register the aligner:\n{(r.stdout or '') + (r.stderr or '')}")
    console.print(
        f"[green]✓[/green] [cyan]@{ALIGNER_HANDLE}[/cyan] registered [dim]· the mediator, "
        "dormant until summoned[/dim]"
    )

    for agent in scenario.agents:
        r = _run(
            [
                "agent",
                "create",
                agent.handle,
                "--adapter",
                "claude_code",
                "--room",
                room,
                "--description",
                f"{agent.label}. {agent.wants}",
                "--cwd",
                str(_agent_workdir(room, agent.handle)),
            ],  # fmt: skip
            capture=True,
        )
        if r.returncode != 0:
            _fail(f"Couldn't register @{agent.handle}:\n{(r.stdout or '') + (r.stderr or '')}")
        console.print(
            f"[green]✓[/green] [cyan]@{agent.handle}[/cyan] registered [dim]· {agent.label}[/dim]"
        )

    key, thread = _create_task(config, room, scenario.task, me)
    short = thread.rsplit(":", 1)[-1]
    r = _run(["board", "send", short, kickoff_text(scenario), "--room", room], capture=True)
    if r.returncode != 0:
        _fail(f"Couldn't post in the task's thread:\n{(r.stdout or '') + (r.stderr or '')}")
    console.print(f"[green]✓[/green] Opened the task's thread [dim]· board messages {short}[/dim]")
    return key, thread


# ── the agents ───────────────────────────────────────────────────────────────


def _copy_to_clipboard(text: str) -> bool:
    """Best effort: the first clipboard tool this machine has."""
    for cmd in (
        ["pbcopy"],
        ["wl-copy"],
        ["xclip", "-selection", "clipboard"],
        ["xsel", "--clipboard", "--input"],
        ["clip.exe"],
    ):
        if shutil.which(cmd[0]) is None:
            continue
        try:
            subprocess.run(cmd, input=text, text=True, check=True, capture_output=True)  # noqa: S603
        except (OSError, subprocess.CalledProcessError):
            continue
        return True
    return False


def _write_briefings(
    scenario: Scenario, room: str, key: str, hub_url: str, gated: bool
) -> dict[str, tuple[Path, str]]:
    out: dict[str, tuple[Path, str]] = {}
    for agent in scenario.agents:
        text = briefing(scenario, agent, room=room, row=key, hub_url=hub_url, gated=gated)
        path = _agent_workdir(room, agent.handle).parent / f"{agent.handle}.md"
        path.write_text(text)
        out[agent.handle] = (path, text)
    return out


def _herdr_panes() -> tuple[Any, list[dict[str, Any]]]:
    """The herdr bridge and its live agents, or ``(bridge, [])`` when it can't help."""
    from mycelium.integrations.herdr import HerdrBridge, HerdrError

    bridge = HerdrBridge()
    if not bridge.available():
        return bridge, []
    try:
        agents = [a for a in bridge.list_agents() if a.get("pane_id")]
    except HerdrError:
        agents = []
    return bridge, agents


def _hand_over_by_herdr(
    bridge: Any, panes: list[dict[str, Any]], room: str, agent: DemoAgent, text: str
) -> bool:
    """Type the briefing into a herdr pane the user picks; False to fall back to paste."""
    from mycelium.integrations.herdr import HerdrError, HerdrPaneMapping

    manual = "I'll paste it into a coding agent myself"
    labels: dict[str, dict[str, Any]] = {}
    for a in panes:
        title = a.get("terminal_title_stripped") or a.get("terminal_title") or ""
        label = f"{a['pane_id']}  {a.get('agent') or '?'}  {a.get('agent_status') or ''}  {title}".rstrip()
        labels[label] = a
    picked = _select(f"Which herdr pane should play @{agent.handle}?", [*labels, manual])
    if picked is None or picked == manual:
        return False
    pane = str(labels[picked]["pane_id"])
    bridge.registry.set(
        HerdrPaneMapping(
            room=room, handle=agent.handle, pane=pane, kind=labels[picked].get("agent")
        )
    )
    try:
        bridge.prompt(pane, text, wait=False)
    except HerdrError as exc:
        console.print(f"[yellow]![/yellow] herdr couldn't type into {pane}: {exc}")
        return False
    console.print(
        f"[green]✓[/green] Typed @{agent.handle}'s briefing into pane [cyan]{pane}[/cyan]"
    )
    return True


def _hand_over_by_paste(agent: DemoAgent, path: Path, text: str, n: int, yes: bool) -> None:
    where = f"coding agent {n}"
    if _interactive(yes) and _copy_to_clipboard(text):
        console.print(
            Panel(
                f"[bold]Copied to your clipboard:[/bold] the briefing for [cyan]@{agent.handle}[/cyan] "
                f"({agent.label}).\n\n"
                f"Open {where} (Claude Code, Cursor, anything with a shell), paste it, and let it run.\n"
                f"[dim]The same text is at {path}[/dim]",
                border_style="cyan",
            )
        )
        _pause(yes, f"Press Enter once {where} has it")
        return
    console.print(Rule(f"[bold]Paste this into {where} → @{agent.handle} ({agent.label})[/bold]"))
    console.print(text, markup=False, highlight=False)
    console.print(Rule())
    console.print(f"[dim]Also saved at {path}[/dim]")
    _pause(yes, f"Press Enter once {where} has it")


def _offer_herdr(
    bridge: Any, panes: list[dict[str, Any]], yes: bool
) -> tuple[Any, list[dict[str, Any]]]:
    """Say what herdr adds and offer it, then look again; never required.

    Three states, each with its own ask: not installed (open the site, come back),
    running with no agents (start two, come back), running with agents (nothing
    to ask). Each ask ends the same way: the user presses Enter and the wizard
    re-checks, so continuing without herdr is always one keypress.
    """
    if panes or not _interactive(yes):
        return bridge, panes
    if not bridge.binary_present():
        console.print(
            f"[bold]herdr[/bold] ({HERDR_URL}) is optional. It keeps coding agents open in named "
            "panes, so this wizard can type each briefing straight into one, and a mention to an "
            "agent that has stepped away wakes it later. Without it, you paste two prompts by hand."
        )
        if _confirm("Open herdr.dev to install it now?", default=False):
            import webbrowser

            webbrowser.open(HERDR_URL)
            _pause(
                yes,
                "Press Enter once herdr is running with two coding agents open, "
                "or to go on without it",
            )
            return _herdr_panes()
        return bridge, panes
    console.print(
        "[bold]herdr[/bold] is running but has no coding agents open. Start two in herdr panes and "
        "the wizard will type each briefing in; or go on and paste them by hand."
    )
    _pause(yes, "Press Enter once the agents are open, or to go on without them")
    return _herdr_panes()


def _bring_in_agents(
    config: MyceliumConfig, scenario: Scenario, room: str, key: str, gated: bool, yes: bool
) -> None:
    """Step 5: one briefing per agent, handed to a session the user runs."""
    console.print(
        "Mycelium doesn't run agents. Your coding agents are the agents: each one gets\n"
        "a short briefing that says who it plays and how to talk to the room."
    )
    console.print()
    briefings = _write_briefings(scenario, room, key, config.server.api_url, gated)

    bridge, panes = _offer_herdr(*_herdr_panes(), yes)
    if panes and _interactive(yes):
        console.print(
            f"[green]✓[/green] herdr is running with {len(panes)} coding agent(s) open; the wizard "
            "can type each briefing straight into a pane."
        )
    console.print()

    for n, agent in enumerate(scenario.agents, start=1):
        path, text = briefings[agent.handle]
        if panes and _interactive(yes) and _hand_over_by_herdr(bridge, panes, room, agent, text):
            continue
        _hand_over_by_paste(agent, path, text, n, yes)


def _thread_senders(
    config: MyceliumConfig, room: str, thread: str, since: datetime | None = None
) -> set[str]:
    """Who has spoken in the thread, plus anyone who spoke in the room since ``since``.

    The briefing says to post into the task's thread, and the aligner reads
    positions off the whole transcript regardless, so an agent that posted
    room-wide instead has still stated one and should not be waited on forever.
    """
    senders: set[str] = set()
    queries: list[dict[str, Any]] = [{"episode": thread, "limit": 100}]
    if since is not None:
        queries.append({"since": since.isoformat(), "limit": 200})
    for params in queries:
        try:
            with hub_client(config, timeout=10) as client:
                resp = client.get(f"/api/rooms/{room}/messages", params=params)
            resp.raise_for_status()
            messages = resp.json().get("messages", [])
        except (httpx.HTTPError, ValueError):
            continue
        senders |= {
            str(m.get("sender_handle") or "").lstrip("@").lower()
            for m in messages
            if m.get("message_type") in ("broadcast", "direct", "announce")
        }
    return senders


def _present(config: MyceliumConfig, room: str) -> set[str]:
    try:
        with hub_client(config, timeout=10) as client:
            resp = client.get(f"/api/rooms/{room}/sessions/members")
        resp.raise_for_status()
    except (httpx.HTTPError, ValueError):
        return set()
    return {str(m.get("handle") or "").lstrip("@").lower() for m in resp.json().get("members", [])}


def _wait_for_agents(
    config: MyceliumConfig,
    room: str,
    thread: str,
    handles: list[str],
    since: datetime | None = None,
) -> None:
    """Block until every agent has stated a position and is present to be addressed.

    Both matter: the aligner reads positions off the transcript and addresses
    whoever is present, so an agent that posted and left would be argued about
    but never argued with.
    """
    want = [h.lower() for h in handles]
    spoke: set[str] = set()
    last_hint = time.monotonic()
    with console.status("[dim]waiting for the agents…[/dim]") as status:
        while True:
            for h in want:
                if h not in spoke and h in _thread_senders(config, room, thread, since):
                    spoke.add(h)
                    console.print(f"[green]✓[/green] [cyan]@{h}[/cyan] stated a position")
            here = _present(config, room)
            if all(h in spoke and h in here for h in want):
                return
            waiting = [h for h in want if h not in spoke]
            away = [h for h in want if h in spoke and h not in here]
            parts = []
            if waiting:
                parts.append("a position from " + ", ".join(f"@{h}" for h in waiting))
            if away:
                parts.append(", ".join(f"@{h}" for h in away) + " to run `mycelium await`")
            status.update(f"[dim]waiting for {' and '.join(parts)}…[/dim]")
            if time.monotonic() - last_hint > 90:
                last_hint = time.monotonic()
                console.print(
                    "[dim]Still waiting. Each agent should have posted with `mycelium respond` "
                    "and be sitting in `mycelium await`. Ctrl-C stops the tour.[/dim]"
                )
            time.sleep(POLL_S)


# ── the aligner ──────────────────────────────────────────────────────────────


def parse_verdict(message: dict[str, Any]) -> dict[str, Any] | None:
    """The outcome inside an ``l9_commit`` message, or None for anything else.

    A commit is the aligner's terminal statement: ``converged`` carries the
    agreed ``issue = value`` map, ``rejected`` says the mechanism ran out.
    """
    if message.get("message_type") != "l9_commit":
        return None
    try:
        record = json.loads(message.get("content") or "{}")
    except ValueError:
        return None
    header = (record.get("l9") or {}).get("header") or {}
    payload = (record.get("l9") or {}).get("payload") or {}
    data = payload.get("data")
    assignments = data.get("assignments") if isinstance(data, dict) else None
    text = record.get("content") if isinstance(record.get("content"), str) else ""
    return {
        "converged": header.get("subkind") == "converged",
        "assignments": assignments if isinstance(assignments, dict) else {},
        "text": text,
        "sender": message.get("sender_handle") or ALIGNER_HANDLE,
    }


def _messages_since(config: MyceliumConfig, room: str, since: datetime) -> list[dict[str, Any]]:
    try:
        with hub_client(config, timeout=10) as client:
            resp = client.get(
                f"/api/rooms/{room}/messages", params={"since": since.isoformat(), "limit": 200}
            )
        resp.raise_for_status()
    except (httpx.HTTPError, ValueError):
        return []
    msgs = resp.json().get("messages", [])
    return sorted(msgs, key=lambda m: str(m.get("created_at") or ""))


def _tail_until_verdict(
    config: MyceliumConfig, room: str, since: datetime, handles: list[str]
) -> dict[str, Any] | None:
    """Print the negotiation as it happens; return the verdict, or None on timeout."""
    seen: set[str] = set()
    deadline = time.monotonic() + VERDICT_TIMEOUT_S
    with console.status("[dim]the aligner is reading the positions…[/dim]") as status:
        while time.monotonic() < deadline:
            for m in _messages_since(config, room, since):
                mid = str(m.get("id") or m.get("message_id") or "")
                if mid in seen:
                    continue
                seen.add(mid)
                verdict = parse_verdict(m)
                if verdict is not None:
                    return verdict
                if m.get("message_type") not in ("broadcast", "direct", "announce"):
                    continue
                sender = str(m.get("sender_handle") or "?").lstrip("@")
                text = str(m.get("content") or "").strip().replace("\n", " ")
                if len(text) > 400:
                    text = text[:400] + "…"
                color = "magenta" if sender.lower() == ALIGNER_HANDLE else "yellow"
                console.print(f"  [{color}]{sender}[/{color}]: {text}")
                if sender.lower() == ALIGNER_HANDLE:
                    status.update("[dim]waiting for the agent it addressed…[/dim]")
                elif sender.lower() in {h.lower() for h in handles}:
                    status.update("[dim]the aligner is weighing that reply…[/dim]")
            time.sleep(POLL_S)
    return None


def _work_rows(config: MyceliumConfig, room: str) -> set[str]:
    from mycelium.commands.board import _fetch

    try:
        _name, items, _health = _fetch(room)
    except Exception:  # noqa: BLE001 - a board read failing is not the tour failing
        return set()
    return {i.id for i in items if i.id.startswith("memory:work/")}


def _mediate(
    config: MyceliumConfig, scenario: Scenario, room: str, thread: str, yes: bool
) -> dict[str, Any] | None:
    """Step 6: summon the aligner on the task and watch it work."""
    console.print(
        "The aligner is a mediator the room owns. Summoned on a task, it reads both\n"
        "positions, works out what is actually in dispute, and addresses one agent at a\n"
        "time with the offer on the table until they agree or clearly won't."
    )
    console.print()
    _pause(yes, "Press Enter to summon it")
    short = thread.rsplit(":", 1)[-1]
    before = _work_rows(config, room)
    started = datetime.now(UTC)
    r = _run(
        ["board", "coordinate", short, ALIGNER_HANDLE, scenario.question, "--room", room],
        capture=True,
    )
    if r.returncode != 0:
        _fail(f"Couldn't summon the aligner:\n{(r.stdout or '') + (r.stderr or '')}")
    console.print()
    verdict = _tail_until_verdict(config, room, started, scenario.handles)
    console.print()
    if verdict is None:
        console.print(
            f"[yellow]![/yellow] No verdict after {VERDICT_TIMEOUT_S // 60} minutes. "
            f"Keep an eye on it with: mycelium watch {room}"
        )
        return None
    if verdict["converged"]:
        terms = "\n".join(f"  {issue}: {value}" for issue, value in verdict["assignments"].items())
        console.print(
            Panel(
                "[bold green]Agreement[/bold green]\n\n" + (terms or verdict["text"]),
                border_style="green",
            )
        )
        with console.status("[dim]compiling the agreement into tasks on the board…[/dim]"):
            deadline = time.monotonic() + COMPILE_TIMEOUT_S
            while time.monotonic() < deadline and _work_rows(config, room) <= before:
                time.sleep(POLL_S)
        console.print("The agreement became work on the board, one row per task:")
    else:
        console.print(
            Panel(
                "[bold yellow]No agreement[/bold yellow]\n\n"
                + (verdict["text"] or "The agents didn't converge. That is a clean outcome too."),
                border_style="yellow",
            )
        )
    console.print()
    _run(["board", "--room", room, "--filter", "all"])
    return verdict


# ── the board ────────────────────────────────────────────────────────────────


def _work_the_board(
    config: MyceliumConfig, scenario: Scenario, room: str, key: str, yes: bool
) -> None:
    """Step 7: file follow-up work by hand and hand one piece to an agent."""
    if not scenario.followups:
        return
    console.print(
        "Work doesn't have to come out of a negotiation. Anyone can put a task on the\n"
        "board, nest it under another, and hand it to someone."
    )
    console.print()
    _pause(yes)
    first_row: str | None = None
    for title, assignee in scenario.followups:
        r = _run(
            ["board", "new", title, "--parent", key, "--assign", f"@{assignee}", "--room", room],
            capture=True,
        )
        out = (r.stdout or "").strip()
        if r.returncode != 0:
            console.print(f"[yellow]![/yellow] {out or (r.stderr or '').strip()}")
            continue
        console.print(out)
        if first_row is None:
            first_row = _row_key_from(out) or f"work/{slugify(title)}"
    if first_row is None:
        return
    assignee = scenario.followups[0][1]
    r = _run(
        [
            "board",
            "send",
            first_row,
            f"@{assignee} this one is yours when you have a moment. Claim it and say how you'd start.",
            "--room",
            room,
        ],
        capture=True,
    )
    if r.returncode != 0:
        console.print(f"[yellow]![/yellow] {(r.stdout or '') + (r.stderr or '')}")
        return
    console.print(f"[green]✓[/green] Pinged [cyan]@{assignee}[/cyan] in the task's thread")
    with console.status(f"[dim]giving @{assignee} a minute to pick it up…[/dim]"):
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if _claimed(config, room, first_row, assignee):
                break
            time.sleep(POLL_S)
    console.print()
    _run(["board", "--room", room, "--filter", "all"])
    console.print()
    _run(["board", "messages", first_row, "--room", room])


def _claimed(config: MyceliumConfig, room: str, key: str, handle: str) -> bool:
    from mycelium.commands.board import _row

    try:
        item = _row(room, key)
    except Exception:  # noqa: BLE001 - a read blip just means "not yet"
        return False
    if item is None:
        return False
    return (item.owner or "").lstrip("@").lower() == handle.lower()


_ROW_KEY = re.compile(r"\b(work/[a-z0-9-]+)\b")


def _row_key_from(text: str) -> str | None:
    m = _ROW_KEY.search(text)
    return m.group(1) if m else None


def slugify(title: str) -> str:
    """The hub's rule for a task key, mirrored so a row can be named before it is read back."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")[:48].strip("-")
    return slug or "task"


# ── the wrap-up ──────────────────────────────────────────────────────────────


def _welcome() -> None:
    console.print(
        Panel(
            "[bold]Welcome to Mycelium[/bold]\n\n"
            "A shared board and chat where people and coding agents coordinate work: rooms,\n"
            "tasks with a thread inside each one, shared memory, and a mediator you can\n"
            "summon when two agents disagree.\n\n"
            "This tour takes about ten minutes. It points this machine at a hub, signs you\n"
            "in, puts a task on a board, hands two of your coding agents a briefing each,\n"
            "lets the mediator get them to an agreement, and files the follow-up work.\n"
            "Every step prints the command it runs. Ctrl-C leaves at any point.",
            border_style="cyan",
        )
    )


def _done(
    config: MyceliumConfig,
    scenario: Scenario,
    room: str,
    thread: str,
    verdict: dict[str, Any] | None,
) -> None:
    console.print()
    console.print(Rule("[bold]That's the tour[/bold]"))
    console.print()
    outcome = (
        "the agents reached an agreement and it became tasks"
        if verdict and verdict["converged"]
        else "the agents didn't converge, which the room records honestly"
        if verdict
        else "the negotiation is still running"
    )
    console.print(f"In [cyan]{room}[/cyan], {outcome}.")
    console.print()
    console.print(f"[bold]Open it in the browser:[/bold] {ui_url(config, room)}")
    console.print()
    console.print("[bold]Keep going from here:[/bold]")
    # The thread's short id rather than the row key: it is what a ping names and
    # what the reader has been typing all tour, and it keeps these lines short
    # enough that the notes line up in a normal terminal.
    rows = (
        (f"mycelium board --room {room}", "the board"),
        (f"mycelium board messages {thread.rsplit(':', 1)[-1]} --room {room}", "the task's thread"),
        (f"mycelium watch {room}", "the room's timeline, live"),
        (f"mycelium memory ls --room {room}", "what the room remembers"),
        (f'mycelium board new "…" --room {room}', "put your own task on it"),
    )
    width = max(len(cmd) for cmd, _ in rows)
    for cmd, note in rows:
        console.print(f"  {cmd:<{width}}   [dim]{note}[/dim]")
    console.print()
    console.print(f"[dim]The agents' briefings are under {_state_path(room).parent}.[/dim]")
    console.print(
        f"[dim]Start over: mycelium room delete {room} --force, then mycelium onboard.[/dim]"
    )


def _reprint_briefings(
    config: MyceliumConfig, scenario_flag: str | None, room_flag: str | None
) -> None:
    scenario = SCENARIOS.get(scenario_flag or DEFAULT_SCENARIO)
    if scenario is None:
        _fail(f"Unknown scenario '{scenario_flag}'.", "See the list with: mycelium onboard --list")
    room = room_flag or scenario.room
    state = _load_state(room)
    if state is None:
        _fail(
            f"No onboarding state for room '{room}' on this machine.",
            "Run the tour first: mycelium onboard",
        )
    briefings = _write_briefings(
        scenario, room, state["row"], config.server.api_url, bool(state.get("gated"))
    )
    for n, agent in enumerate(scenario.agents, start=1):
        path, text = briefings[agent.handle]
        console.print(Rule(f"[bold]coding agent {n} → @{agent.handle} ({agent.label})[/bold]"))
        console.print(text, markup=False, highlight=False)
        console.print(f"[dim]saved at {path}[/dim]\n")


# ── the command ──────────────────────────────────────────────────────────────


@doc_ref(
    usage="mycelium onboard [--hub <url>] [--scenario <id>] [--room <name>] [--yes] [--list] [--briefings]",
    desc=(
        "Guided first run: point at a hub, sign in, put a task on a board, brief two of "
        "your coding agents, watch the aligner mediate them, and work the board."
    ),
    group="setup",
)
def onboard(
    ctx: typer.Context,
    hub: str | None = typer.Option(None, "--hub", help="Hub address to use (skips the question)."),
    scenario: str | None = typer.Option(None, "--scenario", "-s", help="Scenario id; see --list."),
    room: str | None = typer.Option(None, "--room", help="Room name (default: demo-<scenario>)."),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="No questions, no pauses; take the defaults."
    ),
    list_flag: bool = typer.Option(False, "--list", help="List the scenarios and exit."),
    briefings_flag: bool = typer.Option(
        False,
        "--briefings",
        help="Print the agents' briefings for a room set up earlier, and exit.",
    ),
) -> None:
    """Walk through Mycelium end to end, on a real hub, with your own coding agents.

    Examples:
        mycelium onboard
        mycelium onboard --hub https://mycelium.outshift.io
        mycelium onboard --scenario database-choice --yes
        mycelium onboard --briefings        # lost the prompts? print them again
    """
    if list_flag:
        _list_scenarios()
        return

    try:
        config = MyceliumConfig.load()
    except Exception:  # noqa: BLE001 - a fresh machine has no config yet, which is fine
        config = MyceliumConfig()

    if briefings_flag:
        _reprint_briefings(config, scenario, room)
        return

    try:
        _welcome()
        _pause(yes)

        _step(1)
        health = _point_at_hub(config, hub, yes)
        gated = bool((health.get("auth") or {}).get("enabled"))

        _step(2)
        me = _sign_in(config, health, yes)

        _step(3)
        chosen = _pick_scenario(scenario, yes)
        room_name = room or chosen.room
        _print_scenario(chosen, room_name)
        _pause(yes)

        _step(4)
        key, thread = _set_up_room(config, chosen, room_name, me)
        _save_state(
            room_name, {"scenario": chosen.id, "row": key, "thread": thread, "gated": gated}
        )
        _pause(yes)

        _step(5)
        briefed_at = datetime.now(UTC)
        _bring_in_agents(config, chosen, room_name, key, gated, yes)
        console.print()
        _wait_for_agents(config, room_name, thread, chosen.handles, briefed_at)
        console.print(
            "[green]✓[/green] Both agents are in the room and have stated their positions"
        )
        console.print()
        _run(["board", "messages", key, "--room", room_name])

        _step(6)
        verdict = _mediate(config, chosen, room_name, thread, yes)

        _step(7)
        _work_the_board(config, chosen, room_name, key, yes)

        _done(config, chosen, room_name, thread, verdict)
    except KeyboardInterrupt:
        console.print(
            "\n[dim]Stopped. The room keeps whatever was set up; re-run mycelium onboard any time.[/dim]"
        )
        raise typer.Exit(130) from None
    except typer.Exit:
        raise
    except Exception as exc:
        from mycelium.error_handler import print_error

        print_error(exc, verbose=bool(ctx.obj and ctx.obj.get("verbose")))
        raise typer.Exit(1) from None
