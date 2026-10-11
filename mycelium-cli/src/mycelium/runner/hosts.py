# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Where the runner starts agents: its host.

The runner decides *what* to start (a framework from its scan, in a folder
inside its roots, as a member of a room) and asks the person here first. An
``AgentHost`` is *where*: it opens somewhere for the agent to run, starts it,
reports whether it is still there and what it's doing, hands it its wakes, and
stops it. ``runner.host`` in config picks one; each class below says how it
does those things.

A host that can't tell an agent who it is through its environment sets
``joins``: the runner then asks the hub for a join code and puts it first in the
agent's introduction (``mycelium.commands.join``).
"""

from __future__ import annotations

import logging
import platform
import re
import time
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

import httpx
from rich.console import Console

from mycelium.integrations.herdr import (
    PANES_PER_TAB,
    HerdrBridge,
    HerdrError,
    HerdrPaneMapping,
)
from mycelium.runner.log import ms

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig
    from mycelium.runner.daemon import State, Tracked


#: Wakes delivered, in the runner's log.
_log = logging.getLogger("mycelium.runner.sync")


#: The steps of a start, as the runner reports them and the app draws them:
#: a terminal opened for the agent, its shell reached a prompt and the agent
#: CLI started in it, and the agent came up.
STEP_TERMINAL, STEP_SHELL, STEP_AGENT = "terminal", "shell", "agent"


class HostError(Exception):
    """A host couldn't do what it was asked; the message says why, for a person.

    A start that got partway also says which step it stopped at (``step``), the
    terminal it left open for the person to look at (``ref``) and what that
    terminal showed (``screen``).
    """

    def __init__(
        self,
        message: str,
        *,
        step: str | None = None,
        ref: str | None = None,
        screen: str | None = None,
    ) -> None:
        super().__init__(message)
        self.step = step
        self.ref = ref
        self.screen = screen


class StartHooks:
    """What a host tells the runner while it starts an agent. Does nothing by default."""

    def step(self, step: str) -> None:
        """The start reached ``step`` (``STEP_TERMINAL``, ``STEP_SHELL``...)."""

    def unlocked(self) -> AbstractContextManager[None]:
        """Held while the host waits on the agent, with nothing of the runner's locked."""
        return nullcontext()


@dataclass
class Started:
    """Where a started agent runs."""

    #: How the host names it: a herdr pane, an Omnigent session id.
    ref: str
    #: The herdr workspace it was opened in, when there is one.
    workspace: str | None = None
    #: The folder it works in, when the host chose another (an Omnigent worktree).
    cwd: str | None = None
    #: Its state in the app's words, when it isn't plain running: ``blocked`` is
    #: an agent that came up waiting for input from the person at the machine.
    status: str | None = None
    #: Its introduction wasn't handed over: the runner gives it once the agent is idle.
    intro_pending: bool = False


