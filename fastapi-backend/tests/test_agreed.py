# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""What a team agreed inside a task: where it is kept, and how later work finds it."""

from __future__ import annotations

import pytest

from app.services import agreed, message_format
from app.services.filesystem import get_room_dir, read_memory_file, room_exists, write_memory_file
from app.services.message_models import Kind
from app.services.message_slim import serialize_content
from app.services.persister import record_from

ROOM = "agreed-room"


def _write(key: str, body: str, **meta: object) -> None:
    write_memory_file(get_room_dir(ROOM), key, body, created_by="t", extra_meta=dict(meta))


def test_results_are_kept_by_task_under_context_never_on_the_board():
    assert agreed.summary_key("work/acme-renewal") == "context/summary/acme-renewal"
    assert agreed.decision_key("work/acme-renewal") == "context/decision/acme-renewal"
    assert agreed.summary_key("status/x") == "context/summary/status/x"


def test_a_child_row_reads_its_nearest_ancestors_when_it_has_none():
    _write("work/parent", "# Parent")
    _write("work/child", "# Child", **{"part-of": "work/parent"})
    _write("work/grandchild", "# Grandchild", **{"part-of": "work/child"})
    _write("context/summary/parent", "# Shared summary: Parent\n\nKeep it small.")

    ((key, _meta, body),) = agreed.found_for(ROOM, "work/grandchild")
    assert key == "context/summary/parent"
    assert "Keep it small." in agreed.for_prompt(ROOM, "work/grandchild")


def test_a_task_with_its_own_reads_its_own_and_both_kinds():
    _write("work/own", "# Own")
    _write("context/summary/own", "# Shared summary")
    _write("context/decision/own", "# Decision")
    keys = [k for k, _m, _b in agreed.found_for(ROOM, "work/own")]
    assert keys == ["context/summary/own", "context/decision/own"]


def test_nothing_agreed_renders_empty_never_an_error():
    assert agreed.for_prompt(ROOM, "work/none") == ""
    assert agreed.for_prompt(ROOM, "") == ""
    assert agreed.pointer(ROOM, "work/none") == []
    assert not room_exists("no-such-room-at-all")
    assert agreed.for_prompt("no-such-room-at-all", "work/x") == ""


def test_a_loop_in_part_of_ends():
    _write("work/l1", "# L1", **{"part-of": "work/l2"})
    _write("work/l2", "# L2", **{"part-of": "work/l1"})
    assert agreed.found_for(ROOM, "work/l1") == []


def test_open_items_are_read_off_the_saved_contract():
    meta = {"contract": {"flags": [{"kind": "single", "text": "Only one person said this: p1"}]}}
    assert agreed.open_items(meta) == ["Only one person said this: p1"]
    assert agreed.open_items({}) == []


# ── what later work is told, and what it can add ─────────────────────────────

SUMMARY = {
    "task": "work/refunds",
    "title": "Ship refunds",
    "cast": ["a", "b"],
    "points": [
        {"id": "p1", "type": "objective", "text": "Ship refunds.", "support": 2,
         "authors": ["a", "b"], "flags": []},
        {"id": "p2", "type": "constraint", "text": "No weekend deploys.", "support": 1,
         "authors": ["a"], "flags": ["single"]},
    ],
    "glossary": [
        {"term": "refund window", "status": "agreed",
         "meanings": [{"text": "14 calendar days", "members": ["a", "b"]}]},
    ],
    "checks": [],
    "unchecked": [],
    "flags": [{"kind": "single", "text": "Only one person said this: p2"}],
}  # fmt: skip
THREAD = message_format.episode_urn(ROOM, "t0000001")


def test_a_wake_is_told_what_the_summary_says_not_only_where_it_is():
    _write("work/refunds", "# Ship refunds")
    _write("context/summary/refunds", "# Shared summary", contract=SUMMARY)
    (line,) = agreed.pointer(ROOM, "work/refunds")
    assert line.startswith(
        "context/summary/refunds (shared summary): Ship refunds; refund window means "
        "14 calendar days; No weekend deploys; read it: mycelium memory get"
    )
    assert line.endswith("Open items: Only one person said this: p2")
    assert "`conflict:`" in agreed.for_prompt(ROOM, "work/refunds")


def test_a_decision_is_said_with_where_it_stands():
    decided = {"pick": "C", "text": "15% off for two years", "agreed": False,
               "short": [{"member": "finance", "placed": 0.4, "why": "margin dips in year one"}]}  # fmt: skip
    assert agreed.gist("context/decision/x", {"decision": decided}) == (
        "going with C: 15% off for two years; best found, short of the bar for "
        "finance (margin dips in year one)"
    )
    decided |= {"agreed": True}
    assert agreed.gist("context/decision/x", {"decision": decided}).endswith(
        "; everyone meets the bar"
    )


