# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""This machine's agents: what runs here, what's wrong with it, and what to do.

Every agent a person has on this machine, wherever it runs (a herdr pane, an
Omnigent session) and however it got there (started by the runner or
``mycelium swarm``, or a pane a person bound to a room), read from the three
places that each know part of it:

- herdr's registry (``~/.mycelium/herdr/``): which handle in which room is
  which pane, of which kind, working in which folder.
- the runner's state: the agents it started, and the workspaces it opened.
- the host itself: which panes are open, and which have an agent running.

From those, :func:`report` says each agent's state (working, idle, stopped
with its pane still open, or gone) and the problems, with the command that
fixes each. ``mycelium machine`` prints it, the runner sends it to the hub with
every heartbeat for the Machines page, and both do the same actions through the
functions at the bottom.

The runner keeps every bound workspace synced (presence up, wakes down), so
the one thing to say about syncing is whether the runner is running.

An agent's own session is herdr's to keep, not Mycelium's: with herdr's
integration for its CLI installed (:func:`install_integrations`), herdr brings
it back in that session after herdr restarts. What Mycelium does for any agent
that stopped is restart it as itself, to catch up from the room.
"""

from __future__ import annotations

import json
import shlex
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from mycelium.filesystem import get_mycelium_dir
from mycelium.integrations.herdr import HerdrBridge, HerdrError, HerdrPaneMapping
from mycelium.integrations.herdr.bridge import (
    MIN_VERSION,
    integration_for,
    too_old,
    version_tuple,
)

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig
    from mycelium.runner.daemon import State

State_ = Literal["working", "idle", "blocked", "stopped", "gone", "unknown"]

#: herdr's agent states, as this report says them.
_HERDR_STATE: dict[str, State_] = {
    "working": "working",
    "idle": "idle",
    "done": "idle",
    "blocked": "blocked",
}
#: Where agents whose pane is gone, with no workspace to say, are grouped.
NOWHERE = "gone"


class MachineError(Exception):
    """An action that couldn't be done, said for a person."""


def _herdr_dir() -> Path:
    return get_mycelium_dir() / "herdr"


# ── the report ───────────────────────────────────────────────────────────────


@dataclass
class Agent:
    """One agent on this machine, as the report says it."""

    handle: str
    room: str
    #: ``herdr`` or ``omnigent``.
    host: str
    #: How the host names where it runs: a herdr pane, an Omnigent session id.
    ref: str
    state: State_
    #: The folder it works in, when known.
    folder: str | None = None
    #: The agent CLI, as herdr names its kind, when known.
    kind: str | None = None
    #: The herdr workspace its pane is (or was) in.
    workspace: str | None = None
    #: Who put it here: the runner (or ``swarm``), or a person binding a pane.
    started_by: Literal["runner", "you"] = "you"
    #: Whether herdr brings it back in its own session after herdr's server
    #: restarts (its kind's herdr integration is current); ``None`` if unknown.
    restores: bool | None = None

    @property
    def restartable(self) -> bool:
        """Whether Mycelium can start it again: stopped or gone, with a folder and kind."""
        return (
            self.host == "herdr"
            and self.state in ("stopped", "gone")
            and bool(self.folder)
            and bool(self.kind)
        )


@dataclass
class Workspace:
    """Where agents run together: a herdr workspace, or the Omnigent host."""

    id: str
    label: str
    host: str
    room: str | None
    agents: list[Agent] = field(default_factory=list)


@dataclass
class Problem:
    """Something wrong here, and the command that fixes it."""

    kind: Literal["stopped", "lost", "runner_down", "no_restore", "herdr_update", "herdr_down"]
    text: str
    #: The ``mycelium machine`` command that fixes it, when one does.
    fix: str | None = None
    handles: list[str] = field(default_factory=list)


