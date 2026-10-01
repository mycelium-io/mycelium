# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Thin, fail-soft wrapper over the ``herdr`` CLI + a durable pane registry.

The ``herdr`` CLI speaks JSON over a Unix socket; every control command returns
``{"id": ..., "result": {...}}`` on success, or a JSON error object on stderr
with a non-zero exit (status 1 = server error, 2 = CLI syntax error). This module
turns that surface into a few typed methods and keeps a
``mycelium handle -> herdr pane`` registry that survives agent restarts.

Design rules (mirrors the package docstring):

- **Fail-soft everywhere.** A missing binary / down server raises
  :class:`HerdrUnavailableError`; callers on the wake path catch it and fall back
  to the pure-CLI ``await``/``respond`` behavior. Never let a herdr hiccup break
  ``agent invoke``.
- **Interactive sessions only.** Agents started here (``swarm``, the runner)
  are interactive sessions in panes the user can watch and type into; they
  are driven by prompting the pane, never run one-shot.
- **The reply channel is the room.** We never read agent stdout — herdr can't
  scrape alt-screen TUIs anyway. We supply the *wake*; the agent ``respond``s
  through mycelium on its own.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING

from mycelium.filesystem import get_mycelium_dir

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

#: herdr agent lifecycle states that mean "safe to wake now" — the agent is idle
#: and will observe a fresh lifecycle change. ``working``/``blocked`` are held
#: back to the durable cursor (see :meth:`HerdrBridge.wake`).
_WAKEABLE_STATES = frozenset({"idle", "done", "unknown"})

#: Where ``herdr agent start --help`` lists the kinds it can start.
_POSSIBLE_KINDS = re.compile(r"\[possible values:\s*([^\]]+)\]")

#: The oldest herdr Mycelium works with. 0.9.2 is where herdr learned to
#: restart each agent in its own session after its server restarts, which is
#: what keeps a room's agents alive across one; 0.9.3 fixes its key handling.
MIN_VERSION = "0.9.3"

#: herdr's integration for an agent kind, where the two names differ.
_INTEGRATION_FOR = {"agy": "antigravity-cli"}


def integration_for(kind: str) -> str:
    """The herdr integration that lets herdr restore an agent of ``kind``."""
    return _INTEGRATION_FOR.get(kind, kind)


def version_tuple(version: str | None) -> tuple[int, ...] | None:
    """``"0.9.3"`` (or ``"v0.9.3"``, ``"herdr 0.9.3"``) as ``(0, 9, 3)``; ``None`` if unreadable."""
    found = re.search(r"\d+(?:\.\d+)+", version or "")
    return tuple(int(p) for p in found.group(0).split(".")) if found else None


def too_old(version: str | None) -> bool:
    """Whether ``version`` is older than :data:`MIN_VERSION` (unknown is not too old)."""
    have, need = version_tuple(version), version_tuple(MIN_VERSION)
    return bool(have and need and have < need)


class HerdrError(RuntimeError):
    """A herdr CLI call failed. Carries the CLI's error detail when available."""


class HerdrUnavailableError(HerdrError):
    """The herdr binary is missing or its server is unreachable.

    Distinct from :class:`HerdrError` so the wake path can treat "herdr isn't
    here" (fall back silently) differently from "herdr rejected the command"
    (worth surfacing).
    """


@dataclass(frozen=True)
class HerdrPaneMapping:
    """A durable binding of a mycelium ``handle`` (in a ``room``) to a herdr pane.

    ``managed`` marks a binding the sync bridge created by reconciling a bound
    workspace (vs. a hand-run ``herdr map``). Only managed bindings are torn down
    when their pane closes — so the "herdr lifecycle *is* mycelium lifecycle"
    reconcile never removes a mapping a human placed by hand.
    """

    room: str
    handle: str
    pane: str
    kind: str | None = None
    managed: bool = False
    #: The folder it works in, which is where a restart starts it again.
    cwd: str | None = None

    @property
    def key(self) -> str:
        return f"{self.room}/{self.handle.lstrip('@')}"


