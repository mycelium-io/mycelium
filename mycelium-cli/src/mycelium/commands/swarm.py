# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium swarm``: put a team of agents on one task and watch them work it.

One argument, the task. Everything else is a default:

- a room named after the task, created if it is not there;
- three members, ``agent-1`` to ``agent-3``;
- the task filed on the board, with its thread;
- a **kickoff** in that thread, run by the conductor's ``swarm`` flow: each
  member checks in, in turn, then ``agent-1`` splits the work into child tasks,
  one per member;
- from there the members work their rows, ask each other for review, and
  ``agent-1`` puts the result together when the last part is done.

Where the members live is the one choice. By default they are your own CLI
agents (Claude Code, Codex, Pi), started side by side in a new herdr workspace,
each already set up as its own handle in the room. With ``--server`` they are
workers the hub plays, so nothing but the hub needs to be installed.

The terminal you run it in becomes the live view: the conversation across the
task and its child tasks, and the board moving under it. For local members it
also keeps their herdr presence and doorbells flowing (what ``herdr sync``
does) until you stop it. Ctrl-C stops watching; the room, the board and the
agents stay.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
from rich.panel import Panel

from mycelium.client import hub_client
from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref
from mycelium.slim.l9 import payload_data_of, payload_type_of

console = Console()

#: How many members a swarm starts with.
DEFAULT_SIZE = 3
#: Local agent kinds tried in order when none is named, by the executable herdr runs.
LOCAL_KINDS = ("claude", "codex", "pi")
#: Arguments each local agent kind is started with. Claude Code asks before
#: every shell command it has not been allowed; a member that stops at a
#: prompt on its first ``mycelium await`` never takes its turn, so the one
#: command it needs is allowed for this session only, not in the user's settings.
AGENT_ARGS: dict[str, list[str]] = {"claude": ["--allowedTools", "Bash(mycelium:*)"]}
#: Variables passed on to each member's pane when set where swarm runs.
CARRIED_ENV = ("MYCELIUM_API_URL",)
#: The conductor engine's handle in a swarm room, and the flow it runs.
CONDUCTOR = "conductor"
FLOW = "swarm"
#: How often the herdr side refreshes presence and delivers doorbells.
SYNC_INTERVAL_S = 3.0
#: How many lines of one message the live view prints before pointing at the thread.
BODY_LINES = 6
#: How long the room may be silent before the view says so.
QUIET_S = 180.0

_SLUG = re.compile(r"[^a-z0-9]+")
#: Words a room name reads fine without.
_FILLER = frozenset({"a", "an", "the", "for", "to", "of", "and", "in", "on", "with", "our"})


def room_slug(task: str, limit: int = 40) -> str:
    """A room name from a task: its words, lowercase, joined by dashes.

    Filler words go first, and the name stops at the last whole word that
    fits, so a long task reads as a name rather than a string cut mid-word.
    """
    words = [w for w in _SLUG.split(task.lower()) if w]
    kept = [w for w in words if w not in _FILLER] or words
    slug = ""
    for word in kept:
        candidate = f"{slug}-{word}" if slug else word
        if len(candidate) > limit:
            break
        slug = candidate
    return slug or (kept[0][:limit] if kept else "swarm")


def sender_of(config: MyceliumConfig) -> str:
    """Who is starting the swarm: the configured identity, else the login name."""
    import getpass

    me = config.get_current_identity()
    if me and me != "unknown":
        return me
    try:
        login = _SLUG.sub("-", getpass.getuser().lower()).strip("-")
    except Exception:  # noqa: BLE001 - no login name is not worth failing a swarm over
        login = ""
    return login or "you"


def team_handles(size: int) -> list[str]:
    return [f"agent-{i}" for i in range(1, size + 1)]


def pick_kind(explicit: str | None) -> str | None:
    """The agent CLI to start: the one named, else the first one installed."""
    if explicit:
        return explicit
    return next((k for k in LOCAL_KINDS if shutil.which(k)), None)


