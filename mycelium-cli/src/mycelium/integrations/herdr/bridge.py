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
- **Drive, don't spawn.** We prompt agents the user already created. Spawning
  panes/agents is deliberately out of scope.
- **The reply channel is the room.** We never read agent stdout — herdr can't
  scrape alt-screen TUIs anyway. We supply the *wake*; the agent ``respond``s
  through mycelium on its own.
"""

from __future__ import annotations

import json
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


def build_mention_prompt(room: str, handle: str) -> str:
    """A doorbell, not a payload: nudge the agent that messages are waiting.

    Deliberately carries no message text — the room transcript is the source of
    truth, so the agent reads it itself (seeing everything, in order, nothing
    lost) and keeps full agency: catch up now, or finish what it's doing and
    address mycelium after. This also sidesteps the accumulate/dedup/first-await
    problems that come with trying to hand the messages over inline.
    """
    h = handle.lstrip("@")
    return (
        f"[mycelium] You have messages awaiting in room '{room}'. "
        f"Run `mycelium room messages --room {room}` to see them, then reply with "
        f'`mycelium respond --room {room} --handle {h} "..."`.'
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

    def all(self) -> list[HerdrPaneMapping]:
        out: list[HerdrPaneMapping] = []
        for key, entry in self._load().items():
            room, _, handle = key.partition("/")
            if not room or not handle or not isinstance(entry, dict):
                continue
            pane = entry.get("pane")
            if not pane:
                continue
            out.append(
                HerdrPaneMapping(
                    room=room,
                    handle=handle,
                    pane=pane,
                    kind=entry.get("kind"),
                    managed=bool(entry.get("managed", False)),
                )
            )
        return sorted(out, key=lambda m: m.key)

    def get(self, room: str, handle: str) -> HerdrPaneMapping | None:
        h = handle.lstrip("@")
        entry = self._load().get(f"{room}/{h}")
        if not isinstance(entry, dict) or not entry.get("pane"):
            return None
        return HerdrPaneMapping(
            room=room,
            handle=h,
            pane=entry["pane"],
            kind=entry.get("kind"),
            managed=bool(entry.get("managed", False)),
        )

    def set(self, mapping: HerdrPaneMapping) -> None:
        data = self._load()
        data[mapping.key] = {
            "pane": mapping.pane,
            "kind": mapping.kind,
            "managed": mapping.managed,
        }
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

    # ── workspace surface ────────────────────────────────────────────────────

    def list_workspaces(self) -> list[dict]:
        """Live workspaces as dicts (``workspace_id``, ``label``, ``tab_count``, …)."""
        result = self._run_json(["workspace", "list"]).get("result", {})
        workspaces = result.get("workspaces", [])
        return workspaces if isinstance(workspaces, list) else []

    def resolve_workspace(self, selector: str) -> str:
        """Return the ``workspace_id`` that ``selector`` names.

        The label is what a person actually knows — they typed it when they named
        the workspace ("Mycelium") — while the id (``w4``) is a counter they have
        no reason to have seen. So the label matches first, and an id is still
        accepted for a script that already carries one.

        The match on a label is exact (bar case) rather than a substring: binding
        enrolls every live agent in the workspace, so a short selector quietly
        reaching a bigger workspace than the caller pictured is worse than being
        made to type the name out.

        Raising on a miss is the point. An unresolvable selector used to bind
        cleanly and then match zero live agents, so the run reported success and
        enrolled nobody, which reads as herdr being broken rather than as a typo.
        """
        workspaces = self.list_workspaces()
        if not workspaces:
            raise HerdrError("herdr reports no open workspaces")

        wanted = selector.strip()
        folded = wanted.casefold()

        exact = [w for w in workspaces if _ws_label(w).casefold() == folded]
        if len(exact) == 1:
            return _ws_id(exact[0])
        if exact:
            raise HerdrError(_ambiguous_workspace(wanted, exact))

        for w in workspaces:
            if _ws_id(w) == wanted:
                return _ws_id(w)

        known = ", ".join(f"{_ws_label(w)!r} ({_ws_id(w)})" for w in workspaces)
        raise HerdrError(f"no herdr workspace matches {wanted!r}. Open workspaces: {known}")

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

    # ── the wake orchestration ───────────────────────────────────────────────

    def wake(self, mapping: HerdrPaneMapping, prompt_text: str, *, timeout_ms: int) -> WakeResult:
        """Wake the agent bound to ``mapping`` for one coordination turn.

        Only wakes an ``idle``/``done`` agent: a ``working``/``blocked`` agent is
        left alone so its message holds on the durable cursor (waking mid-turn
        would race the current turn — see the design doc's "wake-while-working").
        A stale mapping (no agent at the pane) also fails soft.
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
            result = self.prompt(mapping.pane, prompt_text, wait=True, timeout_ms=timeout_ms)
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


def _ws_id(workspace: dict) -> str:
    return str(workspace.get("workspace_id") or "")


def _ws_label(workspace: dict) -> str:
    return str(workspace.get("label") or "")


def _ambiguous_workspace(selector: str, matches: list[dict]) -> str:
    names = ", ".join(f"{_ws_label(w)!r} ({_ws_id(w)})" for w in matches)
    return f"{selector!r} matches more than one herdr workspace: {names}. Use the id."


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
