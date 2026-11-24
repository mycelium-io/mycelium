# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""What a room's team learned: memories with a kind, a task, and what they came from.

A memory written with ``kind`` (fact, finding, dead end), the ``task`` it was
learned in and ``derived-from`` is a node in the room's knowledge graph, and a
task is a lens on it. The fields are checked at the memory write like every
other, so a bad one is refused with a stable code and saves nothing.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from app.services import links
from app.services.filesystem import room_path, write_memory_file

ROOM = "checkout"
TASK = "work/apple-pay-for-everyone"
OTHER = "work/payment-alerts"


@pytest.fixture
async def room(client: AsyncClient) -> AsyncClient:
    await client.post("/api/rooms", json={"name": ROOM})
    for key, title in ((TASK, "Apple Pay for everyone"), (OTHER, "Payment alerts")):
        write_memory_file(room_path(ROOM), key, f"# {title}", created_by="operator")
    return client


async def learn(client: AsyncClient, key: str, text: str, by: str = "builder", **meta: Any):
    item = {"key": key, "value": text, "created_by": by, "embed": False, "meta": meta}
    return await client.post(f"/api/rooms/{ROOM}/memory", json={"items": [item]})


async def graph(client: AsyncClient, task: str | None = None) -> dict:
    params = {"task": task} if task else {}
    resp = await client.get(f"/api/rooms/{ROOM}/knowledge", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def by_key(found: dict) -> dict[str, dict]:
    return {m["key"]: m for m in found["memories"]}


async def test_a_finding_is_a_node_with_who_wrote_it_and_what_it_came_from(room):
    assert (
        await learn(
            room, "payments/stripe-dedupes", "Stripe dedupes a retry", kind="fact", task=TASK
        )
    ).status_code == 201
    # A subagent writes as itself, once its parent has started it.
    started = await room.post(
        f"/api/rooms/{ROOM}/subagents", json={"name": "retry", "parent": "builder"}
    )
    assert started.status_code == 201, started.text
    written = await learn(
        room,
        "payments/retries-reuse-key",
        "Retries reuse the key",
        by="builder:retry",
        kind="finding",
        open=True,
        **{"derived-from": ["payments/stripe-dedupes"]},
    )
    assert written.status_code == 201, written.text

    found = by_key(await graph(room))
    finding = found["payments/retries-reuse-key"]
    assert finding["kind"] == "finding"
    assert finding["title"] == "Retries reuse the key"
    assert finding["by"] == "builder:retry"
    assert finding["open"] is True
    assert finding["derived_from"] == ["payments/stripe-dedupes"]
    # It named no task, so it's in the task of what it came from.
    assert finding["task"] == TASK
    assert (await graph(room))["tasks"] == [{"key": TASK, "title": "Apple Pay for everyone"}]


async def test_derived_from_is_a_relation_with_backlinks(room):
    await learn(room, "payments/stripe-dedupes", "Stripe dedupes a retry", kind="fact", task=TASK)
    await learn(
        room,
        "payments/retries-reuse-key",
        "Retries reuse the key",
        kind="finding",
        **{"derived-from": "payments/stripe-dedupes"},
    )
    back = links.backlinks(ROOM, "payments/stripe-dedupes")
    assert [(b.source, b.relation) for b in back] == [
        ("payments/retries-reuse-key", "derived-from")
    ]


async def test_a_task_is_a_lens_on_the_room(room):
    await learn(room, "payments/stripe-dedupes", "Stripe dedupes a retry", kind="fact", task=TASK)
    await learn(room, "payments/new-key", "A new key for every retry", kind="dead-end", task=TASK)
    await learn(
        room,
        "payments/alert-on-captures",
        "Alert on two captures in 10s",
        kind="finding",
        task=OTHER,
        **{"derived-from": "payments/stripe-dedupes"},
    )
    await learn(room, "payments/unrelated", "Webhooks arrive in order", kind="fact", task=OTHER)

    lens = by_key(await graph(room, TASK))
    assert set(lens) == {
        "payments/stripe-dedupes",
        "payments/new-key",
        "payments/alert-on-captures",
    }
    assert lens["payments/stripe-dedupes"]["in_task"] is True
    # What the task's memories fed into elsewhere is in the picture, marked as not its own.
    assert lens["payments/alert-on-captures"]["in_task"] is False


async def test_only_memories_with_a_kind_are_knowledge(room):
    await learn(room, "context/notes", "Some notes")
    assert "context/notes" not in by_key(await graph(room))
    assert TASK not in by_key(await graph(room)), "a task is where knowledge is learned, not a node"


@pytest.mark.parametrize(
    ("meta", "code"),
    [
        ({"kind": "hunch"}, "memory.learned_kind"),
        (
            {"kind": "finding", "derived-from": "payments/nothing-here"},
            "memory.derived_from_missing",
        ),
        ({"kind": "fact", "task": "work/no-such-task"}, "memory.task_missing"),
        ({"kind": "fact", "task": "context/not-a-task"}, "memory.task_missing"),
    ],
)
async def test_a_bad_field_is_refused_and_saves_nothing(room, meta: dict, code: str):
    resp = await learn(room, "payments/bad", "Something", **meta)
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == code
    assert (await room.get(f"/api/rooms/{ROOM}/memory/payments/bad")).status_code == 404


async def test_a_task_row_keeps_its_own_kind(room):
    resp = await learn(room, TASK, "# Apple Pay for everyone", kind="finding")
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "memory.learned_on_task"


async def test_a_memory_is_settled_once_it_holds(room):
    await learn(
        room, "payments/timeout", "A timeout isn't refunded", kind="finding", task=TASK, open=True
    )
    resp = await room.post(
        f"/api/rooms/{ROOM}/knowledge/settle", json={"key": "payments/timeout", "handle": "builder"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["open"] is False
    assert by_key(await graph(room))["payments/timeout"]["open"] is False


async def test_the_graph_is_kept_until_a_memory_in_the_room_changes(room, monkeypatch):
    from app.services import knowledge

    builds = []
    build = knowledge.list_memory_files

    def counted(*args, **kwargs):
        builds.append(1)
        return build(*args, **kwargs)

    monkeypatch.setattr(knowledge, "list_memory_files", counted)
    await learn(room, "payments/timeout", "A timeout", kind="finding", task=TASK, open=True)

    await graph(room)
    await graph(room, TASK)
    assert len(builds) == 1, "a second read rebuilt a room nothing changed in"

    # A write, a settle and a delete each show on the next read.
    await learn(room, "payments/refunds", "Refunds land in a day", kind="fact", task=TASK)
    assert "payments/refunds" in by_key(await graph(room))
    await room.post(
        f"/api/rooms/{ROOM}/knowledge/settle", json={"key": "payments/timeout", "handle": "builder"}
    )
    assert by_key(await graph(room))["payments/timeout"]["open"] is False
    assert (await room.delete(f"/api/rooms/{ROOM}/memory/payments/refunds")).status_code == 204
    assert "payments/refunds" not in by_key(await graph(room))

    # A file edited on disk shows once the room is reindexed, the step after one.
    (room_path(ROOM) / "payments" / "by-hand.md").write_text(
        f"---\nkey: payments/by-hand\nkind: fact\ntask: {TASK}\n---\nEdited on disk\n"
    )
    assert "payments/by-hand" not in by_key(await graph(room))
    await room.post(f"/api/rooms/{ROOM}/reindex")
    assert "payments/by-hand" in by_key(await graph(room))


async def test_only_knowledge_can_be_settled(room):
    await learn(room, "context/notes", "Some notes")
    resp = await room.post(f"/api/rooms/{ROOM}/knowledge/settle", json={"key": "context/notes"})
    assert resp.status_code == 422
    missing = await room.post(f"/api/rooms/{ROOM}/knowledge/settle", json={"key": "context/none"})
    assert missing.status_code == 404
