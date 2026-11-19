# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The wake, as the app reads it.

The app parses a wake into its parts (``mycelium-frontend/src/lib/wake-digest.ts``)
to draw it in an agent's window. ``contracts/wake-digests.json`` holds wakes
this module builds from fixed inputs, with what the parser should find in each.
This test fails when a wake changes, and the app's test parses every sample, so
a change to the wake can't leave the parser reading it wrong without a red test.

After changing the wake on purpose, write the samples again and check the app's
test still passes:

    MYCELIUM_WRITE_CONTRACTS=1 uv run pytest tests/test_wake_digest_contract.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.services import wake_digest
from tests.test_wake_digest import (
    LONG,
    NOW,
    ROOM,
    THREAD,
    _handed,
    _notice,
    _room_of,
    _said,
    _task_thread,
)

CONTRACT = Path(__file__).resolve().parents[2] / "contracts" / "wake-digests.json"

COMMENT = (
    "Wakes the hub builds (app/services/wake_digest.py), with what the app's wake "
    "parser should find in each. Written by fastapi-backend/tests/"
    "test_wake_digest_contract.py, which fails when a wake changes; read by "
    "mycelium-frontend/src/lib/wake-digest.test.ts, which parses every sample. To "
    "write it again after changing the wake: MYCELIUM_WRITE_CONTRACTS=1 uv run "
    "pytest tests/test_wake_digest_contract.py"
)


def _mention_in_a_thread() -> dict:
    """Two messages ask for it in a task's thread; the newest woke it."""
    _task_thread()
    records = [
        _said(1, "builder", "on it", 41),
        _said(
            2, "reviewer", "@builder I went through the receipt code. Two places round.", 40, THREAD
        ),
        _said(3, "hay", "unrelated chatter in the room", 30),
        _notice(
            4,
            20,
            subkind="claimed",
            key="work/fix-the-receipt-tax",
            title="Fix the receipt tax",
            by="builder",
        ),
        _said(5, "scout", LONG, 2, THREAD),
    ]
    text = wake_digest.build(
        ROOM, {"handle": "builder", "reason": "mention", "from": "scout"}, records, NOW
    )
    return {
        "name": "mention in a task's thread, with another ask",
        "text": text,
        "expect": {
            "handle": "builder",
            "room": ROOM,
            "messages": [
                # The one that woke it, then one under "Also asking you".
                {"sender": "scout", "id": wake_digest.short_id(records[4]), "also": False},
                {"sender": "reviewer", "id": wake_digest.short_id(records[1]), "also": True},
            ],
        },
    }


def _task_given() -> dict:
    """Someone gave it a task."""
    _task_thread()
    records = [_said(1, "builder", "back", 30), _said(2, "hay", "filing the tax fix", 5)]
    text = wake_digest.build(
        ROOM,
        {
            "handle": "builder",
            "reason": "assigned",
            "from": "hay",
            "key": "work/fix-the-receipt-tax",
            "title": "Fix the receipt tax",
        },
        records,
        NOW,
    )
    return {
        "name": "a task given to it",
        "text": text,
        "expect": {"handle": "builder", "room": ROOM, "messages": []},
    }


def _turn_with_members(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Its turn in the room, named silently once, with the members pane."""
    _task_thread()
    _room_of(
        monkeypatch,
        ["builder", "desktop", "research", "themes"],
        {"builder": "working", "desktop": "working", "research": "done", "themes": "blocked"},
    )
    _handed(monkeypatch, 1, "desktop", 4, reason="mention", **{"from": "hay"})
    records = [
        _said(1, "builder", "pushed the fix", 50),
        _said(2, "hay", "cc @~builder for the record", 20),
        _said(3, "hay", "@builder does the rounding cover refunds?", 1),
    ]
    text = wake_digest.build(
        ROOM, {"handle": "builder", "reason": "turn", "from": "hay"}, records, NOW
    )
    return {
        "name": "its turn in the room, named silently, with the members pane",
        "text": text,
        "expect": {
            "handle": "builder",
            "room": ROOM,
            "messages": [{"sender": "hay", "id": wake_digest.short_id(records[2]), "also": False}],
        },
    }


def _samples(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    # Each sample is built in a room of its own, so none sees another's state.
    out = []
    for build in (_mention_in_a_thread, _task_given, lambda: _turn_with_members(monkeypatch)):
        from app.services import in_memory_store

        in_memory_store.clear_all()
        out.append(build())
    return out


def test_the_wakes_the_app_parses_are_the_wakes_the_hub_builds(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    samples = _samples(monkeypatch)
    want = {"_comment": COMMENT, "samples": samples}
    if os.environ.get("MYCELIUM_WRITE_CONTRACTS"):
        CONTRACT.write_text(json.dumps(want, indent=2, ensure_ascii=False) + "\n")
    have = json.loads(CONTRACT.read_text())
    for built, kept in zip(samples, have["samples"], strict=True):
        assert built == kept, (
            f"The wake changed ({built['name']}). Check that the app's wake parser "
            "(mycelium-frontend/src/lib/wake-digest.ts) still reads it, then write the "
            "samples again: MYCELIUM_WRITE_CONTRACTS=1 uv run pytest "
            "tests/test_wake_digest_contract.py"
        )
