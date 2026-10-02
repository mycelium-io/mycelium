# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Where a pattern's run stands, restated after every step.

What Pi is asked and how its answer is read; that a room loaded from a pattern
with ``after`` gets its standing written as a memory, from what was said in the
task's thread; that a room made any other way gets nothing; that steps landing
during a call fold into one call after it; and that a failed hook never stops a
run.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest
import yaml

from app.config import settings
from app.services import patterns, standing
from app.services.conductor import ConductorEngine
from app.services.filesystem import get_room_dir, read_memory_file

if TYPE_CHECKING:
    from pathlib import Path

SCENARIO: dict[str, Any] = {
    "pattern": "approval-gate-agent",
    "title": "Approval gate",
    "summary": "An agent proposes, a person decides.",
    "room": {"title": "Refund batch"},
    "members": [
        {"handle": "ops", "kind": "persona", "notes": "You are ops."},
        {"handle": "you", "kind": "human"},
    ],
    "task": {"title": "Refund the batch"},
    "summon": {"flow": "gated", "members": ["ops", "you"], "ask": "Refund them."},
    "before": {"headline": "8,400 in refunds, ready", "detail": "Over the limit."},
    "after": {"track": "Whether the batch went out."},
}


@pytest.fixture(autouse=True)
def _no_embedding(monkeypatch):
    monkeypatch.setattr("app.routes.memory.embed_text", lambda _text: [0.0])


@pytest.fixture
def pack(tmp_path: Path, monkeypatch) -> Path:
    folder = tmp_path / "pack" / "scenarios" / SCENARIO["pattern"]
    folder.mkdir(parents=True)
    (folder / "scenario.yaml").write_text(yaml.safe_dump(SCENARIO))
    monkeypatch.setattr(settings, "PATTERNS_DIR", str(tmp_path / "pack"))
    return tmp_path / "pack"


async def loaded(client) -> tuple[str, str]:
    resp = await client.post("/api/patterns/approval-gate-agent/load", json={"created_by": "julia"})
    assert resp.status_code == 201, resp.text
    return resp.json()["room"], resp.json()["episode"]


async def say(client, room: str, episode: str, who: str, text: str) -> None:
    resp = await client.post(
        f"/api/rooms/{room}/messages",
        json={
            "sender_handle": who,
            "message_type": "broadcast",
            "content": text,
            "episode": episode,
        },
    )
    assert resp.status_code in (200, 201), resp.text


# ── what Pi is asked, and how its answer is read ─────────────────────────────


def test_the_prompt_carries_the_start_what_matters_and_what_was_said():
    scenario = patterns.Scenario.model_validate(SCENARIO)
    prompt = standing.build_prompt(scenario, [("ops", "I propose 8,400.")], None)
    assert "It started here: 8,400 in refunds, ready. Over the limit." in prompt
    assert "What the result is about: Whether the batch went out." in prompt
    assert "It is still going." in prompt
    assert "- ops: I propose 8,400." in prompt

    done = standing.build_prompt(scenario, [("ops", "x" * 5000)], "resolved")
    assert "It has finished and reached its end." in done
    assert "x" * standing.MESSAGE_CHARS + " […]" in done


@pytest.mark.parametrize(
    ("answer", "read"),
    [
        (
            "Held for a list\nThe approver wants names first.",
            ("Held for a list", "The approver wants names first."),
        ),
        ("**Held for a list**\n\nNames first.", ("Held for a list", "Names first.")),
        ("Line 1: Held\nLine 2: Names first.", ("Held", "Names first.")),
        ("Approved", ("Approved", "")),
        ("  \n ", None),
    ],
)
def test_the_answer_is_a_headline_and_a_detail(answer, read):
    assert standing.parse_answer(answer) == read


# ── writing it ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_patterns_run_has_where_it_stands_written(client, pack, monkeypatch):
    room, episode = await loaded(client)
    await say(client, room, episode, "dana", "I intend to refund 23 customers, 8,400 in total.")
    await say(client, room, episode, "julia", "Which customers? I want the list first.")
    await say(client, room, "", "julia", "An aside in the room, not the task.")
    asked: list[str] = []

    def complete(prompt: str, _room: str) -> str:
        asked.append(prompt)
        return "Held until the approver sees the list\nNothing refunded yet; ops owes a list."

    monkeypatch.setattr(standing, "_complete", complete)
    assert await standing.restate(room, episode, None) is True

    assert "- julia: Which customers?" in asked[0]
    assert "An aside" not in asked[0]
    found = read_memory_file(get_room_dir(room), standing.STANDING_KEY)
    assert found is not None
    meta = yaml.safe_load(found[0]) if isinstance(found[0], str) else found[0]
    assert meta["headline"] == "Held until the approver sees the list"
    assert meta["state"] == "running"
    assert meta["said"] == 2


@pytest.mark.asyncio
async def test_nothing_is_written_with_nothing_said_or_no_answer(client, pack, monkeypatch):
    room, episode = await loaded(client)
    monkeypatch.setattr(standing, "_complete", lambda _p, _r: "")
    assert await standing.restate(room, episode, None) is False  # nothing said yet
    await say(client, room, episode, "dana", "A proposal.")
    assert await standing.restate(room, episode, None) is False  # an empty answer
    assert read_memory_file(get_room_dir(room), standing.STANDING_KEY) is None


@pytest.mark.asyncio
async def test_a_room_made_any_other_way_is_left_alone(client, pack):
    await client.post("/api/rooms", json={"name": "plain"})
    assert standing.scenario_of("plain") is None
    tracker = standing.Standing()
    tracker.on_step("plain", "urn:x", None)
    assert tracker._running == {}


# ── one call at a time ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_steps_during_a_call_fold_into_one_call_after_it(client, pack, monkeypatch):
    room, episode = await loaded(client)
    calls: list[str | None] = []
    gate = asyncio.Event()

    async def restate(_room: str, _thread: str, outcome: str | None) -> bool:
        calls.append(outcome)
        await gate.wait()
        return True

    monkeypatch.setattr(standing, "restate", restate)
    tracker = standing.Standing()
    tracker.on_step(room, episode, None)
    await asyncio.sleep(0)
    tracker.on_step(room, episode, None)
    tracker.on_step(room, episode, "resolved")
    gate.set()
    await tracker.idle()
    assert calls == [None, "resolved"]


def test_a_hook_that_fails_never_stops_a_run():
    engine = ConductorEngine(MagicMock())

    def boom(*_args: object) -> None:
        raise RuntimeError

    engine.on_step = boom
    engine._stepped("room", "urn:x", None)  # logged, not raised
