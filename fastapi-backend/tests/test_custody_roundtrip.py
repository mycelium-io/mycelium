# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Live custodial-session integration (#666) — needs a running SLIM node.

Productizes the #662/#665 spike against the backend's own code paths. Guarded so
the default task suite stays green without a node: unreachable → skipped. Point at
a node with ``MYCELIUM_SLIM_ENDPOINT`` (default ``http://127.0.0.1:46357``); run
one via ``mycelium hub host``.

Two things the offline suite (``test_custody.py``) cannot show:

1. **Cryptographic wire attribution.** A custodial session for @alice publishes a
   real MLS message the moderator receives with wire sender == ``alice`` —
   non-forgeable, recovered off the ``MessageContext``, not a backend-stamped field.
2. **Within-process resume.** Dropping the App (store intact) and calling
   ``restore_sessions`` revives the group session with no re-invite; it keeps
   sending as @alice. (The full two-process kill/restart is
   ``test_custody_two_process_restart.py``; this covers the in-code resume seam.)
"""

import asyncio
import datetime
import os
import socket
import uuid
from urllib.parse import urlparse

import pytest

pytest.importorskip("slim_bindings")

from app.services import custody, slim_identity
from app.services.slim_client import (
    DEFAULT_NODE_ENDPOINT,
    SlimClient,
    SlimIdentity,
    to_channel_name,
)

_ENDPOINT = os.getenv("MYCELIUM_SLIM_ENDPOINT", DEFAULT_NODE_ENDPOINT)
_WS = "mycelium"


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


@pytest.fixture
def _identity_env(tmp_path, monkeypatch):
    """SignerJwt identity in a fresh data dir + a real custody-store secret."""
    monkeypatch.setenv("MYCELIUM_SLIM_IDENTITY", "signerjwt")
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MYCELIUM_CUSTODY_STORE_SECRET", "custody-roundtrip-secret")
    return tmp_path


async def _recv_sender(session, *, timeout_s: float = 10.0) -> tuple[str, str | None]:
    """Pull one broadcast on ``session``; return ``(payload_text, wire_sender)``."""
    msg = await session.get_message_async(timeout=datetime.timedelta(seconds=timeout_s))
    return msg.payload.decode(errors="replace"), custody.wire_sender(msg.context)


@pytest.mark.asyncio
async def test_custodial_session_is_a_distinct_member_with_wire_attribution(_identity_env):
    """A custodial session publishes as itself; the moderator recovers @alice."""
    room = f"custroom-{uuid.uuid4().hex[:8]}"
    handle = "alice"
    # Complete roster before the moderator App snapshots its verifier.
    slim_identity.ensure_agent_keypair("backend")
    slim_identity.ensure_agent_keypair(handle)

    moderator = await SlimClient(SlimIdentity(_WS, room, "backend")).connect(_ENDPOINT)
    cs = None
    try:
        session = await moderator.create_group(to_channel_name(_WS, room))

        cs = await custody.create_session(_ENDPOINT, _WS, room, handle)
        join = asyncio.create_task(custody.join_session(cs))
        await moderator.invite(session, cs.name)
        await join

        await cs.publish(b"alice: hello over MLS as myself")
        payload, sender = await _recv_sender(session)
        assert payload == "alice: hello over MLS as myself"
        # Non-forgeable: the sender leaf is the actor's own MLS identity.
        assert sender == handle

        # ── within-process resume: drop the App (store intact), restore ──
        await cs.close(graceful=False)
        cs = await custody.restore_session(_ENDPOINT, _WS, room, handle)
        assert cs is not None, "restore_sessions revived no session"
        await cs.publish(b"alice: back from persisted MLS state")
        payload2, sender2 = await _recv_sender(session)
        assert payload2 == "alice: back from persisted MLS state"
        assert sender2 == handle
    finally:
        if cs is not None:
            await cs.close(graceful=False)
        await moderator.close()


@pytest.mark.asyncio
async def test_manager_send_as_custodian_stands_up_a_member(_identity_env):
    """The manager's respond seam stands up a custodial session and counts it a member."""
    from app.services.room_channels import RoomChannelManager

    room = f"custmgr-{uuid.uuid4().hex[:8]}"
    handle = "bob"
    slim_identity.ensure_agent_keypair("backend")
    slim_identity.ensure_agent_keypair(handle)

    mgr = RoomChannelManager(endpoint=_ENDPOINT, default_workspace=_WS)
    try:
        managed = await mgr.provision(room)
        assert managed is not None
        sent = await mgr.send_as_custodian(room, handle, b'{"l9": {}, "content": "hi"}')
        assert sent is True
        assert handle in mgr.members(room)
        assert handle in managed.custody
    finally:
        await mgr.close_all()
