# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""This machine's agents: what runs here, what's wrong with it, and what to do.

Every agent a person has on this machine, wherever it runs (a herdr pane, an
Omnigent session) and however it got there (started by the runner or
``mycelium swarm``, or a pane a person bound to a room), read from the three
places that each know part of it:

- herdr's registry (``~/.mycelium/herdr/``): which handle in which room is
  which pane, and since agents are started with a chosen session, which session.
- the runner's state: the agents it started, and the workspaces it opened.
- the host itself: which panes are open, and which have an agent running.

From those, :func:`report` says each agent's state (working, idle, stopped
with its pane still open, or gone), who keeps each workspace synced, and the
problems with the command that fixes each. ``mycelium machine`` prints it, the
runner sends it to the hub with every heartbeat for the Machines page, and both
do the same actions through the functions at the bottom.

Who syncs a workspace is the person's choice (:func:`set_runner_sync`), and
only one thing does at a time: each sync loop leaves a heartbeat per workspace
(:func:`mark_syncing`), and a terminal ``herdr sync`` leaves alone a workspace
the runner is keeping.
"""

from __future__ import annotations

import json
import os
import shlex
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import quote

from mycelium.filesystem import get_mycelium_dir
from mycelium.integrations.herdr import HerdrBridge, HerdrError, HerdrPaneMapping
from mycelium.integrations.herdr.agents import FoundSession, agent_kind

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig
    from mycelium.runner.daemon import State

State_ = Literal["working", "idle", "blocked", "stopped", "gone", "unknown"]
SyncedBy = Literal["runner", "terminal"]

#: herdr's agent states, as this report says them.
_HERDR_STATE: dict[str, State_] = {
    "working": "working",
    "idle": "idle",
    "done": "idle",
    "blocked": "blocked",
}
#: A sync heartbeat older than this means nothing is syncing that workspace.
FRESH_S = 30.0
#: Where agents whose pane is gone, with no workspace to say, are grouped.
NOWHERE = "gone"


class MachineError(Exception):
    """An action that couldn't be done, said for a person."""


# ── who syncs what ───────────────────────────────────────────────────────────


def _herdr_dir() -> Path:
    return get_mycelium_dir() / "herdr"


def _chosen_path() -> Path:
    return _herdr_dir() / "runner-sync.json"


def _heartbeat_dir() -> Path:
    return _herdr_dir() / "syncing"


def runner_sync_choices() -> set[str]:
    """Workspaces the person asked the runner to keep synced (besides the ones it opened)."""
    try:
        raw = json.loads(_chosen_path().read_text())
    except (OSError, ValueError):
        return set()
    return {str(w) for w in raw} if isinstance(raw, list) else set()


def set_runner_sync(workspace: str, on: bool) -> None:
    """Ask the runner to keep ``workspace`` synced, or to stop."""
    chosen = runner_sync_choices()
    chosen = chosen | {workspace} if on else chosen - {workspace}
    path = _chosen_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(chosen), indent=2) + "\n")


def mark_syncing(workspaces: list[str], by: SyncedBy) -> None:
    """Leave a heartbeat saying ``by`` is syncing each of ``workspaces`` right now."""
    folder = _heartbeat_dir()
    folder.mkdir(parents=True, exist_ok=True)
    beat = {"by": by, "pid": os.getpid(), "at": time.time()}
    for workspace in workspaces:
        try:
            body = json.dumps({**beat, "workspace": workspace})
            (folder / f"{_safe(workspace)}.json").write_text(body)
        except OSError:
            continue


def syncing() -> dict[str, SyncedBy]:
    """Which workspaces something is syncing now, and what: runner or a terminal loop.

    Keyed by the workspace's own id, which the heartbeat carries; its file name
    is only a safe spelling of it.
    """
    out: dict[str, SyncedBy] = {}
    folder = _heartbeat_dir()
    if not folder.is_dir():
        return out
    now = time.time()
    for path in folder.glob("*.json"):
        try:
            beat = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if now - float(beat.get("at", 0)) > FRESH_S or not _alive(int(beat.get("pid", 0))):
            continue
        workspace = beat.get("workspace")
        if beat.get("by") in ("runner", "terminal") and isinstance(workspace, str):
            out[workspace] = beat["by"]
    return out


