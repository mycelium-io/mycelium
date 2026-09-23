# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A server-side swarm, end to end: kickoff, split, work, review, wrap-up.

The real conductor and real workers over a loopback channel, with only the
Pi turn scripted. The channel records every post into the transcript and fires
the persister's two seams (a mention is a summon, a turn that names nobody is
addressed), and board notices reach the workers through the manager's notice
hook, as they do in the app. What this holds is that the pieces meet: the
conductor's check-in and split are answered by workers, the split files rows
the workers pick up, each part is reviewed by another member before it
resolves, and the lead resolves the task once the last part is in.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from typing import Any

import pytest
import yaml

from app.services import assignments, conductor, room_channels, tasks, worker_engine
from app.services.filesystem import (
    get_room_dir,
    list_memory_files,
    read_memory_file,
    write_memory_file,
)
from app.services.l9_slim import serialize_content
from app.services.persister import (
    envelope_recipients,
    find_summons,
    is_addressed_turn,
    record_from,
)
from tests.fakes import FakeChannel, FakeManaged, FakeManager, FakePersister

ROOM = "swarm-flow"
TEAM = ["agent-1", "agent-2", "agent-3"]


class Loopback(FakeManaged):
    """A channel whose posts land in the transcript and fire the persister's seams."""

    worker: worker_engine.WorkerEngine | None = None

    async def post(self, envelope: Any, text: str, **kwargs: Any) -> None:
        await super().post(envelope, text, **kwargs)
        content = serialize_content(envelope, extra={"content": text})
        self.persister.log.record(record_from(envelope, content), delivered_to=set())
        assert self.worker is not None
        summons = find_summons(content)
        for handle in summons:
            self.worker.handle_summon(ROOM, handle, envelope, summons, text)
        if is_addressed_turn(envelope):
            for handle in envelope_recipients(envelope):
                if handle not in summons:
                    self.worker.handle_addressed(ROOM, handle, envelope, text)


class Manager(FakeManager):
    def enqueue_herdr_wakes_for_mentions(self, *_a: Any, **_k: Any) -> list[str]:
        return []

    async def raise_ping(self, *_a: Any, **_k: Any) -> None:
        return None


def _who_reviews(handle: str) -> str:
    return TEAM[(TEAM.index(handle) + 1) % len(TEAM)]


def _pi(room: str, handle: str, prompt: str, system: str, _t: float) -> str:
    """A scripted teammate: what each kind of turn says back."""
    ask = prompt.rsplit("\n\n", 1)[-1] if "said to you" not in prompt else prompt
    if "check-in" in prompt and "Check in" in prompt:
        return f"Here. I'll take part {TEAM.index(handle) + 1}."
    if "You are the lead" in prompt:
        return "Split three ways.\n" + "\n".join(
            f"[[new: Part {i + 1} -> @{h}]]" for i, h in enumerate(TEAM)
        )
    if "is yours" in ask:
        part = re.search(r"'(Part \d)'", ask)
        return (
            f"{part.group(1) if part else 'It'} is done. @{_who_reviews(handle)} can you check it?"
        )
    if "Every part of" in ask:
        return "All three parts are in; here is the whole.\n[[done]]"
    if "can you check it?" in prompt:
        return "Checked, it holds up.\n[[done]]"
    return "Noted."


@pytest.fixture(autouse=True)
def _setup(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "ENGINE_RUNTIME", "backend")
    monkeypatch.setattr("app.routes.memory.embed_text", lambda _text: [0.0])
    monkeypatch.setattr(worker_engine, "_pi_complete", _pi)
    room_dir = get_room_dir(ROOM)
    for handle, kind in [("conductor", "conductor"), *((h, "worker") for h in TEAM)]:
        write_memory_file(
            room_dir,
            f"agents/{handle}",
            yaml.safe_dump({"adapter": "engine", "kind": kind}),
            created_by="julia",
        )


async def _until(check, timeout: float = 5.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not check():
        if loop.time() > deadline:
            raise AssertionError("the swarm did not get there in time")
        await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_a_team_kicks_off_splits_reviews_and_wraps_up(monkeypatch: pytest.MonkeyPatch):
    persister = FakePersister()
    managed = Loopback(ROOM, "mycelium", FakeChannel(), persister)
    manager = Manager(managed, [])
    worker = worker_engine.WorkerEngine(manager)  # type: ignore[arg-type]
    managed.worker = worker
    monkeypatch.setattr(room_channels.manager, "on_notice", worker.handle_notice)
    engine = conductor.ConductorEngine(
        manager,  # type: ignore[arg-type]
        handle="conductor",
        step_timeout_s=2.0,
        poll_interval_s=0.01,
    )
    root = await tasks.create_task(ROOM, "Fix the flaky auth tests", created_by="julia")

    outcome = await engine.run(
        ROOM,
        episode=str(root.episode),
        directive="swarm @agent-1 @agent-2 @agent-3: fix the flaky auth tests",
        named=TEAM,
    )
    assert outcome == "resolved"

    def root_settled() -> bool:
        found = read_memory_file(get_room_dir(ROOM), root.key)
        return found is not None and assignments.settled(found[0], datetime.now(UTC))

    await _until(root_settled)

    said = [
        (r.sender, r.content.get("content", "")) for r in persister.log.records if r.sender in TEAM
    ]
    # Everyone checked in, in order, before anything else was said.
    assert [s for s, _t in said[:3]] == TEAM
    assert all("I'll take part" in t for _s, t in said[:3])
    # The lead's split filed one part per member, each claimed by its member
    # and resolved by a different one: the reviewer.
    parts = [
        (key, meta)
        for key, meta, _b in list_memory_files(get_room_dir(ROOM), prefix="work/")
        if meta.get(assignments.PARENT_RELATION) == root.key
    ]
    assert sorted(meta[tasks.ASSIGNEE_FIELD] for _k, meta in parts) == TEAM
    for _key, meta in parts:
        assert meta.get("owner") == f"@{meta[tasks.ASSIGNEE_FIELD]}"
        assert meta.get("assignment_note_by") == _who_reviews(meta[tasks.ASSIGNEE_FIELD])
    # Each part was asked to be reviewed by name, and the lead had the last word.
    assert sum("can you check it?" in t for _s, t in said) == 3
    assert said[-1] == ("agent-1", "All three parts are in; here is the whole.")
    found = read_memory_file(get_room_dir(ROOM), root.key)
    assert found is not None
    assert found[0].get("assignment_note_by") == "agent-1"
