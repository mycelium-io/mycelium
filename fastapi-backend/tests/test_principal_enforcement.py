# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Principal enforcement: who may post as whom.

Self-asserted tier, so we can't verify *identity*, but we can enforce *role*:
an engine is never impersonable, and a phantom handle (neither a registered
agent nor a known user) can't post through the agent path.
"""

import pytest
import yaml
from httpx import AsyncClient

from app.services import principals
from app.services.filesystem import get_room_dir, write_memory_file


def _seed_agent(room: str, handle: str, *, adapter: str = "claude_code", **extra) -> None:
    body = {"adapter": adapter, **extra}
    write_memory_file(
        get_room_dir(room),
        f"agents/{handle}",
        yaml.safe_dump(body, sort_keys=False),
        created_by="tester",
    )


# ── classify_sender ───────────────────────────────────────────────────────────


def test_classify_registered_agent():
    _seed_agent("r", "bot", adapter="claude_code", cwd="/tmp")
    assert principals.classify_sender("r", "bot") == "agent"


def test_classify_engine():
    _seed_agent("r", "aligner", adapter="engine", kind="aligner")
    assert principals.classify_sender("r", "aligner") == "engine"


def test_classify_user_normalized():
    principals.write_user({"handle": "avery"})
    assert principals.classify_sender("r", "@Avery") == "user"


def test_classify_unknown_is_phantom():
    assert principals.classify_sender("r", "foobar") == "unknown"


# ── post_rejection_reason ─────────────────────────────────────────────────────


def test_agent_path_rejects_engine_and_phantom_allows_real():
    _seed_agent("r", "aligner", adapter="engine", kind="aligner")
    _seed_agent("r", "bot", adapter="claude_code", cwd="/tmp")
    principals.write_user({"handle": "avery"})

    # engine: never impersonable
    assert principals.post_rejection_reason("r", "aligner", allow_unregistered=False)
    # phantom: neither agent nor user
    assert principals.post_rejection_reason("r", "foobar", allow_unregistered=False)
    # real agent + known user: allowed
    assert principals.post_rejection_reason("r", "bot", allow_unregistered=False) is None
    assert principals.post_rejection_reason("r", "avery", allow_unregistered=False) is None


def test_human_path_tolerates_unregistered_but_not_engine():
    _seed_agent("r", "aligner", adapter="engine", kind="aligner")
    # a human may post under an unregistered handle (anonymous chat)
    assert principals.post_rejection_reason("r", "somebody", allow_unregistered=True) is None
    # but still cannot pose as an engine
    assert principals.post_rejection_reason("r", "aligner", allow_unregistered=True)


# ── /reply route guard ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reply_rejects_engine_impersonation(client: AsyncClient):
    await client.post("/api/rooms", json={"name": "r"})
    _seed_agent("r", "aligner", adapter="engine", kind="aligner")
    resp = await client.post("/api/rooms/r/reply", json={"handle": "aligner", "text": "hi"})
    assert resp.status_code == 403
    assert "engine" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_reply_rejects_phantom_handle(client: AsyncClient):
    await client.post("/api/rooms", json={"name": "r"})
    resp = await client.post("/api/rooms/r/reply", json={"handle": "foobar", "text": "hi"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_reply_lets_registered_agent_past_the_guard(client: AsyncClient):
    await client.post("/api/rooms", json={"name": "r"})
    _seed_agent("r", "bot", adapter="claude_code", cwd="/tmp")
    resp = await client.post("/api/rooms/r/reply", json={"handle": "bot", "text": "hi"})
    # The guard passes; with no live SLIM channel in the task env the route then
    # 503s. The point is it is NOT a 403 — a real agent is allowed to post.
    assert resp.status_code != 403


# ── broadcast (human) route guard ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_broadcast_rejects_engine_impersonation(client: AsyncClient):
    await client.post("/api/rooms", json={"name": "r"})
    _seed_agent("r", "aligner", adapter="engine", kind="aligner")
    resp = await client.post(
        "/api/rooms/r/messages",
        json={"message_type": "broadcast", "sender_handle": "aligner", "content": "hi"},
    )
    assert resp.status_code == 403
    assert "engine" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_broadcast_allows_unregistered_human(client: AsyncClient):
    await client.post("/api/rooms", json={"name": "r"})
    resp = await client.post(
        "/api/rooms/r/messages",
        json={"message_type": "broadcast", "sender_handle": "user", "content": "hi"},
    )
    assert resp.status_code == 201
