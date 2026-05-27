"""OpenClaw gateway helpers — session management, agent control, SSH/Docker wrappers."""

from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

RESET_SESSION_TAGS = ("mycelium-room", "matrix:channel:")

TRANSPORT = os.environ.get("OPENCLAW_TRANSPORT", "ssh")


def run_openclaw(
    args: list[str],
    *,
    host: str | None = None,
    container: str | None = None,
    transport: str | None = None,
    ssh_key: str = "~/.ssh/ioc.pem",
    user: str = "ubuntu",
    timeout: float = 15.0,
) -> subprocess.CompletedProcess[str] | None:
    """Run ``openclaw <args>`` locally, via SSH, or via ``docker exec``.

    Transport selection:
    - ``host is None`` and ``container is None``: run locally
    - ``transport="docker"`` or ``container`` is set: ``docker exec``
    - otherwise: SSH to ``host``
    """
    effective_transport = transport or TRANSPORT

    if host is None and container is None:
        try:
            return subprocess.run(
                ["openclaw", *args],
                capture_output=True, text=True, timeout=timeout, check=False,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return None

    if effective_transport == "docker" or container:
        ctr = container or host
        if not ctr:
            return None
        cmd = ["docker", "exec", ctr, "openclaw", *args]
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return None

    key_path = os.path.expanduser(ssh_key)
    if not os.path.exists(key_path):
        return None

    remote_cmd = " ".join(shlex.quote(a) for a in ["openclaw", *args])
    full_remote = (
        '[ -s "$HOME/.nvm/nvm.sh" ] && . "$HOME/.nvm/nvm.sh" >/dev/null 2>&1; '
        + remote_cmd
    )
    cmd = [
        "ssh", "-i", key_path, "-o", "StrictHostKeyChecking=no",
        "-o", f"ConnectTimeout=5", f"{user}@{host}", full_remote,
    ]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def list_agent_sessions(
    agent_id: str,
    *,
    host: str | None = None,
    container: str | None = None,
    transport: str | None = None,
    tags: tuple[str, ...] = RESET_SESSION_TAGS,
) -> list[dict[str, Any]]:
    """List an agent's sessions that carry negotiation traffic."""
    proc = run_openclaw(
        ["sessions", "--agent", agent_id, "--json", "--limit", "100"],
        host=host, container=container, transport=transport, timeout=20.0,
    )
    if proc is None or proc.returncode != 0 or not proc.stdout.strip():
        return []
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return []
    sessions = data if isinstance(data, list) else data.get("sessions", [])
    return [
        s for s in sessions
        if any(tag in (s.get("key") or s.get("sessionKey") or "") for tag in tags)
    ]


def reset_session(
    key: str,
    *,
    host: str | None = None,
    container: str | None = None,
    transport: str | None = None,
) -> bool:
    """Call gateway RPC ``sessions.reset`` for a single session key."""
    proc = run_openclaw(
        ["gateway", "call", "sessions.reset", "--params", json.dumps({"key": key})],
        host=host, container=container, transport=transport, timeout=15.0,
    )
    return proc is not None and proc.returncode == 0


def reset_agent_sessions(
    agents_by_host: dict[str | None, tuple[str, ...]],
    containers: dict[str, str] | None = None,
) -> tuple[int, int]:
    """Reset negotiation-carrying sessions for all agents. Returns (ok, failed).

    ``containers`` maps host keys to Docker container names for the docker
    transport (e.g. ``{"spoke1": "e2e-openclaw-spoke1"}``).
    """
    containers = containers or {}
    total_reset = 0
    total_failed = 0
    for host, agent_ids in agents_by_host.items():
        label = host or "local"
        ctr = containers.get(host) if host else None
        for agent_id in agent_ids:
            sessions = list_agent_sessions(agent_id, host=host, container=ctr)
            for s in sessions:
                key = s.get("key") or s.get("sessionKey")
                if not key:
                    continue
                tokens = s.get("inputTokens") or s.get("totalTokens") or 0
                context_cap = s.get("contextTokens") or 0
                pct = (tokens / context_cap * 100) if context_cap else 0
                if reset_session(key, host=host, container=ctr):
                    total_reset += 1
                    log.info("Reset %s:%s (%d tokens, %.0f%% ctx)", label, agent_id, tokens, pct)
                else:
                    total_failed += 1
                    log.warning("Reset FAILED %s:%s key=%s", label, agent_id, key)
    return total_reset, total_failed


def trim_agent_sessions(max_files: int = 5) -> int:
    """Remove excess .jsonl session files for local agents."""
    agents_dir = Path.home() / ".openclaw" / "agents"
    if not agents_dir.exists():
        return 0
    total_trimmed = 0
    for agent_dir in agents_dir.iterdir():
        if not agent_dir.is_dir():
            continue
        sessions_dir = agent_dir / "sessions"
        if not sessions_dir.exists():
            continue
        jsonl_files = sorted(sessions_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
        excess = len(jsonl_files) - max_files
        if excess > 0:
            for f in jsonl_files[:excess]:
                f.unlink(missing_ok=True)
            total_trimmed += excess
            log.info("Trimmed %d session files for %s", excess, agent_dir.name)
    return total_trimmed


def trim_remote_agent_sessions(
    hosts: list[str],
    max_files: int = 5,
    ssh_key: str = "~/.ssh/ioc.pem",
    user: str = "ubuntu",
    containers: dict[str, str] | None = None,
) -> None:
    """Trim .jsonl session files on remote gateway hosts (SSH or Docker)."""
    containers = containers or {}
    trim_script = (
        f"for d in ~/.openclaw/agents/*/sessions; do "
        f'  [ -d "$d" ] || continue; '
        f'  count=$(ls -1 "$d"/*.jsonl 2>/dev/null | wc -l); '
        f'  if [ "$count" -gt {max_files} ]; then '
        f'    ls -1t "$d"/*.jsonl | tail -n +{max_files + 1} | xargs rm -f; '
        f'    echo "trimmed $d: $count -> {max_files}"; '
        f"  fi; "
        f"done"
    )

    for host in hosts:
        ctr = containers.get(host)
        try:
            if ctr:
                result = subprocess.run(
                    ["docker", "exec", ctr, "sh", "-c", trim_script],
                    capture_output=True, text=True, timeout=10,
                )
            else:
                key_path = os.path.expanduser(ssh_key)
                if not os.path.exists(key_path):
                    continue
                result = subprocess.run(
                    ["ssh", "-i", key_path, "-o", "StrictHostKeyChecking=no",
                     "-o", "ConnectTimeout=5", f"{user}@{host}", trim_script],
                    capture_output=True, text=True, timeout=10,
                )
            for line in result.stdout.strip().splitlines():
                if line:
                    log.info("%s: %s", host, line)
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass


def wait_for_agents_idle(
    agents_by_host: dict[str | None, tuple[str, ...]],
    timeout: int = 20,
    poll_interval: float = 2.0,
    containers: dict[str, str] | None = None,
) -> dict[str, int]:
    """Poll until all agents have 0 active turns. Returns final counts."""
    import time
    containers = containers or {}
    deadline = time.time() + timeout
    counts: dict[str, int] = {}
    while time.time() < deadline:
        counts.clear()
        all_idle = True
        for host, agent_ids in agents_by_host.items():
            ctr = containers.get(host) if host else None
            for agent_id in agent_ids:
                proc = run_openclaw(
                    ["sessions", "--agent", agent_id, "--json", "--limit", "1"],
                    host=host, container=ctr, timeout=10.0,
                )
                active = 0
                if proc and proc.returncode == 0 and proc.stdout.strip():
                    try:
                        data = json.loads(proc.stdout)
                        sessions = data if isinstance(data, list) else data.get("sessions", [])
                        active = sum(1 for s in sessions if s.get("active"))
                    except (json.JSONDecodeError, TypeError):
                        pass
                label = f"{host or 'local'}:{agent_id}"
                counts[label] = active
                if active > 0:
                    all_idle = False
        if all_idle:
            break
        time.sleep(poll_interval)
    return counts