def kickoff_brief(room: str, handle: str, team: list[str], key: str, task: str) -> str:
    """What a local member is told before the kickoff: who it is and how the team works."""
    lead = team[0]
    others = ", ".join(f"@{h}" for h in team if h != handle)
    return f"""\
# You are @{handle}

You are one of {len(team)} agents working together in the Mycelium room `{room}`,
with {others}. The team's task is `{key}`:

> {task}

Your terminal is already set up as @{handle} in that room
(`MYCELIUM_AGENT_HANDLE={handle}`, `MYCELIUM_ROOM_ID={room}`), so every
`mycelium` command acts as you.

## How the team works

1. **Kickoff.** A conductor asks each member to check in, one at a time, then
   asks @{lead} to split the work. Wait for your turn; do not start early.
2. **Turns.** When a line starting with `[mycelium]` appears in your terminal,
   do what it says. For a turn that means
   `mycelium await --handle {handle} --json --timeout 5`, then
   `mycelium respond --handle {handle} "<your reply>"`. The reply lands in the
   thread you were asked in.
3. **The split** (@{lead}). One child task per member, matching what each
   offered: `mycelium board new "<title>" --parent {key} --assign @<member>`.
   Make them pieces that can be worked at the same time; no task that only
   reviews or waits on another, since every piece gets reviewed anyway.
4. **Your task.** Claim it (`mycelium board claim <id> --to @{handle}`), do it
   for real, and post progress and results in its thread
   (`mycelium board send <id> "..." --as {handle}`).
5. **Review.** Before resolving, ask a teammate to review in the task's thread
   (`mycelium board send <id> "@<member> can you check ...?" --as {handle}`).
   When you review, say what is good and what has to change, and @mention the
   author by name so they hear it. Once the review is good, resolve it:
   `mycelium board resolve <id>`.
6. **Wrap-up.** Whoever resolves the last child task tells @{lead} in `{key}`'s
   thread. @{lead} then posts the combined result there and resolves `{key}`.

When the task leaves something open, do not wait for an answer: say in one
line what you will assume, and go on. Talk like a teammate: short, specific,
no filler. Now wait for the conductor.
"""


# ── the hub ──────────────────────────────────────────────────────────────────


class SwarmError(Exception):
    """A step of setting up a swarm that failed, with what to do about it."""


def _check(resp: httpx.Response, what: str, *, ok: tuple[int, ...] = ()) -> httpx.Response:
    if resp.status_code >= 400 and resp.status_code not in ok:
        raise SwarmError(f"could not {what}: {resp.text.strip() or resp.status_code}")
    return resp


def ensure_room(client: httpx.Client, room: str) -> bool:
    """Create ``room`` unless it exists; ``True`` when it was created."""
    if client.get(f"/api/rooms/{room}").status_code == 200:
        return False
    _check(client.post("/api/rooms", json={"name": room, "is_public": True}), "create the room")
    return True


def ensure_engine(client: httpx.Client, room: str, handle: str, kind: str, me: str) -> None:
    """Register an engine in ``room``; one already there is fine."""
    body = {"handle": handle, "kind": kind, "created_by": me}
    resp = client.post(f"/api/rooms/{room}/engines", json=body)
    if resp.status_code == 422 and "engine kind" in resp.text:
        raise SwarmError(
            f"this hub doesn't run {kind} engines yet. Upgrade it (mycelium upgrade), "
            + ("or drop --server to use your own agents." if kind == "worker" else "then retry.")
        )
    _check(resp, f"register @{handle}", ok=(409,))


def file_task(client: httpx.Client, room: str, title: str, me: str) -> tuple[str, str]:
    """Put the task on the board; ``(row key, thread URN)``."""
    resp = _check(
        client.post(f"/api/rooms/{room}/tasks", json={"title": title, "handle": me}),
        "file the task",
    )
    task = resp.json()
    return str(task["key"]), str(task.get("episode") or "")


def record_result(
    client: httpx.Client, room: str, key: str, title: str, result: str, by: str
) -> None:
    """Write the team's result into the task's row, under its title, as the room's memory."""
    item = {"key": key, "value": f"{title}\n\n{result.strip()}", "created_by": by}
    _check(client.post(f"/api/rooms/{room}/memory", json={"items": [item]}), "save the result")


def kick_off(client: httpx.Client, room: str, episode: str, team: list[str], task: str, me: str):
    """Summon the conductor in the task's thread to run the kickoff flow over the team."""
    names = " ".join(f"@{h}" for h in team)
    body = {
        "sender_handle": me,
        "message_type": "broadcast",
        "content": f"@{CONDUCTOR} {FLOW} {names}: {task}",
        "episode": episode,
    }
    _check(client.post(f"/api/rooms/{room}/messages", json=body), "start the kickoff")