@dataclass
class Report:
    machine: str
    herdr: bool
    herdr_server: str | None
    herdr_client: str | None
    omnigent_url: str | None
    workspaces: list[Workspace]
    problems: list[Problem]
    #: Whether this machine's runner is running, which is what keeps every bound
    #: workspace synced: agents hear their mentions, and the room sees them busy.
    runner: bool = True
    #: The oldest herdr Mycelium works with.
    herdr_minimum: str = MIN_VERSION
    #: herdr's integrations for the agent kinds in use here that aren't current,
    #: so herdr can't bring those agents back after its server restarts.
    missing_integrations: list[str] = field(default_factory=list)

    @property
    def agents(self) -> list[Agent]:
        return [a for w in self.workspaces for a in w.agents]

    def find(self, handle: str, room: str | None = None) -> Agent:
        """The agent ``handle`` names (in ``room``, when two rooms share a handle)."""
        h = handle.lstrip("@")
        matches = [a for a in self.agents if a.handle == h and (room is None or a.room == room)]
        if not matches:
            where = f" in {room}" if room else ""
            raise MachineError(f"No agent @{h}{where} on {self.machine}.")
        if len(matches) > 1:
            rooms = ", ".join(sorted(a.room for a in matches))
            raise MachineError(
                f"@{h} is in more than one room here ({rooms}); say which with --room."
            )
        return matches[0]

    def wire(self) -> dict[str, Any]:
        """The report as JSON, for ``--json`` and the runner's heartbeat."""
        return {
            "machine": self.machine,
            "herdr": self.herdr,
            "herdr_server": self.herdr_server,
            "herdr_client": self.herdr_client,
            "omnigent_url": self.omnigent_url,
            "runner": self.runner,
            "herdr_minimum": self.herdr_minimum,
            "missing_integrations": self.missing_integrations,
            "workspaces": [
                {
                    **{k: v for k, v in asdict(w).items() if k != "agents"},
                    "agents": [{**asdict(a), "restartable": a.restartable} for a in w.agents],
                }
                for w in self.workspaces
            ],
            "problems": [asdict(p) for p in self.problems],
        }


def report(
    config: MyceliumConfig,
    *,
    bridge: HerdrBridge | None = None,
    state: State | None = None,
    omnigent: Any = None,
    machine: str | None = None,
    runner: bool | None = None,
) -> Report:
    """Everything on this machine, read now. Never raises for a host that's down.

    ``runner`` says whether this machine's runner is running; the runner
    building its own report says so, anything else finds out.
    """
    from mycelium.runner.daemon import State as RunnerState
    from mycelium.runner.daemon import machine_label, runner_dir

    bridge = bridge or HerdrBridge()
    if state is None:
        state = RunnerState.load(runner_dir() / "state.json")
    machine = machine or machine_label()
    if runner is None:
        from mycelium.commands.runner import running_pid

        runner = running_pid() is not None

    herdr_up = bridge.available()
    client_version = bridge.version()
    server_version = bridge.server_version() if herdr_up else None
    live: dict[str, dict] = {}
    panes: dict[str, dict] = {}
    labels: dict[str, str] = {}
    if herdr_up:
        try:
            live = {str(a["pane_id"]): a for a in bridge.list_agents() if a.get("pane_id")}
            panes = {str(p["pane_id"]): p for p in bridge.list_panes() if p.get("pane_id")}
        except HerdrError:
            herdr_up = False
        labels = {
            str(w["workspace_id"]): str(w.get("label") or "")
            for w in bridge.list_workspaces()
            if w.get("workspace_id")
        }

    bindings = bridge.registry.bindings()
    runner_panes = {a.pane: a for a in state.agents.values()}
    workspaces: dict[str, Workspace] = {}

    def workspace(wid: str, room: str | None) -> Workspace:
        if wid not in workspaces:
            nowhere = wid == NOWHERE
            workspaces[wid] = Workspace(
                id=wid,
                label="Panes that are gone" if nowhere else labels.get(wid) or wid,
                host="herdr",
                room=None if nowhere else room or bindings.get(wid),
            )
        return workspaces[wid]

    for mapping in bridge.registry.all():
        agent = _herdr_agent(mapping, live, panes, runner_panes, herdr_up)
        wid = agent.workspace or (
            NOWHERE if agent.state == "gone" else _bound_workspace(bindings, mapping.room)
        )
        wid = wid or NOWHERE
        agent.workspace = None if wid == NOWHERE else wid
        workspace(wid, None if wid == NOWHERE else mapping.room).agents.append(agent)
    # A bound workspace with no agents mapped yet still shows: it's synced all the same.
    for wid, room in bindings.items():
        workspace(wid, room)

    if config.runner.host == "omnigent":
        if omnigent is None:
            from mycelium.runner.hosts import OmnigentHost

            omnigent = OmnigentHost(config.runner.omnigent_url)
        _add_omnigent(workspaces, omnigent, state)

    ordered = sorted(workspaces.values(), key=lambda w: (w.host != "herdr", w.label))
    for w in ordered:
        w.agents.sort(key=lambda a: a.handle)
    missing = _restores(bridge, [a for w in ordered for a in w.agents if a.host == "herdr"])
    problems = _problems(
        ordered, herdr_up, server_version, client_version, machine, missing, runner=runner
    )
    return Report(
        machine=machine,
        herdr=herdr_up,
        herdr_server=server_version,
        herdr_client=client_version,
        omnigent_url=config.runner.omnigent_url if config.runner.host == "omnigent" else None,
        workspaces=ordered,
        problems=problems,
        runner=runner,
        missing_integrations=missing,
    )


