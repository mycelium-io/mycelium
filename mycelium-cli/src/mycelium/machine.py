# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The agents on this machine: what's running, what's wrong, and what to do.

Every herdr agent bound to a room here, however it got there (the runner,
``mycelium swarm``, or a pane a person bound), read from herdr's registry
(which handle in which room is which pane, of which kind, in which folder) and
from herdr itself (which panes are open, and which have an agent running).

:func:`report` says each agent's state, whether herdr brings it back after
herdr restarts, and the problems with the command that fixes each.
``mycelium machine`` prints it, the runner sends it to the hub with every
heartbeat for the Machines page, and both act through the functions below.

An agent's own session is herdr's to keep: with herdr's integration for its
CLI installed, herdr restarts it in that session after herdr's server
restarts. What Mycelium does for an agent that stopped is :func:`restart` it,
as itself, to catch up from the room. The runner keeps every bound workspace
synced, so the one thing to say about syncing is whether the runner is up.
"""

from __future__ import annotations

import json
import shlex
import shutil
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

State = Literal["working", "idle", "blocked", "stopped", "gone", "unknown"]

#: herdr's agent states, as the report says them.
_STATES: dict[str, State] = {
    "working": "working",
    "idle": "idle",
    "done": "idle",
    "blocked": "blocked",
}
#: Where agents whose pane is gone, with no workspace to say, are grouped.
NOWHERE = "gone"
#: How many handles a problem names before it counts the rest.
NAMED = 4


class MachineError(Exception):
    """An action that couldn't be done, said for a person."""


# ── the report ───────────────────────────────────────────────────────────────


@dataclass
class Agent:
    """One agent on this machine."""

    handle: str
    room: str
    pane: str
    #: ``stopped``: its pane is open with nothing running in it. ``gone``: the pane closed.
    state: State
    #: The agent CLI, as herdr names its kind.
    kind: str | None = None
    folder: str | None = None
    workspace: str | None = None
    #: Whether herdr brings it back in its own session after herdr restarts
    #: (its CLI's herdr integration is current); ``None`` when unknown.
    restores: bool | None = None

    @property
    def restartable(self) -> bool:
        """Stopped or gone, with the folder and kind to start it again."""
        return self.state in ("stopped", "gone") and bool(self.folder) and bool(self.kind)


@dataclass
class Workspace:
    """A herdr workspace, and the room it's bound to."""

    id: str
    label: str
    room: str | None
    agents: list[Agent] = field(default_factory=list)


ProblemKind = Literal["stopped", "lost", "runner_down", "no_restore", "herdr_update", "herdr_down"]


@dataclass
class Problem:
    """Something wrong here, and the command that fixes it."""

    kind: ProblemKind
    text: str
    fix: str | None = None
    handles: list[str] = field(default_factory=list)


@dataclass
class Report:
    machine: str
    herdr: bool
    herdr_server: str | None
    herdr_client: str | None
    #: Whether this machine's runner is running, which keeps every bound
    #: workspace synced: agents hear their mentions, and the room sees them busy.
    runner: bool
    workspaces: list[Workspace]
    problems: list[Problem]
    #: herdr's integrations not current for agent CLIs with agents running here.
    missing_integrations: list[str] = field(default_factory=list)
    herdr_minimum: str = MIN_VERSION

    @property
    def agents(self) -> list[Agent]:
        return [a for w in self.workspaces for a in w.agents]

    def find(self, handle: str, room: str | None = None) -> Agent:
        """The agent ``handle`` names (in ``room``, when two rooms share a handle)."""
        h = handle.lstrip("@")
        matches = [a for a in self.agents if a.handle == h and room in (None, a.room)]
        if not matches:
            raise MachineError(f"No agent @{h}{f' in {room}' if room else ''} on {self.machine}.")
        if len(matches) > 1:
            rooms = ", ".join(sorted(a.room for a in matches))
            raise MachineError(
                f"@{h} is in more than one room here ({rooms}); say which with --room."
            )
        return matches[0]

    def wire(self) -> dict[str, Any]:
        """The report as JSON, for ``--json`` and the runner's heartbeat."""
        body = asdict(self)
        for w, workspace in zip(body["workspaces"], self.workspaces, strict=True):
            for a, agent in zip(w["agents"], workspace.agents, strict=True):
                a["restartable"] = agent.restartable
        return body


