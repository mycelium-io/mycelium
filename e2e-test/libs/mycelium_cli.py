"""Subprocess wrapper for the ``mycelium`` CLI (SLIM-native)."""

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

    # ── Await / Respond (SLIM-native turn loop) ───────────────────────────

    def await_turn(
        self,
        room: str,
        handle: str,
        timeout: int = 120,
    ) -> CLIResult:
        """Block until a turn arrives for *handle* in *room*. Returns JSON turn."""
        return self.run(
            "await", "--room", room, "--handle", handle,
            "--timeout", str(timeout), "--json",
            timeout=timeout + 15,
            json_mode=False,
        )

    def respond(self, room: str, handle: str, text: str) -> CLIResult:
        """Publish a reply for *handle* in *room*.

        Append a position marker to *text* if desired:
        ``"I can accept this [<accept>]"``
        """
        return self.run("respond", "--room", room, "--handle", handle, text, timeout=30)

    # ── Agent / Engine commands ───────────────────────────────────────────

    def agent_create(
        self,
        handle: str,
        room: str,
        adapter: str = "claude_code",
        cwd: str = "",
        description: str = "",
    ) -> CLIResult:
        args = ["agent", "create", handle, "--room", room, "--adapter", adapter]
        if cwd:
            args.extend(["--cwd", cwd])
        if description:
            args.extend(["--description", description])
        return self.run(*args, timeout=60)

    def agent_ls(self, room: str) -> CLIResult:
        return self.run("agent", "ls", "--room", room, json_mode=True)

    def agent_rm(self, handle: str, room: str) -> CLIResult:
        return self.run("agent", "rm", handle, "--room", room, timeout=30)

    def agent_invoke(self, handle: str, room: str, message: str = "") -> CLIResult:
        args = ["agent", "invoke", handle, "--room", room]
        if message:
            args.append(message)
        return self.run(*args, timeout=60)

    def engine_create(self, handle: str, room: str, kind: str = "aligner") -> CLIResult:
        return self.run("engine", "create", handle, "--room", room, "--kind", kind, timeout=60)

    def engine_invoke(self, handle: str, room: str, message: str = "") -> CLIResult:
        args = ["engine", "invoke", handle, "--room", room]
        if message:
            args.append(message)
        return self.run(*args, timeout=60)

    # ── Network / Status ──────────────────────────────────────────────────

    def network(self, room: str = "") -> CLIResult:
        args = ["network"]
        if room:
            args.append(room)
        return self.run(*args, json_mode=True, timeout=15)

    def status(self) -> CLIResult:
        return self.run("status", json_mode=True, timeout=15)

    # ── Config / Doctor ───────────────────────────────────────────────────

    def config_get(self, key: str) -> CLIResult:
        return self.run("config", "get", key)

    def config_set(self, key: str, value: str) -> CLIResult:
        return self.run("config", "set", key, value)

    def doctor(self) -> CLIResult:
        return self.run("doctor", json_mode=True, timeout=30)
