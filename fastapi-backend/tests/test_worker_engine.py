# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The worker engine: a member the hub plays that takes work off the board.

Node-free; the Pi turn is patched. What these hold: action lines are lifted out
of the prose and carried out against the row the thread belongs to; a worker
may name a teammate but never an engine; a row filed for a worker gets claimed
and worked; the last child settling hands the split back to whoever made it;
the seams gate on the manifest kind; and a room's turns are capped.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
import yaml

from app.services import assignments, l9, tasks, worker_engine
from app.services.filesystem import (
    get_room_dir,
    list_memory_files,
    read_memory_file,
    write_memory_file,
)
from app.services.l9_models import Kind
from tests.fakes import FakeChannel, FakeManaged, FakeManager, FakePersister

_ROOM = "worker-room"


class _Manager(FakeManager):
    """The fake manager plus the two calls a worker makes after it speaks."""

    def __init__(self, managed: FakeManaged) -> None:
        super().__init__(managed, [])
        self.rung: list[str] = []
        self.pings: list[str] = []

    def enqueue_herdr_wakes_for_mentions(
        self, room: str, content: str, *, exclude: str | None = None
    ) -> list[str]:
        self.rung.append(content)
        return []

    async def raise_ping(self, room: str, *, episode: str | None, sender: str, message_id: Any):
        self.pings.append(sender)


def _engine(**kwargs: Any) -> tuple[worker_engine.WorkerEngine, FakeManaged, _Manager]:
    managed = FakeManaged(_ROOM, "mycelium", FakeChannel(), FakePersister())
    manager = _Manager(managed)
    return worker_engine.WorkerEngine(manager, **kwargs), managed, manager  # type: ignore[arg-type]


def _register(handle: str, kind: str | None = "worker", adapter: str = "engine") -> None:
    body: dict[str, Any] = {"adapter": adapter}
    if kind:
        body["kind"] = kind
    write_memory_file(
        get_room_dir(_ROOM), f"agents/{handle}", yaml.safe_dump(body), created_by="julia"
    )


def _posted(managed: FakeManaged) -> list[tuple[Any, str]]:
    return [(env, (extra or {}).get("content", "")) for env, extra in managed.channel.sent]


def _patch_pi(monkeypatch: pytest.MonkeyPatch, *replies: str) -> list[dict[str, str]]:
    seen: list[dict[str, str]] = []
    queue = list(replies)

    def fake(room: str, handle: str, prompt: str, system: str, _t: float) -> str:
        seen.append({"handle": handle, "prompt": prompt, "system": system})
        return queue.pop(0) if queue else ""

    monkeypatch.setattr(worker_engine, "_pi_complete", fake)
    return seen


@pytest.fixture(autouse=True)
def _backend_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "ENGINE_RUNTIME", "backend")
    monkeypatch.setattr("app.routes.memory.embed_text", lambda _text: [0.0])
    get_room_dir(_ROOM)


async def _task(title: str, **meta: Any) -> tuple[str, str]:
    row = await tasks.create_task(_ROOM, title, created_by="julia", meta=meta or None)
    return row.key, str(row.episode)


async def _settle(engine: worker_engine.WorkerEngine) -> None:
    for _ in range(50):
        if not engine._tasks:
            return
        await asyncio.sleep(0.01)


# ── reading a reply ────────────────────────────────────────────────────────────


def test_action_lines_are_lifted_out_of_the_prose():
    actions, prose = worker_engine.parse_actions(
        "Here is the split.\n\n[[new: Reproduce the flake -> @agent-2]]\n"
        "[[NEW: Find the root cause → agent-3]]\n[[done]]\nThat's it."
    )
    assert actions == [
        worker_engine.Action("new", "Reproduce the flake", "agent-2"),
        worker_engine.Action("new", "Find the root cause", "agent-3"),
        worker_engine.Action("done"),
    ]
    assert "[[" not in prose
    assert prose.startswith("Here is the split.")
    assert prose.endswith("That's it.")


