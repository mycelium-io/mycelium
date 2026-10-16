# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""What a team agreed inside a task: where it is kept, and how later work finds it."""

from __future__ import annotations

from app.services import agreed
from app.services.filesystem import get_room_dir, room_exists, write_memory_file

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
