# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""What a write from the memory route may do to each kind of memory.

Every case goes through ``POST /rooms/{room}/memory``, the route the app's
editor, ``memory set`` and agents use, and checks the refusal's code, that it
says why, and that nothing was saved. The table is asserted against
``contracts/memory-kinds.json``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from app.routes.memory import upsert_memories
from app.schemas import MemoryBatchCreate, MemoryCreate
from app.services import memory_kinds, memory_sync
from app.services.filesystem import get_room_dir, read_memory_file

ROOM = "kinds"
CONTRACT = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts" / "memory-kinds.json").read_text()
)


@pytest.fixture
async def room(client: AsyncClient) -> AsyncClient:
    await client.post("/api/rooms", json={"name": ROOM})
    return client


async def write(client: AsyncClient, key: str, value: Any = "text", **extra: Any):
    item = {"key": key, "value": value, "created_by": "operator", "embed": False, **extra}
    return await client.post(f"/api/rooms/{ROOM}/memory", json={"items": [item]})


async def hub_writes(key: str, value: str, **meta: Any) -> None:
    """As the hub's own writer would: not through the memory route."""
    item = MemoryCreate(key=key, value=value, created_by="mycelium", embed=False, meta=meta or None)
    await upsert_memories(ROOM, MemoryBatchCreate(items=[item]))


def stored(key: str) -> tuple[dict, str]:
    found = read_memory_file(get_room_dir(ROOM), key)
    assert found is not None, f"{key} wasn't saved"
    return found


def absent(key: str) -> bool:
    return read_memory_file(get_room_dir(ROOM), key) is None


def refused(resp, code: str) -> dict:
    assert resp.status_code == memory_kinds.CODES[code], resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == code
    assert detail["message"]
    return detail


def test_the_table_is_the_contract():
    kinds = [
        {
            "id": k.id,
            "patterns": list(k.patterns),
            "edit": k.edit,
            **({"source": k.source} if k.source else {}),
            **({"fixed": list(k.fixed)} if k.fixed else {}),
            **({"checks": list(k.checks)} if k.checks else {}),
            **({"says": k.says} if k.says else {}),
        }
        for k in memory_kinds.KINDS
    ]
    assert kinds == CONTRACT["kinds"]
    assert CONTRACT["codes"] == memory_kinds.CODES
    assert sorted(memory_kinds.MANAGED_META) == sorted(CONTRACT["store_fields"])


@pytest.mark.parametrize(
    ("key", "kind"),
    [
        ("uploads/plan.md", "upload"),
        ("agents/builder", "agent"),
        ("agents/builder/notes", "memory"),
        ("protocols/review", "protocol"),
        ("work/ship-it", "task"),
        ("work/ship-it/part", "task"),
        ("context/summary/ship-it", "summary"),
        ("context/synthesis", "synthesis"),
        ("context/standing", "standing"),
        ("log/episodes/ab12cd34", "episode_record"),
        ("context/plan", "memory"),
    ],
)
def test_a_key_s_kind_is_the_first_that_matches(key: str, kind: str):
    assert memory_kinds.kind_of(key).id == kind


@pytest.mark.parametrize("key", ["uploads/plan.md", "context/standing", "log/episodes/ab12cd34"])
async def test_a_kind_nobody_edits_is_refused_and_says_why(room, key: str):
    refused(await write(room, key), "memory.read_only")
    assert absent(key)


async def test_an_upload_is_refused_even_when_it_exists(room):
    await hub_writes("uploads/plan.md", "the file's text")
    detail = refused(await write(room, "uploads/plan.md", "edited"), "memory.read_only")
    assert "Upload the file again" in detail["message"]
    assert stored("uploads/plan.md")[1].strip() == "the file's text"


async def test_a_store_field_is_refused_but_sending_it_back_unchanged_is_not(room):
    await write(room, "context/plan", "v1")
    detail = refused(
        await write(room, "context/plan", "v2", meta={"version": 9}), "memory.store_field"
    )
    assert detail["fields"] == ["version"]
    created = stored("context/plan")[0]["created_by"]
    resp = await write(room, "context/plan", "v2", meta={"created_by": created})
    assert resp.status_code == 201, resp.text


