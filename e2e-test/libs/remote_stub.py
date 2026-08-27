"""Remote stub agent — drives mycelium await/respond via host_exec.

Since await/respond are stateless HTTP calls to the backend, a stub can run
on any device (local, docker, ssh) simply by dispatching CLI commands through
host_exec.execute(). No SLIM socket or special networking is required on the
spoke — only HTTP connectivity to MYCELIUM_BACKEND_URL.

Usage::

    hub_device = testscript.parameters["testbed"].devices["hub"]
    spoke1_device = testscript.parameters["testbed"].devices["spoke1"]

    stubs = [
        RemoteStubAgent(hub_device, room, "stub-hub", action="accept"),
        RemoteStubAgent(spoke1_device, room, "stub-spoke1", action="accept"),
    ]
    result = run_remote_stubs_until_terminal(
        api, stubs, setup=coord_setup,
        total_timeout=180,
    )
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from libs.coordination_flow import (
    CoordinationSetup,
    poll_for_terminal_state,
    wait_for_coordination_join,
)
from libs.host_exec import execute, HostExecError, describe
from libs.mycelium_api import MyceliumAPI

log = logging.getLogger(__name__)

Action = Literal["accept", "reject", "counter"]

CODE_OK = "OK"
CODE_SILENT = "SILENT"
CODE_EXEC_ERROR = "EXEC_ERROR"


@dataclass
class TurnResult:
    handle: str
    device: str  # describe(device) string
    round_num: int
    action: Action
    ok: bool
    code: str = CODE_OK
    detail: str = ""


@dataclass
class RemoteStubRunResult:
    turns: list[TurnResult] = field(default_factory=list)
    terminal: dict | None = None
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
    return "I propose a modified compromise approach."


class RemoteStubAgent:
    """Stub agent that runs mycelium CLI on a remote device via host_exec."""

    def __init__(
        self,
        device: Any,
        room: str,
        handle: str,
        action: Action = "accept",
        prose: str = "",
        backend_url: str = "",
        action_fn: Callable[[int], Action] | None = None,
        use_cursor: bool = False,
        cursor_model: str = "",
    ):
        self.device = device
        self.device_desc = describe(device)
        self.room = room
        self.handle = handle
        self.default_action = action
        self.prose = prose
        self.backend_url = backend_url
        self.action_fn = action_fn
        # Opt-in: have a real `cursor-agent`/`agent` CLI generate this
        # stub's replies instead of the scripted accept/reject/counter
        # prose. Requires CURSOR_API_KEY set in the environment on
        # ``device`` (host_exec forwards it to docker-transport spokes;
        # local/hub inherits it directly) and the cursor CLI on PATH.
        # Any failure (missing key, binary absent, empty output, timeout)
        # falls back to the scripted prose so a flaky/unconfigured cursor
        # setup never turns into a silent turn.
        self.use_cursor = use_cursor
        self.cursor_model = cursor_model or os.environ.get("CURSOR_MODEL", "")

    def _env_args(self) -> list[str]:
        """Build env var prefix for CLI commands if backend_url is set."""
        if self.backend_url:
            return ["env", f"MYCELIUM_BACKEND_URL={self.backend_url}"]
        return []

    def _choose_action(self, round_num: int) -> Action:
        if self.action_fn:
            return self.action_fn(round_num)
        return self.default_action

    def _respond_text(self, action: Action) -> str:
        body = self.prose or _default_prose(action)
        return body  # plain prose — aligner interprets it, no markers needed

    def _cursor_respond_text(self, turn_data: dict | None, action: Action, timeout: int = 45) -> str | None:
        """Generate this turn's reply with a real `cursor-agent`/`agent` CLI call.

        Returns the model's plain-text output, or None on any failure
        (missing binary, no CURSOR_API_KEY, empty output, timeout) so the
        caller can fall back to the scripted prose.
        """
        stance = self.prose or _default_prose(action)
        prompt = (
            "You are one participant in a multi-agent negotiation coordinated "
            "by the mycelium CLI. Reply with ONE short paragraph of plain text "
            "(no markdown, no preamble, no your-name prefix) stating your "
            "position — accept, reject, or propose a compromise — based on the "
            "context below.\n\n"
            f"Your handle: {self.handle}\n"
            f"Your stance: {stance}\n"
            f"Latest room context (JSON, may be empty): {json.dumps(turn_data or {})}"
        )
        cmd = ["agent", "-p", prompt, "--output-format", "text"]
        if self.cursor_model:
            cmd.extend(["--model", self.cursor_model])
        try:
            result = execute(self.device, cmd, timeout=timeout)
        except HostExecError as e:
            log.warning("RemoteStub %s@%s cursor-agent exec error: %s",
                       self.handle, self.device_desc, e)
            return None
        if result.returncode != 0:
            log.warning("RemoteStub %s@%s cursor-agent rc=%d stderr=%s",
                       self.handle, self.device_desc, result.returncode, result.stderr.strip()[:200])
            return None
        text = result.stdout.strip()
        return text or None

    def await_turn(self, turn_timeout: int, stop_event: threading.Event) -> dict | None:
        """Call `mycelium await` on the device. Returns parsed JSON or None."""
        cmd = [
            *self._env_args(),
            "mycelium", "await",
            "--room", self.room,
            "--handle", self.handle,
            "--timeout", str(turn_timeout),
            "--json",
        ]
        try:
            result = execute(self.device, cmd, timeout=turn_timeout + 10)
        except HostExecError as e:
            if not stop_event.is_set():
                log.warning("RemoteStub %s@%s await exec error: %s",
                           self.handle, self.device_desc, e)
            return None

        if result.returncode != 0 or not result.stdout.strip():
            return None

        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return None

    def post_respond(self, text: str, turn_timeout: int) -> bool:
        """Call `mycelium respond` on the device. Returns True on success."""
        cmd = [
            *self._env_args(),
            "mycelium", "respond",
            "--room", self.room,
            "--handle", self.handle,
            text,
        ]
        try:
            result = execute(self.device, cmd, timeout=turn_timeout)
            return result.returncode == 0
        except HostExecError as e:
            log.warning("RemoteStub %s@%s respond exec error: %s",
                       self.handle, self.device_desc, e)
            return False

    def do_one_turn(
        self,
        round_num: int,
        turn_timeout: int,
        stop_event: threading.Event,
    ) -> TurnResult:
        turn_data = self.await_turn(turn_timeout, stop_event)
        if stop_event.is_set():
            return TurnResult(self.handle, self.device_desc, round_num,
                              self.default_action, ok=True, detail="stop_event set")

        if turn_data is None:
            return TurnResult(self.handle, self.device_desc, round_num,
                              self.default_action, ok=False, code=CODE_SILENT,
                              detail="await returned no message")

        action = self._choose_action(round_num)
        text = None
        if self.use_cursor:
            text = self._cursor_respond_text(turn_data, action)
            if text is None:
                log.warning("RemoteStub %s@%s cursor-agent produced no usable reply, "
                           "falling back to scripted prose", self.handle, self.device_desc)
        if text is None:
            text = self._respond_text(action)
        ok = self.post_respond(text, turn_timeout)
        return TurnResult(
            self.handle, self.device_desc, round_num, action, ok=ok,
            code=CODE_OK if ok else CODE_SILENT,
            detail="" if ok else "respond failed",
        )


def run_remote_stubs_until_terminal(
    api: MyceliumAPI,
    stubs: list[RemoteStubAgent],
    *,
    setup: CoordinationSetup,
    max_rounds: int = 30,
    turn_timeout: int = 90,
    join_wait: int = 10,
    total_timeout: int = 600,
    cli: Any = None,
) -> RemoteStubRunResult:
    """Drive remote stubs through SLIM-native coordination flow.

    Same flow as stub_agent.run_stubs_until_terminal but each agent
    dispatches CLI commands via host_exec to its own device.
    """
    from libs.mycelium_cli import MyceliumCLI
    _cli = cli or MyceliumCLI()

    result = RemoteStubRunResult()
    stop_event = threading.Event()
    lock = threading.Lock()

    def run_stub(stub: RemoteStubAgent) -> None:
        for round_num in range(max_rounds):
            if stop_event.is_set():
                break
            tr = stub.do_one_turn(round_num, turn_timeout, stop_event)
            if stop_event.is_set() and tr.detail == "stop_event set":
                break
            with lock:
                result.turns.append(tr)
            if not tr.ok:
                log.warning("RemoteStub %s@%s round %d: %s — %s",
                           stub.handle, stub.device_desc, round_num, tr.code, tr.detail)
            else:
                log.debug("RemoteStub %s@%s round %d: %s",
                         stub.handle, stub.device_desc, round_num, tr.action)

    # Phase 1: start stub threads (they register presence via await)
    threads = [threading.Thread(target=run_stub, args=(s,), daemon=True) for s in stubs]
    for t in threads:
        t.start()

    # Phase 2: wait for coordination_join events
    expected = [s.handle for s in stubs]
    joined = wait_for_coordination_join(api, setup.room, expected, timeout=join_wait)
    if not joined:
        log.warning("Not all agents joined within %ds — invoking aligner anyway", join_wait)

    # Phase 3: invoke aligner
    r = _cli.engine_invoke(setup.aligner_handle, setup.room,
                           "Please mediate the participants to an agreement.")
    if not r.ok:
        log.error("engine invoke failed: %s", r.error_message)

    # Phase 4: poll for l9_commit
    deadline = time.time() + total_timeout
    seen_ids: set[str] = set()
    while time.time() < deadline:
        terminal = poll_for_terminal_state(
            api, setup.room, timeout=5, poll_interval=2,
            seen_message_ids=seen_ids,
        )
        if terminal is not None:
            result.terminal = terminal
            log.info("Terminal: subkind=%s converged=%s",
                     terminal.get("subkind"), terminal.get("converged"))
            stop_event.set()
            break
        time.sleep(3)
    else:
        result.timed_out = True
        stop_event.set()
        log.warning("run_remote_stubs_until_terminal timed out after %ds", total_timeout)

    for t in threads:
        t.join(timeout=turn_timeout + 5)

    return result