def test_a_new_task_that_names_nobody_is_not_filed():
    actions, _prose = worker_engine.parse_actions("[[new: An orphan task]]")
    assert actions == []


def test_a_worker_may_name_a_teammate_but_never_an_engine():
    team = ["agent-1", "agent-2", "julia"]
    text = "@agent-2 can you review? @aligner @conductor @agent-1 @julia @nobody"
    kept = worker_engine.keep_team_mentions(text, team, "agent-1")
    assert kept == "@agent-2 can you review? aligner conductor agent-1 @julia nobody"


def test_the_team_is_the_agents_and_the_workers_not_the_other_engines():
    _register("agent-1")
    _register("agent-2")
    _register("conductor", "conductor")
    _register("aligner", "aligner")
    _register("julia-laptop", None, adapter="claude_code")
    assert worker_engine.team_of(_ROOM) == ["agent-1", "agent-2", "julia-laptop"]


def test_the_prompt_names_the_team_the_task_and_the_thread():
    prompt = worker_engine.build_prompt(
        _ROOM,
        "agent-2",
        team=["agent-1", "agent-2", "agent-3"],
        task=("work/fix-flake", "Fix the flaky test"),
        thread="- agent-1: I'll split it.",
        ask="Check in.",
    )
    assert "You are @agent-2" in prompt
    assert "agent-1, agent-3" in prompt
    assert "work/fix-flake: Fix the flaky test" in prompt
    assert "- agent-1: I'll split it." in prompt
    assert prompt.endswith("Check in.")


# ── a turn ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_turn_posts_the_prose_and_files_the_split(monkeypatch: pytest.MonkeyPatch):
    for h in ("agent-1", "agent-2", "agent-3"):
        _register(h)
    parent, episode = await _task("Fix the flaky auth tests")
    seen = _patch_pi(
        monkeypatch,
        "Splitting it three ways.\n[[new: Reproduce it -> @agent-2]]\n"
        "[[new: Root-cause it -> @agent-3]]\n[[new: Ghost task -> @nobody]]",
    )
    engine, managed, _manager = _engine()

    said = await engine.turn(_ROOM, "agent-1", episode=episode, ask="Split the work.")

    assert said == "Splitting it three ways."
    assert "You have no tools" in seen[0]["system"]
    env, text = _posted(managed)[0]
    assert text == "Splitting it three ways."
    assert env.header.message.episode == episode
    children = [
        (key, meta)
        for key, meta, _body in list_memory_files(get_room_dir(_ROOM), prefix="work/")
        if meta.get(assignments.PARENT_RELATION) == parent
    ]
    assert sorted(meta[tasks.ASSIGNEE_FIELD] for _k, meta in children) == ["agent-2", "agent-3"]
    assert all(meta.get("created_by") == "agent-1" for _k, meta in children)
    await _settle(engine)


@pytest.mark.asyncio
async def test_done_resolves_the_row_the_thread_belongs_to(monkeypatch: pytest.MonkeyPatch):
    _register("agent-2")
    key, episode = await _task("Review the fix")
    _patch_pi(monkeypatch, "Looks right to me.\n[[done]]")
    engine, _managed, _manager = _engine()

    await engine.turn(_ROOM, "agent-2", episode=episode, ask="Review it.")

    found = read_memory_file(get_room_dir(_ROOM), key)
    assert found is not None
    assert assignments.state_of(found[0], datetime.now(UTC)) == "resolved"


@pytest.mark.asyncio
async def test_a_mention_of_a_teammate_rings_their_doorbell(monkeypatch: pytest.MonkeyPatch):
    _register("agent-1")
    _register("agent-2")
    _key, episode = await _task("Draft it")
    _patch_pi(monkeypatch, "Draft is up. @agent-2 can you check the edge cases?")
    engine, _managed, manager = _engine()

    await engine.turn(_ROOM, "agent-1", episode=episode, ask="Do it.")

    assert manager.rung == ["Draft is up. @agent-2 can you check the edge cases?"]
    assert manager.pings == ["agent-1"]