def report(
    *,
    bridge: HerdrBridge | None = None,
    machine: str | None = None,
    runner: bool | None = None,
) -> Report:
    """Every agent on this machine, read now. Never raises for herdr being down.

    ``runner`` says whether this machine's runner is running; the runner
    building its own report says so, anything else finds out.
    """
    from mycelium.runner.daemon import machine_label

    bridge = bridge or HerdrBridge()
    machine = machine or machine_label()
    if runner is None:
        from mycelium.commands.runner import running_pid

        runner = running_pid() is not None

    herdr_up = bridge.available()
    client = bridge.version()
    server = bridge.server_version() if herdr_up else None
    live: dict[str, dict] = {}
    panes: dict[str, dict] = {}
    if herdr_up:
        try:
            live = {str(a["pane_id"]): a for a in bridge.list_agents() if a.get("pane_id")}
            panes = {str(p["pane_id"]): p for p in bridge.list_panes() if p.get("pane_id")}
        except HerdrError:
            herdr_up = False
    labels = bridge.workspace_labels() if herdr_up else {}
    bindings = bridge.registry.bindings()

    workspaces: dict[str, Workspace] = {}

    def workspace(wid: str) -> Workspace:
        if wid not in workspaces:
            gone = wid == NOWHERE
            workspaces[wid] = Workspace(
                id=wid,
                label="Panes that are gone" if gone else labels.get(wid) or wid,
                room=None if gone else bindings.get(wid),
            )
        return workspaces[wid]

    for mapping in bridge.registry.all():
        agent = _agent(mapping, live, panes, herdr_up)
        if agent.workspace is None and agent.state != "gone":
            # herdr can't say where it is: under its room's workspace, if there's one.
            bound = [w for w, r in bindings.items() if r == agent.room]
            agent.workspace = bound[0] if len(bound) == 1 else None
        workspace(agent.workspace or NOWHERE).agents.append(agent)
    # A bound workspace with no agents yet still shows, with its room.
    for wid in bindings:
        workspace(wid)

    ordered = sorted(workspaces.values(), key=lambda w: (w.id == NOWHERE, w.label))
    for w in ordered:
        w.agents.sort(key=lambda a: a.handle)
    agents = [a for w in ordered for a in w.agents]
    missing = _restores(bridge, agents)
    return Report(
        machine=machine,
        herdr=herdr_up,
        herdr_server=server,
        herdr_client=client,
        runner=runner,
        workspaces=ordered,
        problems=_problems(agents, ordered, herdr_up, server, client, machine, missing, runner),
        missing_integrations=missing,
    )


def _agent(
    mapping: HerdrPaneMapping, live: dict[str, dict], panes: dict[str, dict], herdr_up: bool
) -> Agent:
    pane, running = panes.get(mapping.pane), live.get(mapping.pane)
    if not herdr_up:
        state: State = "unknown"
    elif running is not None:
        state = _STATES.get(str(running.get("agent_status") or ""), "working")
    elif pane is not None:
        state = "stopped"
    else:
        state = "gone"
    seen = running or pane or {}
    return Agent(
        handle=mapping.handle,
        room=mapping.room,
        pane=mapping.pane,
        state=state,
        kind=mapping.kind or (running or {}).get("agent"),
        folder=mapping.cwd or seen.get("foreground_cwd") or seen.get("cwd"),
        workspace=str(seen.get("workspace_id") or "") or None,
    )


def _restores(bridge: HerdrBridge, agents: list[Agent]) -> list[str]:
    """Mark whether herdr brings each agent back; return the integrations it lacks.

    Only agents with a pane open count: a gone pane has nothing to restore.
    """
    current = bridge.integrations()
    if current is None:
        return []
    missing: set[str] = set()
    for agent in agents:
        if not agent.kind or agent.state in ("gone", "unknown"):
            continue
        name = integration_for(agent.kind)
        if name in current:  # herdr has an integration for this kind
            agent.restores = current[name]
            if not current[name]:
                missing.add(name)
    return sorted(missing)


def _names(agents: list[Agent]) -> str:
    handles = [f"@{a.handle}" for a in agents]
    if len(handles) > NAMED:
        return ", ".join(handles[:NAMED]) + f" and {len(handles) - NAMED} more"
    if len(handles) <= 2:
        return " and ".join(handles)
    return ", ".join(handles[:-1]) + f" and {handles[-1]}"