def _restores(bridge: HerdrBridge, agents: list[Agent]) -> list[str]:
    """Mark whether herdr restores each agent; return the integrations it lacks.

    herdr restores an agent after its server restarts when that agent's kind
    has a current herdr integration. Only the integrations for agents with a
    pane open are named: a gone pane has nothing for herdr to restore, and an
    integration for a CLI nobody runs is nothing to fix.
    """
    current = bridge.integrations()
    if current is None:
        return []
    missing: set[str] = set()
    for agent in agents:
        if not agent.kind or agent.state in ("gone", "unknown"):
            continue
        name = integration_for(agent.kind)
        if name not in current:
            continue  # herdr has no integration for this kind at all
        agent.restores = current[name]
        if not current[name]:
            missing.add(name)
    return sorted(missing)


def _bound_workspace(bindings: dict[str, str], room: str) -> str | None:
    """The one workspace bound to ``room``, when there's exactly one."""
    matches = [w for w, r in bindings.items() if r == room]
    return matches[0] if len(matches) == 1 else None


def _herdr_agent(
    mapping: HerdrPaneMapping,
    live: dict[str, dict],
    panes: dict[str, dict],
    runner_panes: dict[str, Any],
    herdr_up: bool,
) -> Agent:
    pane = panes.get(mapping.pane)
    running = live.get(mapping.pane)
    if not herdr_up:
        state: State_ = "unknown"
    elif running is not None:
        state = _HERDR_STATE.get(str(running.get("agent_status") or ""), "working")
    elif pane is not None:
        state = "stopped"
    else:
        state = "gone"
    tracked = runner_panes.get(mapping.pane)
    folder = (
        mapping.cwd
        or (tracked.cwd if tracked else None)
        or (pane or {}).get("cwd")
        or (running or {}).get("cwd")
    )
    return Agent(
        handle=mapping.handle,
        room=mapping.room,
        host="herdr",
        ref=mapping.pane,
        state=state,
        folder=folder,
        kind=mapping.kind or (running or {}).get("agent"),
        workspace=str((pane or running or {}).get("workspace_id") or "")
        or (tracked.workspace if tracked else None),
        started_by="runner" if tracked is not None else "you",
    )


def _add_omnigent(workspaces: dict[str, Workspace], omnigent: Any, state: State) -> None:
    statuses = omnigent.statuses()
    host = Workspace(id="omnigent", label="Omnigent", host="omnigent", room=None)
    for tracked in state.agents.values():
        if not tracked.live and tracked.status != "stopped":
            continue
        found = (statuses or {}).get(tracked.pane)
        if statuses is None:
            agent_state: State_ = "unknown"
        elif found is None:
            agent_state = "gone"
        else:
            agent_state = _HERDR_STATE.get(found[0], "working")
        host.agents.append(
            Agent(
                handle=tracked.handle,
                room=tracked.room,
                host="omnigent",
                ref=tracked.pane,
                state=agent_state,
                folder=tracked.cwd,
                kind=tracked.framework,
                started_by="runner",
            )
        )
    if host.agents:
        workspaces[host.id] = host