@pytest.mark.asyncio
async def test_a_room_runs_out_of_worker_turns(monkeypatch: pytest.MonkeyPatch):
    _register("agent-1")
    _key, episode = await _task("Chatter")
    seen = _patch_pi(monkeypatch, "one", "two", "three")
    engine, managed, _manager = _engine(max_turns=2)

    for _ in range(3):
        await engine.turn(_ROOM, "agent-1", episode=episode, ask="Say something.")

    assert len(seen) == 2
    assert [text for _env, text in _posted(managed)] == ["one", "two"]


@pytest.mark.asyncio
async def test_off_the_floor_a_worker_says_nothing(monkeypatch: pytest.MonkeyPatch):
    _register("agent-2")
    _key, episode = await _task("Kickoff")
    _patch_pi(monkeypatch, "Jumping in early.")
    engine, managed, manager = _engine()
    manager.hold_floor(_ROOM, episode, holder="conductor", speakers=["agent-1"])

    await engine.turn(_ROOM, "agent-2", episode=episode, ask="Hi.")

    assert _posted(managed) == []


# ── the seams ──────────────────────────────────────────────────────────────────


def _env(sender: str, episode: str, recipients: list[str] | None = None) -> Any:
    return l9.build_envelope(
        kind=Kind.exchange,
        episode=episode,
        sender=sender,
        recipients=recipients,
        topic=l9.topic_urn(_ROOM),
        payload_type="message",
    )


@pytest.mark.asyncio
async def test_an_addressed_turn_is_answered_where_it_was_asked(monkeypatch: pytest.MonkeyPatch):
    _register("agent-1")
    _key, episode = await _task("Kickoff")
    seen = _patch_pi(monkeypatch, "Here. I'll take the repro.")
    engine, managed, _manager = _engine()

    engine.handle_addressed(_ROOM, "agent-1", _env("conductor", episode, ["agent-1"]), "Check in.")
    await _settle(engine)

    assert "conductor said to you" in seen[0]["prompt"]
    env, text = _posted(managed)[0]
    assert text == "Here. I'll take the repro."
    assert env.header.message.episode == episode


@pytest.mark.asyncio
async def test_a_review_request_names_who_to_answer(monkeypatch: pytest.MonkeyPatch):
    _register("agent-1")
    _register("agent-2")
    _key, episode = await _task("Draft it")
    seen = _patch_pi(monkeypatch, "Looks good.\n[[done]]")
    engine, _managed, _manager = _engine()

    engine.handle_summon(
        _ROOM, "agent-1", _env("agent-2", episode), ["agent-1"], "@agent-1 can you check it?"
    )
    await _settle(engine)

    assert "tell @agent-2 exactly what to fix" in seen[0]["prompt"]


async def _held_by(handle: str, title: str) -> tuple[str, str]:
    key, episode = await _task(title, assignee=handle)
    await assignments.claim(_ROOM, key, handle, 30, datetime.now(UTC))
    return key, episode


@pytest.mark.asyncio
async def test_a_review_that_names_nobody_goes_back_to_the_holder(
    monkeypatch: pytest.MonkeyPatch,
):
    # The live failure: the reviewer asked for changes but addressed itself,
    # so the holder never heard and the row went quiet.
    for h in ("agent-1", "agent-2"):
        _register(h)
    _key, episode = await _held_by("agent-2", "Technical review")
    seen = _patch_pi(
        monkeypatch,
        "Missing shell compatibility. agent-1: add the missing sections.",
        "Added shell compatibility. @agent-1 can you look again?",
    )
    engine, managed, _manager = _engine()

    await engine.turn(_ROOM, "agent-1", episode=episode, ask="Review it.")
    await _settle(engine)

    assert [s["handle"] for s in seen] == ["agent-1", "agent-2"]
    assert "agent-1 said to you" in seen[1]["prompt"]
    # The revision it is asked for is the work itself, since that is what the
    # row keeps once it resolves.
    assert "complete new version" in seen[1]["prompt"]
    assert "Missing shell compatibility" in seen[1]["prompt"]
    assert _posted(managed)[1][1] == "Added shell compatibility. @agent-1 can you look again?"


