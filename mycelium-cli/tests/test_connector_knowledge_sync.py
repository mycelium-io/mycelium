# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Connector memory-sync — the L9 ``knowledge`` write path (Step 8, bible §11).

The merge gate for the CLI half of Step 8 (no SLIM node): a ``knowledge`` message
carries markdown content, and the connector writes it into the local store
(push-with-content) without waking a turn; the last-write-wins conflict policy
keeps a stale-base write out with details.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mycelium import filesystem
from mycelium.daemon import connector
from mycelium.slim import l9


@pytest.fixture(autouse=True)
def _tmp_mycelium_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(filesystem, "get_mycelium_dir", lambda: tmp_path)


def _knowledge(key: str, content: str, *, version: int = 1) -> dict:
    """A ``knowledge`` content dict as the backend's memory_sync emits it."""
    return {
        "content": f"plan updated → {key}",
        "l9": {
            "header": {
                "protocol": "SSTP",
                "subprotocol": "mycelium",
                "version": "0.0.6",
                "kind": l9.KNOWLEDGE_KIND,
                "subkind": "distillation",
                "participants": {
                    "actors": [{"id": "CognitiveEngine", "role": "coordinator"}],
                    "groups": None,
                },
                "message": {"id": f"k-{version}", "parents": [], "episode": "urn:x"},
            },
            "payload": {
                "type": "distillation",
                "data": {
                    "key": key,
                    "content": content,
                    "version": version,
                    "base_version": version - 1 if version > 1 else None,
                    "created_by": "CognitiveEngine",
                    "updated_by": "CognitiveEngine",
                    "updated_at": "2026-08-04T00:00:00+00:00",
                },
            },
        },
    }


def test_knowledge_message_writes_markdown_locally(tmp_path: Path):
    connector.apply_knowledge_message("demo", _knowledge("plan/tasks", "# Plan\n\n- [ ] ship it"))
    got = filesystem.read_memory(filesystem.get_room_dir("demo"), "plan/tasks")
    assert got is not None
    meta, body = got
    assert "ship it" in body and meta["version"] == 1


def test_knowledge_newer_version_overwrites():
    connector.apply_knowledge_message("demo", _knowledge("plan/tasks", "# v1", version=1))
    connector.apply_knowledge_message("demo", _knowledge("plan/tasks", "# v2 wins", version=2))
    got = filesystem.read_memory(filesystem.get_room_dir("demo"), "plan/tasks")
    assert got is not None and "v2 wins" in got[1] and got[0]["version"] == 2


def test_knowledge_stale_base_is_rejected():
    connector.apply_knowledge_message("demo", _knowledge("plan/tasks", "# v3", version=3))
    # An older write (v2) must not clobber the newer local v3.
    connector.apply_knowledge_message("demo", _knowledge("plan/tasks", "# stale v2", version=2))
    got = filesystem.read_memory(filesystem.get_room_dir("demo"), "plan/tasks")
    assert got is not None and got[1].strip() == "# v3" and got[0]["version"] == 3


def test_malformed_knowledge_is_ignored():
    # Missing key/content → no write, no raise.
    bad = _knowledge("plan/tasks", "x")
    bad["l9"]["payload"]["data"] = {"version": 1}
    connector.apply_knowledge_message("demo", bad)
    assert filesystem.read_memory(filesystem.get_room_dir("demo"), "plan/tasks") is None


@pytest.mark.asyncio
async def test_handle_inbound_routes_knowledge_without_waking(monkeypatch):
    """A ``knowledge`` arrival applies the write and never spawns a turn."""
    woke = False

    def _no_wake(*a, **k):  # pragma: no cover - asserts it isn't called
        nonlocal woke
        woke = True
        return True

    monkeypatch.setattr(connector, "should_wake", _no_wake)
    published: list = []

    async def _publish(content: dict) -> None:
        published.append(content)

    await connector.handle_inbound(
        config=None,  # ty: ignore[invalid-argument-type]
        daemon_cfg=None,  # ty: ignore[invalid-argument-type]
        state=None,  # ty: ignore[invalid-argument-type]
        room="demo",
        handle="agent-a",
        content=_knowledge("plan/tasks", "# Plan\n\n- [ ] a"),
        publish=_publish,
    )
    assert not woke and not published
    assert filesystem.read_memory(filesystem.get_room_dir("demo"), "plan/tasks") is not None