class AgentHost(Protocol):
    #: The host's name, as ``runner.host`` spells it; said in the hello and in messages.
    name: str
    #: The agent learns who it is from a join code in its first message, rather
    #: than from the environment of where it runs.
    joins: bool
    #: The host gives each agent its own git worktree itself, so the runner
    #: makes none when a launch asks for one.
    worktrees: bool
    #: Why an agent the host no longer has reads as stopped, for a person.
    gone_detail: str

    def available(self) -> bool:
        """Whether agents can be started here right now."""
        ...

    def kinds(self) -> set[str] | None:
        """The agent kinds this host can start (``claude``, ``codex``...), or ``None`` if it's down."""
        ...

    def start(
        self,
        state: State,
        *,
        room: str,
        handle: str,
        kind: str,
        cwd: Path,
        env: dict[str, str],
        intro: str,
        hooks: StartHooks | None = None,
    ) -> Started:
        """Start ``kind`` as ``@handle`` and give it ``intro``. Raises :class:`HostError`.

        ``hooks`` hears each step as it's reached, and is asked to unlock the
        runner while the host waits on the agent.
        """
        ...

    def alive(self, ref: str) -> bool:
        """Whether the agent at ``ref`` is still there."""
        ...

    def statuses(self) -> dict[str, tuple[str, str | None]] | None:
        """``{ref: (status, title)}`` for every agent it has; ``None`` when it can't be read.

        A status is the app's word: ``idle``, ``working`` or ``blocked``.
        """
        ...

    def blocker(self, ref: str, kind: str) -> str | None:
        """What a person needs to answer the ``blocked`` agent at ``ref``: what its
        screen shows and how to get to it. ``None`` when the host can't say."""
        ...

    def wake(self, ref: str, text: str) -> None:
        """Hand the agent at ``ref`` a message. Raises :class:`HostError`."""
        ...

    def stop(self, agent: Tracked) -> None:
        """End the agent. Best-effort: one that's already gone is stopped."""
        ...

    def interrupt(self, ref: str, kind: str | None) -> bool:
        """Stop the agent at ``ref`` mid-turn, keeping its session. ``True`` if it was
        working and was sent its key.

        Only a working agent is interrupted: on an idle one the key could clear
        what a person was typing into it. ``kind`` picks the key. What it is told
        comes after, as the wake the hub queued, once it is idle.
        """
        ...

    def gone(self, agent: Tracked) -> None:
        """Forget what this host kept about an agent that has stopped."""
        ...

    def release(self, state: State) -> None:
        """Let go of whatever the runner opened that no live agent uses any more."""
        ...

    def sync(self, config: MyceliumConfig, state: State, log: Console) -> None:
        """One pass of presence up to the hub and wakes down to the agents."""
        ...


# ── herdr ────────────────────────────────────────────────────────────────────

#: herdr states as the app reads them.
_HERDR_STATUS = {"idle": "idle", "done": "idle", "working": "working", "blocked": "blocked"}
#: How many of a blocked agent's last screen lines the app is shown.
_BLOCKER_LINES = 6


