# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The headline #666 acceptance: a **two-process** custodial-session kill/restart.

The moderator is the always-draining test process; the custodial session is a real
subprocess (:mod:`scripts.custody_restart_probe`) that genuinely dies via SIGKILL,
so the node forgets its subscription — the faithful backend/session bounce the
spike's early single-process runs could not stage. After the kill a fresh
subprocess resumes the session from its on-disk MLS state via ``restore_sessions``
with **no re-invite** and keeps publishing as itself; the moderator (still in the
group) receives it with the same cryptographic wire sender. Persistence resumes
crypto state only, so no missed message is replayed — the transcript stays the
offline-replay layer.

Needs a running SLIM node (skips without one). Uses the backend's shipped
``app.services.custody`` code on both sides, not a spike copy.
"""

import datetime
import os
import signal
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import pytest

pytest.importorskip("slim_bindings")

from app.services import custody, slim_identity
from app.services.slim_client import (
    DEFAULT_NODE_ENDPOINT,
    SlimClient,
    SlimIdentity,
    to_channel_name,
    to_slim_name,
)

_ENDPOINT = os.getenv("MYCELIUM_SLIM_ENDPOINT", DEFAULT_NODE_ENDPOINT)
_WS = "mycelium"
_PROBE = Path(__file__).resolve().parent.parent / "scripts" / "custody_restart_probe.py"


def _node_reachable(endpoint: str, *, timeout: float = 1.0) -> bool:
    parsed = urlparse(endpoint)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 46357
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _node_reachable(_ENDPOINT),
    reason=f"no reachable SLIM node at {_ENDPOINT} (set MYCELIUM_SLIM_ENDPOINT or run `mycelium hub host`)",
)


def _wait_for(path: Path, *, timeout_s: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.05)
    return False


async def _recv(session, *, timeout_s: float = 25.0) -> tuple[str, str | None]:
    msg = await session.get_message_async(timeout=datetime.timedelta(seconds=timeout_s))
    return msg.payload.decode(errors="replace"), custody.wire_sender(msg.context)


def _spawn(phase: str, room: str, handle: str, workdir: Path, env: dict) -> subprocess.Popen:
    log = (workdir / f"{phase}.stderr").open("wb")
    return subprocess.Popen(
        [
            sys.executable,
            str(_PROBE),
            "--phase",
            phase,
            "--endpoint",
            _ENDPOINT,
            "--room",
            room,
            "--handle",
            handle,
            "--workdir",
            str(workdir),
        ],
        env=env,
        cwd=str(_PROBE.parent.parent),
        stderr=log,
    )


@pytest.mark.asyncio
async def test_two_process_custody_kill_restart_resumes_without_reinvite(tmp_path, monkeypatch):
    room = f"cust2p-{uuid.uuid4().hex[:8]}"
    handle = "alice"
    data_dir = tmp_path / "data"
    workdir = tmp_path / "work"
    workdir.mkdir(parents=True)

    # Shared identity env: both the moderator (this process) and the custodial-session
    # subprocess resolve the same data dir, roster, and custody-store secret.
    monkeypatch.setenv("MYCELIUM_SLIM_IDENTITY", "signerjwt")
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(data_dir))
    monkeypatch.setenv("MYCELIUM_CUSTODY_STORE_SECRET", "two-process-custody-secret")
    # Complete the roster before the moderator App snapshots its verifier.
    slim_identity.ensure_agent_keypair("backend")
    slim_identity.ensure_agent_keypair(handle)

    # The probe imports ``app.*``; put the backend root on the child's path.
    child_env = {**os.environ, "PYTHONPATH": str(_PROBE.parent.parent)}

    moderator = await SlimClient(SlimIdentity(_WS, room, "backend")).connect(_ENDPOINT)
    proc1 = proc2 = None
    try:
        session = await moderator.create_group(to_channel_name(_WS, room))

        # ── phase 1: the subprocess joins + publishes ──
        proc1 = _spawn("create", room, handle, workdir, child_env)
        assert _wait_for(workdir / "listening"), "session never started listening"
        await moderator.invite(session, to_slim_name(_WS, room, handle))
        payload1, sender1 = await _recv(session)
        assert "phase1" in payload1
        assert sender1 == handle  # cryptographic wire attribution, cross-process

        # ── real kill: SIGKILL the process, node forgets its subscription ──
        assert _wait_for(workdir / "sent1")
        proc1.send_signal(signal.SIGKILL)
        proc1.wait(timeout=10)

        # ── phase 2: a FRESH process restores from disk, no re-invite ──
        proc2 = _spawn("restore", room, handle, workdir, child_env)
        # The moderator is draining (in _recv) so it heals the restored session's rejoin.
        payload2, sender2 = await _recv(session)
        assert "phase2" in payload2, f"restored session did not resume: {payload2!r}"
        assert sender2 == handle
        assert proc2.wait(timeout=15) == 0
        assert not (workdir / "restore_empty").exists(), "restore_sessions revived nothing"
    finally:
        for proc in (proc1, proc2):
            if proc is not None and proc.poll() is None:
                proc.send_signal(signal.SIGKILL)
                proc.wait(timeout=10)
        await moderator.close()
