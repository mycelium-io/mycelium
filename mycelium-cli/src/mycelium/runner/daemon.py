# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The runner: this machine, dialed in to the hub, starting agents in herdr.

Three loops, each on its own thread:

- **hello**: what this machine has (the scan, herdr, the folders agents may be
  started in) and the agents it is running, re-sent as a heartbeat.
- **jobs**: a long-poll for what the app asked for (``launch``, ``stop``,
  ``scan``, ``swarm``), done one at a time and reported back.
- **sync**: ``herdr sync`` over the workspaces this runner opened, so the
  agents it started hear their turns (presence up, doorbells down).

The runner only ever dials out, so it works behind NAT and against a hub
anywhere. A job names a framework from its own scan and a folder inside its
own roots; it never carries a command, so what the hub can ask of this machine
is exactly "start one of the agent CLIs you found, here, in herdr".
"""

from __future__ import annotations

import json
import platform
import re
import secrets
import socket
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from rich.console import Console

from mycelium import __version__
from mycelium.client import hub_client
from mycelium.config import MyceliumConfig
from mycelium.filesystem import get_mycelium_dir
from mycelium.integrations.herdr import HerdrBridge, HerdrError, HerdrPaneMapping
from mycelium.runner import frameworks

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

#: herdr states as the app reads them.
_STATUS = {"idle": "idle", "done": "idle", "working": "working", "blocked": "blocked"}

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


def intro_prompt(room: str, handle: str, *, has_notes: bool) -> str:
    """What a freshly started agent is told: who it is, where, and how turns reach it."""
    who = f"[mycelium] You are @{handle}, a member of the Mycelium room '{room}'. "
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
        f'its thread (`mycelium board send <id> "..." --room {room} --as {handle}`). {later}'
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


class Runner:
    """This machine's runner. ``run()`` blocks; ``stop()`` ends it from another thread."""

    def __init__(
        self,
        config: MyceliumConfig,
        *,
        roots: list[Path],
        bridge: HerdrBridge | None = None,
        rid: str | None = None,
        state_path: Path | None = None,
        log: Console | None = None,
    ) -> None:
        self.config = config
        self.roots = [r.expanduser().resolve() for r in roots]
        self.bridge = bridge or HerdrBridge()
        self.id = rid or runner_id()
        self.label = machine_label()
        self.log = log or Console()
        self._state_path = state_path or runner_dir() / "state.json"
        self.state = State.load(self._state_path)
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
        self.herdr = self.bridge.available()
        self.found = frameworks.scan(self.bridge.supported_kinds() if self.herdr else None)
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
            "roots": [str(r) for r in self.roots],
            "frameworks": [f.wire() for f in self.found],
            "agents": agents,
        }

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
        """Read each tracked agent's state from herdr; a closed pane is a stopped agent."""
        if not self.herdr or not self.state.agents:
            return
        try:
            live = {str(a["pane_id"]): a for a in self.bridge.list_agents() if a.get("pane_id")}
        except HerdrError:
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
                    agent.detail = "its herdr pane closed"
                    agent.stopped_at = _now()
                    self._forget_mapping(agent)
                    changed = True
                    continue
                status = _STATUS.get(str(found.get("agent_status") or ""), "running")
                title = found.get("terminal_title_stripped") or found.get("terminal_title")
                if (status, title) != (agent.status, agent.detail):
                    agent.status, agent.detail = status, title
                    changed = True
            if changed:
                self._release_workspaces()
                self.state.save(self._state_path)

    def _forget_mapping(self, agent: Tracked) -> None:
        mapping = self.bridge.registry.get(agent.room, agent.handle)
        if mapping is not None and mapping.pane == agent.pane:
            self.bridge.registry.remove(agent.room, agent.handle)

    def _release_workspaces(self) -> None:
        """Let go of every workspace this runner opened that none of its agents is live in.

        It stops being synced and its room binding is dropped, so nothing of a
        finished workspace is left in the user's herdr bindings.
        """
        busy = {a.workspace for a in self.state.agents.values() if a.live}
        for workspace in [w for w in self.state.owned if w not in busy]:
            del self.state.owned[workspace]
            self.bridge.registry.unbind(workspace)
            for room in [r for r, (w, _p) in self.state.workspaces.items() if w == workspace]:
                del self.state.workspaces[room]

    def framework(self, framework_id: str) -> frameworks.Known:
        known = frameworks.by_id(framework_id)
        found = next((f for f in self.found if f.id == framework_id), None)
        if known is None or found is None or not found.installed:
            raise JobError(f"{framework_id} is not installed on {self.label}.")
        if not found.launchable or known.herdr_kind is None:
            raise JobError(f"herdr can't start {found.name} here: {found.note or 'no herdr kind'}.")
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

    def open_pane(self, room: str, cwd: Path, env: dict[str, str]) -> tuple[str, str]:
        """A new pane for ``room``: split from its workspace's last pane, or a new workspace."""
        held = self.state.workspaces.get(room)
        if held is not None:
            workspace, last = held
            try:
                pane = self.bridge.split_pane(last, direction="right", cwd=str(cwd), env=env)
            except HerdrError:
                pass
            else:
                self.state.workspaces[room] = (workspace, pane)
                return workspace, pane
        workspace, pane = self.bridge.create_workspace(room, cwd=str(cwd), env=env)
        self.state.workspaces[room] = (workspace, pane)
        return workspace, pane

    def has_notes(self, room: str, handle: str) -> bool:
        try:
            with hub_client(self.config, timeout=10) as client:
                resp = client.get(f"/api/rooms/{room}/memory/agents/{handle}/notes")
        except httpx.HTTPError:
            return False
        return resp.status_code == 200 and resp.content not in (b"", b"null")

    def launch(self, spec: dict[str, Any]) -> dict[str, Any]:
        """Start one agent in a herdr pane, as ``@handle`` in ``room``, and tell it who it is."""
        from mycelium.commands.swarm import _start_when_ready

        if not self.herdr:
            raise JobError(f"herdr isn't running on {self.label}.")
        room, handle = str(spec["room"]), str(spec["handle"])
        known = self.framework(str(spec["framework"]))
        cwd = self.folder(spec.get("cwd"))
        key = f"{room}/{handle}"
        with self._lock:
            running = self.state.agents.get(key)
            if running is not None and running.live:
                if self.bridge.get_agent(running.pane) is not None:
                    return {"pane": running.pane, "already": True}

        workspace, pane = self.open_pane(room, cwd, self.pane_env(room, handle))
        try:
            _start_when_ready(self.bridge, handle, known.herdr_kind or known.id, pane)
        except HerdrError as e:
            self._close_quietly(pane)
            raise JobError(f"herdr could not start {known.name}: {e}") from e
        # Not ``managed``: a closed pane stops the agent, it does not delete it
        # from the room, so the app can start it again with its notes intact.
        self.bridge.registry.set(
            HerdrPaneMapping(room=room, handle=handle, pane=pane, kind=known.herdr_kind)
        )
        self.bridge.registry.bind(workspace, room)
        self.bridge.prompt(
            pane, intro_prompt(room, handle, has_notes=self.has_notes(room, handle)), wait=False
        )
        with self._lock:
            self.state.owned[workspace] = room
            self.state.agents[key] = Tracked(
                handle=handle,
                room=room,
                framework=known.id,
                pane=pane,
                cwd=str(cwd),
                started_at=_now(),
                status="running",
                workspace=workspace,
            )
            self.state.save(self._state_path)
        self.log.print(f"[green]started[/green] @{handle} ({known.name}) in {room} → {pane}")
        return {"pane": pane, "workspace": workspace}

    def _close_quietly(self, pane: str) -> None:
        try:
            self.bridge.close_pane(pane)
        except HerdrError:
            pass

    def stop_agent(self, spec: dict[str, Any]) -> dict[str, Any]:
        key = f"{spec['room']}/{spec['handle']}"
        with self._lock:
            agent = self.state.agents.get(key)
            if agent is None:
                raise JobError(f"{self.label} isn't running @{spec['handle']} in {spec['room']}.")
            self._close_quietly(agent.pane)
            self._forget_mapping(agent)
            agent.status = "stopped"
            agent.detail = "stopped from the app"
            agent.stopped_at = _now()
            self._release_workspaces()
            self.state.save(self._state_path)
        self.log.print(f"[yellow]stopped[/yellow] @{agent.handle} in {agent.room}")
        return {"pane": agent.pane}

    def swarm(self, spec: dict[str, Any], created_by: str | None) -> dict[str, Any]:
        """Open a herdr workspace for a team the hub set up, brief it, and start the kickoff.

        The same steps as ``mycelium swarm`` from a terminal, with the hub's
        manifests in place of the ones the CLI would write.
        """
        from mycelium.commands.swarm import SwarmError, brief_local, kick_off, start_local

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
        raise JobError(f"this runner doesn't know how to do '{kind}'; update mycelium here.")

    def take(self, job: dict[str, Any]) -> None:
        """Do one job and report it; a job that fails says why rather than raising."""
        job_id = str(job["id"])
        self.log.print(
            f"[dim]job {job_id}: {job.get('kind')} {json.dumps(job.get('spec') or {})}[/dim]"
        )
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
        from mycelium.commands.herdr import sync_pass

        while not self._stop.wait(SYNC_S):
            if not self.herdr:
                continue
            # Only the workspaces this runner opened: any other binding is the
            # user's own `herdr sync`'s to keep.
            with self._lock:
                targets = list(self.state.owned.items())
            if not targets:
                continue
            with self._panes:
                self._sync_once(sync_pass, targets)

    def _sync_once(self, sync_pass: Any, targets: list[tuple[str, str]]) -> None:
        try:
            sync_pass(
                self.config,
                self.bridge,
                targets,
                room_filter=None,
                ttl_s=max(90.0, SYNC_S * 4),
                log=self.log,
                wait=False,
            )
        except Exception as e:  # noqa: BLE001 - a missed pass is retried on the next
            self.log.print(f"[dim]herdr sync: {e}[/dim]")

    def run(self) -> None:
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