def _said(text: str, *, payload: dict | None = None):
    env = message_format.build_envelope(
        kind=Kind.exchange,
        episode=THREAD,
        sender="b",
        topic=message_format.topic_urn(ROOM),
        payload_type="message",
        payload_data=payload,
    )
    return record_from(env, serialize_content(env, extra={"content": text}))


def test_a_conflict_line_in_the_tasks_thread_is_found(monkeypatch):
    from app.services import tasks

    _write("work/refunds", "# Ship refunds")
    _write("context/summary/refunds", "# Shared summary", contract=SUMMARY)
    monkeypatch.setattr(
        tasks,
        "row_of_episode",
        lambda _r, e: ("work/refunds", "Ship refunds") if e == THREAD else None,
    )
    said = "Built it.\nconflict: the payment provider holds refunds for 30 days, not 14"
    assert agreed.reported(ROOM, _said(said)) == (
        "context/summary/refunds",
        ["the payment provider holds refunds for 30 days, not 14"],
    )
    assert agreed.reported(ROOM, _said("Built it, no surprises.")) is None
    # The conductor's own prompts report nothing.
    assert agreed.reported(ROOM, _said(said, payload={"conductor": {"event": "turn"}})) is None


@pytest.mark.asyncio
async def test_a_reported_conflict_is_added_to_the_open_items_once(monkeypatch):
    from app.services import embedding

    monkeypatch.setattr(embedding, "_STUB", True)
    _write(
        "context/summary/refunds",
        "# Shared summary",
        contract=SUMMARY,
        flow="accord",
        reviewed="by julia",
        **{"relates-to": "work/refunds"},
    )
    conflict = ["the payment provider holds refunds for 30 days, not 14"]

    assert await agreed.add_conflicts(ROOM, "context/summary/refunds", "b", conflict)
    assert not await agreed.add_conflicts(ROOM, "context/summary/refunds", "b", conflict)

    meta, body = read_memory_file(get_room_dir(ROOM), "context/summary/refunds") or ({}, "")
    flags = meta["contract"]["flags"]
    assert flags[-1] == {
        "kind": "reported_conflict",
        "text": "b says this doesn't fit: the payment provider holds refunds for 30 days, not 14",
        "members": ["b"],
    }
    assert len(flags) == 2
    assert "- b says this doesn't fit: the payment provider holds refunds" in body
    # Only the contract changed: the summary's other frontmatter is as it was.
    assert meta["relates-to"] == "work/refunds"
    assert meta["flow"] == "accord"
    assert meta["reviewed"] == "by julia"


@pytest.mark.asyncio
async def test_conflicts_arriving_together_are_all_kept(monkeypatch):
    import asyncio

    from app.services import embedding

    monkeypatch.setattr(embedding, "_STUB", True)
    _write("context/summary/together", "# Shared summary", contract=SUMMARY)

    await asyncio.gather(
        agreed.add_conflicts(ROOM, "context/summary/together", "a", ["one"]),
        agreed.add_conflicts(ROOM, "context/summary/together", "b", ["two"]),
        agreed.add_conflicts(ROOM, "context/summary/together", "c", ["three"]),
    )

    meta, _body = read_memory_file(get_room_dir(ROOM), "context/summary/together") or ({}, "")
    reported = [f["text"] for f in meta["contract"]["flags"] if f["kind"] == "reported_conflict"]
    assert sorted(reported) == [
        "a says this doesn't fit: one",
        "b says this doesn't fit: two",
        "c says this doesn't fit: three",
    ]


@pytest.mark.asyncio
async def test_a_summary_rewritten_mid_add_is_read_again_not_overwritten(monkeypatch):
    from app.services import embedding

    monkeypatch.setattr(embedding, "_STUB", True)
    key = "context/summary/rewritten"
    _write(key, "# Shared summary", contract=SUMMARY)
    real_save = agreed.save
    rewrites = []

    async def save_after_a_rewrite(*args, **kwargs):
        # Another writer (an accord run again) saves the summary first, once.
        if not rewrites:
            rewrites.append(1)
            again = {**SUMMARY, "flags": [{"kind": "single", "text": "From the rerun"}]}
            await real_save(
                ROOM, key, body="# Shared summary", meta={"contract": again}, task="",
                by="conductor", tags=["shared-summary"],
            )  # fmt: skip
        return await real_save(*args, **kwargs)

    monkeypatch.setattr(agreed, "save", save_after_a_rewrite)

    assert await agreed.add_conflicts(ROOM, key, "b", ["it doesn't fit"])

    meta, _body = read_memory_file(get_room_dir(ROOM), key) or ({}, "")
    assert [f["text"] for f in meta["contract"]["flags"]] == [
        "From the rerun",
        "b says this doesn't fit: it doesn't fit",
    ]