@pytest.mark.asyncio
async def test_nothing_is_handed_back_that_settles_or_names_someone(
    monkeypatch: pytest.MonkeyPatch,
):
    for h in ("agent-1", "agent-2", "agent-3"):
        _register(h)
    _one, first = await _held_by("agent-2", "Part one")
    _two, second = await _held_by("agent-2", "Part two")
    _three, own = await _held_by("agent-1", "Part three")
    seen = _patch_pi(
        monkeypatch,
        "Good.\n[[done]]",  # resolves it
        "@agent-3 can you weigh in?",  # names someone else
        "Here is my part. @agent-2 can you check it?",  # on its own row, naming its reviewer
    )
    engine, _managed, _manager = _engine()

    await engine.turn(_ROOM, "agent-1", episode=first, ask="Review it.")
    await engine.turn(_ROOM, "agent-1", episode=second, ask="Review it.")
    await engine.turn(_ROOM, "agent-1", episode=own, ask="Do it.")
    await _settle(engine)

    assert [s["handle"] for s in seen] == ["agent-1", "agent-1", "agent-1"]


@pytest.mark.asyncio
async def test_a_revision_that_names_nobody_goes_to_the_reviewer_who_settles_it_in_time(
    monkeypatch: pytest.MonkeyPatch,
):
    # The sixth live run: an author posted its revision without naming its
    # reviewer, nobody heard, and the part never resolved.
    for h in ("agent-1", "agent-2"):
        _register(h)
    key, episode = await _held_by("agent-2", "Changelog")
    reviewer_says = ["Needs dates.", "Needs versions.", "Workable, notes left.\n[[done]]"]
    seen: list[dict[str, str]] = []

    def fake(room: str, handle: str, prompt: str, system: str, _t: float) -> str:
        seen.append({"handle": handle, "prompt": prompt})
        # The author revises without naming anyone; the reviewer answers in turn.
        return "Revised version." if handle == "agent-2" else reviewer_says.pop(0)

    monkeypatch.setattr(worker_engine, "_pi_complete", fake)
    engine, _managed, _manager = _engine()

    for _ in range(worker_engine.REVIEW_ROUNDS):
        await engine.turn(_ROOM, "agent-2", episode=episode, ask="Revise.")
        await _settle(engine)
        await _settle(engine)

    reviews = [s for s in seen if s["handle"] == "agent-1"]
    assert len(reviews) == worker_engine.REVIEW_ROUNDS
    assert "you are its reviewer" in reviews[0]["prompt"]
    assert "final round" not in reviews[0]["prompt"]
    assert "final round" in reviews[-1]["prompt"]
    found = read_memory_file(get_room_dir(_ROOM), key)
    assert found is not None
    assert assignments.settled(found[0], datetime.now(UTC))


def test_the_seams_gate_on_the_worker_kind(monkeypatch: pytest.MonkeyPatch):
    _register("sec", "persona")
    engine, _managed, _manager = _engine()
    env = _env("julia", l9.live_episode_urn(_ROOM))
    engine.handle_addressed(_ROOM, "sec", env, "hi")
    engine.handle_summon(_ROOM, "sec", env, ["sec"], "@sec hi")
    engine.handle_notice(_ROOM, {"subkind": "filed", "key": "work/x", "episode": "e", "for": "sec"})
    assert engine._tasks == set()


def test_a_role_named_beside_a_conductor_is_not_asked_anything():
    _register("agent-1")
    _register("conductor", "conductor")
    engine, _managed, _manager = _engine()
    env = _env("julia", l9.live_episode_urn(_ROOM))
    engine.handle_summon(
        _ROOM, "agent-1", env, ["conductor", "agent-1"], "@conductor swarm @agent-1: go"
    )
    assert engine._tasks == set()