def _safe(workspace: str) -> str:
    """A file name for ``workspace``'s heartbeat: escaped, so no two ids share one."""
    return quote(workspace, safe="")


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


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
    #: The agent CLI's session, which resuming picks up. ``None`` when nothing saved it.
    session: str | None = None
    #: The agent CLI, as herdr names its kind, when known.
    kind: str | None = None
    #: The herdr workspace its pane is (or was) in.
    workspace: str | None = None
    #: Who put it here: the runner (or ``swarm``), or a person binding a pane.
    started_by: Literal["runner", "you"] = "you"

    @property
    def resumes(self) -> bool:
        """Whether its agent CLI can ever be resumed, saved session or not."""
        return self.host == "herdr" and agent_kind(self.kind).resumes

    @property
    def resumable(self) -> bool:
        """Whether it can be resumed now: stopped, with a session saved."""
        return (
            self.host == "herdr"
            and self.state in ("stopped", "gone")
            and bool(self.folder)
            and agent_kind(self.kind).valid_session(self.session) is not None
        )


@dataclass
class Workspace:
    """Where agents run together: a herdr workspace, or the Omnigent host."""

    id: str
    label: str
    host: str
    room: str | None
    #: What is syncing it right now (from the heartbeats), if anything.
    synced_by: SyncedBy | None
    #: Whether the runner is meant to keep it synced (it opened it, or the person chose so).
    runner_keeps: bool
    agents: list[Agent] = field(default_factory=list)


@dataclass
class Problem:
    """Something wrong here, and the command that fixes it."""

    kind: Literal["stopped", "unresumable", "unsynced", "herdr_update", "herdr_down"]
    text: str
    #: The ``mycelium machine`` command that fixes it, when one does.
    fix: str | None = None
    handles: list[str] = field(default_factory=list)
    workspace: str | None = None


@dataclass
class Report:
    machine: str
    herdr: bool
    herdr_server: str | None
    herdr_client: str | None
    omnigent_url: str | None
    workspaces: list[Workspace]
    problems: list[Problem]

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
            "workspaces": [
                {
                    **{k: v for k, v in asdict(w).items() if k != "agents"},
                    # The command each resumable one would run, built here by
                    # its kind, so whoever shows it needn't know any CLI.
                    "agents": [
                        {
                            **asdict(a),
                            "resumes": a.resumes,
                            "resumable": a.resumable,
                            "resume_command": resume_line(a) if a.resumable else None,
                        }
                        for a in w.agents
                    ],
                }
                for w in self.workspaces
            ],
            "problems": [asdict(p) for p in self.problems],
        }


def _major_minor(version: str | None) -> tuple[int, ...] | None:
    if not version:
        return None
    parts = []
    for piece in version.strip().lstrip("v").split(".")[:2]:
        digits = "".join(c for c in piece if c.isdigit())
        if not digits:
            return None
        parts.append(int(digits))
    return tuple(parts)


def report(
    config: MyceliumConfig,
    *,
    bridge: HerdrBridge | None = None,
    state: State | None = None,
    omnigent: Any = None,
    machine: str | None = None,
) -> Report:
    """Everything on this machine, read now. Never raises for a host that's down."""
    from mycelium.runner.daemon import State as RunnerState
    from mycelium.runner.daemon import machine_label, runner_dir

    bridge = bridge or HerdrBridge()
    if state is None:
        state = RunnerState.load(runner_dir() / "state.json")
    machine = machine or machine_label()

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
    chosen = runner_sync_choices()
    now_syncing = syncing()
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
                synced_by=None if nowhere else now_syncing.get(wid),
                runner_keeps=wid in state.owned or wid in chosen,
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
    # A bound workspace with no agents mapped yet still shows, so it can be synced.
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
    problems = _problems(ordered, herdr_up, server_version, client_version, machine)
    return Report(
        machine=machine,
        herdr=herdr_up,
        herdr_server=server_version,
        herdr_client=client_version,
        omnigent_url=config.runner.omnigent_url if config.runner.host == "omnigent" else None,
        workspaces=ordered,
        problems=problems,
    )


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
        session=mapping.session,
        kind=mapping.kind or (running or {}).get("agent"),
        workspace=str((pane or running or {}).get("workspace_id") or "")
        or (tracked.workspace if tracked else None),
        started_by="runner" if tracked is not None else "you",
    )


