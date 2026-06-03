"""Cursor adapter helpers — SSH dispatch, health checks, workspace management, polling."""

from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
import time
from typing import Optional
from urllib.parse import quote

from libs.mycelium_cli import CLIResult

log = logging.getLogger(__name__)

# Host topology
OCLW4_IP = os.environ.get("OCLW4_IP", "10.0.50.125")
OCLW3_IP = os.environ.get("OCLW3_IP", "10.0.50.171")
OCLW5_IP = os.environ.get("OCLW5_IP", "10.0.50.142")

HUB_HOST = os.environ.get("CURSOR_HUB_HOST", OCLW4_IP)
CURSOR_SPOKE_HOSTS = {
    "oclw3": OCLW3_IP,
    "oclw5": OCLW5_IP,
}

SSH_KEY = os.environ.get("SSH_KEY_PATH", "~/.ssh/ioc.pem")
SSH_USER = os.environ.get("SSH_USER", "ubuntu")
SSH_CONNECT_TIMEOUT = int(os.environ.get("SSH_CONNECT_TIMEOUT", "5"))

BACKEND_URL = os.environ.get("MYCELIUM_BACKEND_URL", f"http://{OCLW4_IP}:8000/api")

PATH_PREFIX = "export PATH=$HOME/.local/bin:$PATH;"


def ssh_run(
    host: str,
    cmd: str,
    *,
    timeout: float = 30.0,
    ssh_key: str | None = None,
    user: str | None = None,
) -> CLIResult:
    """Run a command on a remote host via SSH.

    Prepends PATH_PREFIX to ensure mycelium/cursor-agent are available
    in non-interactive shells.
    """
    key_path = os.path.expanduser(ssh_key or SSH_KEY)
    effective_user = user or SSH_USER
    remote_cmd = f"{PATH_PREFIX} {cmd}"

    ssh_cmd = [
        "ssh", "-i", key_path,
        "-o", "StrictHostKeyChecking=no",
        "-o", f"ConnectTimeout={SSH_CONNECT_TIMEOUT}",
        f"{effective_user}@{host}",
        remote_cmd,
    ]

    start = time.time()
    try:
        result = subprocess.run(
            ssh_cmd, capture_output=True, text=True, timeout=timeout, check=False,
        )
        elapsed = int((time.time() - start) * 1000)
        return CLIResult(result.returncode, result.stdout, result.stderr, elapsed, ssh_cmd)
    except subprocess.TimeoutExpired:
        elapsed = int((time.time() - start) * 1000)
        return CLIResult(124, "", "SSH command timed out", elapsed, ssh_cmd)
    except (FileNotFoundError, OSError) as exc:
        elapsed = int((time.time() - start) * 1000)
        return CLIResult(127, "", str(exc), elapsed, ssh_cmd)


def check_cursor_agent_installed(host: str) -> bool:
    """Return True if cursor-agent binary is reachable on the remote host."""
    r = ssh_run(host, "which cursor-agent", timeout=10.0)
    return r.ok and "cursor-agent" in r.stdout


def check_ssh_connectivity(host: str) -> bool:
    """Return True if SSH to host succeeds."""
    r = ssh_run(host, "echo ok", timeout=10.0)
    return r.ok and "ok" in r.stdout


def create_cursor_workspace(host: str) -> str | None:
    """Create a temp directory on the remote host for a cursor agent workspace.

    Returns the path on the remote host, or None on failure.
    """
    r = ssh_run(host, "mktemp -d /tmp/cursor-e2e-XXXXXX", timeout=10.0)
    if r.ok and r.stdout.strip():
        path = r.stdout.strip()
        log.info("Created workspace on %s: %s", host, path)
        return path
    log.warning("Failed to create workspace on %s: %s", host, r.stderr)
    return None


def cleanup_cursor_workspace(host: str, path: str) -> None:
    """Remove a temp workspace directory on the remote host."""
    if not path or not path.startswith("/tmp/cursor-e2e-"):
        log.warning("Refusing to remove suspicious path: %s", path)
        return
    r = ssh_run(host, f"rm -rf {shlex.quote(path)}", timeout=10.0)
    if not r.ok:
        log.warning("Cleanup of %s on %s failed: %s", path, host, r.stderr)


def verify_agents_md(host: str, workspace_path: str) -> bool:
    """Check that AGENTS.md exists at workspace root and contains marker fences."""
    agents_md = f"{workspace_path}/AGENTS.md"
    r = ssh_run(host, f"cat {shlex.quote(agents_md)}", timeout=10.0)
    if not r.ok:
        return False
    content = r.stdout
    return "<!-- mycelium:start -->" in content


def run_mycelium_cli(
    host: str | None,
    *args: str,
    timeout: float = 30.0,
) -> CLIResult:
    """Run ``mycelium <args>`` either locally (host=None) or on a remote host."""
    cmd_str = "mycelium " + " ".join(shlex.quote(a) for a in args)

    if host is None:
        full_cmd = ["mycelium", *args]
        start = time.time()
        try:
            result = subprocess.run(
                full_cmd, capture_output=True, text=True, timeout=timeout, check=False,
            )
            elapsed = int((time.time() - start) * 1000)
            return CLIResult(result.returncode, result.stdout, result.stderr, elapsed, full_cmd)
        except subprocess.TimeoutExpired:
            elapsed = int((time.time() - start) * 1000)
            return CLIResult(124, "", "Command timed out", elapsed, full_cmd)
        except (FileNotFoundError, OSError) as exc:
            elapsed = int((time.time() - start) * 1000)
            return CLIResult(127, "", str(exc), elapsed, full_cmd)

    return ssh_run(host, cmd_str, timeout=timeout)


