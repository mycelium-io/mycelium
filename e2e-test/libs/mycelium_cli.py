"""Subprocess wrapper for the ``mycelium`` CLI."""

from __future__ import annotations

import json
import logging
import subprocess
import time
from typing import Any

log = logging.getLogger(__name__)


class CLIResult:
    """Wraps a CLI invocation result with convenience accessors."""

    def __init__(self, returncode: int, stdout: str, stderr: str, elapsed_ms: int, cmd: list[str]):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.elapsed_ms = elapsed_ms
        self.cmd = cmd

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def json(self) -> Any:
        try:
            return json.loads(self.stdout)
        except (json.JSONDecodeError, ValueError):
            return None

    @property
    def error_message(self) -> str:
        if self.ok:
            return ""
        msg = self.stderr.strip() or self.stdout.strip()
        return msg or f"Exit code {self.returncode}"

    def __repr__(self) -> str:
        return f"CLIResult(rc={self.returncode}, elapsed={self.elapsed_ms}ms, cmd={self.cmd!r})"


class MyceliumCLI:
    """Drives the ``mycelium`` CLI via subprocess."""

    def __init__(self, binary: str = "mycelium", default_timeout: int = 30):
        self.binary = binary
        self.default_timeout = default_timeout

    def run(self, *args: str, timeout: int | None = None, json_mode: bool = False) -> CLIResult:
        cmd = [self.binary]
        if json_mode:
            cmd.append("--json")
        cmd.extend(args)

        t = timeout or self.default_timeout
        start = time.time()
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=t)
            elapsed = int((time.time() - start) * 1000)
            log.debug("CLI %s -> rc=%d (%dms)", " ".join(cmd), result.returncode, elapsed)
            return CLIResult(result.returncode, result.stdout, result.stderr, elapsed, cmd)
        except subprocess.TimeoutExpired:
            elapsed = int((time.time() - start) * 1000)
            log.warning("CLI timeout after %ds: %s", t, " ".join(cmd))
            return CLIResult(-1, "", f"Command timed out after {t}s", elapsed, cmd)
        except Exception as e:
            elapsed = int((time.time() - start) * 1000)
            log.warning("CLI error: %s: %s", " ".join(cmd), e)
            return CLIResult(-1, "", str(e), elapsed, cmd)

    # ── Room commands ─────────────────────────────────────────────────────

    def room_create(self, name: str) -> CLIResult:
        return self.run("room", "create", name)

    def room_use(self, name: str) -> CLIResult:
        return self.run("room", "use", name)

    def room_ls(self) -> CLIResult:
        return self.run("room", "ls")

    def room_watch(self, name: str, timeout: int = 60) -> CLIResult:
        return self.run("room", "watch", name, timeout=timeout)

    # ── Memory commands ───────────────────────────────────────────────────

    def memory_set(self, room: str, handle: str, key: str, content: str) -> CLIResult:
        return self.run("memory", "set", "--room", room, "--handle", handle, key, content)

    def memory_get(self, room: str, key: str) -> CLIResult:
        return self.run("memory", "get", "--room", room, key)

    def memory_ls(self, room: str) -> CLIResult:
        return self.run("memory", "ls", "--room", room)

    def memory_search(self, room: str, query: str) -> CLIResult:
        return self.run("memory", "search", "--room", room, query)

    def memory_decisions(self, room: str) -> CLIResult:
        return self.run("memory", "decisions", "--room", room)

    def memory_status(self, room: str) -> CLIResult:
        return self.run("memory", "status", "--room", room)

    def memory_reindex(self, room: str) -> CLIResult:
        return self.run("memory", "reindex", "--room", room, timeout=120)

    # ── Session commands ──────────────────────────────────────────────────

    def session_join(self, room: str, handle: str, position: str = "") -> CLIResult:
        args = ["session", "join", "--room", room, "--handle", handle]
        result = self.run(*args, timeout=60)
        if result.ok and position:
            self.message_send(room, handle, position)
        return result

    def session_ls(self, room: str) -> CLIResult:
        return self.run("session", "ls", "--room", room)

    def session_await(self, room: str, timeout: int = 300) -> CLIResult:
        return self.run("session", "await", "--room", room, timeout=timeout)

    def session_watch(self, room: str, timeout: int = 300) -> CLIResult:
        return self.run("session", "watch", "--room", room, timeout=timeout)

    # ── Negotiation commands ──────────────────────────────────────────────

    def negotiate_propose(self, room: str, handle: str, topic: str) -> CLIResult:
        return self.run("negotiate", "propose", "--room", room, "--handle", handle,
                        f"topic={topic}", timeout=60)

    def negotiate_respond(self, room: str, handle: str, response: str) -> CLIResult:
        return self.run("negotiate", "respond", "--room", room, "--handle", handle,
                        f"response={response}", timeout=60)

    def negotiate_query(self, room: str) -> CLIResult:
        return self.run("negotiate", "query", "--room", room, timeout=30)

    # ── Synthesis / Catchup ───────────────────────────────────────────────

    def synthesize(self, room: str) -> CLIResult:
        return self.run("synthesize", "--room", room, timeout=120)

    def catchup(self, room: str) -> CLIResult:
        return self.run("catchup", "--room", room, timeout=60)

    # ── Config / Doctor ───────────────────────────────────────────────────

    def config_get(self, key: str) -> CLIResult:
        return self.run("config", "get", key)

    def config_set(self, key: str, value: str) -> CLIResult:
        return self.run("config", "set", key, value)

    def doctor(self) -> CLIResult:
        return self.run("doctor", json_mode=True, timeout=30)

    # ── Message ───────────────────────────────────────────────────────────

    def message_send(self, room: str, handle: str, content: str) -> CLIResult:
        return self.run("message", "send", "--room", room, "--handle", handle, content)