@dataclass(frozen=True)
class WakeResult:
    """Outcome of a wake attempt. ``ok`` gates whether the message was handed off."""

    ok: bool
    pane: str
    status: str | None
    detail: str
    raw: dict | None = None


def build_wake_prompt(room: str, handle: str) -> str:
    """The prompt injected into a herdr-managed agent to run one coordination turn.

    Tells the (already-context-rich) resident agent to drain its pending mycelium
    turn and reply through the room. Kept explicit so the agent needs no state
    beyond its own accumulated context + the mycelium skill.
    """
    h = handle.lstrip("@")
    return (
        f"[mycelium wake] You have a pending coordination message in mycelium room "
        f"'{room}' addressed to you as '@{h}'. Run one turn now: "
        f"`mycelium await --room {room} --handle {h} --json --timeout 5` to read it, "
        f"reason about the returned prompt using your full context, then post your reply "
        f'with `mycelium respond --room {room} --handle {h} "<your reply>"`. '
        f"Your reply flows through the room, not this terminal."
    )


def build_assigned_prompt(room: str, handle: str, key: str, title: str | None = None) -> str:
    """The doorbell for a row just filed for this agent: go take it."""
    h = handle.lstrip("@")
    what = f"'{title}' ({key})" if title else key
    return (
        f"[mycelium] The task {what} in room '{room}' was given to you as '@{h}'. "
        f"Claim it (`mycelium board claim {key} --room {room} --to @{h}`), read its thread "
        f"(`mycelium board messages {key} --room {room}`), do the work, and post what you "
        f'did there with `mycelium board send {key} "..." --room {room} --as {h}`.'
    )


def build_mention_prompt(room: str, handle: str) -> str:
    """A doorbell, not a payload: nudge the agent that messages are waiting.

    Deliberately carries no message text — the room transcript is the source of
    truth, so the agent reads it itself (seeing everything, in order, nothing
    lost) and keeps full agency: catch up now, or finish what it's doing and
    address mycelium after. This also sidesteps the accumulate/dedup/first-await
    problems that come with trying to hand the messages over inline.
    """
    h = handle.lstrip("@")
    # Read through ``await``, not the room's message list: it hands over the
    # mention and everything said before it, tells the room this agent is
    # responding, and lets the reply land in the thread it was asked in.
    return (
        f"[mycelium] You were mentioned in room '{room}'. "
        f"Run `mycelium await --room {room} --handle {h} --json --timeout 5` to read it "
        f"with everything said since your last turn, then reply with "
        f'`mycelium respond --room {room} --handle {h} "..."`. '
        f"Your reply lands where you were asked."
    )


