# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for ``mycelium.spoke`` — the thin-spoke member's receive→apply path.

Node-free: the inbound frames are the **frozen contract envelope** the backend
actually produces (``contracts/slim-l9-wire.json``), so these assert the spoke
applies real hub traffic rather than a shape invented here. ``run_spoke``'s join
is exercised against :class:`~tests.conftest.FakeSlimClient` and the httpx fakes.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from mycelium import spoke as spoke_module
from mycelium.filesystem import read_memory, write_memory
from mycelium.slim import member
from mycelium.spoke import SpokeCounters, apply_message, knowledge_write_of, run_spoke
from tests.conftest import FakeHTTPX, FakeSlimClient

_CONTRACT_PATH = Path(__file__).resolve().parent.parent.parent / "contracts" / "slim-l9-wire.json"


def _contract_knowledge() -> dict[str, Any]:
    with _CONTRACT_PATH.open() as fh:
        return json.load(fh)["knowledge"]


def _frame(*, version: int | None = None, content: str | None = None) -> bytes:
    """The wire bytes of the contract's ``knowledge:distillation`` envelope."""
    envelope = copy.deepcopy(_contract_knowledge()["expected_envelope"])
    if version is not None:
        envelope["payload"]["data"]["version"] = version
    if content is not None:
        envelope["payload"]["data"]["content"] = content
    return json.dumps({"content": "", "l9": envelope}).encode()


# ── decode ────────────────────────────────────────────────────────────────────


def test_knowledge_write_of_reads_the_contract_write() -> None:
    write = knowledge_write_of(json.loads(_frame().decode()))

    expected = _contract_knowledge()["write"]
    assert write is not None
    assert write["key"] == expected["key"]
    assert write["content"] == expected["content"]
    assert write["version"] == expected["version"]
    assert write["created_by"] == expected["created_by"]
    assert write["updated_by"] == expected["updated_by"]


def test_non_knowledge_message_carries_no_write() -> None:
    exchange = {"content": "hello", "l9": {"header": {"kind": "exchange"}}}
    assert knowledge_write_of(exchange) is None


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"key": "a.md"},  # no content
        {"content": "body"},  # no key
        {"key": "", "content": "body"},  # empty key
        {"key": "a.md", "content": 42},  # content not markdown
    ],
)
def test_malformed_knowledge_payload_carries_no_write(data: dict[str, Any]) -> None:
    content = {"l9": {"header": {"kind": "knowledge"}, "payload": {"data": data}}}
    assert knowledge_write_of(content) is None


def test_unparseable_frame_is_skipped(tmp_path: Path) -> None:
    assert apply_message(tmp_path, b"not json at all") is None


# ── apply ─────────────────────────────────────────────────────────────────────


def test_applies_an_inbound_write_to_the_local_store(tmp_path: Path) -> None:
    result = apply_message(tmp_path, _frame())

    assert result is not None
    assert result.applied and not result.conflict

    expected = _contract_knowledge()["write"]
    stored = read_memory(tmp_path, expected["key"])
    assert stored is not None
    meta, body = stored
    assert body == expected["content"].strip()
    assert meta["version"] == expected["version"]


def test_redelivery_of_the_same_version_is_a_no_op(tmp_path: Path) -> None:
    first = apply_message(tmp_path, _frame())
    second = apply_message(tmp_path, _frame())

    assert first is not None and first.applied
    assert second is not None
    assert not second.applied
    assert not second.conflict
    assert "idempotent" in second.reason

    counters = SpokeCounters()
    counters.record(first)
    counters.record(second)
    assert (counters.applied, counters.conflicts, counters.ignored) == (1, 0, 1)


def test_stale_base_write_is_a_conflict_not_a_clobber(tmp_path: Path) -> None:
    key = _contract_knowledge()["write"]["key"]
    write_memory(
        tmp_path,
        key,
        "the newer local content\n",
        created_by="local",
        updated_by="local",
        version=5,
    )

    result = apply_message(tmp_path, _frame(version=2, content="stale incoming\n"))

    assert result is not None
    assert result.conflict
    assert not result.applied
    assert result.current is not None
    assert result.current["version"] == 5

    stored = read_memory(tmp_path, key)
    assert stored is not None
    _meta, body = stored
    assert body == "the newer local content"  # local content survived

    counters = SpokeCounters()
    counters.record(result)
    assert (counters.applied, counters.conflicts) == (0, 1)


def test_a_newer_version_supersedes_the_local_copy(tmp_path: Path) -> None:
    key = _contract_knowledge()["write"]["key"]
    write_memory(tmp_path, key, "old\n", created_by="local", updated_by="local", version=1)

    result = apply_message(tmp_path, _frame(version=9, content="fresher from the hub\n"))

    assert result is not None
    assert result.applied
    stored = read_memory(tmp_path, key)
    assert stored is not None
    _meta, body = stored
    assert body == "fresher from the hub"


# ── join + receive ────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _patch_slim_client(monkeypatch: pytest.MonkeyPatch, fake_slim_client: type[FakeSlimClient]):
    monkeypatch.setattr(member, "SlimClient", fake_slim_client)
    monkeypatch.setattr(member, "node_reachable", lambda _endpoint: True)
    monkeypatch.setattr(spoke_module, "SlimClient", fake_slim_client)
    return fake_slim_client


async def test_run_spoke_joins_as_a_member_and_applies_inbound_writes(
    fake_httpx: FakeHTTPX, isolated_home: Path
) -> None:
    FakeSlimClient.inbox = [_frame()]

    counters = await run_spoke(
        api_url="http://hub:8000",
        node_endpoint="http://hub:46357",
        room="acme",
        handle="spoke",
        max_messages=1,
    )

    # Membership came from asking the hub's moderator to invite us — the member
    # path. A spoke never creates a group of its own.
    assert fake_httpx.calls == [
        ("POST", "http://hub:8000/api/rooms/acme/sessions", {"agent_handle": "spoke"})
    ]
    assert FakeSlimClient.published == []
    assert (counters.applied, counters.conflicts) == (1, 0)

    expected = _contract_knowledge()["write"]
    stored = read_memory(isolated_home / ".mycelium" / "rooms" / "acme", expected["key"])
    assert stored is not None
    _meta, body = stored
    assert body == expected["content"].strip()


async def test_run_spoke_ignores_traffic_that_carries_no_write(
    fake_httpx: FakeHTTPX, isolated_home: Path
) -> None:
    FakeSlimClient.inbox = [
        json.dumps({"content": "just chatter", "l9": {"header": {"kind": "exchange"}}}).encode(),
        b"{ not json",
    ]

    counters = await run_spoke(
        api_url="http://hub:8000",
        node_endpoint="http://hub:46357",
        room="acme",
        handle="spoke",
        max_messages=2,
    )

    assert (counters.applied, counters.conflicts, counters.ignored) == (0, 0, 0)


async def test_run_spoke_reports_the_join_before_receiving(
    fake_httpx: FakeHTTPX, isolated_home: Path
) -> None:
    events: list[str] = []
    FakeSlimClient.inbox = [_frame()]

    await run_spoke(
        api_url="http://hub:8000",
        node_endpoint="http://hub:46357",
        room="acme",
        handle="spoke",
        on_joined=lambda: events.append("joined"),
        on_apply=lambda result: events.append(f"applied:{result.key}"),
        max_messages=1,
    )

    assert events == ["joined", f"applied:{_contract_knowledge()['write']['key']}"]