@pytest.mark.asyncio
async def test_a_row_filed_for_a_worker_is_claimed_and_worked(monkeypatch: pytest.MonkeyPatch):
    _register("agent-2")
    key, episode = await _task("Reproduce the flake", assignee="agent-2")
    seen = _patch_pi(monkeypatch, "Reproduced it: the seed 4412 fails. @agent-3 can you check?")
    engine, managed, _manager = _engine()

    engine.handle_notice(
        _ROOM,
        {"subkind": "filed", "key": key, "episode": episode, "for": "agent-2", "title": "x"},
    )
    await _settle(engine)

    found = read_memory_file(get_room_dir(_ROOM), key)
    assert found is not None
    assert found[0].get("owner") == "@agent-2"
    assert "is yours" in seen[0]["prompt"]
    assert _posted(managed)[0][0].header.message.episode == episode


@pytest.mark.asyncio
async def test_the_last_child_settling_hands_the_split_back(monkeypatch: pytest.MonkeyPatch):
    for h in ("agent-1", "agent-2"):
        _register(h)
    parent, parent_episode = await _task("Ship the fix")
    one = await tasks.create_task(
        _ROOM, "Part one", created_by="agent-1", meta={"part-of": parent, "assignee": "agent-1"}
    )
    two = await tasks.create_task(
        _ROOM, "Part two", created_by="agent-1", meta={"part-of": parent, "assignee": "agent-2"}
    )
    now = datetime.now(UTC)
    await assignments.resolve(_ROOM, one.key, "agent-2", now)
    assert assignments.parent_completed(_ROOM, one.key, now) is None
    await assignments.resolve(_ROOM, two.key, "agent-1", now)
    assert assignments.parent_completed(_ROOM, two.key, now) == (parent, "agent-1")

    seen = _patch_pi(monkeypatch, "Both parts landed; here is the whole of it.\n[[done]]")
    engine, managed, _manager = _engine()
    engine.handle_notice(_ROOM, {"subkind": "resolved", "key": two.key})
    await _settle(engine)

    assert seen[0]["handle"] == "agent-1"
    assert "Every part of 'Ship the fix'" in seen[0]["prompt"]
    assert _posted(managed)[0][0].header.message.episode == parent_episode
    found = read_memory_file(get_room_dir(_ROOM), parent)
    assert found is not None
    assert assignments.settled(found[0], datetime.now(UTC))


@pytest.mark.asyncio
async def test_the_wrap_up_works_from_each_parts_final_version(monkeypatch: pytest.MonkeyPatch):
    from app.services.in_memory_store import StoredMessage

    for h in ("agent-1", "agent-2"):
        _register(h)
    parent, _parent_episode = await _task("Write the guide")
    one = await tasks.create_task(
        _ROOM,
        "Setup section",
        created_by="agent-1",
        meta={"part-of": parent, "assignee": "agent-2"},
    )
    await assignments.claim(_ROOM, one.key, "agent-2", 30, datetime.now(UTC))
    said = [
        StoredMessage("agent-2", "broadcast", "Setup v1: npm i", episode=one.episode),
        StoredMessage("agent-1", "broadcast", "Trim it.", episode=one.episode),
        StoredMessage("agent-2", "broadcast", "Setup v2: npm ci", episode=one.episode),
        StoredMessage("agent-1", "broadcast", "Good. ", episode=one.episode),
    ]
    monkeypatch.setattr("app.services.persister.prose_messages", lambda _room: said)

    parts = worker_engine._parts_of(_ROOM, parent)

    assert parts.startswith("### Setup section (by agent-2)")
    assert "Setup v2: npm ci" in parts
    assert "Setup v1" not in parts
    assert "Trim it." not in parts


@pytest.mark.asyncio
async def test_a_second_done_on_a_settled_row_changes_nothing(monkeypatch: pytest.MonkeyPatch):
    for h in ("agent-2", "agent-3"):
        _register(h)
    key, episode = await _task("Review it")
    _patch_pi(monkeypatch, "Good.\n[[done]]", "Agreed.\n[[done]]")
    engine, _managed, _manager = _engine()

    await engine.turn(_ROOM, "agent-2", episode=episode, ask="Review it.")
    await engine.turn(_ROOM, "agent-3", episode=episode, ask="Review it.")

    found = read_memory_file(get_room_dir(_ROOM), key)
    assert found is not None
    assert found[0].get("assignment_note_by") == "agent-2"


