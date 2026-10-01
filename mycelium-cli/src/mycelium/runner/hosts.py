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

import platform
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

import httpx
from rich.console import Console

from mycelium.integrations.herdr import HerdrBridge, HerdrError, HerdrPaneMapping

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig
    from mycelium.runner.daemon import State, Tracked


class HostError(Exception):
    """A host couldn't do what it was asked; the message says why, for a person."""


@dataclass
class Started:
    """Where a started agent runs."""

    #: How the host names it: a herdr pane, an Omnigent session id.
    ref: str
    #: The herdr workspace it was opened in, when there is one.
    workspace: str | None = None
    #: The folder it works in, when the host chose another (an Omnigent worktree).
    cwd: str | None = None


class AgentHost(Protocol):
    #: The host's name, as ``runner.host`` spells it; said in the hello and in messages.
    name: str
    #: The agent learns who it is from a join code in its first message, rather
    #: than from the environment of where it runs.
    joins: bool
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
    ) -> Started:
        """Start ``kind`` as ``@handle`` and give it ``intro``. Raises :class:`HostError`."""
        ...

    def alive(self, ref: str) -> bool:
        """Whether the agent at ``ref`` is still there."""
        ...

    def statuses(self) -> dict[str, tuple[str, str | None]] | None:
        """``{ref: (status, title)}`` for every agent it has; ``None`` when it can't be read.

        A status is the app's word: ``idle``, ``working`` or ``blocked``.
        """
        ...

    def stop(self, agent: Tracked) -> None:
        """End the agent. Best-effort: one that's already gone is stopped."""
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


class HerdrHost:
    """Each agent in a herdr pane on this machine.

    The pane's environment says which member it is, and herdr's workspace sync
    (``commands.herdr.sync_pass``) pushes presence and delivers wakes, waiting
    for an agent to be idle before it wakes it.
    """

    name = "herdr"
    joins = False
    gone_detail = "its herdr pane closed"

    def __init__(self, bridge: HerdrBridge | None = None, *, sync_every_s: float = 3.0) -> None:
        self.bridge = bridge or HerdrBridge()
        self._ttl_s = max(90.0, sync_every_s * 4)

    def available(self) -> bool:
        return self.bridge.available()

    def kinds(self) -> set[str] | None:
        return self.bridge.supported_kinds()

    def _open_pane(
        self, state: State, room: str, cwd: Path, env: dict[str, str]
    ) -> tuple[str, str]:
        """A new pane for ``room``: split from its workspace's last pane, or a new workspace."""
        held = state.workspaces.get(room)
        if held is not None:
            workspace, last = held
            try:
                pane = self.bridge.split_pane(last, direction="right", cwd=str(cwd), env=env)
            except HerdrError:
                pass
            else:
                state.workspaces[room] = (workspace, pane)
                return workspace, pane
        workspace, pane = self.bridge.create_workspace(room, cwd=str(cwd), env=env)
        state.workspaces[room] = (workspace, pane)
        return workspace, pane

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
    ) -> Started:
        from mycelium.commands.swarm import _start_when_ready

        workspace, pane = self._open_pane(state, room, cwd, env)
        try:
            session = _start_when_ready(self.bridge, handle, kind, pane)
        except HerdrError as e:
            self._close_quietly(pane)
            raise HostError(str(e)) from e
        # Not ``managed``: a closed pane stops the agent, it does not delete it
        # from the room, so the app can start it again with its notes intact.
        # Its session and folder are kept so it can be resumed after a restart.
        self.bridge.registry.set(
            HerdrPaneMapping(
                room=room, handle=handle, pane=pane, kind=kind, session=session, cwd=str(cwd)
            )
        )
        self.bridge.registry.bind(workspace, room)
        self.bridge.prompt(pane, intro, wait=False)
        state.owned[workspace] = room
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

    def _close_quietly(self, pane: str) -> None:
        try:
            self.bridge.close_pane(pane)
        except HerdrError:
            pass

    def stop(self, agent: Tracked) -> None:
        self._close_quietly(agent.pane)
        self.gone(agent)

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
        from mycelium.commands.herdr import sync_pass
        from mycelium.machine import mark_syncing, runner_sync_choices

        # The workspaces this runner opened, and any other bound workspace the
        # person asked it to keep (`mycelium machine sync <workspace> on`, or the
        # Machines page). The rest are left to a `herdr sync` of their own.
        bindings = self.bridge.registry.bindings()
        targets = dict(state.owned)
        targets |= {w: bindings[w] for w in runner_sync_choices() if w in bindings}
        if not targets:
            return
        mark_syncing(list(targets), "runner")
        sync_pass(
            config,
            self.bridge,
            list(targets.items()),
            room_filter=None,
            ttl_s=self._ttl_s,
            log=log,
            wait=False,
        )


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
    ) -> Started:
        from mycelium.integrations.herdr.agents import agent_kind

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
        if args := agent_kind(kind).launch_args():
            body["terminal_launch_args"] = args
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
        from mycelium.machine import mark_syncing

        live = [a for a in state.agents.values() if a.live]
        if not live:
            return
        mark_syncing(["omnigent"], "runner")
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
                agent = members.get(str(wake.get("handle") or ""))
                if agent is None:
                    continue
                try:
                    self.wake(agent.pane, wake_prompt_for(room, wake))
                except HostError as e:
                    log.print(f"[yellow]↯ skip[/yellow] @{agent.handle} [dim]{e}[/dim]")
                    continue
                log.print(
                    f"[green]↯ woke[/green] @{agent.handle} "
                    f"[dim]on {wake.get('reason') or 'mention'} → {agent.pane}[/dim]"
                )


def branch_for(room: str, handle: str) -> str:
    """The git branch an agent's worktree is on: ``mycelium/<room>/<handle>``."""
    parts = [_BRANCH_UNSAFE.sub("-", p).strip("-.") or "x" for p in (room, handle)]
    return "mycelium/" + "/".join(parts)