def _add_omnigent(workspaces: dict[str, Workspace], omnigent: Any, state: State) -> None:
    statuses = omnigent.statuses()
    host = Workspace(
        id="omnigent",
        label="Omnigent",
        host="omnigent",
        room=None,
        synced_by="runner" if syncing().get("omnigent") == "runner" else None,
        runner_keeps=True,
    )
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
                session=tracked.pane,
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
    resumable = [a for a in stopped if a.resumable]
    if resumable:
        whose = "Their sessions are" if len(resumable) > 1 else "Its session is"
        problems.append(
            Problem(
                kind="stopped",
                text=(
                    f"{_names(resumable)} stopped. {whose} saved, so they can pick up "
                    "where they left off."
                ),
                fix="mycelium machine resume --all",
                handles=[a.handle for a in resumable],
            )
        )
    # The ones that can't be resumed, said once per kind rather than once each:
    # a machine that has run a lot of agents has a lot of old panes.
    lost = [a for a in stopped if not a.resumable and a.state == "gone"]
    if lost:
        have, stay = ("has", "It stays") if len(lost) == 1 else ("have", "They stay")
        problems.append(
            Problem(
                kind="unresumable",
                text=(
                    f"{_names(lost)} {have} no pane any more and no saved session, so there's "
                    f"nothing to resume. Unbinding forgets the pane. {stay} in the room."
                ),
                fix="mycelium machine unbind --gone",
                handles=[a.handle for a in lost],
            )
        )
    # Stopped with nothing saved: a session worth looking for, or none to find.
    unsaved = [a for a in stopped if not a.resumable and a.state == "stopped" and a.resumes]
    cannot = [a for a in stopped if a.state == "stopped" and not a.resumes]
    if cannot:
        one = len(cannot) == 1
        its, it = ("its agent CLI", "it") if one else ("their agent CLIs", "they")
        again = "Start it again in its pane" if one else "Start each again in its pane"
        problems.append(
            Problem(
                kind="unresumable",
                text=(
                    f"{_names(cannot)} stopped, and Mycelium can't resume {its}, so {it} "
                    f"can't pick up where {it} left off. {again}; the room keeps "
                    f"{'its' if one else 'their'} place."
                ),
                fix=None,
                handles=[a.handle for a in cannot],
            )
        )
    if unsaved:
        first = unsaved[0]
        problems.append(
            Problem(
                kind="unresumable",
                text=(
                    f"{_names(unsaved)} stopped with no saved session. Mycelium can look for "
                    "the conversation in each one's folder; check it's the right one, then resume."
                ),
                fix=f"mycelium machine session {first.handle} --room {first.room} --find",
                handles=[a.handle for a in unsaved],
            )
        )
    for w in workspaces:
        live = [a for a in w.agents if a.state in ("working", "idle", "blocked")]
        if w.host == "herdr" and w.room and live and w.synced_by is None and not w.runner_keeps:
            problems.append(
                Problem(
                    kind="unsynced",
                    text=(
                        f"Nothing keeps {w.label} synced, so {_names(live)} won't be woken by "
                        "mentions and the room can't see whether they're busy."
                    ),
                    fix=f"mycelium machine sync {w.id} on",
                    workspace=w.id,
                )
            )
    s, c = _major_minor(server), _major_minor(client)
    if herdr_up and s and c and s < c:
        problems.append(
            Problem(
                kind="herdr_update",
                text=(
                    f"herdr's server ({server}) is older than its client ({client}). Updating "
                    "restarts the server, which stops every agent in it; resume them after."
                ),
                fix="herdr server stop  (then: mycelium machine resume --all)",
            )
        )
    return problems


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