class HerdrRegistry:
    """JSON-file registry of ``handle -> pane`` mappings under ``~/.mycelium/herdr``.

    Keyed by ``room/handle`` so the same handle can bind different panes across
    rooms. Best-effort: a corrupt/missing file reads as empty rather than raising,
    keeping the wake path resilient.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or (get_mycelium_dir() / "herdr" / "registry.json")

    @property
    def path(self) -> Path:
        return self._path

    @property
    def _bindings_path(self) -> Path:
        """Sibling file holding the durable ``workspace -> room`` bindings."""
        return self._path.parent / "bindings.json"

    def _load(self) -> dict[str, dict]:
        try:
            raw = json.loads(self._path.read_text())
        except (FileNotFoundError, ValueError, OSError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def _save(self, data: dict[str, dict]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")

    @staticmethod
    def _mapping(room: str, handle: str, entry: dict) -> HerdrPaneMapping:
        return HerdrPaneMapping(
            room=room,
            handle=handle,
            pane=entry["pane"],
            kind=entry.get("kind"),
            managed=bool(entry.get("managed", False)),
            cwd=entry.get("cwd") or None,
        )

    def all(self) -> list[HerdrPaneMapping]:
        out: list[HerdrPaneMapping] = []
        for key, entry in self._load().items():
            room, _, handle = key.partition("/")
            if not room or not handle or not isinstance(entry, dict) or not entry.get("pane"):
                continue
            out.append(self._mapping(room, handle, entry))
        return sorted(out, key=lambda m: m.key)

    def get(self, room: str, handle: str) -> HerdrPaneMapping | None:
        h = handle.lstrip("@")
        entry = self._load().get(f"{room}/{h}")
        if not isinstance(entry, dict) or not entry.get("pane"):
            return None
        return self._mapping(room, h, entry)

    def set(self, mapping: HerdrPaneMapping) -> None:
        """Write ``mapping``. A folder it doesn't say is kept from before, for
        the same pane and the same kind of agent.

        The workspace sync rewrites a pane's mapping without knowing which
        folder the agent was started in, and that folder is where a restart
        starts it again. Another pane or kind is another agent.
        """
        data = self._load()
        raw = data.get(mapping.key)
        before: dict = raw if isinstance(raw, dict) else {}
        same = before.get("pane") == mapping.pane and mapping.kind in (None, before.get("kind"))
        entry: dict = {"pane": mapping.pane, "kind": mapping.kind, "managed": mapping.managed}
        cwd = mapping.cwd or (before.get("cwd") if same else None)
        if cwd:
            entry["cwd"] = cwd
        data[mapping.key] = entry
        self._save(data)

    def remove(self, room: str, handle: str) -> bool:
        data = self._load()
        key = f"{room}/{handle.lstrip('@')}"
        if key in data:
            del data[key]
            self._save(data)
            return True
        return False

    # ── workspace -> room bindings ────────────────────────────────────────────
    # The durable unit of the sync bridge: "this herdr workspace's live agents are
    # this room's members." Kept in a sibling file so a bare `herdr sync` can
    # reconcile every bound workspace with no arguments.

    def bindings(self) -> dict[str, str]:
        """All ``workspace -> room`` bindings (empty on a missing/corrupt file)."""
        try:
            raw = json.loads(self._bindings_path.read_text())
        except (FileNotFoundError, ValueError, OSError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return {str(w): str(r) for w, r in raw.items() if w and isinstance(r, str) and r}

    def bind(self, workspace: str, room: str) -> None:
        """Bind a herdr ``workspace`` to a mycelium ``room`` (idempotent upsert)."""
        data = self.bindings()
        data[workspace] = room
        self._bindings_path.parent.mkdir(parents=True, exist_ok=True)
        self._bindings_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")

    def unbind(self, workspace: str) -> bool:
        """Forget a workspace binding. Returns whether one was present."""
        data = self.bindings()
        if workspace in data:
            del data[workspace]
            self._bindings_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
            return True
        return False


class HerdrBridge:
    """Typed, fail-soft facade over the ``herdr`` CLI.

    The CLI invocation is injectable (``runner``) so tests exercise the parsing
    and wake logic without a live herdr server.
    """

    def __init__(
        self,
        *,
        binary: str = "herdr",
        runner: Callable[[list[str]], subprocess.CompletedProcess] | None = None,
        registry: HerdrRegistry | None = None,
    ) -> None:
        self._binary = binary
        self._runner = runner or self._default_runner
        self.registry = registry or HerdrRegistry()

    def _default_runner(self, args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(  # noqa: S603 - args are code-built, never shell-interpolated
            [self._binary, *args],
            capture_output=True,
            text=True,
            check=False,
        )

    # ── availability ─────────────────────────────────────────────────────────

    def binary_present(self) -> bool:
        """Cheap check: is the ``herdr`` executable on PATH?"""
        return shutil.which(self._binary) is not None

    def available(self) -> bool:
        """Is herdr usable right now (binary present *and* server reachable)?

        Best-effort and swallows all errors — this gates the opt-in wake path, so
        "not sure" must read as "no, fall back to the cursor."
        """
        if not self.binary_present():
            return False
        try:
            self.list_agents()
        except HerdrError:
            return False
        return True

    # ── raw call + JSON ──────────────────────────────────────────────────────

    def _run_json(self, args: list[str]) -> dict:
        if not self.binary_present():
            raise HerdrUnavailableError("herdr binary not found on PATH")
        try:
            proc = self._runner(args)
        except OSError as e:  # binary vanished between check and exec, etc.
            raise HerdrUnavailableError(str(e)) from e
        if proc.returncode != 0:
            detail = (
                _extract_error(proc.stderr) or (proc.stderr or "").strip() or "herdr call failed"
            )
            # A dead server surfaces as a connection error on stderr; treat that
            # as unavailable so callers fall back rather than surface a scary error.
            if _looks_like_server_down(proc.stderr):
                raise HerdrUnavailableError(detail)
            raise HerdrError(detail)
        try:
            return json.loads(proc.stdout)
        except ValueError as e:
            raise HerdrError(f"could not parse herdr output: {e}") from e

    # ── agent surface ────────────────────────────────────────────────────────

    def list_agents(self) -> list[dict]:
        """Live agents as dicts (``agent``, ``agent_status``, ``pane_id``, …)."""
        result = self._run_json(["agent", "list"]).get("result", {})
        agents = result.get("agents", [])
        return agents if isinstance(agents, list) else []

    def tab_labels(self, workspace: str | None = None) -> dict[str, str]:
        """Map ``tab_id -> label`` (the user-set tab name), optionally scoped.

        The tab label is a far more meaningful handle source than a pane id — it's
        what the user named the work ("pr review", "explore herdr"). Empty on any
        herdr error so callers fall back to pane-derived names.
        """
        args = ["tab", "list"]
        if workspace:
            args += ["--workspace", workspace]
        try:
            tabs = self._run_json(args).get("result", {}).get("tabs", [])
        except HerdrError:
            return {}
        return {
            str(t["tab_id"]): str(t.get("label") or "")
            for t in tabs
            if isinstance(t, dict) and t.get("tab_id")
        }

    def list_panes(self) -> list[dict]:
        """Every open pane (``pane_id``, ``workspace_id``…), with an agent in it or not."""
        result = self._run_json(["pane", "list"]).get("result", {})
        panes = result.get("panes", []) if isinstance(result, dict) else []
        return panes if isinstance(panes, list) else []

    def workspace_labels(self) -> dict[str, str]:
        """Map ``workspace_id -> label``; empty on a herdr error."""
        try:
            result = self._run_json(["workspace", "list"]).get("result", {})
        except HerdrError:
            return {}
        workspaces = result.get("workspaces", []) if isinstance(result, dict) else []
        return {
            str(w["workspace_id"]): str(w.get("label") or "")
            for w in workspaces
            if isinstance(w, dict) and w.get("workspace_id")
        }

    def get_agent(self, target: str) -> dict | None:
        """One agent's live state, or ``None`` if no agent occupies ``target``."""
        try:
            result = self._run_json(["agent", "get", target]).get("result", {})
        except HerdrError:
            return None
        # `agent get` wraps the agent under `result.agent` (or returns it flat).
        agent = result.get("agent", result)
        return agent if isinstance(agent, dict) and agent.get("pane_id") else None

    def prompt(
        self,
        target: str,
        text: str,
        *,
        wait: bool = True,
        until: str | None = None,
        timeout_ms: int | None = None,
    ) -> dict:
        """Inject ``text`` + Enter into the agent at ``target``.

        Returns the parsed ``result``. Raises :class:`HerdrError` on a stall /
        timeout / server error (the CLI's own error contract).
        """
        args = ["agent", "prompt", target, text]
        if wait:
            args.append("--wait")
        if until:
            args += ["--until", until]
        if timeout_ms is not None:
            args += ["--timeout", str(timeout_ms)]
        return self._run_json(args).get("result", {})

    # ── making panes ─────────────────────────────────────────────────────────

    @staticmethod
    def _env_args(env: dict[str, str] | None) -> list[str]:
        return [arg for k, v in (env or {}).items() for arg in ("--env", f"{k}={v}")]

    def create_workspace(
        self, label: str, *, cwd: str | None = None, env: dict[str, str] | None = None
    ) -> tuple[str, str]:
        """Open a new workspace; ``(workspace id, its first pane id)``.

        Opened without taking focus, so the terminal the caller runs in stays
        where it is.
        """
        args = ["workspace", "create", "--label", label, "--no-focus"]
        if cwd:
            args += ["--cwd", cwd]
        args += self._env_args(env)
        result = self._run_json(args).get("result", {})
        workspace = str((result.get("workspace") or {}).get("workspace_id") or "")
        pane = str((result.get("root_pane") or {}).get("pane_id") or "")
        if not workspace or not pane:
            raise HerdrError("herdr created a workspace but named no workspace or pane")
        return workspace, pane

    def split_pane(
        self,
        pane: str,
        *,
        direction: str = "right",
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> str:
        """Split ``pane``; return the new pane's id."""
        args = ["pane", "split", pane, "--direction", direction, "--no-focus"]
        if cwd:
            args += ["--cwd", cwd]
        args += self._env_args(env)
        result = self._run_json(args).get("result", {})
        new = str((result.get("pane") or {}).get("pane_id") or "")
        if not new:
            raise HerdrError("herdr split a pane but named no new pane")
        return new

    def close_pane(self, pane: str) -> None:
        """Close ``pane``, ending whatever runs in it."""
        self._run_json(["pane", "close", pane])

    def _run_quiet(self, args: list[str]) -> None:
        """Run a herdr command that prints nothing when it works."""
        if not self.binary_present():
            raise HerdrUnavailableError("herdr binary not found on PATH")
        try:
            proc = self._runner(args)
        except OSError as e:
            raise HerdrUnavailableError(str(e)) from e
        if proc.returncode != 0:
            raise HerdrError(
                _extract_error(proc.stderr) or (proc.stderr or "").strip() or "herdr call failed"
            )

    def run_in_pane(self, pane: str, command: str) -> None:
        """Type ``command`` into ``pane``'s shell and run it."""
        self._run_quiet(["pane", "run", pane, command])

    def rename_agent(self, target: str, name: str) -> None:
        """Set the name herdr shows for the agent at ``target``."""
        self._run_quiet(["agent", "rename", target, name])

    def integrations(self) -> dict[str, bool] | None:
        """Each herdr integration, and whether it's current; ``None`` if herdr can't say.

        A current integration tells herdr which session its agent is in, so
        herdr restarts the agent in that session after its server restarts.
        One not installed, outdated or needing repair doesn't.
        """
        if not self.binary_present():
            return None
        try:
            proc = self._runner(["integration", "status"])
        except OSError:
            return None
        if proc.returncode != 0:
            return None
        out: dict[str, bool] = {}
        for line in (proc.stdout or "").splitlines():
            name, sep, state = line.partition(":")
            if sep and name.strip():
                out[name.strip()] = state.strip().startswith("current")
        return out or None

    def install_integration(self, name: str) -> None:
        """Install (or bring up to date) herdr's integration ``name``.

        It writes a hook into that agent CLI's own settings, so it only ever
        runs on a yes from the person.
        """
        self._run_quiet(["integration", "install", name])

    def supported_kinds(self) -> set[str] | None:
        """The agent kinds ``herdr agent start --kind`` accepts, read from its own help.

        ``None`` when herdr is missing or its help no longer lists them, so a
        caller can tell "herdr starts none of these" from "couldn't tell".
        """
        if not self.binary_present():
            return None
        try:
            proc = self._runner(["agent", "start", "--help"])
        except OSError:
            return None
        found = _POSSIBLE_KINDS.search(proc.stdout or "")
        if not found:
            return None
        return {k.strip() for k in found.group(1).split(",") if k.strip()}

    def version(self) -> str | None:
        """herdr's version string, or ``None`` when it can't be read."""
        if not self.binary_present():
            return None
        try:
            proc = self._runner(["--version"])
        except OSError:
            return None
        out = (proc.stdout or "").strip()
        return out.removeprefix("herdr").strip() or None if proc.returncode == 0 else None

    def server_version(self) -> str | None:
        """The running server's version (the client's is :meth:`version`), or ``None``."""
        if not self.binary_present():
            return None
        try:
            proc = self._runner(["status", "server"])
        except OSError:
            return None
        if proc.returncode != 0:
            return None
        for line in (proc.stdout or "").splitlines():
            label, _, value = line.partition(":")
            if label.strip() == "version" and value.strip():
                return value.strip()
        return None

    def start_agent(
        self,
        name: str,
        kind: str,
        pane: str,
        *,
        agent_args: list[str] | None = None,
        timeout_ms: int = 60000,
    ) -> dict:
        """Start an interactive ``kind`` agent named ``name`` in ``pane``; wait until it is ready.

        ``agent_args`` are passed through to the agent's own command line.
        """
        args = ["agent", "start", name, "--kind", kind, "--pane", pane]
        args += ["--timeout", str(timeout_ms)]
        if agent_args:
            args += ["--", *agent_args]
        return self._run_json(args).get("result", {})

    # ── the wake orchestration ───────────────────────────────────────────────

    def wake(
        self,
        mapping: HerdrPaneMapping,
        prompt_text: str,
        *,
        timeout_ms: int,
        wait: bool = True,
    ) -> WakeResult:
        """Wake the agent bound to ``mapping`` for one coordination turn.

        Only wakes an ``idle``/``done`` agent: a ``working``/``blocked`` agent is
        left alone so its message holds on the durable cursor (waking mid-turn
        would race the current turn — see the design doc's "wake-while-working").
        A stale mapping (no agent at the pane) also fails soft.

        ``wait=False`` hands the prompt over and returns at once, rather than
        waiting for the turn it starts to settle, so one caller can wake several
        agents that then work at the same time.
        """
        agent = self.get_agent(mapping.pane)
        if agent is None:
            return WakeResult(
                ok=False,
                pane=mapping.pane,
                status=None,
                detail=f"no live agent at pane {mapping.pane} (stale mapping?)",
            )
        status = str(agent.get("agent_status") or "unknown")
        if status not in _WAKEABLE_STATES:
            return WakeResult(
                ok=False,
                pane=mapping.pane,
                status=status,
                detail=f"agent is '{status}' — holding on the cursor rather than waking mid-turn",
            )
        try:
            result = self.prompt(
                mapping.pane, prompt_text, wait=wait, timeout_ms=timeout_ms if wait else None
            )
        except HerdrError as e:
            return WakeResult(
                ok=False, pane=mapping.pane, status=status, detail=f"wake failed: {e}"
            )
        settled = _settled_status(result)
        return WakeResult(
            ok=True,
            pane=mapping.pane,
            status=settled or status,
            detail=f"woke agent at {mapping.pane}" + (f" (settled: {settled})" if settled else ""),
            raw=result,
        )


def _extract_error(stderr: str | None) -> str | None:
    """Pull a human message out of herdr's JSON-on-stderr error, if present."""
    if not stderr:
        return None
    for line in reversed(stderr.strip().splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            err = obj.get("error") or obj.get("message")
            if isinstance(err, dict):
                return err.get("message") or err.get("code") or json.dumps(err)
            if isinstance(err, str):
                return err
    return None


def _looks_like_server_down(stderr: str | None) -> bool:
    if not stderr:
        return False
    low = stderr.lower()
    return any(s in low for s in ("connection refused", "no such file", "socket", "not running"))


def _settled_status(result: dict) -> str | None:
    """Best-effort read of the settled agent_status from a prompt result."""
    for key in ("agent_status", "status", "state"):
        val = result.get(key)
        if isinstance(val, str):
            return val
    agent = result.get("agent")
    if isinstance(agent, dict):
        val = agent.get("agent_status")
        if isinstance(val, str):
            return val
    return None