def _problems(
    workspaces: list[Workspace],
    herdr_up: bool,
    server: str | None,
    client: str | None,
    machine: str,
    missing: list[str],
    *,
    runner: bool,
) -> list[Problem]:
    problems: list[Problem] = []
    herdr_agents = [a for w in workspaces if w.host == "herdr" for a in w.agents]
    if not herdr_up and herdr_agents:
        problems.append(
            Problem(
                kind="herdr_down",
                text=f"herdr isn't running on {machine}, so none of its agents can be reached.",
                fix=None,
            )
        )
    stopped = [a for a in herdr_agents if a.state in ("stopped", "gone")]
    restartable = [a for a in stopped if a.restartable]
    if restartable:
        one = len(restartable) == 1
        problems.append(
            Problem(
                kind="stopped",
                text=(
                    f"{_names(restartable)} stopped. Restarting starts "
                    f"{'it' if one else 'each'} again in its folder, as itself, to catch up "
                    "from the room."
                ),
                fix="mycelium machine restart --all",
                handles=[a.handle for a in restartable],
            )
        )
    # The ones there's nothing to restart from, said once rather than once each:
    # a machine that has run a lot of agents has a lot of old panes.
    lost = [a for a in stopped if not a.restartable]
    if lost:
        have, stay = ("has", "It stays") if len(lost) == 1 else ("have", "They stay")
        problems.append(
            Problem(
                kind="lost",
                text=(
                    f"{_names(lost)} {have} no pane any more and no folder on record, so "
                    f"there's nothing to restart. Unbinding forgets the pane. {stay} in the room."
                ),
                fix="mycelium machine unbind --gone",
                handles=[a.handle for a in lost],
            )
        )
    if missing:
        names = ", ".join(missing)
        without = [a for a in herdr_agents if a.restores is False]
        problems.append(
            Problem(
                kind="no_restore",
                text=(
                    f"If herdr restarts, {_names(without)} won't come back on "
                    f"{'its' if len(without) == 1 else 'their'} own: "
                    f"herdr's integration for {names} isn't installed (or is out of date). "
                    "Installing it adds a hook to that agent CLI's own settings."
                ),
                fix="mycelium machine integrations --install",
                handles=[a.handle for a in without],
            )
        )
    live = [
        a
        for w in workspaces
        if w.host == "herdr" and w.room
        for a in w.agents
        if a.state in ("working", "idle", "blocked")
    ]
    if not runner and live:
        problems.append(
            Problem(
                kind="runner_down",
                text=(
                    f"The runner isn't running on {machine}, so {_names(live)} won't be woken "
                    "by mentions and the room can't see whether they're busy."
                ),
                fix="mycelium runner --detach",
                handles=[a.handle for a in live],
            )
        )
    update = _herdr_update(server if herdr_up else None, client)
    if update is not None:
        problems.append(update)
    return problems


def _herdr_update(server: str | None, client: str | None) -> Problem | None:
    """What's out of date about herdr here, and how to bring it up to date, if anything.

    The server is what agents run in; the client is the ``herdr`` that runs
    commands. A newer client starts a newer server once the old one stops.
    """
    s, c = version_tuple(server), version_tuple(client)
    restart = (
        "Restarting herdr's server stops the agents in it; those with herdr's "
        "integration come back on their own, and the rest can be restarted from here."
    )
    if c is not None and too_old(client):
        return Problem(
            kind="herdr_update",
            text=f"herdr {client} is out of date. Mycelium needs {MIN_VERSION} or newer. {restart}",
            fix="herdr update",
        )
    if s is not None and (too_old(server) or (c is not None and s < c)):
        why = (
            f"out of date: Mycelium needs {MIN_VERSION} or newer"
            if too_old(server)
            else "older than its client"
        )
        return Problem(
            kind="herdr_update",
            text=(
                f"herdr's server is {server}, {why}. This machine has {client}, which "
                f"starts when the old server stops. {restart}"
            ),
            fix="herdr server stop",
        )
    return None


#: How many handles a problem names before it counts the rest.
NAMED = 4


def _names(agents: list[Agent]) -> str:
    handles = [f"@{a.handle}" for a in agents]
    if len(handles) > NAMED:
        return ", ".join(handles[:NAMED]) + f" and {len(handles) - NAMED} more"
    if len(handles) <= 2:
        return " and ".join(handles)
    return ", ".join(handles[:-1]) + f" and {handles[-1]}"


# ── actions ──────────────────────────────────────────────────────────────────


def restart_prompt(agent: Agent) -> str:
    """What a restarted agent is told: who it is, and to catch up from the room."""
    h, room = agent.handle, agent.room
    return (
        f"[mycelium] You are @{h}, a member of the Mycelium room '{room}'. You were "
        "restarted, so you don't remember what you were doing. If you have notes, "
        f"`mycelium memory get agents/{h}/notes` says how to work. Then run `mycelium "
        f"await --room {room} --handle {h} --json --timeout 5` to catch up on what happened "
        f"since your last turn, and `mycelium board --room {room}` for your tasks. When a line "
        "starting with [mycelium] appears here later, do what it says."
    )