class HerdrHost:
    """Each agent in a herdr pane on this machine.

    The pane's environment says which member it is, and herdr's workspace sync
    (``commands.herdr.sync_pass``) pushes presence and delivers wakes, waiting
    for an agent to be idle before it wakes it.
    """

    name = "herdr"
    joins = False
    worktrees = False
    gone_detail = "its herdr pane closed"

    def __init__(
        self,
        bridge: HerdrBridge | None = None,
        *,
        sync_every_s: float = 3.0,
        panes_per_tab: int = PANES_PER_TAB,
    ) -> None:
        self.bridge = bridge or HerdrBridge()
        self._ttl_s = max(90.0, sync_every_s * 4)
        self._per_tab = panes_per_tab

    def available(self) -> bool:
        return self.bridge.available()

    def kinds(self) -> set[str] | None:
        return self.bridge.supported_kinds()

    def _open_pane(
        self, state: State, room: str, handle: str, cwd: Path, env: dict[str, str]
    ) -> tuple[str, str]:
        """A new pane for ``room``, placed in its workspace, or a new workspace."""
        held = state.workspaces.get(room)
        workspace, pane = self.bridge.place_pane(
            room,
            held[0] if held else None,
            handle=handle,
            cwd=str(cwd),
            env=env,
            per_tab=self._per_tab,
        )
        state.workspaces[room] = (workspace, pane)
        return workspace, pane

    def _left_open(
        self, state: State, room: str, handle: str, kind: str, cwd: Path
    ) -> tuple[str, str] | None:
        """The pane an earlier start of ``@handle`` left open, if it's still there to start in.

        A start that fails leaves its pane open, so starting again goes back to
        it rather than opening another one each time. Only a pane in the same
        folder, and not holding some other kind of agent, is taken back.
        """
        mapping = self.bridge.registry.get(room, handle)
        if mapping is None or mapping.cwd != str(cwd):
            return None
        try:
            panes = self.bridge.list_panes()
        except HerdrError:
            return None
        found = next((p for p in panes if str(p.get("pane_id")) == mapping.pane), None)
        workspace = str(found.get("workspace_id") or "") if found else ""
        if not workspace:
            return None
        agent = self.bridge.get_agent(mapping.pane)
        if agent is not None and mapping.kind != kind:
            return None
        state.workspaces[room] = (workspace, mapping.pane)
        return workspace, mapping.pane

    def start(
        self,
        state: State,
        *,
        room: str,
        handle: str,
        kind: str,
        cwd: Path,
        env: dict[str, str],
        intro: str,
        hooks: StartHooks | None = None,
    ) -> Started:
        from mycelium.commands.swarm import _start_when_ready
        from mycelium.integrations.herdr import ShellNotReadyError

        hooks = hooks or StartHooks()
        hooks.step(STEP_TERMINAL)
        workspace, pane = self._left_open(state, room, handle, kind, cwd) or self._open_pane(
            state, room, handle, cwd, env
        )
        # Mapped before anything starts in it, so a sync pass that finds the
        # agent knows whose it is, and the wait below needs no lock against one.
        # Not ``managed``: a closed pane stops the agent, it does not delete it
        # from the room, so the app can start it again with its notes intact.
        # Its folder is kept so it can be restarted there.
        self.bridge.registry.set(
            HerdrPaneMapping(room=room, handle=handle, pane=pane, kind=kind, cwd=str(cwd))
        )
        self.bridge.registry.bind(workspace, room)
        state.owned[workspace] = room
        hooks.step(STEP_SHELL)
        try:
            with hooks.unlocked():
                came_up = _start_when_ready(self.bridge, handle, kind, pane)
        except HerdrError as e:
            # The pane stays open: whatever it shows (a shell still starting, an
            # update or sign-in the agent CLI asks for first) is the person's to
            # see and answer, and starting again goes back to it.
            raise HostError(
                str(e),
                step=STEP_SHELL if isinstance(e, ShellNotReadyError) else STEP_AGENT,
                ref=pane,
                screen=self.bridge.read_pane(pane, lines=_BLOCKER_LINES),
            ) from e
        if came_up is not None:
            # It started but never read as ready, most often stopped at a prompt.
            # The pane stays open for the person to answer, and the introduction
            # waits until the agent is idle rather than being typed into it.
            status = _HERDR_STATUS.get(str(came_up.get("agent_status") or ""), "running")
            return Started(ref=pane, workspace=workspace, status=status, intro_pending=True)
        self.bridge.prompt(pane, intro, wait=False)
        return Started(ref=pane, workspace=workspace)

    def alive(self, ref: str) -> bool:
        return self.bridge.get_agent(ref) is not None

    def statuses(self) -> dict[str, tuple[str, str | None]] | None:
        try:
            agents = self.bridge.list_agents()
        except HerdrError:
            return None
        return {
            str(a["pane_id"]): (
                _HERDR_STATUS.get(str(a.get("agent_status") or ""), "running"),
                a.get("terminal_title_stripped") or a.get("terminal_title"),
            )
            for a in agents
            if a.get("pane_id")
        }

    def blocker(self, ref: str, kind: str) -> str | None:
        from mycelium.integrations.agents import of_kind

        parts = [self.bridge.read_pane(ref, lines=_BLOCKER_LINES), of_kind(kind).blocked_hint()]
        parts.append(f"Answer it in its pane: herdr agent focus {ref}")
        return "\n".join(p for p in parts if p)

    def wake(self, ref: str, text: str) -> None:
        try:
            self.bridge.prompt(ref, text, wait=False)
        except HerdrError as e:
            raise HostError(str(e)) from e

    def _close_quietly(self, pane: str) -> None:
        try:
            self.bridge.close_pane(pane)
        except HerdrError:
            pass

    def stop(self, agent: Tracked) -> None:
        self._close_quietly(agent.pane)
        self.gone(agent)

    def interrupt(self, ref: str, kind: str | None) -> bool:
        from mycelium.integrations.agents import of_kind

        agent = self.bridge.get_agent(ref)
        if agent is None or agent.get("agent_status") != "working":
            return False
        try:
            self.bridge.send_keys(ref, of_kind(kind or agent.get("agent")).interrupt_key())
        except HerdrError as e:
            raise HostError(f"couldn't interrupt the agent in {ref}: {e}") from e
        return True

    def gone(self, agent: Tracked) -> None:
        mapping = self.bridge.registry.get(agent.room, agent.handle)
        if mapping is not None and mapping.pane == agent.pane:
            self.bridge.registry.remove(agent.room, agent.handle)

    def release(self, state: State) -> None:
        """Let go of every workspace the runner opened that none of its agents is live in.

        It stops being synced and its room binding is dropped, so nothing of a
        finished workspace is left in the user's herdr bindings.
        """
        busy = {a.workspace for a in state.agents.values() if a.live}
        for workspace in [w for w in state.owned if w not in busy]:
            del state.owned[workspace]
            self.bridge.registry.unbind(workspace)
            for room in [r for r, (w, _p) in state.workspaces.items() if w == workspace]:
                del state.workspaces[room]

    def sync(self, config: MyceliumConfig, state: State, log: Console) -> None:
        from mycelium.commands.herdr import BindingSyncError, sync_pass

        # Every workspace bound to a room on this machine: the ones this runner
        # opened and any a person bound (`mycelium herdr sync --workspace …`).
        # Binding one is the choice to sync it, and the runner is what does.
        targets = dict(state.owned) | self.bridge.registry.bindings()
        if not targets:
            return
        result = sync_pass(
            config,
            self.bridge,
            list(targets.items()),
            room_filter=None,
            ttl_s=self._ttl_s,
            log=log,
            wait=False,
        )
        if result.failed:
            raise BindingSyncError(result.failed)


