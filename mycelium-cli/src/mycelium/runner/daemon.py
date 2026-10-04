# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The runner: this machine, dialed in to the hub, starting agents on its host.

Three loops, each on its own thread:

- **hello**: what this machine has (the scan, whether its host is up, the
  folders agents may be started in), the agents it is running, and every agent
  on the machine (``mycelium.machine``'s report), re-sent as a heartbeat.
- **jobs**: a long-poll for what the app asked for (``launch``, ``stop``,
  ``scan``, ``swarm``, ``restart``), done one at a time and reported back.
- **sync**: presence up and doorbells down for every agent in a workspace
  bound to a room on this machine, so they hear their turns.

Where an agent runs is the host's business (``hosts.py``, picked by
``runner.host``). Everything else here is the same whichever host it is.

The runner only ever dials out, so it works behind NAT and against a hub
anywhere. A job names a framework from its own scan and a folder inside its
own roots; it never carries a command, so what the hub can ask of this machine
is exactly "start one of the agent CLIs you found, here".

Even that is asked of the person here first. Anyone who can reach a hub can
queue a job for any runner on it, so a launch, swarm or restart waits for a yes on
this machine (``approvals``) unless the runner trusts its hub: the Mac app's
own hub, which only this machine can reach, or one the person said to trust
with ``--trust-hub``. Scans and stops don't ask: a scan changes nothing, and a
stop only ends an agent this machine already agreed to start.
"""

from __future__ import annotations

import json
import platform
import re
import secrets
import socket
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from rich.console import Console

from mycelium import __version__
from mycelium import machine as this_machine
from mycelium.client import hub_client
from mycelium.config import MyceliumConfig
from mycelium.filesystem import get_mycelium_dir
from mycelium.integrations.herdr import HerdrBridge, HerdrError
from mycelium.runner import approvals, frameworks
from mycelium.runner.hosts import AgentHost, HerdrHost, HostError, OmnigentHost

#: Jobs that start something on this machine, and so wait for a yes here.
ASK_FIRST = frozenset({"launch", "swarm", "restart"})
#: How much of an agent's instructions the question shows.
NOTES_PREVIEW = 400

#: How often the runner says hello when nothing else has.
HEARTBEAT_S = 10.0
#: How long one long-poll for a job is held by the hub.
POLL_S = 25.0
#: How often herdr presence and doorbells are synced.
SYNC_S = 3.0
#: How long to wait before dialing again after the hub was unreachable.
RETRY_S = 3.0
#: A stopped agent is still listed for this long, so the app can start it again.
KEEP_STOPPED = timedelta(hours=24)

_SLUG = re.compile(r"[^a-z0-9]+")
#: A UUID-shaped identity: an id, not a handle anyone reads.
_OPAQUE_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


class JobError(Exception):
    """A job this runner could not do, said as a sentence for the app to show."""


def runner_dir() -> Path:
    path = get_mycelium_dir() / "runner"
    path.mkdir(parents=True, exist_ok=True)
    return path


def machine_label() -> str:
    return socket.gethostname().removesuffix(".local") or "this machine"


def runner_id(path: Path | None = None) -> str:
    """This machine's runner id, made once and kept, so the app knows it across restarts."""
    path = path or runner_dir() / "id"
    try:
        existing = path.read_text().strip()
    except OSError:
        existing = ""
    if existing:
        return existing
    slug = _SLUG.sub("-", machine_label().lower()).strip("-")[:40] or "runner"
    rid = f"{slug}-{secrets.token_hex(2)}"
    path.write_text(rid + "\n")
    return rid