@pytest.mark.asyncio
async def test_a_part_is_not_done_on_its_holders_word_alone(monkeypatch: pytest.MonkeyPatch):
    from app.services.in_memory_store import StoredMessage

    for h in ("agent-1", "agent-2"):
        _register(h)
    parent, _pe = await _task("The whole")
    part = await tasks.create_task(
        _ROOM, "A part", created_by="agent-1", meta={"part-of": parent, "assignee": "agent-2"}
    )
    await assignments.claim(_ROOM, part.key, "agent-2", 30, datetime.now(UTC))
    said: list[StoredMessage] = []
    monkeypatch.setattr("app.services.persister.prose_messages", lambda _room: said)
    _patch_pi(monkeypatch, "Here it is, and it is done.\n[[done]]", "Fixed as asked.\n[[done]]")
    engine, _managed, _manager = _engine()

    await engine.turn(_ROOM, "agent-2", episode=str(part.episode), ask="Do it.")
    found = read_memory_file(get_room_dir(_ROOM), part.key)
    assert found is not None
    assert not assignments.settled(found[0], datetime.now(UTC))

    # Once a teammate has reviewed it, the holder closing it out is fine.
    said.append(StoredMessage("agent-1", "broadcast", "Looks good.", episode=part.episode))
    await engine.turn(_ROOM, "agent-2", episode=str(part.episode), ask="Close it out.")
    found = read_memory_file(get_room_dir(_ROOM), part.key)
    assert found is not None
    assert assignments.settled(found[0], datetime.now(UTC))


@pytest.mark.asyncio
async def test_a_split_is_wrapped_up_once(monkeypatch: pytest.MonkeyPatch):
    _register("agent-1")
    parent, _pe = await _task("Ship it")
    only = await tasks.create_task(
        _ROOM, "The only part", created_by="agent-1", meta={"part-of": parent}
    )
    await assignments.resolve(_ROOM, only.key, "agent-1", datetime.now(UTC))
    seen = _patch_pi(monkeypatch, "Here is the whole.", "Here is the whole, again.")
    engine, _managed, _manager = _engine()

    engine.handle_notice(_ROOM, {"subkind": "resolved", "key": only.key})
    engine.handle_notice(_ROOM, {"subkind": "resolved", "key": only.key})
    await _settle(engine)

    assert len(seen) == 1


@pytest.mark.asyncio
async def test_a_part_resolved_by_its_reviewer_keeps_the_holders_final_version(
    monkeypatch: pytest.MonkeyPatch,
):
    from app.services.filesystem import EPISODE_META, system_meta
    from app.services.in_memory_store import StoredMessage

    for h in ("agent-1", "agent-2"):
        _register(h)
    parent, _pe = await _task("The whole")
    part = await tasks.create_task(
        _ROOM,
        "Setup section",
        created_by="agent-1",
        meta={"part-of": parent, "assignee": "agent-2"},
    )
    await assignments.claim(_ROOM, part.key, "agent-2", 30, datetime.now(UTC))
    said = [
        StoredMessage("agent-2", "broadcast", "Setup v1", episode=part.episode),
        StoredMessage("agent-2", "broadcast", "Setup v2: npm ci", episode=part.episode),
    ]
    monkeypatch.setattr("app.services.persister.prose_messages", lambda _room: said)
    _patch_pi(monkeypatch, "Good to go.\n[[done]]")
    engine, _managed, _manager = _engine()

    await engine.turn(_ROOM, "agent-1", episode=str(part.episode), ask="Review it.")

    found = read_memory_file(get_room_dir(_ROOM), part.key)
    assert found is not None
    meta, body = found
    assert body.startswith("Setup section")
    assert "Setup v2: npm ci" in body
    assert "Good to go" not in body
    # The row is still the same row: resolved, part of its parent, on its thread.
    assert assignments.settled(meta, datetime.now(UTC))
    assert meta.get("part-of") == parent
    assert system_meta(meta).get(EPISODE_META) == part.episode