async def test_a_manifest_that_isn_t_yaml_or_a_mapping_is_refused(room):
    detail = refused(await write(room, "agents/builder", "adapter: [claude"), "memory.yaml_invalid")
    assert "line" in detail["message"]
    refused(await write(room, "agents/builder", "just words"), "memory.schema_invalid")
    refused(await write(room, "agents/builder", "allow_from: operator"), "memory.schema_invalid")
    assert absent("agents/builder")
    assert (
        await write(room, "agents/builder", "adapter: claude_code\nallow_from: [operator]")
    ).status_code == 201


async def test_a_flow_that_won_t_run_is_refused(room):
    refused(await write(room, "protocols/review", "steps: [unclosed"), "memory.yaml_invalid")
    detail = refused(
        await write(room, "protocols/review", "roles: [a]\nsteps:\n  - id: s1\n    to: nobody\n"),
        "memory.schema_invalid",
    )
    assert "isn't a flow Mycelium can run" in detail["message"]
    assert absent("protocols/review")


async def test_a_setting_takes_its_codes(room):
    refused(
        await write(room, "settings/no-such", "why", meta={"setting": 1}), "memory.setting_unknown"
    )
    refused(
        await write(room, "settings/worker-turns", "why", meta={"setting": 0}),
        "memory.setting_invalid",
    )


async def test_a_skill_s_description_is_one_line(room):
    long = "x" * (memory_kinds.SKILL_DESCRIPTION_MAX + 1)
    refused(
        await write(room, "skills/deploy", "steps", meta={"description": long}),
        "memory.schema_invalid",
    )


async def test_a_thread_s_message_is_fixed(room):
    await hub_writes("threads/a-question", "A question", **{"from": "m-1"})
    detail = refused(
        await write(room, "threads/a-question", "A question", meta={"from": "m-2"}),
        "memory.fixed_field",
    )
    assert detail["fields"] == ["from"]
    assert (await write(room, "threads/a-question", "A better title")).status_code == 201


async def test_a_claim_can_t_be_forged_on_a_task(room):
    detail = refused(
        await write(
            room, "work/ship-it", "Ship it", meta={"owner": "builder", "assignment": "held"}
        ),
        "memory.claim_field",
    )
    assert "board claim" in detail["message"]
    assert absent("work/ship-it")
    assert (
        await write(room, "work/ship-it", "Ship it", meta={"assignee": "builder"})
    ).status_code == 201


async def test_the_synthesis_cursor_is_fixed(room):
    refused(
        await write(room, "context/synthesis", "briefing", meta={"synthesized_through": {}}),
        "memory.fixed_field",
    )


SUMMARY = {
    "title": "Checkout",
    "cast": ["operator", "builder"],
    "points": [
        {
            "id": "p1",
            "type": "constraint",
            "text": "Cards only",
            "authors": ["operator"],
            "support": 1,
        }
    ],
    "flags": [],
}


async def test_a_summary_s_text_follows_its_contract(room):
    await hub_writes("context/summary/ship-it", "the drawn text", contract=SUMMARY)
    refused(await write(room, "context/summary/ship-it", "my own words"), "memory.rendered_body")

    changed = {**SUMMARY, "title": "Checkout v2"}
    resp = await write(room, "context/summary/ship-it", "ignored", meta={"contract": changed})
    assert resp.status_code == 201, resp.text
    meta, body = stored("context/summary/ship-it")
    assert meta["contract"]["title"] == "Checkout v2"
    assert body.startswith("# Shared summary: Checkout v2")

    refused(
        await write(room, "context/summary/ship-it", "x", meta={"contract": {"points": "no"}}),
        "memory.schema_invalid",
    )


async def test_a_decision_s_text_follows_its_field(room):
    await hub_writes("context/decision/ship-it", "drawn", decision={"pick": "A", "text": "Cards"})
    resp = await write(
        room, "context/decision/ship-it", "x", meta={"decision": {"pick": "B", "text": "Cash"}}
    )
    assert resp.status_code == 201, resp.text
    assert "Going with B: Cash" in stored("context/decision/ship-it")[1]
    refused(
        await write(room, "context/decision/ship-it", "x", meta={"decision": "B"}),
        "memory.schema_invalid",
    )