def _problems(
    agents: list[Agent],
    workspaces: list[Workspace],
    herdr_up: bool,
    server: str | None,
    client: str | None,
    machine: str,
    missing: list[str],
    runner: bool,
) -> list[Problem]:
    problems: list[Problem] = []
    if not herdr_up and agents:
        problems.append(
            Problem(
                "herdr_down",
                f"herdr isn't running on {machine}, so none of its agents can be reached.",
            )
        )
    stopped = [a for a in agents if a.state in ("stopped", "gone")]
    if restartable := [a for a in stopped if a.restartable]:
        problems.append(
            Problem(
                "stopped",
                f"{_names(restartable)} stopped. Restarting starts "
                f"{'it' if len(restartable) == 1 else 'each'} again in its folder, as itself, "
                "to catch up from the room.",
                "mycelium machine restart --all",
                [a.handle for a in restartable],
            )
        )
    # Said once, not once each: a machine that has run many agents has many old panes.
    if lost := [a for a in stopped if not a.restartable]:
        have, stay = ("has", "It stays") if len(lost) == 1 else ("have", "They stay")
        problems.append(
            Problem(
                "lost",
                f"{_names(lost)} {have} no pane any more and nothing to restart it from. "
                f"Unbinding forgets the pane. {stay} in the room.",
                "mycelium machine unbind --gone",
                [a.handle for a in lost],
            )
        )
    live = [
        a
        for w in workspaces
        if w.room
        for a in w.agents
        if a.state in ("working", "idle", "blocked")
    ]
    if not runner and live:
        problems.append(
            Problem(
                "runner_down",
                f"The runner isn't running on {machine}, so {_names(live)} won't be woken by "
                "mentions and the room can't see whether they're busy.",
                "mycelium runner --detach",
                [a.handle for a in live],
            )
        )
    if missing:
        without = [a for a in agents if a.restores is False]
        problems.append(
            Problem(
                "no_restore",
                f"If herdr restarts, {_names(without)} won't come back on "
                f"{'its' if len(without) == 1 else 'their'} own: herdr's integration for "
                f"{', '.join(missing)} isn't installed (or is out of date). Installing it adds a "
                "hook to that agent CLI's own settings.",
                "mycelium machine integrations --install",
                [a.handle for a in without],
            )
        )
    if (update := _herdr_update(server if herdr_up else None, client)) is not None:
        problems.append(update)
    return problems


def _herdr_update(server: str | None, client: str | None) -> Problem | None:
    """What's out of date about herdr here, and how to bring it up to date.

    The server is what agents run in; the client is the ``herdr`` command. A
    newer client starts a newer server once the old one stops.
    """
    after = (
        "Restarting herdr's server stops the agents in it; those with herdr's integration "
        "come back on their own, and the rest can be restarted from here."
    )
    if too_old(client):
        return Problem(
            "herdr_update",
            f"herdr {client} is out of date. Mycelium needs {MIN_VERSION} or newer. {after}",
            "herdr update",
        )
    s, c = version_tuple(server), version_tuple(client)
    if s is not None and (too_old(server) or (c is not None and s < c)):
        why = (
            f"out of date: Mycelium needs {MIN_VERSION} or newer"
            if too_old(server)
            else "older than its client"
        )
        return Problem(
            "herdr_update",
            f"herdr's server is {server}, {why}. This machine has {client}, which starts when "
            f"the old server stops. {after}",
            "herdr server stop",
        )
    return None


# ── actions ──────────────────────────────────────────────────────────────────


def restart_prompt(agent: Agent) -> str:
    """What a restarted agent is told: who it is, and to catch up from the room."""
    h, room = agent.handle, agent.room
    return (
        f"[mycelium] You are @{h}, a member of the Mycelium room '{room}'. You were restarted, "
        "so you don't remember what you were doing. If you have notes, `mycelium memory get "
        f"agents/{h}/notes` says how to work. Then run `mycelium await --room {room} --handle "
        f"{h} --json --timeout 5` to catch up on what happened since your last turn, and "
        f"`mycelium board --room {room}` for your tasks. When a line starting with [mycelium] "
        "appears here later, do what it says."
    )


def restart_command(agent: Agent) -> str:
    """What restarting ``agent`` does, said for a person to read before saying yes."""
    where = f"pane {agent.pane}" if agent.state == "stopped" else "a new pane beside its room's"
    return f"{agent.kind} in {_tilde(agent.folder or '.')}, {where}, as @{agent.handle} in {agent.room}"