@pytest.mark.asyncio
async def test_the_parent_keeps_the_leads_combined_result(monkeypatch: pytest.MonkeyPatch):
    _register("agent-1")
    parent, episode = await _task("Write the guide")
    _patch_pi(monkeypatch, "# The guide\n\nAll of it, together.\n[[done]]")
    engine, _managed, _manager = _engine()

    await engine.turn(_ROOM, "agent-1", episode=episode, ask="Put it together.")

    found = read_memory_file(get_room_dir(_ROOM), parent)
    assert found is not None
    meta, body = found
    assert body.splitlines()[0] == "Write the guide"
    assert "All of it, together." in body
    assert assignments.settled(meta, datetime.now(UTC))


def test_a_title_written_as_a_key_is_filed_in_words():
    assert worker_engine.task_title("work/draft-template-structure") == "Draft template structure"
    assert worker_engine.task_title("`write_guidance_text`") == "Write guidance text"
    assert worker_engine.task_title("Reproduce the flake") == "Reproduce the flake"
    assert worker_engine.task_title("  'fix CI-only tests'  ") == "fix CI-only tests"
    actions, _prose = worker_engine.parse_actions("[[new: work/create-sample -> @agent-3]]")
    assert actions == [worker_engine.Action("new", "Create sample", "agent-3")]


def test_review_goes_round_a_ring_of_workers():
    for h in ("agent-1", "agent-2", "agent-3"):
        _register(h)
    _register("conductor", "conductor")
    _register("julia-laptop", None, adapter="claude_code")
    assert worker_engine.reviewer_for(_ROOM, "agent-1") == "agent-2"
    assert worker_engine.reviewer_for(_ROOM, "agent-3") == "agent-1"
    assert worker_engine.reviewer_for(_ROOM, "julia-laptop") is None


def test_a_lone_worker_has_no_reviewer():
    _register("agent-1")
    assert worker_engine.reviewer_for(_ROOM, "agent-1") is None


@pytest.mark.asyncio
async def test_work_that_asks_nobody_to_review_it_is_put_to_its_reviewer(
    monkeypatch: pytest.MonkeyPatch,
):
    # The fifth live run: a worker answered its task with a question for no
    # one, nobody heard, and the row sat held for good.
    for h in ("agent-1", "agent-2"):
        _register(h)
    key, episode = await _task("New features", assignee="agent-2")
    seen = _patch_pi(
        monkeypatch,
        "I don't have the changelog, so here is a draft with placeholders: [feature].",
        "Placeholders are clear. Good enough.\n[[done]]",
    )
    engine, _managed, _manager = _engine()

    engine.handle_notice(
        _ROOM, {"subkind": "filed", "key": key, "episode": episode, "for": "agent-2"}
    )
    await _settle(engine)
    await _settle(engine)

    assert [s["handle"] for s in seen] == ["agent-2", "agent-1"]
    assert "ask @agent-1 to review it" in seen[0]["prompt"]
    assert "you are its reviewer" in seen[1]["prompt"]
    found = read_memory_file(get_room_dir(_ROOM), key)
    assert found is not None
    assert assignments.settled(found[0], datetime.now(UTC))


@pytest.mark.asyncio
async def test_work_that_asks_its_reviewer_is_left_to_the_mention(monkeypatch: pytest.MonkeyPatch):
    for h in ("agent-1", "agent-2"):
        _register(h)
    key, episode = await _task("New features", assignee="agent-2")
    seen = _patch_pi(monkeypatch, "Here it is. @agent-1 can you check the list?")
    engine, _managed, _manager = _engine()

    engine.handle_notice(
        _ROOM, {"subkind": "filed", "key": key, "episode": episode, "for": "agent-2"}
    )
    await _settle(engine)

    # The fake channel fires no summons, so only the work turn itself ran.
    assert [s["handle"] for s in seen] == ["agent-2"]
