"""Stub agent driver for Tier B coordination tests.

Correct SLIM-native stub flow:
  1. ``setup_coordination`` creates agents and posts opening positions.
  2. Stub threads start ``mycelium await`` — this registers presence
     (generates coordination_join) so the aligner can see them.
  3. Main thread waits briefly for all coordination_join events, then
     invokes the aligner engine.
  4. Aligner sees agents present with opening positions → starts rounds.
  5. Each stub's ``await`` returns with a tick; stub calls ``respond``.
  6. Repeat until l9_commit (converged or rejected) appears in room.

Position markers appended to respond text::

    [<accept>]   accept current proposal
    [<reject>]   reject; no counter
    [<counter>]  counter-offer
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from libs.mycelium_api import MyceliumAPI
from libs.mycelium_cli import MyceliumCLI
from libs.coordination_flow import (
    CoordinationSetup,
    collect_debug_info,
    poll_for_terminal_state,
    wait_for_coordination_join,
)

log = logging.getLogger(__name__)

Action = Literal["accept", "reject", "counter"]

CODE_SILENT = "SILENT"
CODE_OK = "OK"


@dataclass
class TurnResult:
    handle: str
    round_num: int
    action: Action
    ok: bool
    code: str = CODE_OK
    detail: str = ""


@dataclass
class StubRunResult:
    turns: list[TurnResult] = field(default_factory=list)
    terminal: dict | None = None   # result from poll_for_terminal_state
    timed_out: bool = False

    @property
    def converged(self) -> bool:
        return bool(self.terminal and self.terminal.get("converged"))

    @property
    def response_rate(self) -> float:
        if not self.turns:
            return 0.0
        return sum(1 for t in self.turns if t.ok) / len(self.turns)


def _default_prose(action: Action) -> str:
    if action == "accept":
        return "Agreed, I can accept this proposal."
    if action == "reject":
        return "This does not meet my requirements."
    return "I propose a modified approach to resolve the gap."


class StubAgent:
    """Single-handle stub that responds with a scripted action per turn."""

    def __init__(
        self,
        room: str,
        handle: str,
        action: Action = "accept",
        prose: str = "",
        cli: MyceliumCLI | None = None,
        action_fn: Callable[[int, dict], Action] | None = None,
    ):
        self.room = room
        self.handle = handle
        self.default_action = action
        self.prose = prose
        self.cli = cli or MyceliumCLI()
        self.action_fn = action_fn

    def _choose_action(self, round_num: int, turn_json: dict) -> Action:
        if self.action_fn is not None:
            return self.action_fn(round_num, turn_json)
        return self.default_action

    def _respond_text(self, action: Action) -> str:
        body = self.prose or _default_prose(action)
        return f"{body} [<{action}>]"

    def await_and_respond(
        self,
        round_num: int,
        turn_timeout: int,
        stop_event: threading.Event,
    ) -> TurnResult:
        """Call await; if a tick arrives, respond. Return a TurnResult."""
        await_r = self.cli.await_turn(self.room, self.handle, timeout=turn_timeout)

        if stop_event.is_set():
            # Terminal already reached while we were awaiting — not a failure
            return TurnResult(self.handle, round_num, self.default_action, ok=True,
                              detail="stop_event set")

        if not await_r.ok:
            return TurnResult(
                self.handle, round_num, self.default_action, ok=False,
                code=CODE_SILENT,
                detail=await_r.error_message or f"await rc={await_r.returncode}",
            )

        turn_json: dict[str, Any] = {}
        if await_r.stdout.strip():
            try:
                turn_json = json.loads(await_r.stdout)
            except json.JSONDecodeError:
                pass

        action = self._choose_action(round_num, turn_json)
        respond_r = self.cli.respond(self.room, self.handle, self._respond_text(action))
        return TurnResult(
            self.handle, round_num, action,
            ok=respond_r.ok,
            code=CODE_OK if respond_r.ok else CODE_SILENT,
            detail=respond_r.error_message if not respond_r.ok else "",
        )


def run_stubs_until_terminal(
    api: MyceliumAPI,
    stubs: list[StubAgent],
    *,
    setup: CoordinationSetup,
    max_rounds: int = 30,
    turn_timeout: int = 90,
    join_wait: int = 10,
    total_timeout: int = 600,
) -> StubRunResult:
    """Drive stubs through the correct SLIM-native coordination flow.

    Flow:
      1. Start stub threads — each calls ``await`` immediately, registering
         presence (coordination_join).
      2. Wait for all coordination_join events (up to *join_wait* seconds).
      3. Invoke the aligner engine in the main thread.
      4. Stub threads respond to ticks until l9_commit appears or timeout.
    """
    result = StubRunResult()
    stop_event = threading.Event()
    lock = threading.Lock()
    cli = stubs[0].cli if stubs else MyceliumCLI()

    def run_stub(stub: StubAgent) -> None:
        for round_num in range(max_rounds):
            if stop_event.is_set():
                break
            turn_result = stub.await_and_respond(round_num, turn_timeout, stop_event)
            if stop_event.is_set() and turn_result.detail == "stop_event set":
                break
            with lock:
                result.turns.append(turn_result)
            if not turn_result.ok:
                log.warning(
                    "Stub %s round %d: %s — %s",
                    stub.handle, round_num, turn_result.code, turn_result.detail,
                )
            else:
                log.debug("Stub %s round %d: %s", stub.handle, round_num, turn_result.action)

    # ── Phase 1: start await threads ─────────────────────────────────────────
    threads = [threading.Thread(target=run_stub, args=(s,), daemon=True) for s in stubs]
    for t in threads:
        t.start()

    # ── Phase 2: wait for coordination_join events ────────────────────────────
    expected_handles = [s.handle for s in stubs]
    joined = wait_for_coordination_join(api, setup.room, expected_handles, timeout=join_wait)
    if not joined:
        log.warning(
            "Not all agents joined within %ds — invoking aligner anyway", join_wait
        )

    # ── Phase 3: invoke aligner ───────────────────────────────────────────────
    r = cli.engine_invoke(
        setup.aligner_handle,
        setup.room,
        message="Please mediate the participants to an agreement.",
    )
    if not r.ok:
        log.error("engine invoke failed: %s", r.error_message)

    # ── Phase 4: poll for l9_commit terminal ─────────────────────────────────
    deadline = time.time() + total_timeout
    seen_ids: set[str] = set()
    while time.time() < deadline:
        terminal = poll_for_terminal_state(
            api, setup.room,
            timeout=5, poll_interval=2,
            seen_message_ids=seen_ids,
        )
        if terminal is not None:
            result.terminal = terminal
            log.info(
                "Terminal state: subkind=%s converged=%s",
                terminal.get("subkind"), terminal.get("converged"),
            )
            stop_event.set()
            break
        time.sleep(3)
    else:
        result.timed_out = True
        stop_event.set()
        log.warning("run_stubs_until_terminal timed out after %ds", total_timeout)

    for t in threads:
        t.join(timeout=turn_timeout + 5)

    return result