def intro_prompt(
    room: str, handle: str, *, has_notes: bool, join: tuple[str, str] | None = None
) -> str:
    """What a freshly started agent is told: who it is, where, and how turns reach it.

    ``join`` is ``(code, hub)`` for an agent whose environment doesn't say who it
    is: it joins first, so every command after acts as it.
    """
    who = f"[mycelium] You are @{handle}, a member of the Mycelium room '{room}'. "
    if join is not None:
        code, hub = join
        who += (
            f"First, in the folder you work in, run `mycelium join {code} --hub {hub}` "
            "(install the mycelium CLI first if it isn't there). That makes every "
            "mycelium command you run there act as you. "
        )
    who += "Run `mycelium skill print` and read it: it is how you take part in a room. "
    later = "When a line starting with [mycelium] appears here later, do what it says."
    if has_notes:
        return (
            who + f"Your notes say who you are and how to work: run `mycelium memory get "
            f"agents/{handle}/notes` and follow them. Then run `mycelium board --room {room}` "
            f"to see the work. {later}"
        )
    return (
        who + f"Run `mycelium board --room {room}` to see the work. Take something that fits "
        f"(`mycelium board claim <id> --room {room} --to @{handle}`) and post what you do in "
        f'its thread (`mycelium board send <id> --room {room} --as {handle} --body "..."`). {later}'
    )


@dataclass
class Tracked:
    """An agent this runner started, as it reports it."""

    handle: str
    room: str
    framework: str
    pane: str
    cwd: str | None
    started_at: str
    status: str = "starting"
    detail: str | None = None
    stopped_at: str | None = None
    workspace: str | None = None

    @property
    def live(self) -> bool:
        return self.status not in ("stopped", "failed")

    @property
    def key(self) -> str:
        return f"{self.room}/{self.handle}"

    def wire(self) -> dict:
        return {
            "handle": self.handle,
            "room": self.room,
            "framework": self.framework,
            "status": self.status,
            "pane": self.pane,
            "cwd": self.cwd,
            "started_at": self.started_at,
            "detail": self.detail,
        }


@dataclass
class State:
    """What survives a runner restart: its agents, and the herdr workspaces it opened."""

    agents: dict[str, Tracked] = field(default_factory=dict)
    #: room -> (workspace, the last pane opened there, which the next one splits)
    workspaces: dict[str, tuple[str, str]] = field(default_factory=dict)
    #: workspace -> room, for every workspace this runner opened, swarms included.
    owned: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> State:
        try:
            raw = json.loads(path.read_text())
        except (OSError, ValueError):
            return cls()
        agents = {}
        for entry in raw.get("agents", []):
            try:
                t = Tracked(**entry)
            except TypeError:
                continue
            agents[t.key] = t
        workspaces = {
            str(r): (str(w[0]), str(w[1]))
            for r, w in (raw.get("workspaces") or {}).items()
            if isinstance(w, list) and len(w) == 2
        }
        owned = {str(w): str(r) for w, r in (raw.get("owned") or {}).items()}
        return cls(agents=agents, workspaces=workspaces, owned=owned)

    def save(self, path: Path) -> None:
        body = {
            "agents": [asdict(a) for a in self.agents.values()],
            "workspaces": {r: list(w) for r, w in self.workspaces.items()},
            "owned": self.owned,
        }
        path.write_text(json.dumps(body, indent=2) + "\n")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _tilde(path: Path) -> str:
    home = Path.home()
    return "~/" + str(path.relative_to(home)) if _inside(path, home) and path != home else str(path)


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


