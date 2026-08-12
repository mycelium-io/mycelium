# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Cross-machine memory sync — live-node integration slice.

Needs a running ``slim`` node. Guarded so the default unit suite stays green
without one (mirrors ``test_connector_wake_over_slim.py``): point at a node with
``MYCELIUM_SLIM_ENDPOINT`` (default ``http://127.0.0.1:46357``); run one via
``mycelium hub host``. For a
genuine two-host proof, run the node on host A and export
``MYCELIUM_SLIM_ENDPOINT=http://<A-LAN-IP>:46357`` on host B (or put two
containers on a shared docker **bridge network** and route by service name).

Proves the memory-sync half over a real MLS group channel: a moderator
(host A's backend, faked here) broadcasts an L9 ``knowledge`` message that
**carries** a compiled plan; the connector (host B) — pulling from its own member
session — applies the carried markdown to a **genuinely separate data dir** and
triggers a reindex on that store, with no file watcher in sight. This is the
cross-machine realization of the same-machine path
(``test_l9_over_slim_roundtrip.py::test_converged_compiles_plan_and_syncs_memory_over_slim``):
the "second store" is a distinct dir reached only through the real connector
receiver, not a swapped ``MYCELIUM_DATA_DIR``.

The connector's transport primitives are driven directly (member session +
``handle_inbound``); the full ``run_connector`` reconnect loop is thin glue over
them and is unit-covered in ``test_daemon_connector.py``.
"""

from __future__ import annotations

import asyncio
import os
import socket
from pathlib import Path
from urllib.parse import urlparse

import pytest

pytest.importorskip("slim_bindings")

from mycelium import filesystem
from mycelium.config import MyceliumConfig, ServerConfig
from mycelium.daemon import connector
from mycelium.daemon.config import DaemonConfig
from mycelium.daemon.state import DaemonState
from mycelium.slim import l9
from mycelium.slim.client import SlimClient, close_connection
from mycelium.slim.naming import DEFAULT_NODE_ENDPOINT, SlimIdentity, to_channel_name, to_slim_name

_ENDPOINT = os.getenv("MYCELIUM_SLIM_ENDPOINT", DEFAULT_NODE_ENDPOINT)
_WORKSPACE = "mycelium"
_ROOM = "knowledge-sync-room"
_HANDLE = "agent-b"
_PLAN_KEY = "plan/tasks"
_PLAN_BODY = "# Converged Plan\n\n- [ ] ship the thing @agent-a\n- [ ] document it @agent-b\n"


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


def _knowledge_push() -> dict:
    """The content dict the backend's memory_sync broadcasts for a compiled plan."""
    return {
        "content": f"plan updated → {_PLAN_KEY}",
        "l9": {
            "header": {
                "protocol": "SSTP",
                "subprotocol": "mycelium",
                "version": "0.0.6",
                "kind": l9.KNOWLEDGE_KIND,
                "subkind": "distillation",
                "participants": {
                    "actors": [{"id": "system", "role": "coordinator"}],
                    "groups": None,
                },
                "message": {"id": "plan-push-1", "parents": [], "episode": "urn:x"},
            },
            "payload": {
                "type": "distillation",
                "data": {
                    "key": _PLAN_KEY,
                    "content": _PLAN_BODY,
                    "version": 1,
                    "base_version": None,
                    "created_by": "system",
                    "updated_by": "system",
                    "updated_at": "2026-08-04T00:00:00+00:00",
                },
            },
        },
    }


@pytest.mark.asyncio
async def test_knowledge_push_syncs_to_remote_store_over_slim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Host B's store is a genuinely separate data dir, reached only through the
    # real connector receiver over the node.
    remote_store = tmp_path / "host-b"
    monkeypatch.setattr(filesystem, "get_mycelium_dir", lambda: remote_store)

    # No backend is co-located in this slice, so record that the connector fired
    # the explicit reindex (its markdown-lands-but-search-is-stale gap closer)
    # rather than standing one up. The reindex → JSONL wiring itself is proven in
    # the backend suite roundtrip and by unit tests.
    reindexed: list[str] = []

    async def _record_reindex(_config: MyceliumConfig, room: str) -> None:
        reindexed.append(room)

    monkeypatch.setattr(connector, "reindex_after_knowledge", _record_reindex)

    moderator = await SlimClient(SlimIdentity(_WORKSPACE, _ROOM, "backend")).connect(_ENDPOINT)
    member = await SlimClient(SlimIdentity(_WORKSPACE, _ROOM, _HANDLE)).connect(_ENDPOINT)
    session = await moderator.create_group(to_channel_name(_WORKSPACE, _ROOM))

    applied = asyncio.Event()

    async def member_side() -> None:
        joined = await member.listen_for_session()

        async def publish(_content: dict) -> None:  # pragma: no cover - knowledge never replies
            pass

        message = await SlimClient.receive_message(joined, timeout_s=15.0)
        content = l9.parse(message.payload)
        assert content is not None
        await connector.handle_inbound(
            config=MyceliumConfig(server=ServerConfig(api_url="http://localhost:8000")),
            daemon_cfg=DaemonConfig(),
            state=DaemonState(),
            room=_ROOM,
            handle=_HANDLE,
            content=content,
            publish=publish,
        )
        applied.set()

    member_task = asyncio.create_task(member_side())
    try:
        # The member must be in the group before the moderator broadcasts, or the
        # push lands before it is subscribed (SLIM keeps nothing for an absent
        # member). Invite, then broadcast the knowledge push.
        await moderator.invite(session, to_slim_name(_WORKSPACE, _ROOM, _HANDLE))
        await SlimClient.publish(session, l9.serialize(_knowledge_push()))
        await asyncio.wait_for(applied.wait(), timeout=20.0)
    finally:
        member_task.cancel()
        try:
            await member_task
        except asyncio.CancelledError:
            pass
        await moderator.close()
        await member.close()
        await close_connection(_ENDPOINT)

    # The carried markdown landed on host B's separate store …
    got = filesystem.read_memory(filesystem.get_room_dir(_ROOM), _PLAN_KEY)
    assert got is not None
    meta, body = got
    assert "ship the thing" in body and meta["version"] == 1
    # … and the connector triggered a reindex there (no watcher required).
    assert reindexed == [_ROOM]
