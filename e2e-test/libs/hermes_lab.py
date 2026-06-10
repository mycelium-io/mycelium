"""Hermes lab provisioner — idempotent setup of hermes + Matrix across nodes.

Handles per-node state that must exist before any hermes E2E test runs:
  - mautrix (the hermes[matrix] extra) installed in the hermes venv
  - Dedicated Matrix user created on Synapse (hermes-oclw4/3/5)
  - hermes adapter registered in mycelium (``mycelium adapter add hermes``)
  - hermes gateway running

All operations are idempotent — safe to re-run against an already-provisioned
node. Designed to be called from ``scripts/provision_hermes_lab.py`` in CI
(full setup from scratch) or from ``CommonSetup.check_hermes_prereqs`` in the
test suite (fast check, skip-not-fail if missing).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

log = logging.getLogger(__name__)

# Synapse container name — same default as refresh-matrix-tokens.sh
_SYNAPSE_CONTAINER = "matrix-synapse"

# mautrix version pinned to match hermes pyproject.toml extras
_MAUTRIX_PACKAGES = (
    "mautrix[encryption]==0.21.0",
    "aiosqlite",
    "asyncpg",
    "aiohttp-socks",
    "Markdown",
)


@dataclass
class NodeConfig:
    """Per-node hermes provisioning config."""

    name: str               # human label (e.g. "hub", "spoke1")
    ssh_ip: str
    ssh_user: str = "ubuntu"
    ssh_key: str = "~/.ssh/ioc.pem"
    matrix_user: str = ""   # e.g. "hermes-oclw4"; derived from name if empty
    matrix_homeserver: str = "http://localhost:8008"
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
        ["ssh", "-i", os.path.expanduser(key),
         "-o", "StrictHostKeyChecking=no",
         "-o", "ConnectTimeout=5",
         f"{user}@{ip}", full],
        capture_output=True, text=True, timeout=timeout,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _detect_hermes_python(ip: str, user: str, key: str) -> str:
    """Return the python3 path inside the hermes venv on the remote node."""
    rc, out, _ = _ssh(ip, user, key, "head -1 $(which hermes) 2>/dev/null", timeout=10.0)
    if rc == 0 and out.strip().startswith("#!"):
        return out.strip()[2:].strip()
    return "/home/ubuntu/hermes-agent/venv/bin/python3"


# ── Synapse helpers ────────────────────────────────────────────────────────────

def _synapse_secret() -> str:
    raw = subprocess.check_output(
        ["docker", "exec", _SYNAPSE_CONTAINER,
         "grep", "registration_shared_secret:", "/data/homeserver.yaml"],
        text=True,
    )
    return raw.split('"')[1]


def _synapse_server_name() -> str:
    raw = subprocess.check_output(
        ["docker", "exec", _SYNAPSE_CONTAINER,
         "grep", "server_name:", "/data/homeserver.yaml"],
        text=True,
    )
    return raw.split('"')[1]


def get_admin_token(homeserver: str) -> str:
    """Create a short-lived Synapse admin user; return its access token."""
    secret = _synapse_secret()
    nonce = httpx.get(f"{homeserver}/_synapse/admin/v1/register").json()["nonce"]
    admin_user = f"mycelium-admin-{uuid.uuid4().hex[:12]}"
    admin_pass = uuid.uuid4().hex

    mac = hmac.new(secret.encode(), digestmod=hashlib.sha1)
    for part in [nonce, "\x00", admin_user, "\x00", admin_pass, "\x00", "admin"]:
        mac.update(part.encode())

    resp = httpx.post(
        f"{homeserver}/_synapse/admin/v1/register",
        json={"nonce": nonce, "username": admin_user,
              "password": admin_pass, "admin": True, "mac": mac.hexdigest()},
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def ensure_matrix_user(homeserver: str, admin_token: str, username: str) -> None:
    """Create *username* on Synapse if it does not already exist."""
    server_name = _synapse_server_name()
    user_id = f"@{username}:{server_name}"
    resp = httpx.get(
        f"{homeserver}/_synapse/admin/v2/users/{user_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    if resp.status_code == 200:
        log.info("Matrix user %s already exists", user_id)
        return
    httpx.put(
        f"{homeserver}/_synapse/admin/v2/users/{user_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"password": uuid.uuid4().hex, "admin": False, "displayname": username},
    ).raise_for_status()
    log.info("Created Matrix user %s", user_id)


def impersonate_user(homeserver: str, admin_token: str, username: str) -> str:
    """Return a fresh access token for *username* via admin impersonation."""
    server_name = _synapse_server_name()
    resp = httpx.post(
        f"{homeserver}/_synapse/admin/v1/users/@{username}:{server_name}/login",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={},
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


# ── per-node provisioning ──────────────────────────────────────────────────────

def provision_node(cfg: NodeConfig, admin_token: str) -> ProvisionResult:
    """Idempotently provision hermes + Matrix on a single node."""
    result = ProvisionResult(node=cfg.name, success=False)
    ip, user, key = cfg.ssh_ip, cfg.ssh_user, cfg.ssh_key

    # ── 1. Detect hermes python ────────────────────────────────────────
    hermes_python = cfg.hermes_python or _detect_hermes_python(ip, user, key)
    rc, _, _ = _ssh(ip, user, key, f"{hermes_python} -c 'import sys; print(sys.version)'", timeout=10.0)
    if not result.record("hermes python reachable", rc == 0, hermes_python):
        result.error = f"hermes venv python not found at {hermes_python}"
        return result

    # ── 2. Install mautrix ────────────────────────────────────────────
    rc, out, err = _ssh(ip, user, key, f"{hermes_python} -c 'import mautrix'", timeout=10.0)
    if rc == 0:
        result.record("mautrix already installed", True)
    else:
        pkgs = " ".join(f"'{p}'" for p in _MAUTRIX_PACKAGES)
        rc, out, err = _ssh(ip, user, key,
            f"{hermes_python} -m pip install {pkgs} 2>&1", timeout=180.0)
        result.record("install mautrix", rc == 0, out + err)
        if rc != 0:
            result.error = "mautrix install failed"
            return result

    # ── 3. Ensure Matrix user exists ──────────────────────────────────
    matrix_user = cfg.matrix_user or f"hermes-{cfg.name.replace(' ', '-').lower()}"
    try:
        ensure_matrix_user(cfg.matrix_homeserver, admin_token, matrix_user)
        result.record(f"Matrix user @{matrix_user}", True)
    except Exception as exc:
        result.record(f"Matrix user @{matrix_user}", False, str(exc))
        result.error = str(exc)
        return result

    # ── 4. Register hermes adapter ────────────────────────────────────
    rc, out, _ = _ssh(ip, user, key, "mycelium adapter ls 2>&1", timeout=15.0)
    if rc == 0 and "hermes" in out.lower():
        result.record("hermes adapter registered", True)
    else:
        rc, out, err = _ssh(ip, user, key,
            "mycelium adapter add hermes --reinstall -y 2>&1", timeout=120.0)
        result.record("register hermes adapter", rc == 0, out + err)
        if rc != 0:
            result.error = "adapter registration failed"
            return result

    # ── 5. Ensure gateway is running ──────────────────────────────────
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


def provision_lab(
    nodes: list[NodeConfig],
    matrix_homeserver: str = "http://localhost:8008",
) -> list[ProvisionResult]:
    """Provision all nodes; returns results in input order."""
    try:
        admin_token = get_admin_token(matrix_homeserver)
        log.info("Got Synapse admin token")
    except Exception as exc:
        log.error("Failed to get Synapse admin token: %s", exc)
        return [ProvisionResult(node=n.name, success=False, error=str(exc)) for n in nodes]

    results = []
    for node in nodes:
        log.info("Provisioning %s (%s)…", node.name, node.ssh_ip)
        result = provision_node(node, admin_token)
        results.append(result)

    return results


def check_prereqs(
    ip: str,
    user: str,
    key: str,
    *,
    matrix_homeserver: str = "http://localhost:8008",
    matrix_user: str = "",
) -> list[str]:
    """Return a list of missing prerequisites on the node (empty = all good)."""
    missing = []

    hermes_python = _detect_hermes_python(ip, user, key)
    rc, _, _ = _ssh(ip, user, key, f"{hermes_python} -c 'import mautrix'", timeout=10.0)
    if rc != 0:
        missing.append("mautrix not installed in hermes venv — run provision_hermes_lab.py")

    rc, out, _ = _ssh(ip, user, key, "mycelium adapter ls 2>&1", timeout=15.0)
    if rc != 0 or "hermes" not in out.lower():
        missing.append("hermes adapter not registered — run provision_hermes_lab.py")

    rc, out, _ = _ssh(ip, user, key, "hermes gateway status 2>&1", timeout=10.0)
    if rc != 0 or ("running" not in out.lower() and "pid" not in out.lower()):
        missing.append("hermes gateway not running — run: hermes gateway start")

    if matrix_user:
        try:
            server_name = _synapse_server_name()
            secret = _synapse_secret()
            admin_token = get_admin_token(matrix_homeserver)
            resp = httpx.get(
                f"{matrix_homeserver}/_synapse/admin/v2/users/@{matrix_user}:{server_name}",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            if resp.status_code != 200:
                missing.append(f"Matrix user @{matrix_user} missing — run provision_hermes_lab.py")
        except Exception as exc:
            missing.append(f"Matrix user check failed: {exc}")

    return missing
