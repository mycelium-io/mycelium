"""Subprocess wrapper for the ``mycelium`` CLI (SLIM-native)."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from typing import Any

log = logging.getLogger(__name__)

# `agent create`/`engine create` write agents/<handle>.md locally (see the
# module docstring in mycelium-cli's commands/agent.py: an agent is a memory
# entry the CLI writes directly, not just an HTTP call). In our CI hub setup
# the backend runs in a container under a fixed uid (1000 — "packer" on
# GitHub-hosted runners) that differs from the runner user, so that manifest's
# parent dir (created server-side as a side effect of the same command) is
# owned by a different uid than the CLI process. mycelium-cli's write guard
# (commands/agent.py:_check_writable_or_bail) rejects on exact uid mismatch by
# design (see its test_agent_add_root_owned.py and `mycelium doctor`'s own
# ownership check) — chmod/ACL bits don't satisfy it, only matching ownership
# does, and there's no supported way to make the container use a different
# uid without breaking its own internal logging (fastapi-backend/app/main.py
# writes logs/app.log relative to uid 1000's home).
#
# So instead of chasing the container's uid after the fact, run just the
# local-write commands as that same uid, set via MYCELIUM_LOCAL_WRITE_UID in
# CI. Unset (the default, e.g. local dev use) this is a no-op.
_LOCAL_WRITE_UID = os.environ.get("MYCELIUM_LOCAL_WRITE_UID", "")


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

    def run(
        self,
        *args: str,
        timeout: int | None = None,
        json_mode: bool = False,
        local_write: bool = False,
    ) -> CLIResult:
        cmd = [self.binary]
        if json_mode:
            cmd.append("--json")
        cmd.extend(args)

        if local_write and _LOCAL_WRITE_UID:
            # -u '#uid' addresses by numeric id, skipping any /etc/passwd
            # lookup — no dependency on "packer" staying that exact name.
            # HOME must stay pointed at the shared ~/.mycelium tree: sudo
            # resets it to the target uid's own home by default, which would
            # make the CLI look at (and create) an entirely different,
            # unrelated .mycelium directory. sudo also resets PATH to its
            # own secure_path regardless of what `env` is asked to set
            # afterward — mycelium lives in ~/.local/bin, not on that
            # default, so resolve the binary to an absolute path up front
            # rather than relying on PATH surviving the uid switch.
            binary = shutil.which(self.binary) or self.binary
            cmd[0] = binary
            cmd = [
                "sudo", "-u", f"#{_LOCAL_WRITE_UID}",
                "env", f"HOME={os.path.expanduser('~')}",
                *cmd,
            ]

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
        return self.run(*args, timeout=60, local_write=True)

    def agent_ls(self, room: str) -> CLIResult:
        return self.run("agent", "ls", "--room", room, json_mode=True)

    def agent_rm(self, handle: str, room: str) -> CLIResult:
        return self.run("agent", "rm", handle, "--room", room, timeout=30, local_write=True)

    def agent_invoke(self, handle: str, room: str, message: str = "") -> CLIResult:
        args = ["agent", "invoke", handle, "--room", room]
        if message:
            args.append(message)
        return self.run(*args, timeout=60)

    def engine_create(self, handle: str, room: str, kind: str = "aligner") -> CLIResult:
        return self.run(
            "engine", "create", handle, "--room", room, "--kind", kind,
            timeout=60, local_write=True,
        )

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