# ── local members, in herdr ──────────────────────────────────────────────────


@dataclass
class LocalTeam:
    """The herdr side of a local swarm: its workspace and each member's pane."""

    workspace: str
    panes: dict[str, str] = field(default_factory=dict)


def _worktree(repo: Path, room: str, handle: str) -> Path:
    """A git worktree of ``repo`` for one member, on a branch of its own."""
    path = repo.parent / f"{repo.name}-{room}-{handle}"
    if path.exists():
        return path
    branch = f"swarm/{room}/{handle}"
    proc = subprocess.run(  # noqa: S603 - arguments are code-built
        ["git", "-C", str(repo), "worktree", "add", "-b", branch, str(path)],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise SwarmError(f"could not create a worktree for @{handle}: {proc.stderr.strip()}")
    return path


#: How many times, and how far apart, to try starting an agent in a new pane.
START_ATTEMPTS = 3
START_RETRY_S = 1.5


def _start_when_ready(bridge: Any, handle: str, kind: str, pane: str) -> None:
    """Start ``kind`` in ``pane``, giving a just-opened pane's shell time to come up.

    herdr starts an agent only in a pane sitting at its shell prompt, and a
    pane split a moment ago may still be starting its shell.
    """
    from mycelium.integrations.herdr import HerdrError

    for attempt in range(1, START_ATTEMPTS + 1):
        try:
            bridge.start_agent(handle, kind, pane, agent_args=AGENT_ARGS.get(kind))
        except HerdrError:
            if attempt == START_ATTEMPTS:
                raise
            time.sleep(START_RETRY_S)
        else:
            return


def start_local(
    config: MyceliumConfig,
    bridge: Any,
    room: str,
    team: list[str],
    *,
    kind: str,
    cwd: Path,
    worktree: bool,
    me: str,
) -> LocalTeam:
    """Open a herdr workspace with one ``kind`` agent per member, each set up as itself."""
    from mycelium.commands.agent import _write_manifest
    from mycelium.integrations import AddOptions, get_integration
    from mycelium.integrations.herdr import HerdrPaneMapping

    # The hub this swarm was started against, when the environment chose it,
    # so a member's `mycelium` reaches the same hub rather than its config's.
    carried = {k: os.environ[k] for k in CARRIED_ENV if os.environ.get(k)}

    def env(handle: str) -> dict[str, str]:
        return {**carried, "MYCELIUM_AGENT_HANDLE": handle, "MYCELIUM_ROOM_ID": room}

    dirs = {h: (_worktree(cwd, room, h) if worktree else cwd) for h in team}
    workspace, first = bridge.create_workspace(room, cwd=str(dirs[team[0]]), env=env(team[0]))
    local = LocalTeam(workspace=workspace, panes={team[0]: first})
    last = first
    for i, handle in enumerate(team[1:]):
        last = bridge.split_pane(
            last,
            direction="right" if i % 2 == 0 else "down",
            cwd=str(dirs[handle]),
            env=env(handle),
        )
        local.panes[handle] = last

    for handle, pane in local.panes.items():
        _start_when_ready(bridge, handle, kind, pane)
        manifest = get_integration("claude_code", cwd=str(dirs[handle])).build_manifest(
            handle=handle,
            opts=AddOptions(room=room),
            description=f"swarm member ({kind}) in herdr pane {pane}",
            allow_from=[],
            owner=me,
        )
        _write_manifest(config, room, manifest, created_by=me)
        bridge.registry.set(
            HerdrPaneMapping(room=room, handle=handle, pane=pane, kind=kind, managed=True)
        )
    bridge.registry.bind(workspace, room)
    return local


def brief_key(handle: str) -> str:
    """Where a member's brief lives in the room: its notes, which every agent has."""
    return f"agents/{handle}/notes"


def brief_local(
    client: httpx.Client, bridge: Any, room: str, local: LocalTeam, key: str, task: str, me: str
) -> None:
    """Hand each local member its brief: its notes memory, and a prompt to read it.

    The brief lives in the room rather than a file because a member reads it
    with ``mycelium memory get``, the one command it is allowed without asking;
    a file outside its working directory would stop it at a permission prompt.
    It also puts the brief where the app shows it.
    """
    team = list(local.panes)
    items = [
        {
            "key": brief_key(handle),
            "value": kickoff_brief(room, handle, team, key, task),
            "created_by": me,
            "embed": False,
        }
        for handle in team
    ]
    _check(client.post(f"/api/rooms/{room}/memory", json={"items": items}), "write the briefs")
    for handle, pane in local.panes.items():
        bridge.prompt(
            pane,
            f"[mycelium] You are @{handle} on a team of {len(team)} in room '{room}'. "
            f"Run `mycelium memory get {brief_key(handle)}` and follow it.",
            wait=False,
        )


class HerdrSync:
    """``herdr sync`` for one swarm, on a background thread while the room is shown."""

    def __init__(self, config: MyceliumConfig, bridge: Any, workspace: str, room: str) -> None:
        self._config = config
        self._bridge = bridge
        self._targets = [(workspace, room)]
        self._room = room
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def once(self) -> None:
        from mycelium.commands.herdr import sync_pass

        try:
            sync_pass(
                self._config,
                self._bridge,
                self._targets,
                room_filter=self._room,
                ttl_s=max(90.0, SYNC_INTERVAL_S * 4),
                log=console,
                wait=False,
            )
        except Exception as e:  # noqa: BLE001 - a missed pass is retried on the next
            console.print(f"[dim]herdr sync: {e}[/dim]")

    def _loop(self) -> None:
        while not self._stop.wait(SYNC_INTERVAL_S):
            self.once()

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()


# ── the live view ────────────────────────────────────────────────────────────


@dataclass
class LiveView:
    """Render the room's stream as one conversation across a task and its children."""

    root_key: str
    root_episode: str
    root_title: str
    titles: dict[str, str] = field(default_factory=dict)
    #: Thread → row key, so a cut-short message can say where the rest is.
    keys: dict[str, str] = field(default_factory=dict)
    #: The most recent message in the task's own thread: at the end, the result.
    last_root: tuple[str, str] | None = None
    done: threading.Event = field(default_factory=threading.Event)
    #: When the view last showed something, so a stalled team can be called out.
    last_moved: float = field(default_factory=lambda: time.monotonic())

    def __post_init__(self) -> None:
        self.titles[self.root_episode] = self.root_title
        self.keys[self.root_episode] = self.root_key

    @staticmethod
    def _short(text: str, limit: int = 60) -> str:
        return text if len(text) <= limit else text[: limit - 1] + "…"

    def _where(self, episode: str | None) -> str:
        title = self.titles.get(episode or "")
        return f"[dim]{escape(self._short(title, 32))} ·[/] " if title else ""

    def _notice(self, n: dict[str, Any], stamp: str) -> str | None:
        subkind = n.get("subkind")
        title = str(n.get("title") or n.get("key") or "")
        by = n.get("by") or "someone"
        if n.get("episode") and title:
            self.titles[str(n["episode"])] = title
        if n.get("episode") and n.get("key"):
            self.keys[str(n["episode"])] = str(n["key"])
        title = escape(title)
        by = escape(str(by))
        if subkind == "filed":
            who = f" for [cyan]{escape(str(n['for']))}[/]" if n.get("for") else ""
            return f"  {stamp}  [dim]──[/] [cyan]{by}[/] filed [bold]{title}[/]{who}"
        if subkind == "claimed":
            return f"  {stamp}  [dim]──[/] [cyan]{by}[/] took [bold]{title}[/]"
        if subkind == "resolved":
            if n.get("key") == self.root_key:
                self.done.set()
            return f"  {stamp}  [green]✓[/]  [cyan]{by}[/] resolved [bold]{title}[/]"
        return None

    def quiet_for(self) -> float:
        """Seconds since the view last had anything to show."""
        return time.monotonic() - self.last_moved

    def render(self, frame: dict[str, Any]) -> str | None:
        line = self._render(frame)
        if line is not None:
            self.last_moved = time.monotonic()
        return line

    def _render(self, frame: dict[str, Any]) -> str | None:
        if frame.get("message_type") != "l9_exchange":
            return None
        try:
            data = json.loads(frame.get("content") or "{}")
        except (TypeError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        stamp = f"[dim]{time.strftime('%H:%M:%S')}[/]"
        ptype = payload_type_of(data)
        if ptype == "notice":
            return self._notice(payload_data_of(data), stamp)
        if ptype in {"ping", "presence", "keepalive"}:
            return None
        text = str(data.get("content") or "").strip()
        if not text:
            return None
        sender = str(frame.get("sender_handle") or "?")
        episode = frame.get("episode")
        where = self._where(episode)
        if sender == CONDUCTOR:
            head = text.splitlines()[0]
            parts = [p.strip() for p in head.split("·")]
            if len(parts) == 4 and parts[0] == FLOW:
                return f"  {stamp}  [magenta]{CONDUCTOR}[/] {where}[dim]{parts[1]} → {parts[3]}[/]"
            return (
                f"  {stamp}  [magenta]{CONDUCTOR}[/] {where}[dim]{escape(self._short(head, 80))}[/]"
            )
        if f"@{CONDUCTOR} {FLOW}" in text:
            return f"  {stamp}  [cyan]{escape(sender)}[/] {where}[dim]kicked off the team[/]"
        if episode == self.root_episode:
            self.last_root = (sender, text)
        return f"  {stamp}  [yellow]{escape(sender)}[/] {where}{self._body(text, episode)}"

    def _body(self, text: str, episode: str | None) -> str:
        """A message as the view prints it: its first lines, and where to read the rest."""
        lines = [ln for ln in text.splitlines() if ln.strip()]
        shown = "\n".join(lines[:BODY_LINES])
        more = len(lines) - BODY_LINES
        body = escape(shown).replace("\n", "\n" + " " * 12)
        if more > 0:
            key = self.keys.get(episode or "")
            where = f" · board messages {key}" if key else ""
            body += f"\n{' ' * 12}[dim]… {more} more line{'s' if more > 1 else ''}{where}[/]"
        return body


def watch(config: MyceliumConfig, room: str, view: LiveView, connected: threading.Event) -> None:
    """Stream the room into ``view`` until it says the task is done.

    Returns when the stream ends or drops, too; the caller tells those apart
    by whether ``view.done`` is set.
    """
    try:
        with (
            hub_client(config, timeout=None) as http,
            http.stream("GET", f"/api/rooms/{room}/messages/stream") as response,
        ):
            connected.set()
            for line in response.iter_lines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                try:
                    frame = json.loads(line[5:].strip())
                except ValueError:
                    continue
                rendered = view.render(frame)
                if rendered:
                    console.print(rendered, highlight=False)
                if view.done.is_set():
                    return
    except httpx.HTTPError:
        return
    finally:
        connected.set()


# ── the command ──────────────────────────────────────────────────────────────


def _ui_room_url(room: str) -> str:
    from mycelium.commands.ui import _ui_url

    return f"{_ui_url()}/room/{room}"


@doc_ref(
    usage='mycelium swarm ["<task>"] [--server]',
    desc="Put a team of agents on one task: they check in, split it, work it, and review each other.",
    group="board",
)
def swarm(
    task: str | None = typer.Argument(None, help="What the team should work on"),
    server: bool = typer.Option(
        False, "--server", help="Members the hub plays, instead of your own CLI agents in herdr"
    ),
    size: int = typer.Option(DEFAULT_SIZE, "-n", help="How many members", min=2, max=8),
    room: str | None = typer.Option(
        None, "--room", "-r", help="Room (default: named after the task)"
    ),
    kind: str | None = typer.Option(
        None, "--kind", help="Local agent CLI to start (default: the first of claude, codex, pi)"
    ),
    worktree: bool = typer.Option(
        False, "--worktree", help="Give each local member its own git worktree"
    ),
) -> None:
    """Put a team of agents on one task and watch them work it together.

    Examples:
        mycelium swarm "fix the flaky auth tests"
        mycelium swarm "compare three vendors for billing" --server
    """
    from mycelium.integrations.herdr import HerdrBridge, HerdrError

    config = MyceliumConfig.load()
    me = sender_of(config)
    if not task:
        task = typer.prompt("What should the agents work on?").strip()
    if not task:
        raise typer.Exit(1)
    room_name = room or room_slug(task)
    team = team_handles(size)

    bridge = None
    agent_kind = None
    if not server:
        bridge = HerdrBridge()
        if not bridge.available():
            console.print(
                "[yellow]herdr isn't running here.[/yellow] Install it (https://herdr.dev), "
                "or run the team on the hub:\n"
                f'  mycelium swarm "{task}" --server'
            )
            raise typer.Exit(1)
        agent_kind = pick_kind(kind)
        if agent_kind is None:
            console.print(
                "[yellow]No agent CLI found[/yellow] (claude, codex or pi). Name one with "
                "--kind, or run the team on the hub with --server."
            )
            raise typer.Exit(1)

    local: LocalTeam | None = None
    sync: HerdrSync | None = None
    try:
        with hub_client(config, timeout=30) as client:
            ensure_room(client, room_name)
            ensure_engine(client, room_name, CONDUCTOR, "conductor", me)
            if server:
                for handle in team:
                    ensure_engine(client, room_name, handle, "worker", me)
            key, episode = file_task(client, room_name, task, me)
        if bridge is not None and agent_kind is not None:
            console.print(f"[dim]starting {size} {agent_kind} agents in herdr…[/dim]")
            local = start_local(
                config,
                bridge,
                room_name,
                team,
                kind=agent_kind,
                cwd=Path.cwd(),
                worktree=worktree,
                me=me,
            )
            with hub_client(config, timeout=30) as client:
                brief_local(client, bridge, room_name, local, key, task, me)
            sync = HerdrSync(config, bridge, local.workspace, room_name)
            sync.once()
            sync.start()
    except (SwarmError, HerdrError) as e:
        console.print(f"[red]✗[/red] {e}")
        raise typer.Exit(1) from None
    except httpx.HTTPError as e:
        console.print(f"[red]✗[/red] hub unreachable: {e}")
        raise typer.Exit(1) from None

    where = "on the hub" if server else f"in herdr workspace {local.workspace if local else ''}"
    console.print(
        f"\n[bold]{room_name}[/bold] · {size} agents {where} · "
        f"[link={_ui_room_url(room_name)}]{_ui_room_url(room_name)}[/link]"
    )
    console.print(f"[dim]{task}[/dim]\n")

    view = LiveView(root_key=key, root_episode=episode, root_title=task)
    connected = threading.Event()
    streamer = threading.Thread(
        target=watch, args=(config, room_name, view, connected), daemon=True
    )
    streamer.start()
    connected.wait(timeout=10)
    try:
        with hub_client(config, timeout=30) as client:
            kick_off(client, room_name, episode, team, task, me)
        warned = False
        while streamer.is_alive():
            streamer.join(timeout=0.5)
            quiet = view.quiet_for()
            if quiet >= QUIET_S and not warned:
                console.print(
                    f"  [yellow]Nothing has moved for {int(quiet // 60)} minutes.[/yellow] "
                    f"[dim]See what is open: mycelium board --room {room_name}[/dim]"
                )
                warned = True
            elif quiet < QUIET_S:
                warned = False
        if not view.done.is_set():
            console.print(
                "\n[yellow]Lost the room's stream before the task resolved.[/yellow] "
                f"The team keeps going: {_ui_room_url(room_name)}"
            )
        if view.done.is_set():
            if view.last_root is not None:
                who, result = view.last_root
                if not server:
                    # Workers write their result into the row themselves; a
                    # local lead resolves with `board resolve`, which does not.
                    try:
                        with hub_client(config, timeout=30) as client:
                            record_result(client, room_name, key, task, result, who)
                    except (SwarmError, httpx.HTTPError) as e:
                        console.print(f"[dim]could not save the result to {key}: {e}[/dim]")
                console.print()
                console.print(
                    Panel(
                        Markdown(result),
                        title=f"[bold]{escape(task)}[/]",
                        subtitle=f"[dim]by {escape(who)} and the team[/]",
                        border_style="green",
                        padding=(1, 2),
                    )
                )
            console.print(
                f"\n[green]Done.[/green] The whole conversation: "
                f"mycelium board messages {key} --room {room_name}"
            )
    except KeyboardInterrupt:
        console.print(f"\n[dim]Stopped watching. The room stays: {_ui_room_url(room_name)}[/dim]")
        if sync is not None:
            console.print(
                "[dim]Local agents only hear their turns while herdr sync runs: "
                "mycelium herdr sync[/dim]"
            )
    finally:
        if sync is not None:
            sync.stop()