def restart_command(agent: Agent) -> str:
    """What restarting ``agent`` does, said for a person to read before saying yes."""
    where = f"pane {agent.ref}" if agent.state == "stopped" else "a new pane beside its room's"
    return (
        f"{agent.kind or 'its agent CLI'} in {_tilde(agent.folder or '.')}, {where}, "
        f"as @{agent.handle} in {agent.room}"
    )


def restart(config: MyceliumConfig, agent: Agent, *, bridge: HerdrBridge | None = None) -> str:
    """Start ``agent`` again in its pane (or a new one beside it), in its folder, as itself.

    Returns the pane it's running in. The pane gets the agent's handle, room
    and hub in its environment first, as a pane the runner opens would, and the
    agent is told to catch up from the room: it starts with no memory of its
    last session, whose place the room's record takes.
    """
    from mycelium.commands.swarm import _start_when_ready

    if not agent.restartable:
        if agent.state not in ("stopped", "gone"):
            raise MachineError(f"@{agent.handle} is running ({agent.state}); nothing to restart.")
        raise MachineError(
            f"@{agent.handle} can't be restarted: nothing says which agent CLI it ran or "
            "in which folder."
        )
    kind = str(agent.kind)
    bridge = bridge or HerdrBridge()
    env = {
        "MYCELIUM_API_URL": config.server.api_url,
        "MYCELIUM_AGENT_HANDLE": agent.handle,
        "MYCELIUM_ROOM_ID": agent.room,
    }
    folder = str(Path(agent.folder or ".").expanduser())
    try:
        if agent.state == "stopped":
            pane = agent.ref
            exports = " ".join(f"{k}={shlex.quote(v)}" for k, v in env.items())
            bridge.run_in_pane(pane, f"cd {shlex.quote(folder)} && export {exports}")
        else:
            pane = _new_pane(bridge, agent, folder, env)
        _start_when_ready(bridge, agent.handle, kind, pane)
        bridge.prompt(pane, restart_prompt(agent), wait=False)
    except HerdrError as e:
        raise MachineError(f"herdr couldn't restart @{agent.handle}: {e}") from e
    bridge.registry.set(
        HerdrPaneMapping(
            room=agent.room,
            handle=agent.handle,
            pane=pane,
            kind=kind,
            managed=_was_managed(bridge, agent),
            cwd=folder,
        )
    )
    return pane


def _was_managed(bridge: HerdrBridge, agent: Agent) -> bool:
    before = bridge.registry.get(agent.room, agent.handle)
    return bool(before and before.managed)


def _new_pane(bridge: HerdrBridge, agent: Agent, folder: str, env: dict[str, str]) -> str:
    """A pane for an agent whose own is gone: beside another of its room's, or a new one.

    Its own workspace when it still has panes, else any workspace bound to its
    room that does. A new workspace is bound to the room, so restarting several
    gone agents of one room opens one workspace for them all, not one each.
    """
    try:
        panes = bridge.list_panes()
    except HerdrError:
        panes = []
    room_workspaces = [w for w, r in bridge.registry.bindings().items() if r == agent.room]
    for workspace in [agent.workspace, *room_workspaces]:
        siblings = [
            str(p["pane_id"])
            for p in panes
            if workspace and p.get("workspace_id") == workspace and p.get("pane_id")
        ]
        if siblings:
            return bridge.split_pane(siblings[-1], direction="right", cwd=folder, env=env)
    workspace, pane = bridge.create_workspace(agent.room, cwd=folder, env=env)
    bridge.registry.bind(workspace, agent.room)
    return pane


def stop(agent: Agent, *, bridge: HerdrBridge | None = None) -> None:
    """End ``agent``'s session; its pane stays open, so it can be restarted."""
    if agent.host != "herdr":
        raise MachineError(f"@{agent.handle} runs in {agent.host}; stop it from the app.")
    if agent.state not in ("working", "idle", "blocked"):
        raise MachineError(f"@{agent.handle} isn't running.")
    bridge = bridge or HerdrBridge()
    try:
        # Twice: the first interrupts a turn, the second ends the session.
        bridge.send_keys(agent.ref, "ctrl+c")
        bridge.send_keys(agent.ref, "ctrl+c")
    except HerdrError as e:
        raise MachineError(f"herdr couldn't stop @{agent.handle}: {e}") from e