# ── Omnigent ─────────────────────────────────────────────────────────────────

#: Omnigent's session states as the app reads them.
_OMNIGENT_STATUS = {"idle": "idle", "running": "working", "waiting": "blocked", "failed": "blocked"}
#: A built-in Omnigent agent that runs a CLI in its own terminal: ``claude-native-ui``.
_NATIVE_AGENT = re.compile(r"^(?P<kind>[a-z0-9]+)-native-ui$")
#: What a session's labels say it is, so the runner can find its own.
ROOM_LABEL, HANDLE_LABEL = "mycelium_room", "mycelium_handle"
_BRANCH_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


class OmnigentHost:
    """Each agent as a session on this machine's Omnigent host.

    Omnigent gives a session no environment of its own, so the agent learns who
    it is from a join code. A session gets its own git worktree when the folder
    is a repository, which is what gives each agent its own membership. Wakes
    are posted as messages, which Omnigent queues when the agent is busy.
    """

    name = "omnigent"
    joins = True
    worktrees = True
    gone_detail = "its Omnigent session ended"

    def __init__(
        self,
        url: str,
        *,
        transport: httpx.BaseTransport | None = None,
        machine: str | None = None,
        sync_every_s: float = 3.0,
    ) -> None:
        self.url = url.rstrip("/")
        self._transport = transport
        #: This machine's name as its Omnigent host registered it.
        self.machine = machine or platform.node()
        self._ttl_s = max(90.0, sync_every_s * 4)
        #: kind -> Omnigent agent id, from the last :meth:`kinds`.
        self._agents: dict[str, str] = {}
        self._host: dict[str, Any] | None = None

    # ── talking to Omnigent ──────────────────────────────────────────────────

    def _client(self) -> httpx.Client:
        return httpx.Client(base_url=self.url, timeout=15.0, transport=self._transport)

    def _get(self, path: str, **params: Any) -> Any:
        try:
            with self._client() as client:
                resp = client.get(path, params=params or None)
        except httpx.HTTPError as e:
            raise HostError(f"Omnigent isn't reachable at {self.url}: {e}") from e
        if resp.status_code >= 400:
            raise HostError(f"Omnigent said {resp.status_code} to GET {path}: {resp.text[:200]}")
        return resp.json()

    def _post(self, path: str, body: Any) -> Any:
        try:
            with self._client() as client:
                resp = client.post(path, json=body)
        except httpx.HTTPError as e:
            raise HostError(f"Omnigent isn't reachable at {self.url}: {e}") from e
        if resp.status_code >= 400:
            raise HostError(f"Omnigent said {resp.status_code} to POST {path}: {resp.text[:200]}")
        return resp.json() if resp.content else {}

    def _this_host(self) -> dict[str, Any]:
        """This machine's Omnigent host: the online one registered under its name."""
        hosts = self._get("/v1/hosts").get("hosts", [])
        online = [h for h in hosts if h.get("status") == "online"]
        mine = [h for h in online if h.get("name") == self.machine]
        if not mine:
            raise HostError(
                f"no Omnigent host for {self.machine} is online at {self.url}; "
                "run `omnigent start` on this machine"
            )
        self._host = mine[0]
        return self._host

    # ── the host ─────────────────────────────────────────────────────────────

    def available(self) -> bool:
        try:
            self._this_host()
        except HostError:
            return False
        return True

    def kinds(self) -> set[str] | None:
        """The kinds with a native Omnigent agent whose harness this host has ready."""
        try:
            host = self._this_host()
            listed = self._get("/v1/agents")
        except HostError:
            return None
        rows = listed.get("data", listed) if isinstance(listed, dict) else listed
        ready = host.get("configured_harnesses") or {}
        agents: dict[str, str] = {}
        for row in rows if isinstance(rows, list) else []:
            match = _NATIVE_AGENT.match(str(row.get("name") or ""))
            if match and ready.get(f"{match['kind']}-native") is True:
                agents[match["kind"]] = str(row["id"])
        self._agents = agents
        return set(agents)

    def start(
        self,
        state: State,  # noqa: ARG002 - Omnigent keeps its own sessions
        *,
        room: str,
        handle: str,
        kind: str,
        cwd: Path,
        env: dict[str, str],  # noqa: ARG002 - a session takes no environment; the join code carries it
        intro: str,
        hooks: StartHooks | None = None,  # noqa: ARG002 - a session starts in one call, with no steps to say
    ) -> Started:
        from mycelium.integrations.agents import of_kind

        if kind not in self._agents:
            self.kinds()
        agent_id = self._agents.get(kind)
        if agent_id is None:
            raise HostError(f"this Omnigent host can't start {kind}")
        host = self._host or self._this_host()
        body: dict[str, Any] = {
            "agent_id": agent_id,
            "host_id": host["host_id"],
            "workspace": str(cwd),
            "title": f"@{handle} in {room}",
            "labels": {ROOM_LABEL: room, HANDLE_LABEL: handle},
        }
        if (cwd / ".git").exists():
            # Its own worktree, so its own folder, so its own membership.
            body["git"] = {"branch_name": branch_for(room, handle)}
        if args := of_kind(kind).launch_args():
            body["terminal_launch_args"] = list(args)
        session = self._post("/v1/sessions", body)
        ref = str(session.get("id") or session.get("session_id") or "")
        if not ref:
            raise HostError("Omnigent created a session but named no id")
        self.wake(ref, intro)
        return Started(ref=ref, cwd=session.get("workspace") or None)

    def alive(self, ref: str) -> bool:
        try:
            session = self._get(f"/v1/sessions/{ref}", include_items="false", include_usage="false")
        except HostError:
            return False
        return bool(session.get("runner_online", True)) and session.get("status") != "failed"

    def _sessions(self) -> list[dict[str, Any]]:
        listed = self._get("/v1/sessions", visibility="all", limit="200")
        rows = listed.get("data", []) if isinstance(listed, dict) else listed
        return [r for r in rows if isinstance(r, dict) and (r.get("labels") or {}).get(ROOM_LABEL)]

    def statuses(self) -> dict[str, tuple[str, str | None]] | None:
        try:
            rows = self._sessions()
        except HostError:
            return None
        out: dict[str, tuple[str, str | None]] = {}
        for row in rows:
            # A session whose runner is gone has stopped, even if its row stays.
            if row.get("archived") or row.get("runner_online") is False:
                continue
            status = _OMNIGENT_STATUS.get(str(row.get("status") or ""), "working")
            out[str(row["id"])] = (status, row.get("title"))
        return out

    def blocker(self, ref: str, kind: str) -> str | None:  # noqa: ARG002
        return None

    def wake(self, ref: str, text: str) -> None:
        self._post(
            f"/v1/sessions/{ref}/events",
            {
                "type": "message",
                "data": {"role": "user", "content": [{"type": "input_text", "text": text}]},
            },
        )

    def stop(self, agent: Tracked) -> None:
        try:
            self._post(f"/v1/sessions/{agent.pane}/events", {"type": "stop_session", "data": {}})
        except HostError:
            pass

    def interrupt(self, ref: str, kind: str | None) -> bool:  # noqa: ARG002
        """Omnigent has no interrupt that keeps a session: the message reaches the
        agent as an ordinary wake, at its next idle."""
        return False

    def gone(self, agent: Tracked) -> None:  # noqa: ARG002 - Omnigent keeps nothing to forget
        return None

    def release(self, state: State) -> None:  # noqa: ARG002 - nothing is opened beside a session
        return None

    def sync(self, config: MyceliumConfig, state: State, log: Console) -> None:
        """Presence up for every live agent, then each room's queued wakes down.

        Omnigent queues a message sent to a busy session, so a wake is handed
        over whatever the agent is doing.
        """
        from mycelium.commands.herdr import _push_presence, fetch_wakes, wake_prompt_for

        live = [a for a in state.agents.values() if a.live]
        if not live:
            return
        by_room: dict[str, dict[str, Tracked]] = {}
        for agent in live:
            by_room.setdefault(agent.room, {})[agent.handle] = agent
        for room, members in by_room.items():
            _push_presence(
                config,
                room,
                {h: {"status": a.status, "title": a.detail} for h, a in members.items()},
                self._ttl_s,
            )
            for wake in fetch_wakes(config, room):
                handle, reason = str(wake.get("handle") or ""), wake.get("reason") or "mention"
                agent = members.get(handle)
                if agent is None:
                    _log.warning("wake @%s (%s) in %s: no session here is it", handle, reason, room)
                    continue
                line = f"wake @{handle} ({reason}) -> {agent.pane}"
                started = time.monotonic()
                try:
                    self.wake(agent.pane, wake_prompt_for(room, wake))
                except HostError as e:
                    _log.warning("%s failed %dms: %s", line, ms(started), e)
                    log.print(f"[yellow]↯ skip[/yellow] @{agent.handle} [dim]{e}[/dim]")
                    continue
                _log.info("%s ok %dms", line, ms(started))
                log.print(
                    f"[green]↯ woke[/green] @{agent.handle} "
                    f"[dim]on {wake.get('reason') or 'mention'} → {agent.pane}[/dim]"
                )


def branch_for(room: str, handle: str) -> str:
    """The git branch an agent's worktree is on: ``mycelium/<room>/<handle>``."""
    parts = [_BRANCH_UNSAFE.sub("-", p).strip("-.") or "x" for p in (room, handle)]
    return "mycelium/" + "/".join(parts)