class Runner:
    """This machine's runner. ``run()`` blocks; ``stop()`` ends it from another thread."""

    def __init__(
        self,
        config: MyceliumConfig,
        *,
        roots: list[Path],
        bridge: HerdrBridge | None = None,
        host: AgentHost | None = None,
        rid: str | None = None,
        state_path: Path | None = None,
        log: Console | None = None,
        trust_hub: bool = False,
        on_request: Callable[[dict[str, Any]], None] | None = None,
        requests_base: Path | None = None,
    ) -> None:
        self.config = config
        #: Start what the hub asks without asking here: only for a hub nobody else can reach.
        self.trust_hub = trust_hub
        #: Told of each question as it is asked (the Mac app shows it as a dialog).
        self.on_request = on_request
        self._requests_base = requests_base
        self.roots = [r.expanduser().resolve() for r in roots]
        #: herdr's bridge: a swarm is started in herdr whichever host launches do.
        self.bridge = bridge or HerdrBridge()
        #: Where launched agents run (``runner.host``).
        self.host: AgentHost = host or (
            OmnigentHost(config.runner.omnigent_url, sync_every_s=SYNC_S)
            if config.runner.host == "omnigent"
            else HerdrHost(self.bridge, sync_every_s=SYNC_S)
        )
        self.id = rid or runner_id()
        self.label = machine_label()
        self.log = log or Console()
        self._state_path = state_path or runner_dir() / "state.json"
        self.state = State.load(self._state_path)
        #: Whether the host is up. Named ``herdr`` on the wire, which predates hosts.
        self.herdr = False
        self.found: list[frameworks.Found] = []
        self._lock = threading.RLock()
        #: Held while a job opens or closes panes; a sync pass waits it out,
        #: since it would enroll a pane it finds before the job maps it.
        self._panes = threading.Lock()
        self._stop = threading.Event()
        self.connected = False

    # ── what this machine has ────────────────────────────────────────────────

    def scan(self) -> list[frameworks.Found]:
        self.herdr = self.host.available()
        self.found = frameworks.scan(self.host.kinds() if self.herdr else None, host=self.host.name)
        return self.found

    def hello_body(self) -> dict[str, Any]:
        with self._lock:
            agents = [a.wire() for a in self.state.agents.values()]
        return {
            "id": self.id,
            "label": self.label,
            "owner": self.owner(),
            "platform": f"{platform.system().lower()}-{platform.machine().lower()}",
            "version": __version__,
            "herdr": self.herdr,
            "host": self.host.name,
            "roots": [str(r) for r in self.roots],
            "frameworks": [f.wire() for f in self.found],
            "agents": agents,
            "machine": self.machine_report(),
        }

    def machine_report(self) -> dict[str, Any] | None:
        """Every agent on this machine, for the Machines page (``mycelium machine``'s report)."""
        if self.host.name != "herdr":
            return None
        try:
            return this_machine.report(bridge=self.bridge, machine=self.label, runner=True).wire()
        except Exception as e:  # noqa: BLE001 - a heartbeat must not fail on its report
            self.log.print(f"[dim]couldn't read this machine's agents: {e}[/dim]")
            return None

    def _restartable(self, spec: dict[str, Any]) -> list[this_machine.Agent]:
        """The agents a ``restart`` job names, read now, each one restartable."""
        r = this_machine.report(bridge=self.bridge, machine=self.label, runner=True)
        try:
            if spec.get("all"):
                agents = [a for a in r.agents if a.restartable]
            else:
                agents = [
                    r.find(str(a.get("handle")), a.get("room")) for a in spec.get("agents") or []
                ]
        except this_machine.MachineError as e:
            raise JobError(str(e)) from e
        if not agents:
            raise JobError(f"No agent on {self.label} has stopped.")
        if not_ready := [a for a in agents if not a.restartable]:
            names = ", ".join(f"@{a.handle}" for a in not_ready)
            raise JobError(f"{names} can't be restarted: it's running, or nothing says how.")
        return agents

    def restart_agents(self, spec: dict[str, Any]) -> dict[str, Any]:
        """Start stopped agents again, as themselves (``mycelium machine restart``)."""
        restarted: dict[str, str] = {}
        failed: dict[str, str] = {}
        for agent in self._restartable(spec):
            try:
                restarted[agent.handle] = this_machine.restart(
                    self.config, agent, bridge=self.bridge
                )
            except this_machine.MachineError as e:
                failed[agent.handle] = str(e)
        if failed and not restarted:
            raise JobError("; ".join(failed.values()))
        self.log.print(f"[green]restarted[/green] {', '.join('@' + h for h in restarted)}")
        return {"restarted": restarted, "failed": failed}

    def owner(self) -> str | None:
        """Whose agents these are: this machine's identity when it reads as a handle.

        An identity that is an opaque id (an IdP subject, say) names no one a
        person would recognize on the roster, so the login name stands in, as
        ``mycelium swarm`` does when there is no identity at all.
        """
        import getpass

        me = self.config.get_current_identity()
        if me and me != "unknown" and not _OPAQUE_ID.match(me):
            return me
        try:
            login = _SLUG.sub("-", getpass.getuser().lower()).strip("-")
        except Exception:  # noqa: BLE001 - no login name leaves the agents unowned
            login = ""
        return login or None

    # ── talking to the hub ───────────────────────────────────────────────────

    def hello(self) -> bool:
        """Say hello (or heartbeat). ``False`` when the hub could not be reached."""
        self.refresh()
        try:
            with hub_client(self.config, timeout=10) as client:
                client.post("/api/runners", json=self.hello_body()).raise_for_status()
        except httpx.HTTPError as e:
            if self.connected:
                self.log.print(f"[yellow]lost the hub:[/yellow] {e}")
            self.connected = False
            return False
        if not self.connected:
            self.log.print(f"[green]connected[/green] to {self.config.server.api_url} as {self.id}")
        self.connected = True
        return True

    def goodbye(self) -> None:
        try:
            with hub_client(self.config, timeout=5) as client:
                client.delete(f"/api/runners/{self.id}")
        except httpx.HTTPError:
            pass

    def _report(self, job_id: str, status: str, result: dict | None, error: str | None) -> None:
        body = {"status": status, "result": result, "error": error}
        try:
            with hub_client(self.config, timeout=10) as client:
                client.patch(f"/api/runners/{self.id}/jobs/{job_id}", json=body)
        except httpx.HTTPError as e:
            self.log.print(f"[yellow]could not report job {job_id}:[/yellow] {e}")

    # ── agents ───────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        """Read each tracked agent's state from its host; one the host no longer has has stopped."""
        if not self.herdr or not self.state.agents:
            return
        live = self.host.statuses()
        if live is None:
            return
        cutoff = datetime.now(UTC) - KEEP_STOPPED
        changed = False
        with self._lock:
            for key, agent in list(self.state.agents.items()):
                if agent.status in ("stopped", "failed"):
                    if agent.stopped_at and datetime.fromisoformat(agent.stopped_at) < cutoff:
                        del self.state.agents[key]
                        changed = True
                    continue
                found = live.get(agent.pane)
                if found is None:
                    agent.status = "stopped"
                    agent.detail = self.host.gone_detail
                    agent.stopped_at = _now()
                    self.host.gone(agent)
                    changed = True
                    continue
                if found != (agent.status, agent.detail):
                    agent.status, agent.detail = found
                    changed = True
            if changed:
                self.host.release(self.state)
                self.state.save(self._state_path)

    def framework(self, framework_id: str) -> frameworks.Known:
        known = frameworks.by_id(framework_id)
        found = next((f for f in self.found if f.id == framework_id), None)
        if known is None or found is None or not found.installed:
            raise JobError(f"{framework_id} is not installed on {self.label}.")
        if not found.launchable or known.herdr_kind is None:
            host = self.host.name
            raise JobError(
                f"{host} can't start {found.name} here: {found.note or f'no {host} kind'}."
            )
        return known

    def folder(self, cwd: str | None) -> Path:
        """``cwd`` as a real folder inside one of the roots, or why it may not be used."""
        if not self.roots:
            raise JobError(f"{self.label} has no folders agents may start in.")
        if not cwd:
            return self.roots[0]
        path = Path(cwd).expanduser().resolve()
        if not any(_inside(path, root) for root in self.roots):
            raise JobError(f"{cwd} is outside the folders {self.label} may start agents in.")
        if not path.is_dir():
            raise JobError(f"{cwd} is not a folder on {self.label}.")
        return path

    def pane_env(self, room: str, handle: str) -> dict[str, str]:
        return {
            "MYCELIUM_API_URL": self.config.server.api_url,
            "MYCELIUM_AGENT_HANDLE": handle,
            "MYCELIUM_ROOM_ID": room,
        }

    def join_code(self, room: str, handle: str) -> str:
        """A join code for ``@handle``, asked of the hub as this machine's owner."""
        try:
            with hub_client(self.config, timeout=15) as client:
                resp = client.post(f"/api/rooms/{room}/joins", json={"handle": handle})
        except httpx.HTTPError as e:
            raise JobError(f"couldn't ask the hub for a join code for @{handle}: {e}") from e
        if resp.status_code != 201:
            raise JobError(f"the hub wouldn't give a join code for @{handle}: {resp.text[:200]}")
        return str(resp.json()["code"])

    def notes(self, room: str, handle: str) -> str | None:
        """An agent's notes as the hub has them, or ``None`` when it has none."""
        try:
            with hub_client(self.config, timeout=10) as client:
                resp = client.get(f"/api/rooms/{room}/memory/agents/{handle}/notes")
        except httpx.HTTPError:
            return None
        if resp.status_code != 200 or resp.content in (b"", b"null"):
            return None
        try:
            body = resp.json()
        except ValueError:
            return None
        value = body.get("value") if isinstance(body, dict) else None
        return str(value) if value else None

    def has_notes(self, room: str, handle: str) -> bool:
        return self.notes(room, handle) is not None

    def launch(self, spec: dict[str, Any]) -> dict[str, Any]:
        """Start one agent on this machine's host, as ``@handle`` in ``room``, and tell it who it is."""
        if not self.herdr:
            raise JobError(f"{self.host.name} isn't running on {self.label}.")
        room, handle = str(spec["room"]), str(spec["handle"])
        known = self.framework(str(spec["framework"]))
        cwd = self.folder(spec.get("cwd"))
        key = f"{room}/{handle}"
        with self._lock:
            running = self.state.agents.get(key)
            if running is not None and running.live and self.host.alive(running.pane):
                return {"pane": running.pane, "already": True}

        join = (
            (self.join_code(room, handle), self.config.server.api_url) if self.host.joins else None
        )
        intro = intro_prompt(room, handle, has_notes=self.has_notes(room, handle), join=join)
        try:
            started = self.host.start(
                self.state,
                room=room,
                handle=handle,
                kind=known.herdr_kind or known.id,
                cwd=cwd,
                env=self.pane_env(room, handle),
                intro=intro,
            )
        except HostError as e:
            raise JobError(f"{self.host.name} could not start {known.name}: {e}") from e
        with self._lock:
            self.state.agents[key] = Tracked(
                handle=handle,
                room=room,
                framework=known.id,
                pane=started.ref,
                cwd=started.cwd or str(cwd),
                started_at=_now(),
                status="running",
                workspace=started.workspace,
            )
            self.state.save(self._state_path)
        self.log.print(f"[green]started[/green] @{handle} ({known.name}) in {room} → {started.ref}")
        result = {"pane": started.ref}
        if started.workspace:
            result["workspace"] = started.workspace
        return result

    def stop_agent(self, spec: dict[str, Any]) -> dict[str, Any]:
        key = f"{spec['room']}/{spec['handle']}"
        with self._lock:
            agent = self.state.agents.get(key)
            if agent is None:
                raise JobError(f"{self.label} isn't running @{spec['handle']} in {spec['room']}.")
            self.host.stop(agent)
            agent.status = "stopped"
            agent.detail = "stopped from the app"
            agent.stopped_at = _now()
            self.host.release(self.state)
            self.state.save(self._state_path)
        self.log.print(f"[yellow]stopped[/yellow] @{agent.handle} in {agent.room}")
        return {"pane": agent.pane}

    def swarm(self, spec: dict[str, Any], created_by: str | None) -> dict[str, Any]:
        """Open a herdr workspace for a team the hub set up, brief it, and start the kickoff.

        The same steps as ``mycelium swarm`` from a terminal, with the hub's
        manifests in place of the ones the CLI would write.
        """
        from mycelium.commands.swarm import SwarmError, brief_local, kick_off, start_local

        if self.host.name != "herdr":
            raise JobError(
                f"{self.label} starts agents in {self.host.name}; a swarm starts in herdr for now."
            )
        if not self.herdr:
            raise JobError(f"herdr isn't running on {self.label}.")
        room, key, episode = str(spec["room"]), str(spec["key"]), str(spec["episode"])
        task, team = str(spec["task"]), [str(h) for h in spec["team"]]
        known = self.framework(str(spec["framework"]))
        cwd = self.folder(spec.get("cwd"))
        me = created_by or self.owner() or "web-ui"
        try:
            local = start_local(
                self.config,
                self.bridge,
                room,
                team,
                kind=known.herdr_kind or known.id,
                cwd=cwd,
                worktree=bool(spec.get("worktree")),
                me=me,
                write_manifests=False,
                carry={"MYCELIUM_API_URL": self.config.server.api_url},
            )
            with hub_client(self.config, timeout=30) as client:
                brief_local(client, self.bridge, room, local, key, task, me)
                if spec.get("kickoff", True):
                    kick_off(client, room, episode, team, task, me)
        except (SwarmError, HerdrError) as e:
            raise JobError(str(e)) from e
        with self._lock:
            self.state.owned[local.workspace] = room
            for handle, pane in local.panes.items():
                self.state.agents[f"{room}/{handle}"] = Tracked(
                    handle=handle,
                    room=room,
                    framework=known.id,
                    pane=pane,
                    cwd=str(cwd),
                    started_at=_now(),
                    status="running",
                    workspace=local.workspace,
                )
            self.state.save(self._state_path)
        self.log.print(
            f"[green]swarm[/green] of {len(team)} on {key} in {room} → {local.workspace}"
        )
        return {"workspace": local.workspace, "panes": local.panes}

    # ── jobs ─────────────────────────────────────────────────────────────────

    def do(self, job: dict[str, Any]) -> dict[str, Any]:
        kind, spec = job.get("kind"), job.get("spec") or {}
        if kind == "launch":
            return self.launch(spec)
        if kind == "stop":
            return self.stop_agent(spec)
        if kind == "scan":
            found = self.scan()
            return {"installed": [f.id for f in found if f.installed]}
        if kind == "swarm":
            return self.swarm(spec, job.get("created_by"))
        if kind == "restart":
            return self.restart_agents(spec)
        raise JobError(f"this runner doesn't know how to do '{kind}'; update mycelium here.")

    def question(self, job: dict[str, Any]) -> dict[str, Any]:
        """What the person here is asked before ``job`` runs, checked against this machine first.

        A job this machine couldn't do anyway fails with ``JobError`` without
        asking anyone. Who asked is what the hub says, which it can't prove;
        the question says so.
        """
        kind, spec = job.get("kind"), job.get("spec") or {}
        hub = urlparse(self.config.server.api_url).netloc or self.config.server.api_url
        asked_by = job.get("created_by")
        if kind == "restart":
            agents = self._restartable(spec)
            lines = "\n".join(this_machine.restart_command(a) for a in agents)
            n = len(agents)
            return {
                "kind": kind,
                "title": f"Restart {n} agent{'s' if n != 1 else ''} on {self.label}?",
                "message": (
                    f"Each starts again as itself and catches up from the room:\n{lines}\n\n"
                    f"Asked for by {'@' + asked_by if asked_by else 'someone'} on {hub}."
                ),
                "hub": hub,
                "asked_by": asked_by,
            }
        known = self.framework(str(spec.get("framework")))
        cwd = self.folder(spec.get("cwd"))
        room = str(spec.get("room"))
        where = f"Room {room} on {hub}. Asked for by {'@' + asked_by if asked_by else 'someone on that hub'}."
        if kind == "launch":
            handle = str(spec.get("handle"))
            title = f"Start @{handle} on {self.label}?"
            message = f"{known.name} would start as @{handle}, working in {_tilde(cwd)}.\n\n{where}"
            if notes := self.notes(room, handle):
                message += f"\n\nIts instructions:\n{_clip(notes, NOTES_PREVIEW)}"
        else:
            team = [f"@{h}" for h in spec.get("team") or []]
            title = f"Start a team of {len(team)} on {self.label}?"
            message = (
                f"{', '.join(team)} would start in {known.name}, working in {_tilde(cwd)}, "
                f"on: {_clip(str(spec.get('task') or ''), 200)}\n\n{where}"
            )
        return {"kind": kind, "title": title, "message": message, "hub": hub, "asked_by": asked_by}

    def take(self, job: dict[str, Any]) -> None:
        """Do one job and report it; a job that fails says why rather than raising.

        A job that starts something waits for a yes here, on its own thread,
        so a stop or a scan isn't held up behind a question nobody has seen.
        """
        job_id = str(job["id"])
        self.log.print(
            f"[dim]job {job_id}: {job.get('kind')} {json.dumps(job.get('spec') or {})}[/dim]"
        )
        if job.get("kind") in ASK_FIRST and not self.trust_hub:
            threading.Thread(target=self._take_once_approved, args=(job,), daemon=True).start()
            return
        self._do_and_report(job)

    def _take_once_approved(self, job: dict[str, Any]) -> None:
        job_id = str(job["id"])
        try:
            request = approvals.ask(job_id, self.question(job), base=self._requests_base)
        except (JobError, approvals.ApprovalError) as e:
            self._report(job_id, "failed", None, str(e))
            self.log.print(f"[red]job {job_id} failed:[/red] {e}")
            return
        self._report(job_id, "waiting", None, None)
        self.log.print(
            f"\n[bold]{request['title']}[/bold]\n{request['message']}\n"
            f"Start it: [cyan]mycelium runner approve {job_id}[/cyan]  "
            f"Decline: [cyan]mycelium runner decline {job_id}[/cyan]\n"
        )
        if self.on_request is not None:
            try:
                self.on_request(request)
            except Exception as e:  # noqa: BLE001 - the terminal still has the question
                self.log.print(f"[dim]couldn't show the question: {e}[/dim]")
        answer = approvals.wait(job_id, self._stop, base=self._requests_base)
        approvals.forget(job_id, base=self._requests_base)
        if answer is True:
            self._do_and_report(job)
            return
        if answer is False:
            error = f"Declined on {self.label}."
        elif self._stop.is_set():
            error = f"The runner on {self.label} stopped before anyone answered."
        else:
            error = f"Nobody on {self.label} answered in time."
        self._report(job_id, "failed", None, error)
        self.log.print(f"[yellow]job {job_id}:[/yellow] {error}")

    def _do_and_report(self, job: dict[str, Any]) -> None:
        job_id = str(job["id"])
        try:
            with self._panes:
                result = self.do(job)
        except JobError as e:
            self._report(job_id, "failed", None, str(e))
            self.log.print(f"[red]job {job_id} failed:[/red] {e}")
        except Exception as e:  # noqa: BLE001 - a job must always be reported
            self._report(job_id, "failed", None, f"the runner hit an error: {e}")
            self.log.print(f"[red]job {job_id} failed:[/red] {e!r}")
        else:
            self._report(job_id, "done", result, None)
        self.hello()

    def poll_once(self) -> bool:
        """One long-poll; ``False`` when the hub could not be reached or forgot this runner."""
        try:
            with hub_client(self.config, timeout=POLL_S + 15) as client:
                resp = client.get(f"/api/runners/{self.id}/jobs/next", params={"timeout": POLL_S})
        except httpx.HTTPError:
            return False
        if resp.status_code == 404:
            # The hub restarted, or dropped this runner: say hello again.
            return self.hello()
        if resp.status_code == 204 or not resp.content:
            return True
        if resp.status_code >= 400:
            return False
        self.take(resp.json())
        return True

    # ── loops ────────────────────────────────────────────────────────────────

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(HEARTBEAT_S):
            self.hello()

    def _sync_loop(self) -> None:
        while not self._stop.wait(SYNC_S):
            if not self.herdr:
                continue
            with self._panes:
                self._sync_once()

    def _sync_once(self) -> None:
        try:
            self.host.sync(self.config, self.state, self.log)
        except Exception as e:  # noqa: BLE001 - a missed pass is retried on the next
            self.log.print(f"[dim]{self.host.name} sync: {e}[/dim]")

    def run(self) -> None:
        # Questions left by a runner that stopped are about jobs nobody is waiting on.
        approvals.forget_all(base=self._requests_base)
        self.scan()
        while not self.hello():
            self.log.print(
                f"[dim]hub not reachable at {self.config.server.api_url}; retrying…[/dim]"
            )
            if self._stop.wait(RETRY_S):
                return
        for loop in (self._heartbeat_loop, self._sync_loop):
            threading.Thread(target=loop, daemon=True).start()
        while not self._stop.is_set():
            if not self.poll_once():
                self._stop.wait(RETRY_S)
        self.goodbye()

    def stop(self) -> None:
        self._stop.set()