def create_room(host: str | None, room: str) -> CLIResult:
    """Create a room on the backend."""
    return run_mycelium_cli(host, "room", "create", room, timeout=15.0)


def delete_room(host: str | None, room: str) -> CLIResult:
    """Delete a room from the backend (--force to skip confirmation)."""
    return run_mycelium_cli(host, "room", "delete", room, "--force", timeout=15.0)


def daemon_subscribe(host: str | None, room: str) -> CLIResult:
    """Subscribe the cc-daemon to a room so it receives SSE events."""
    return run_mycelium_cli(host, "daemon", "subscribe", room, timeout=15.0)


def daemon_unsubscribe(host: str | None, room: str) -> CLIResult:
    """Unsubscribe the cc-daemon from a room."""
    return run_mycelium_cli(host, "daemon", "unsubscribe", room, timeout=15.0)


def create_cursor_agent(
    host: str | None,
    handle: str,
    room: str,
    workspace: str,
) -> CLIResult:
    """Create a cursor agent via mycelium CLI (greenfield path)."""
    return run_mycelium_cli(
        host,
        "agent", "create", handle,
        "--adapter", "cursor",
        "--cwd", workspace,
        "--room", room,
        timeout=30.0,
    )


def remove_cursor_agent(host: str | None, handle: str, *, room: str | None = None) -> CLIResult:
    """Remove a cursor agent via mycelium CLI."""
    args = ["agent", "rm", handle, "--force"]
    if room:
        args.extend(["--room", room])
    return run_mycelium_cli(host, *args, timeout=15.0)


def create_session(
    room: str,
    topic: str,
    agents: list[str],
    *,
    host: str | None = None,
    timeout: float = 60.0,
) -> CLIResult:
    """Create a coordination session and have each agent join with a position.

    Uses ``mycelium session create -r <room>`` then
    ``mycelium session join -r <room> -H <handle> -m <position>`` for each agent.
    """
    r = run_mycelium_cli(host, "session", "create", "--room", room, timeout=timeout)
    if not r.ok:
        return r

    for agent in agents:
        position = f"I'm {agent}. My position on '{topic}' is to find the best solution collaboratively."
        join_r = run_mycelium_cli(
            host,
            "session", "join",
            "--room", room,
            "--handle", agent,
            "--message", position,
            timeout=timeout,
        )
        if not join_r.ok:
            return join_r

    return r


def poll_session_status(
    room: str,
    *,
    timeout_seconds: int = 600,
    poll_interval: int = 5,
    target_status: str = "consensus",
) -> dict | None:
    """Poll the backend for a session reaching the target status.

    Returns the session dict if found, None on timeout.
    """
    import urllib.request
    import urllib.error

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            url = f"{BACKEND_URL}/rooms/{quote(room, safe='')}/messages?limit=100"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                messages = data.get("messages", [])
                for msg in messages:
                    msg_type = msg.get("message_type", "")
                    if msg_type == f"coordination_{target_status}":
                        log.info("Session reached %s in room %s", target_status, room)
                        try:
                            return json.loads(msg.get("content", "{}"))
                        except json.JSONDecodeError:
                            return {"raw": msg.get("content")}
        except (urllib.error.URLError, OSError, ValueError) as exc:
            log.debug("Poll error for %s: %s", room, exc)

        time.sleep(poll_interval)

    log.warning("Timeout (%ds) waiting for %s in room %s", timeout_seconds, target_status, room)
    return None


def wait_for_agent_response(
    room: str,
    agent_handle: str,
    *,
    timeout_seconds: int = 120,
    poll_interval: int = 5,
    after_ts: float | None = None,
) -> dict | None:
    """Poll the backend for a message from a specific agent handle.

    Returns the message dict if found, None on timeout.
    The backend returns ``sender_handle`` and ``created_at`` (ISO 8601).
    """
    import urllib.request
    import urllib.error
    from datetime import datetime, timezone

    deadline = time.time() + timeout_seconds
    cutoff_dt = datetime.fromtimestamp(after_ts or time.time(), tz=timezone.utc)

    while time.time() < deadline:
        try:
            url = f"{BACKEND_URL}/rooms/{quote(room, safe='')}/messages?limit=50"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                for msg in data.get("messages", []):
                    sender = msg.get("sender_handle", "") or msg.get("sender", "")
                    created_at = msg.get("created_at", "")
                    if agent_handle in sender and created_at:
                        try:
                            msg_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                        except (ValueError, TypeError):
                            continue
                        if msg_dt >= cutoff_dt:
                            log.info("Response from %s in room %s", agent_handle, room)
                            return msg
        except (urllib.error.URLError, OSError, ValueError) as exc:
            log.debug("Poll error: %s", exc)

        time.sleep(poll_interval)

    log.warning("Timeout waiting for response from %s in %s", agent_handle, room)
    return None


def check_daemon_health(host: str | None) -> bool:
    """Check if mycelium-cc-daemon is responsive on the given host."""
    r = run_mycelium_cli(host, "daemon", "status", timeout=10.0)
    if r.ok:
        return True
    r2 = ssh_run(host, "systemctl --user is-active mycelium-cc-daemon", timeout=10.0) if host else r
    return host is not None and r2.ok and "active" in r2.stdout


def invoke_agent(
    host: str | None,
    handle: str,
    message: str,
    *,
    room: str | None = None,
    timeout: float = 60.0,
) -> CLIResult:
    """Invoke a cursor agent with a message via mycelium CLI.

    CLI signature: ``mycelium agent invoke HANDLE PROMPT [--room ROOM]``
    """
    args = ["agent", "invoke", handle, message]
    if room:
        args.extend(["--room", room])
    return run_mycelium_cli(host, *args, timeout=timeout)