def resume_line(agent: Agent) -> str | None:
    """The command line resuming ``agent`` runs in its pane, or ``None`` if it can't be."""
    kind = agent_kind(agent.kind)
    session = kind.valid_session(agent.session)
    if session is None:
        return None
    line = shlex.join([kind.kind, *kind.resume_args(session)])
    return f"cd {shlex.quote(_tilde(agent.folder or '.'))} && {line}"


def resume_command(agent: Agent) -> str:
    """What resuming ``agent`` runs, said for a person to read before saying yes."""
    line = resume_line(agent)
    if line is None:
        msg = f"@{agent.handle} has no session to resume"
        raise MachineError(msg)
    return f"{line}   (as @{agent.handle} in {agent.room})"


def resume(config: MyceliumConfig, agent: Agent, *, bridge: HerdrBridge | None = None) -> str:
    """Start ``agent`` again in its pane (or a new one beside it), in its saved session.

    Returns the pane it's running in. The pane gets the agent's handle, room
    and hub in its environment first, as a pane the runner opens would.
    """
    from mycelium.commands.swarm import _start_when_ready

    kind = agent_kind(agent.kind)
    if not agent.resumable:
        if agent.state not in ("stopped", "gone"):
            raise MachineError(f"@{agent.handle} is running ({agent.state}); nothing to resume.")
        if not kind.resumes:
            raise MachineError(
                f"@{agent.handle} runs {kind.name or 'an agent CLI'}, which Mycelium can't resume."
            )
        raise MachineError(
            f"@{agent.handle} can't be resumed: no session was saved for it. "
            f"Find it with `mycelium machine session {agent.handle} --room {agent.room} --find`."
        )
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
        _start_when_ready(bridge, agent.handle, kind.kind, pane, resume=agent.session)
    except HerdrError as e:
        raise MachineError(f"herdr couldn't resume @{agent.handle}: {e}") from e
    bridge.registry.set(
        HerdrPaneMapping(
            room=agent.room,
            handle=agent.handle,
            pane=pane,
            kind=kind.kind,
            managed=_was_managed(bridge, agent),
            session=agent.session,
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
    room that does. A new workspace is bound to the room, so resuming several
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
    """End ``agent``'s session; its pane stays open, so it can be resumed."""
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


def find_session(agent: Agent) -> FoundSession | None:
    """The newest session ``agent``'s CLI started in its folder, if it keeps them where we look.

    A guess, for an agent nothing saved a session for: shown to the person
    before it's kept, never kept on its own.
    """
    if not agent.folder:
        return None
    return agent_kind(agent.kind).find_session(Path(agent.folder))


def save_session(agent: Agent, session: str, *, bridge: HerdrBridge | None = None) -> None:
    """Keep ``session`` as ``agent``'s, so it can be resumed."""
    if agent.host != "herdr":
        raise MachineError(f"@{agent.handle} runs in {agent.host}, which keeps its own sessions.")
    bridge = bridge or HerdrBridge()
    before = bridge.registry.get(agent.room, agent.handle)
    if before is None:
        raise MachineError(f"@{agent.handle} isn't bound to a pane here.")
    kind = agent_kind(before.kind or agent.kind)
    if not kind.resumes:
        raise MachineError(
            f"@{agent.handle} runs {kind.name or 'an agent CLI'}, which Mycelium can't resume."
        )
    valid = kind.valid_session(session)
    if valid is None:
        raise MachineError(f"{session!r} isn't a {kind.name} session id.")
    bridge.registry.set(
        HerdrPaneMapping(
            room=before.room,
            handle=before.handle,
            pane=before.pane,
            kind=kind.kind,
            managed=before.managed,
            session=valid,
            cwd=before.cwd or agent.folder,
        )
    )


def _tilde(path: str) -> str:
    home = str(Path.home())
    return "~" + path[len(home) :] if path.startswith(home) else path