async def test_a_refused_item_saves_nothing_from_its_batch(room):
    items = [
        {"key": "context/fine", "value": "ok", "created_by": "operator", "embed": False},
        {"key": "uploads/plan.md", "value": "no", "created_by": "operator", "embed": False},
    ]
    resp = await room.post(f"/api/rooms/{ROOM}/memory", json={"items": items})
    refused(resp, "memory.read_only")
    assert absent("context/fine")


async def test_a_stale_item_saves_nothing_from_its_batch_either(room):
    await write(room, "context/later", "v1")
    items = [
        {"key": "context/first", "value": "ok", "created_by": "operator", "embed": False},
        {"key": "context/later", "value": "v2", "created_by": "operator", "base_version": 0},
    ]
    refused(
        await room.post(f"/api/rooms/{ROOM}/memory", json={"items": items}), "memory.stale_base"
    )
    assert absent("context/first")


async def test_the_hub_s_own_writers_are_not_checked(room):
    await hub_writes("context/standing", "where the run is", headline="Step 2")
    await hub_writes("work/ship-it", "Ship it", owner="builder", assignment="held")
    assert not absent("context/standing")
    assert stored("work/ship-it")[0]["owner"] == "builder"


async def test_a_lease_renewal_keeps_the_version(room):
    await hub_writes("work/ship-it", "Ship it")
    from app.services import fields

    meta, content = stored("work/ship-it")
    before = meta["version"]
    await fields.upsert_patch(
        ROOM,
        "work/ship-it",
        meta,
        content,
        {"claimed_at": "2026-11-13T10:00:00+00:00"},
        "builder",
        notify=False,
        keep_version=True,
    )
    after = stored("work/ship-it")[0]
    assert after["version"] == before
    assert after["claimed_at"] == "2026-11-13T10:00:00+00:00"


async def test_the_synthesizer_leaves_an_edit_made_while_it_ran(room):
    from app.services.synthesizer import SYNTHESIS_KEY, SynthesizerEngine, _briefing_version

    await hub_writes(SYNTHESIS_KEY, "the briefing")
    read_version = _briefing_version(ROOM)
    assert (await write(room, SYNTHESIS_KEY, "a person's edit")).status_code == 201

    engine = SynthesizerEngine.__new__(SynthesizerEngine)
    wrote = await engine._write_summary(ROOM, "the model's briefing", "synth", None, read_version)
    assert wrote is False
    assert stored(SYNTHESIS_KEY)[1].strip() == "a person's edit"


def test_a_copy_from_another_hub_carries_tags_and_frontmatter(tmp_path):
    write = memory_sync.KnowledgeWrite(
        key="context/summary/ship-it",
        content="text",
        version=2,
        created_by="operator",
        updated_by="operator",
        updated_at="2026-11-13T10:00:00+00:00",
        tags=["shared-summary"],
        meta={"contract": SUMMARY, "episode": "urn:other"},
    )
    again = memory_sync.KnowledgeWrite.from_payload(write.to_payload())
    assert again is not None
    memory_sync.apply_knowledge_to_dir(tmp_path, again)
    copied = read_memory_file(tmp_path, "context/summary/ship-it")
    assert copied is not None
    meta, _ = copied
    assert meta["tags"] == ["shared-summary"]
    assert meta["contract"]["title"] == "Checkout"
    assert "episode" not in meta, "a copy never names this store's thread"


def test_a_field_the_original_cleared_is_cleared_on_the_copy(tmp_path):
    def copy(**kw: Any) -> None:
        sent = memory_sync.KnowledgeWrite(
            key="context/plan",
            content="text",
            created_by="operator",
            updated_by="operator",
            updated_at="2026-11-13T10:00:00+00:00",
            **kw,
        )
        received = memory_sync.KnowledgeWrite.from_payload(sent.to_payload())
        assert received is not None
        memory_sync.apply_knowledge_to_dir(tmp_path, received)

    copy(version=1, tags=["plan"], meta={"relates-to": "work/ship-it"})
    copy(version=2, tags=[], meta={})
    copied = read_memory_file(tmp_path, "context/plan")
    assert copied is not None
    assert "relates-to" not in copied[0]
    assert not copied[0].get("tags")


def test_a_plain_copy_reads_as_it_did():
    plain = memory_sync.KnowledgeWrite(
        key="k", content="c", version=1, created_by="a", updated_by="a", updated_at="t"
    )
    assert "tags" not in plain.to_payload()
    assert "meta" not in plain.to_payload()
