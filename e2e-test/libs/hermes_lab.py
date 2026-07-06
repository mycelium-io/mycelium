"""Hermes lab provisioner — idempotent setup of hermes across nodes.

Handles per-node state that must exist before any hermes E2E test runs:
  - hermes binary reachable on PATH
  - hermes adapter registered in mycelium (``mycelium adapter add hermes``)
  - hermes gateway running

Hermes talks to Mycelium rooms directly via the ``mycelium-room`` platform
plugin — no Matrix homeserver, mautrix, or Synapse users are required.

All operations are idempotent — safe to re-run against an already-provisioned
node. Designed to be called from ``scripts/provision_hermes_lab.py`` in CI
(full setup from scratch) or from ``CommonSetup.check_hermes_prereqs`` in the
test suite (fast check, skip-not-fail if missing).
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class NodeConfig:
    """Per-node hermes provisioning config."""

    name: str  # human label (e.g. "hub", "spoke1")
    ssh_ip: str
    ssh_user: str = "ubuntu"
    ssh_key: str = "~/.ssh/ioc.pem"
    # Path to hermes venv python on the node — auto-detected if empty
    hermes_python: str = ""


@dataclass
class ProvisionResult:
    node: str
    success: bool
    steps: list[tuple[str, bool, str]] = field(default_factory=list)
    error: str | None = None

    def record(self, step: str, ok: bool, detail: str = "") -> bool:
        snippet = (detail.splitlines()[-1] if detail else "")[:200]
        self.steps.append((step, ok, snippet))
        if ok:
            log.info("[%s] ✓ %s%s", self.node, step, f" — {snippet}" if snippet else "")
        else:
            log.warning("[%s] ✗ %s — %s", self.node, step, snippet)
        return ok


# ── SSH helpers ────────────────────────────────────────────────────────────────


def _ssh(
    ip: str,
    user: str,
    key: str,
    cmd: str,
    *,
    timeout: float = 60.0,
) -> tuple[int, str, str]:
    import os

    full = f'export PATH="$HOME/.local/bin:$PATH"; {cmd}'
    proc = subprocess.run(
        [
            "ssh",
            "-i",
            os.path.expanduser(key),
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "ConnectTimeout=5",
            f"{user}@{ip}",
            full,
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _detect_hermes_python(ip: str, user: str, key: str) -> str:
    """Return the python3 path inside the hermes venv on the remote node."""
    rc, out, _ = _ssh(ip, user, key, "head -1 $(which hermes) 2>/dev/null", timeout=10.0)
    if rc == 0 and out.strip().startswith("#!"):
        return out.strip()[2:].strip()
    return "/home/ubuntu/hermes-agent/venv/bin/python3"


# ── per-node provisioning ──────────────────────────────────────────────────────


def provision_node(cfg: NodeConfig) -> ProvisionResult:
    """Idempotently provision hermes on a single node."""
    result = ProvisionResult(node=cfg.name, success=False)
    ip, user, key = cfg.ssh_ip, cfg.ssh_user, cfg.ssh_key

    # ── 1. Detect hermes python ────────────────────────────────────────
    hermes_python = cfg.hermes_python or _detect_hermes_python(ip, user, key)
    rc, _, _ = _ssh(ip, user, key, f"{hermes_python} -c 'import sys; print(sys.version)'", timeout=10.0)
    if not result.record("hermes python reachable", rc == 0, hermes_python):
        result.error = f"hermes venv python not found at {hermes_python}"
        return result

    # ── 2. Register hermes adapter ────────────────────────────────────
    rc, out, _ = _ssh(ip, user, key, "mycelium adapter ls 2>&1", timeout=15.0)
    if rc == 0 and "hermes" in out.lower():
        result.record("hermes adapter registered", True)
    else:
        rc, out, err = _ssh(ip, user, key, "mycelium adapter add hermes --reinstall -y 2>&1", timeout=120.0)
        result.record("register hermes adapter", rc == 0, out + err)
        if rc != 0:
            result.error = "adapter registration failed"
            return result

    # ── 3. Ensure gateway is running ──────────────────────────────────
    rc, out, _ = _ssh(ip, user, key, "hermes gateway status 2>&1", timeout=10.0)
    running = rc == 0 and ("running" in out.lower() or "pid" in out.lower())
    if running:
        result.record("hermes gateway running", True)
    else:
        rc, out, err = _ssh(ip, user, key, "hermes gateway start 2>&1", timeout=30.0)
        result.record("start hermes gateway", rc == 0, out + err)
        if rc != 0:
            result.error = "gateway start failed"
            return result

    result.success = True
    return result


def provision_lab(nodes: list[NodeConfig]) -> list[ProvisionResult]:
    """Provision all nodes; returns results in input order."""
    results = []
    for node in nodes:
        log.info("Provisioning %s (%s)…", node.name, node.ssh_ip)
        result = provision_node(node)
        results.append(result)
    return results


def check_prereqs(ip: str, user: str, key: str) -> list[str]:
    """Return a list of missing prerequisites on the node (empty = all good)."""
    missing = []

    rc, _, _ = _ssh(ip, user, key, "command -v hermes >/dev/null 2>&1", timeout=10.0)
    if rc != 0:
        missing.append("hermes binary not on PATH — install hermes-agent first")

    hermes_python = _detect_hermes_python(ip, user, key)
    rc, _, _ = _ssh(ip, user, key, f"{hermes_python} -c 'import sys; print(sys.version)'", timeout=10.0)
    if rc != 0:
        missing.append("hermes venv python not reachable — check hermes install")

    rc, out, _ = _ssh(ip, user, key, "mycelium adapter ls 2>&1", timeout=15.0)
    if rc != 0 or "hermes" not in out.lower():
        missing.append("hermes adapter not registered — run provision_hermes_lab.py")

    rc, out, _ = _ssh(ip, user, key, "hermes gateway status 2>&1", timeout=10.0)
    if rc != 0 or ("running" not in out.lower() and "pid" not in out.lower()):
        missing.append("hermes gateway not running — run: hermes gateway start")

    return missing