def rename(agent: Agent, name: str, *, bridge: HerdrBridge | None = None) -> None:
    """Set the name herdr shows for ``agent`` (its handle in the room doesn't change)."""
    if agent.host != "herdr":
        raise MachineError(f"@{agent.handle} runs in {agent.host}, which names it itself.")
    bridge = bridge or HerdrBridge()
    try:
        bridge.rename_agent(agent.ref, name)
    except HerdrError as e:
        raise MachineError(f"herdr couldn't rename @{agent.handle}: {e}") from e


def unbind(agent: Agent, *, bridge: HerdrBridge | None = None) -> None:
    """Forget which pane ``agent`` is. It stays a member of its room."""
    if agent.host != "herdr":
        raise MachineError(f"@{agent.handle} runs in {agent.host}; there's no pane to unbind.")
    bridge = bridge or HerdrBridge()
    bridge.registry.remove(agent.room, agent.handle)


# ── herdr's integrations ─────────────────────────────────────────────────────
#
# herdr brings an agent back in its own session after herdr's server restarts
# when that agent CLI has herdr's integration installed. Installing one writes a
# hook into the CLI's own settings, so Mycelium asks once and remembers the
# answer; nothing installs one without a yes.


@dataclass
class Integrations:
    """herdr's version and integrations here, and the person's answer about them."""

    herdr_server: str | None
    herdr_client: str | None
    #: The running server is older than Mycelium needs: restarting it starts the client's.
    server_out_of_date: bool
    #: The ``herdr`` command is older than Mycelium needs: it has to be updated.
    client_out_of_date: bool
    #: For each agent CLI installed here that herdr has an integration for,
    #: whether that integration is current.
    current: dict[str, bool]
    #: The person's answer to installing them: ``yes``, ``no``, or not asked yet.
    answer: Literal["yes", "no"] | None
    minimum: str = MIN_VERSION

    @property
    def missing(self) -> list[str]:
        return sorted(name for name, ok in self.current.items() if not ok)

    @property
    def out_of_date(self) -> bool:
        return self.server_out_of_date or self.client_out_of_date

    def wire(self) -> dict[str, Any]:
        return {**asdict(self), "missing": self.missing, "out_of_date": self.out_of_date}


def _answer_path() -> Path:
    return _herdr_dir() / "restore.json"


def _answer() -> Literal["yes", "no"] | None:
    try:
        said = json.loads(_answer_path().read_text()).get("answer")
    except (OSError, ValueError, AttributeError):
        return None
    return said if said in ("yes", "no") else None


def _remember(answer: Literal["yes", "no"]) -> None:
    path = _answer_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"answer": answer, "at": time.time()}) + "\n")


def _installed_kinds() -> set[str]:
    """The herdr kinds of the agent CLIs found on PATH here."""
    import shutil

    from mycelium.runner.frameworks import KNOWN

    return {
        k.herdr_kind for k in KNOWN if k.herdr_kind and any(shutil.which(b) for b in k.binaries)
    }


def integrations(*, bridge: HerdrBridge | None = None) -> Integrations:
    """herdr's version and the state of its integrations for the agent CLIs here."""
    bridge = bridge or HerdrBridge()
    client = bridge.version()
    server = bridge.server_version() if bridge.available() else None
    status = bridge.integrations() or {}
    wanted = {integration_for(k) for k in _installed_kinds()}
    return Integrations(
        herdr_server=server,
        herdr_client=client,
        server_out_of_date=too_old(server),
        client_out_of_date=too_old(client),
        current={name: ok for name, ok in status.items() if name in wanted},
        answer=_answer(),
    )


def install_integrations(*, bridge: HerdrBridge | None = None) -> list[str]:
    """Install herdr's integration for every agent CLI here that lacks a current one.

    The person said yes to get here, so the answer is remembered; returns the
    integrations installed. One that fails to install raises, after the ones
    before it are in.
    """
    bridge = bridge or HerdrBridge()
    _remember("yes")
    done: list[str] = []
    for name in integrations(bridge=bridge).missing:
        try:
            bridge.install_integration(name)
        except HerdrError as e:
            raise MachineError(f"herdr couldn't install its {name} integration: {e}") from e
        done.append(name)
    return done


def decline_integrations() -> None:
    """Remember that the person doesn't want herdr's integrations, so they aren't asked again."""
    _remember("no")


def _tilde(path: str) -> str:
    home = str(Path.home())
    return "~" + path[len(home) :] if path.startswith(home) else path