def restart(config: MyceliumConfig, agent: Agent, *, bridge: HerdrBridge | None = None) -> str:
    """Start ``agent`` again in its pane (or a new one beside it), in its folder, as itself.

    Returns the pane it runs in. The pane gets the agent's handle, room and hub
    in its environment first, as a pane the runner opens would, and its
    workspace is bound to the room again, so the runner syncs it.
    """
    from mycelium.commands.swarm import _start_when_ready

    if not agent.restartable:
        if agent.state not in ("stopped", "gone"):
            raise MachineError(f"@{agent.handle} is running ({agent.state}); nothing to restart.")
        raise MachineError(f"@{agent.handle} can't be restarted: no folder or agent CLI on record.")
    bridge = bridge or HerdrBridge()
    kind, folder = str(agent.kind), str(Path(str(agent.folder)).expanduser())
    env = {
        "MYCELIUM_API_URL": config.server.api_url,
        "MYCELIUM_AGENT_HANDLE": agent.handle,
        "MYCELIUM_ROOM_ID": agent.room,
    }
    try:
        if agent.state == "stopped":
            pane = agent.pane
            exports = " ".join(f"{k}={shlex.quote(v)}" for k, v in env.items())
            bridge.run_in_pane(pane, f"cd {shlex.quote(folder)} && export {exports}")
            workspace = agent.workspace
        else:
            workspace, pane = _new_pane(bridge, agent, folder, env)
        _start_when_ready(bridge, agent.handle, kind, pane)
        bridge.prompt(pane, restart_prompt(agent), wait=False)
    except HerdrError as e:
        raise MachineError(f"herdr couldn't restart @{agent.handle}: {e}") from e
    before = bridge.registry.get(agent.room, agent.handle)
    bridge.registry.set(
        HerdrPaneMapping(
            room=agent.room,
            handle=agent.handle,
            pane=pane,
            kind=kind,
            managed=bool(before and before.managed),
            cwd=folder,
        )
    )
    if workspace and workspace not in bridge.registry.bindings():
        bridge.registry.bind(workspace, agent.room)
    return pane


def _new_pane(
    bridge: HerdrBridge, agent: Agent, folder: str, env: dict[str, str]
) -> tuple[str, str]:
    """``(workspace, pane)`` for an agent whose pane is gone: beside another of its room's.

    A workspace bound to its room that still has panes, else a new one bound to
    the room, so restarting several gone agents of a room opens one workspace.
    """
    try:
        panes = bridge.list_panes()
    except HerdrError:
        panes = []
    for workspace in [w for w, r in bridge.registry.bindings().items() if r == agent.room]:
        siblings = [str(p["pane_id"]) for p in panes if p.get("workspace_id") == workspace]
        if siblings:
            return workspace, bridge.split_pane(siblings[-1], cwd=folder, env=env)
    return bridge.create_workspace(agent.room, cwd=folder, env=env)


def rename(agent: Agent, name: str, *, bridge: HerdrBridge | None = None) -> None:
    """Set the name herdr shows for ``agent``; its handle in the room doesn't change."""
    try:
        (bridge or HerdrBridge()).rename_agent(agent.pane, name)
    except HerdrError as e:
        raise MachineError(f"herdr couldn't rename @{agent.handle}: {e}") from e


def unbind(agent: Agent, *, bridge: HerdrBridge | None = None) -> None:
    """Forget which pane ``agent`` is. It stays a member of its room."""
    (bridge or HerdrBridge()).registry.remove(agent.room, agent.handle)


def _tilde(path: str) -> str:
    home = str(Path.home())
    return "~" + path[len(home) :] if path.startswith(home) else path


# ── herdr's integrations ─────────────────────────────────────────────────────
#
# Installing one writes a hook into that agent CLI's own settings, so Mycelium
# asks once and remembers the answer, and nothing installs one without a yes.


@dataclass
class Integrations:
    """herdr's version and integrations here, and the person's answer about them."""

    herdr_server: str | None
    herdr_client: str | None
    #: The running server is older than Mycelium needs: restarting it starts the client's.
    server_out_of_date: bool
    #: The ``herdr`` command is older than Mycelium needs: it has to be updated.
    client_out_of_date: bool
    #: For each agent CLI on PATH that herdr has an integration for, whether it's current.
    current: dict[str, bool]
    #: The answer to installing them: ``yes``, ``no``, or not asked yet.
    answer: Literal["yes", "no"] | None
    minimum: str = MIN_VERSION

    @property
    def missing(self) -> list[str]:
        return sorted(name for name, ok in self.current.items() if not ok)

    def wire(self) -> dict[str, Any]:
        return {**asdict(self), "missing": self.missing}


def _answer_path() -> Path:
    return get_mycelium_dir() / "herdr" / "restore.json"


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
    from mycelium.runner.frameworks import KNOWN

    return {
        k.herdr_kind for k in KNOWN if k.herdr_kind and any(shutil.which(b) for b in k.binaries)
    }


def integrations(*, bridge: HerdrBridge | None = None) -> Integrations:
    """herdr's version, and its integrations for the agent CLIs on PATH here."""
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
    """Install herdr's integration for each agent CLI here that lacks a current one.

    Remembers the yes; returns the integrations installed.
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
