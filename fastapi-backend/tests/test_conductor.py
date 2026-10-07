# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The conductor: a protocol walked in code, the floor moving with each step.

Node-free and model-free. A scripted channel answers each step the way a
member would — through the transcript, as a reply in the run's thread — so
the tests hold the whole contract: who gets the floor when, which edge a
stance takes, what the record says, and where the run happens.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
import yaml

from app.services import conductor, l9, protocols
from app.services.filesystem import (
    get_room_dir,
    list_memory_files,
    read_memory_file,
    write_memory_file,
)
from app.services.l9_models import Kind
from app.services.l9_slim import serialize_content
from app.services.persister import record_from
from tests.fakes import FakeManaged, FakeManager, FakePersister

ROOM = "conducted"
THREAD = l9.episode_urn(ROOM, "t3aa11bb")
LIVE = l9.live_episode_urn(ROOM)


def _reply(
    handle: str,
    prose: str,
    *,
    episode: str,
    action: str | dict[str, Any] | None,
    role: str = "agent",
):
    """A member's reply as the transcript records it. ``action`` is a stance, or
    a whole payload as the reply route lifts one off a marker."""
    if isinstance(action, dict):
        data = action
    else:
        data = {"action": action} if action else {"note": "no stance"}
    env = l9.build_envelope(
        kind=Kind.exchange,
        episode=episode,
        sender=handle,
        sender_role=role,
        recipients=["conductor"],
        topic=l9.topic_urn(ROOM),
        payload_type="reply",
        payload_data=data,
    )
    return record_from(env, serialize_content(env, extra={"content": prose}))


class ScriptedChannel:
    """Answers each tick from a per-handle script; an exhausted script is silence.

    A script entry is ``(prose, action)`` or ``(prose, action, role)``; the
    reply lands in the tick's own episode, as a real member's would.
    """

    def __init__(self, persister: FakePersister, script: dict[str, list[tuple]]) -> None:
        self.sent: list[tuple[Any, dict[str, Any] | None]] = []
        self._persister = persister
        self._script = {h: list(entries) for h, entries in script.items()}
        self.stray: dict[str, list[Any]] = {}

    async def send(self, envelope: Any, *, extra: dict[str, Any] | None = None) -> None:
        self.sent.append((envelope, extra))
        if envelope.header.kind != Kind.exchange or "step" not in (envelope.payload.data or {}):
            return
        episode = envelope.header.message.episode
        for actor in envelope.header.participants.actors[1:]:
            entries = self._script.get(actor.id) or []
            if not entries:
                continue
            prose, action, *rest = entries.pop(0)
            role = rest[0] if rest else "agent"
            self._persister.log.record(
                _reply(actor.id, prose, episode=episode, action=action, role=role),
                delivered_to=set(),
            )

    def ticks(self) -> list[tuple[str, str, str]]:
        """``(step, recipient, prose)`` for every tick, in order."""
        return [
            (
                env.payload.data["step"],
                env.header.participants.actors[1].id,
                (extra or {})["content"],
            )
            for env, extra in self.sent
            if env.header.kind == Kind.exchange and "step" in (env.payload.data or {})
        ]

    def commit(self) -> Any:
        commits = [env for env, _x in self.sent if env.header.kind == Kind.commit]
        assert len(commits) == 1
        return commits[0]

    def said(self) -> list[str]:
        return [
            (extra or {}).get("content", "")
            for env, extra in self.sent
            if env.payload.type == "message"
        ]


def _engine(script: dict[str, list[tuple]], members: list[str] | None = None):
    persister = FakePersister()
    channel = ScriptedChannel(persister, script)
    managed = FakeManaged(ROOM, "mycelium", channel, persister)
    manager = FakeManager(managed, members if members is not None else [])
    engine = conductor.ConductorEngine(
        manager,  # type: ignore[arg-type]
        handle="conductor",
        step_timeout_s=0.05,
        poll_interval_s=0.005,
    )
    return engine, manager, channel


def _register(handle: str, kind: str) -> None:
    write_memory_file(
        get_room_dir(ROOM),
        f"agents/{handle}",
        yaml.safe_dump({"adapter": "engine", "kind": kind}),
        created_by="julia",
    )


def _records() -> list[str]:
    return [key for key, _m, _c in list_memory_files(get_room_dir(ROOM), prefix="log/episodes/")]


@pytest.fixture(autouse=True)
def _backend_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "ENGINE_RUNTIME", "backend")
    # Saving a result writes a memory, which embeds it: stub vectors, as CI
    # does, so no test loads the model.
    from app.services import embedding

    monkeypatch.setattr(embedding, "_STUB", True)
    get_room_dir(ROOM)


# ── reading the summon ────────────────────────────────────────────────────────


def test_the_first_bare_word_names_the_protocol_and_the_rest_is_the_ask():
    assert conductor.split_directive("gated @sec @julia: pick a token store") == (
        "gated",
        "pick a token store",
    )
    assert conductor.split_directive("  @a round-robin — what next?") == (
        "round-robin",
        "what next?",
    )
    assert conductor.split_directive("@a @b") == ("", "")


def test_roles_bind_in_order_and_too_few_is_none():
    gated = protocols.builtin("gated")
    assert gated is not None
    assert conductor.bind_roles(gated, ["api", "sec", "extra"]) == {
        "proposer": "api",
        "guardian": "sec",
    }
    assert conductor.bind_roles(gated, ["api"]) is None


def test_a_steps_stance_is_the_strictest_answer():
    assert conductor.stance_of_step([("a", "accept")]) == "accept"
    assert conductor.stance_of_step([("a", "accept"), ("b", "reject")]) == "reject"
    assert conductor.stance_of_step([("a", "accept"), ("b", None)]) is None
    assert conductor.stance_of_step([("a", "silent"), ("b", "silent")]) == "silent"
    assert conductor.stance_of_step([("a", "silent"), ("b", "accept")]) is None
    assert conductor.stance_of_step([]) is None


# ── the gated protocol: a guardian that blocks sends it back ──────────────────


@pytest.mark.asyncio
async def test_gated_loops_on_a_block_and_ends_on_an_approval():
    engine, manager, channel = _engine(
        {
            "api": [("rotate the key in place", None), ("rotate with a rollback window", None)],
            "sec": [("no rollback plan", "reject"), ("fine with the window", "accept")],
        }
    )

    outcome = await engine.run(
        ROOM,
        episode=THREAD,
        directive="gated @api @sec: rotate the signing key",
        named=["api", "sec"],
    )

    assert outcome == "resolved"
    assert [(s, to) for s, to, _p in channel.ticks()] == [
        ("propose", "api"),
        ("review", "sec"),
        ("propose", "api"),
        ("review", "sec"),
    ]
    # The proposer's second turn carries the objection it has to answer.
    assert "no rollback plan" in channel.ticks()[2][2]
    # The guardian's turns carry the proposal on the table, and no @ sigils.
    assert "rotate the key in place" in channel.ticks()[1][2]
    assert "@" not in channel.ticks()[1][2].replace("[[mycelium", "")
    commit = channel.commit()
    assert commit.header.subkind == "resolved"
    assert commit.payload.data["steps"] == 4
    assert commit.payload.data["roles"] == {"proposer": "api", "guardian": "sec"}


@pytest.mark.asyncio
async def test_the_floor_follows_the_step_and_is_released_at_the_end():
    engine, manager, _channel = _engine(
        {"api": [("do the thing", None)], "sec": [("approved", "accept")]}
    )

    await engine.run(ROOM, episode=THREAD, directive="gated: go", named=["api", "sec"])

    holds = [(f.holder, sorted(f.speakers)) for f in manager.floor_log]
    assert holds == [("conductor", []), ("conductor", ["api"]), ("conductor", ["sec"])]
    assert manager.floors == {}, "the thread is open again once the run ends"


@pytest.mark.asyncio
async def test_a_guardian_that_never_yields_hits_the_cap():
    engine, _manager, channel = _engine({"api": [("v1", None)] * 6, "sec": [("no", "reject")] * 6})

    outcome = await engine.run(ROOM, episode=THREAD, directive="gated: go", named=["api", "sec"])

    assert outcome == "rejected"
    commit = channel.commit()
    assert commit.header.subkind == "rejected"
    assert "step cap" in commit.payload.data["reason"]
    assert commit.payload.data["steps"] == 6


@pytest.mark.asyncio
async def test_a_person_blocks_with_a_marker_left_in_the_prose():
    """A human answers a step through the message route, which strips no
    marker; the stance is read off the text."""
    engine, _manager, channel = _engine(
        {
            "api": [("ship it", None), ("ship it with a canary", None)],
            "julia": [
                ("Not without a canary. [[mycelium: stance=reject]]", None, "human"),
                ("Good. [[mycelium: stance=accept]]", None, "human"),
            ],
        }
    )

    outcome = await engine.run(
        ROOM, episode=THREAD, directive="gated: ship", named=["api", "julia"]
    )

    assert outcome == "resolved"
    assert len(channel.ticks()) == 4


@pytest.mark.asyncio
async def test_silence_takes_the_fallback_edge():
    """A guardian that never answers is neither an approval nor a block: the
    review's fallback edge sends the proposal round again until the cap."""
    engine, _manager, channel = _engine({"api": [("v1", None)] * 6, "sec": []})

    outcome = await engine.run(ROOM, episode=THREAD, directive="gated: go", named=["api", "sec"])

    assert outcome == "rejected"
    assert [s for s, _to, _p in channel.ticks()][:4] == ["propose", "review", "propose", "review"]


@pytest.mark.asyncio
async def test_a_reply_in_the_room_is_not_an_answer_in_the_thread():
    """The addressed member speaking somewhere else is not its turn here."""
    engine, _manager, channel = _engine({"api": [("v1", None)], "sec": []})
    # The guardian talks in the room before and during the run; none of it counts.
    channel._persister.log.record(
        _reply("sec", "approved!", episode=LIVE, action="accept"), delivered_to=set()
    )

    outcome = await engine.run(ROOM, episode=THREAD, directive="gated: go", named=["api", "sec"])

    assert outcome == "rejected"


# ── fan-out and round-robin ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fan_out_asks_the_workers_at_once_then_the_lead():
    engine, manager, channel = _engine(
        {
            "brazil": [("40 bags, ready Monday", None)],
            "colombia": [("25 bags, weather permitting", None)],
            "exchange": [("Brazil ships Monday, Colombia follows.", None)],
        }
    )

    outcome = await engine.run(
        ROOM,
        episode=THREAD,
        directive="fan-out @exchange @brazil @colombia: fill the 60-bag order",
        named=["exchange", "brazil", "colombia"],
    )

    assert outcome == "resolved"
    ticks = channel.ticks()
    assert [(s, to) for s, to, _p in ticks] == [
        ("gather", "brazil"),
        ("gather", "colombia"),
        ("combine", "exchange"),
    ]
    # One floor for the whole fan-out, both workers on it; then the lead alone.
    assert [sorted(f.speakers) for f in manager.floor_log] == [
        [],
        ["brazil", "colombia"],
        ["exchange"],
    ]
    assert "brazil: 40 bags" in ticks[2][2]
    assert "colombia: 25 bags" in ticks[2][2]
    assert channel.commit().payload.data["steps"] == 2


@pytest.mark.asyncio
async def test_round_robin_gives_everyone_the_floor_in_turn_each_round():
    engine, manager, channel = _engine(
        {
            "a": [("a1", None), ("a2", None)],
            "b": [("b1", None), ("b2", None)],
            "c": [("c1", None), ("c2", None)],
        }
    )

    outcome = await engine.run(
        ROOM, episode=THREAD, directive="round-robin: where next?", named=["a", "b", "c"]
    )

    assert outcome == "resolved"
    assert [to for _s, to, _p in channel.ticks()] == ["a", "b", "c", "a", "b", "c"]
    # The second speaker in round one hears the first; everyone in round two
    # hears the whole first round.
    assert "a: a1" in channel.ticks()[1][2]
    assert "c: c1" in channel.ticks()[3][2] and "Round 2 of 2" in channel.ticks()[3][2]
    assert [sorted(f.speakers) for f in manager.floor_log][1:] == [["a"], ["b"], ["c"]] * 2
    # One step, however many members it turned through.
    assert channel.commit().payload.data["steps"] == 1


@pytest.mark.asyncio
async def test_with_nobody_named_the_room_takes_part():
    engine, _manager, channel = _engine(
        {"a": [("a1", None), ("a2", None)], "b": [("b1", None), ("b2", None)]},
        members=["conductor", "a", "b"],
    )

    outcome = await engine.run(ROOM, episode=THREAD, directive="round-robin: go")

    assert outcome == "resolved"
    assert [to for _s, to, _p in channel.ticks()] == ["a", "b", "a", "b"]


@pytest.mark.asyncio
async def test_swarm_checks_everyone_in_then_the_lead_splits_the_task(
    monkeypatch: pytest.MonkeyPatch,
):
    from app.services import tasks

    monkeypatch.setattr("app.routes.memory.embed_text", lambda _text: [0.0])
    row = await tasks.create_task(ROOM, "Fix the flaky auth tests", created_by="julia")
    engine, manager, channel = _engine(
        {
            "agent-1": [("I'll take the repro.", None), ("Split: repro, cause, fix.", None)],
            "agent-2": [("Root cause is mine.", None)],
            "agent-3": [("I'll write the fix.", None)],
        }
    )

    outcome = await engine.run(
        ROOM,
        episode=str(row.episode),
        directive="swarm @agent-1 @agent-2 @agent-3: fix the flaky auth tests",
        named=["agent-1", "agent-2", "agent-3"],
    )

    assert outcome == "resolved"
    ticks = channel.ticks()
    assert [(s, to) for s, to, _p in ticks] == [
        ("check-in", "agent-1"),
        ("check-in", "agent-2"),
        ("check-in", "agent-3"),
        ("split", "agent-1"),
    ]
    # Each check-in names the row, so a member can file under it; each hears
    # the ones before it; the lead's split carries every check-in.
    assert row.key in ticks[0][2]
    assert "agent-1: I'll take the repro." in ticks[1][2]
    assert "agent-3: I'll write the fix." in ticks[3][2]
    assert f"child tasks of {row.key}" in ticks[3][2]


# ── the record, and what it does not do ───────────────────────────────────────


@pytest.mark.asyncio
async def test_the_record_is_a_nested_episode_carrying_the_flow_and_the_trace():
    from app.services.episode_records import episode_summary, parse_envelopes

    engine, _manager, _channel = _engine(
        {"api": [("v1", None), ("v2", None)], "sec": [("no", "reject"), ("yes", "accept")]}
    )
    before = set(_records())

    outcome = await engine.run(
        ROOM, episode=THREAD, directive="gated: rotate", named=["api", "sec"]
    )

    assert outcome == "resolved"
    new = set(_records()) - before
    assert len(new) == 1, "one record for the run, rewritten as it walked"
    key = new.pop()
    found = read_memory_file(get_room_dir(ROOM), key)
    assert found is not None
    meta, content = found
    summary = episode_summary(key, meta, content)
    assert summary["outcome"] == "resolved"
    assert summary["episode"] == THREAD, "the run's slice is the task's own thread"
    assert summary["within"] == THREAD
    assert summary["current_step"] is None, "a finished run stands nowhere"
    flow = summary["flow"]
    assert flow["name"] == "gated"
    assert flow["bound"] == {"proposer": "api", "guardian": "sec"}
    assert flow["cast"] == ["api", "sec"]
    assert flow["ask"] == "rotate"
    assert [st["id"] for st in flow["steps"]] == ["propose", "review", "approved"]
    assert [(t["step"], t["turn"], t["stance"], t["next"]) for t in summary["trace"]] == [
        ("propose", 1, None, "review"),
        ("review", 2, "reject", "propose"),
        ("propose", 3, None, "review"),
        ("review", 4, "accept", "approved"),
    ]
    assert summary["trace"][1]["stances"] == {"sec": "reject"}
    assert {"api", "sec"} <= set(summary["participants"])
    # Intent, four ticks, four replies, the commit.
    assert len(parse_envelopes(content)) == 10


@pytest.mark.asyncio
async def test_an_open_run_records_where_it_stands():
    """The record is written at the opening and after every step, so the
    episode can be opened while it is still walking."""
    from app.services.episode_records import episode_summary

    seen: list[tuple[str, str | None, int]] = []
    engine, _manager, _channel = _engine({"api": [("v1", None)], "sec": [("yes", "accept")]})
    original = engine._turn

    async def spy(managed, ep, me, run, step, handle, prompt):
        found = read_memory_file(get_room_dir(ROOM), f"log/episodes/{ep.short_id}")
        assert found is not None
        summary = episode_summary(f"log/episodes/{ep.short_id}", *found)
        seen.append((summary["outcome"], summary["current_step"], len(summary["trace"])))
        return await original(managed, ep, me, run, step, handle, prompt)

    engine._turn = spy
    await engine.run(ROOM, episode=THREAD, directive="gated: go", named=["api", "sec"])

    assert seen == [("open", "propose", 0), ("open", "review", 1)]


@pytest.mark.asyncio
async def test_it_opens_no_negotiation_and_never_converges():
    """A protocol run is not a negotiation: nothing freezes, and nothing it
    commits compiles into tasks."""
    engine, manager, channel = _engine(
        {"api": [("do the thing", None)], "sec": [("approved", "accept")]}
    )

    await engine.run(ROOM, episode=THREAD, directive="gated: go", named=["api", "sec"])

    assert manager.opened == []
    assert channel.commit().header.subkind != "converged"


# ── refusing to start ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_unknown_protocol_is_answered_where_it_was_asked():
    engine, manager, channel = _engine({})

    outcome = await engine.run(ROOM, episode=LIVE, directive="waltz @a @b: go", named=["a", "b"])

    assert outcome is None
    assert manager.floor_log == []
    said = channel.said()
    assert len(said) == 1
    assert "gated" in said[0] and "round-robin" in said[0]
    assert channel.sent[0][0].header.message.episode == LIVE


@pytest.mark.asyncio
async def test_too_few_members_is_said_plainly():
    engine, _manager, channel = _engine({})

    outcome = await engine.run(ROOM, episode=THREAD, directive="gated @api: go", named=["api"])

    assert outcome is None
    assert "proposer, guardian" in channel.said()[0]
    assert "1 were named" in channel.said()[0]


@pytest.mark.asyncio
async def test_a_rooms_own_protocol_runs_under_its_name():
    write_memory_file(
        get_room_dir(ROOM),
        "protocols/nudge",
        yaml.safe_dump(
            {
                "roles": ["who"],
                "steps": [
                    {"id": "ask", "to": "who", "prompt": "{ask}", "wait": "none", "next": "done"},
                    {"id": "done", "end": "resolved"},
                ],
            }
        ),
        created_by="julia",
    )
    engine, manager, channel = _engine({})

    outcome = await engine.run(
        ROOM, episode=THREAD, directive="nudge @api: look at #12", named=["api"]
    )

    assert outcome == "resolved"
    assert [(s, to) for s, to, _p in channel.ticks()] == [("ask", "api")]
    assert channel.ticks()[0][2].endswith("\n\nlook at #12")
    # Fire-and-forget gives nobody the floor and waits on nothing.
    assert [sorted(f.speakers) for f in manager.floor_log] == [[], []]


# ── the summon seam ───────────────────────────────────────────────────────────


def _summon(text: str, *, episode: str, sender: str = "julia") -> Any:
    from app.services.persister import find_summons

    env = l9.build_envelope(
        kind=Kind.exchange,
        episode=episode,
        sender=sender,
        sender_role="human",
        topic=l9.topic_urn(ROOM),
        payload_type="message",
    )
    return env, find_summons({"content": text}), text


@pytest.mark.asyncio
async def test_a_summon_from_a_task_walks_in_the_tasks_own_thread():
    """A task is one row and one thread: the run walks in that thread, and its
    record is a nested episode that says which thread it ran within."""
    from app.services.episode_records import episode_summary

    _register("conductor", "conductor")
    engine, _manager, channel = _engine(
        {"api": [("do the thing", None)], "sec": [("approved", "accept")]}
    )
    before = set(_records())
    env, summons, text = _summon("@conductor gated @api @sec: rotate the key", episode=THREAD)

    engine.handle_summon(ROOM, "conductor", env, summons, text)
    await asyncio.sleep(0.1)

    commit = channel.commit()
    assert commit.header.message.episode == THREAD
    assert commit.payload.data["roles"] == {"proposer": "api", "guardian": "sec"}
    assert {e.header.message.episode for e, _x in channel.sent} == {THREAD}, (
        "nothing opens elsewhere"
    )
    (key,) = set(_records()) - before
    assert commit.payload.data["record"] == key
    found = read_memory_file(get_room_dir(ROOM), key)
    assert found is not None
    summary = episode_summary(key, *found)
    assert summary["episode"] == THREAD
    assert summary["within"] == THREAD
    in_task = [
        (extra or {})["content"]
        for e, extra in channel.sent
        if e.header.message.episode == THREAD and e.payload.type == "message"
    ]
    assert in_task[0].startswith("Running gated with api as proposer, sec as guardian.")
    said = [
        (extra or {}).get("content", "")
        for e, extra in channel.sent
        if e.header.kind == Kind.commit
    ]
    assert said[0].startswith("✓ gated: resolved after 2 step(s)")
    assert said[0].endswith(f"Record: {key}.")


@pytest.mark.asyncio
async def test_a_summon_from_the_room_is_refused_and_says_to_use_a_task():
    """The room never holds a floor and a run belongs to a row, so a summon
    from the room is answered there with how to do it, and nothing runs."""
    _register("conductor", "conductor")
    engine, manager, channel = _engine(
        {"api": [("do the thing", None)], "sec": [("approved", "accept")]}
    )
    before = set(_records())
    env, summons, text = _summon("@conductor gated @api @sec: rotate the key", episode=LIVE)

    engine.handle_summon(ROOM, "conductor", env, summons, text)
    await asyncio.sleep(0.1)

    assert [e for e, _x in channel.sent if e.header.kind == Kind.commit] == []
    assert manager.floor_log == [], "the room holds no floor"
    assert set(_records()) == before
    said = channel.said()[0]
    assert "A run needs a task" in said and "board coordinate <row> conductor" in said
    assert channel.sent[0][0].header.message.episode == LIVE


@pytest.mark.asyncio
async def test_only_a_conductor_manifest_fires():
    _register("mediator", "aligner")
    engine, _manager, channel = _engine({})
    env, summons, text = _summon("@mediator gated @api @sec: go", episode=THREAD)

    engine.handle_summon(ROOM, "mediator", env, summons, text)
    engine.handle_summon(ROOM, "ghost", env, summons, text)
    await asyncio.sleep(0.05)

    assert channel.sent == []


@pytest.mark.asyncio
async def test_a_re_summon_into_a_running_thread_is_ignored():
    _register("conductor", "conductor")
    engine, _manager, channel = _engine({"api": [("v1", None)], "sec": []})
    env, summons, text = _summon("@conductor gated @api @sec: go", episode=THREAD)

    engine.handle_summon(ROOM, "conductor", env, summons, text)
    await asyncio.sleep(0.01)
    engine.handle_summon(ROOM, "conductor", env, summons, text)

    def commits() -> int:
        return len([e for e, _x in channel.sent if e.header.kind == Kind.commit])

    # Wait for the run to finish rather than a fixed time a slow runner can miss.
    for _ in range(500):
        if commits():
            break
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.1)  # time for a second run to commit, were there one
    assert commits() == 1


# ── legible from the outside ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_run_opens_by_saying_who_plays_what_and_the_graph():
    engine, _manager, channel = _engine(
        {"api": [("do the thing", None)], "sec": [("approved", "accept")]}
    )

    await engine.run(ROOM, episode=THREAD, directive="gated: rotate", named=["api", "sec"])

    opening = channel.said()[0]
    assert opening.startswith("Running gated with api as proposer, sec as guardian.")
    assert "propose: asks proposer, then review" in opening
    assert "review: asks guardian, then by stance (accept: approved, reject: propose" in opening
    assert "approved: ends resolved" in opening
    assert "up to 6 steps" in opening


@pytest.mark.asyncio
async def test_every_turn_says_which_step_of_which_protocol_it_is():
    engine, _manager, channel = _engine(
        {"api": [("v1", None), ("v2", None)], "sec": [("no", "reject"), ("yes", "accept")]}
    )

    await engine.run(ROOM, episode=THREAD, directive="gated: go", named=["api", "sec"])

    heads = [p.split("\n", 1)[0] for _s, _to, p in channel.ticks()]
    assert heads == [
        "gated · propose · turn 1 of 6 · api",
        "gated · review · turn 2 of 6 · sec",
        "gated · propose · turn 3 of 6 · api",
        "gated · review · turn 4 of 6 · sec",
    ]


@pytest.mark.asyncio
async def test_a_branch_taken_is_said_in_the_thread_and_a_plain_edge_is_not():
    engine, _manager, channel = _engine(
        {"api": [("v1", None), ("v2", None)], "sec": [("no", "reject"), ("yes", "accept")]}
    )

    await engine.run(ROOM, episode=THREAD, directive="gated: go", named=["api", "sec"])

    lines = [t for t in channel.said() if t.startswith("review:")]
    assert lines == ["review: sec blocked, on to propose", "review: sec accepted, on to approved"]
    assert not any(t.startswith("propose:") for t in channel.said())


@pytest.mark.asyncio
async def test_list_says_what_it_can_run():
    engine, manager, channel = _engine({})

    outcome = await engine.run(ROOM, episode=LIVE, directive="list")

    assert outcome is None
    assert manager.floor_log == []
    said = channel.said()[0]
    for name in protocols.builtin_names():
        assert f"**{name}**" in said
    assert "(built in)" in said
    assert channel.sent[0][0].header.message.episode == LIVE


@pytest.mark.asyncio
async def test_a_turn_is_posted_as_a_message_so_the_thread_shows_it():
    """A turn's prose (its ``flow · step · turn`` head and the prompt) is a
    ``message`` in the transcript, the payload the conversational read keeps,
    not a ``tick`` it drops — so a person reading the thread sees each ask."""
    engine, _manager, channel = _engine(
        {"api": [("I will rotate it at noon.", None)], "sec": [("fine", "accept")]}
    )

    await engine.run(
        ROOM, episode=THREAD, directive="gated @api @sec: rotate", named=["api", "sec"]
    )

    turns = [
        env
        for env, _x in channel.sent
        if env.header.kind == Kind.exchange and "step" in env.payload.data
    ]
    assert turns
    assert {env.payload.type for env in turns} == {"message"}


@pytest.mark.asyncio
async def test_show_says_one_flow_as_yaml_to_save_under_protocols():
    engine, manager, channel = _engine({})

    outcome = await engine.run(ROOM, episode=LIVE, directive="show gated")

    assert outcome is None
    assert manager.floor_log == []
    said = channel.said()[0]
    assert "Save this as `protocols/gated`" in said
    assert "```yaml" in said
    assert "roles:" in said and "- proposer" in said
    assert "id: review" in said

    await engine.run(ROOM, episode=LIVE, directive="show nope")
    assert "I know no flow called `nope`" in channel.said()[1]


@pytest.mark.asyncio
async def test_the_floor_is_held_the_instant_the_summon_lands():
    """Before anything else on the loop runs — so a member the summon woke,
    or a persona mentioned as a role, cannot slip a reply in first."""
    _register("conductor", "conductor")
    engine, manager, channel = _engine(
        {"api": [("do the thing", None)], "sec": [("approved", "accept")]}
    )
    env, summons, text = _summon("@conductor gated @api @sec: rotate the key", episode=THREAD)

    engine.handle_summon(ROOM, "conductor", env, summons, text)

    assert len(manager.floors) == 1
    ((held_on, held),) = manager.floors.items()
    assert held_on == THREAD
    assert held.holder == "conductor"
    assert not held.admits("api") and not held.admits("sec")
    await asyncio.sleep(0.1)
    assert manager.floors == {}, "released once the run ends"
    assert channel.commit().header.message.episode == THREAD


@pytest.mark.asyncio
async def test_a_summon_that_cannot_start_lets_the_floor_go():
    _register("conductor", "conductor")
    engine, manager, channel = _engine({})
    env, summons, text = _summon("@conductor waltz @api @sec: go", episode=THREAD)

    engine.handle_summon(ROOM, "conductor", env, summons, text)
    assert len(manager.floors) == 1
    await asyncio.sleep(0.05)

    assert manager.floors == {}
    assert "Built in:" in channel.said()[0]
    assert channel.sent[0][0].header.message.episode == THREAD, "answered where it was asked"


# ── the structured line every post carries ────────────────────────────────────


def _lines(channel: ScriptedChannel) -> list[dict[str, Any]]:
    return [
        (env.payload.data or {})[conductor.LINE_KEY]
        for env, _x in channel.sent
        if conductor.LINE_KEY in (env.payload.data or {})
    ]


@pytest.mark.asyncio
async def test_every_post_of_a_run_carries_a_line_a_surface_can_draw():
    """The text is what members read; the line is what the app draws instead."""
    engine, _manager, channel = _engine(
        {
            "api": [("rotate in place", None), ("with a window", None)],
            "sec": [("no rollback", "reject"), ("fine", "accept")],
        }
    )

    await engine.run(ROOM, episode=THREAD, directive="gated: rotate the key", named=["api", "sec"])

    lines = _lines(channel)
    assert [ln["event"] for ln in lines] == [
        "open",
        "turn",
        "turn",
        "edge",
        "turn",
        "turn",
        "edge",
        "close",
    ]
    opening, first = lines[0], lines[1]
    assert opening["protocol"] == "gated"
    assert opening["roles"] == {"proposer": "api", "guardian": "sec"}
    assert [s["id"] for s in opening["steps"]] == ["propose", "review", "approved"]
    assert first == {
        "event": "turn",
        "protocol": "gated",
        "step": "propose",
        "to": "api",
        "turn": 1,
        "cap": 6,
    }
    assert lines[3] == {
        "event": "edge",
        "step": "review",
        "who": "sec",
        "stance": "reject",
        "next": "propose",
    }
    assert lines[-1] == {
        "event": "close",
        "protocol": "gated",
        "outcome": "resolved",
        "steps": 4,
        "reason": "reached `approved`",
    }


def test_a_reload_carries_a_conductor_line_in_the_messages_metadata():
    from app.services.persister import stored_message_from_record

    env = l9.build_envelope(
        kind=Kind.exchange,
        episode=THREAD,
        sender="conductor",
        recipients=["api"],
        topic=l9.topic_urn(ROOM),
        payload_type="message",
        payload_data={conductor.LINE_KEY: {"event": "turn", "step": "propose", "to": "api"}},
    )
    record = record_from(env, serialize_content(env, extra={"content": "gated · propose · …"}))
    msg = stored_message_from_record(ROOM, record)
    assert msg is not None
    assert msg.content == "gated · propose · …"
    assert msg.event_metadata == {"conductor": {"event": "turn", "step": "propose", "to": "api"}}

    plain = _reply("api", "just talking", episode=THREAD, action=None)
    said = stored_message_from_record(ROOM, plain)
    assert said is not None and said.event_metadata is None


# ── concord: suggest, rate, a pick made in code, a fix from the least happy ───

CAST = ["success", "finance", "legal"]
TASK_KEY = "work/acme-renewal"


@pytest.fixture
def in_a_task(monkeypatch: pytest.MonkeyPatch) -> None:
    """The run walks the thread of the row ``TASK_KEY``."""
    monkeypatch.setattr(
        conductor.tasks,
        "row_of_episode",
        lambda room, episode: (TASK_KEY, "Decide the renewal offer") if episode == THREAD else None,
    )


def _concord(script: dict[str, list[tuple]]):
    return _engine(script), f"concord {' '.join('@' + h for h in CAST)}: decide the renewal offer"


def _selects(channel: ScriptedChannel) -> list[dict[str, Any]]:
    return [line["select"] for line in _lines(channel) if line.get("event") == "select"]


@pytest.mark.asyncio
async def test_concord_agrees_the_first_time_everyone_clears_the_bar(in_a_task):
    from app.services.persister import is_converged

    (engine, _manager, channel), directive = _concord(
        {
            "success": [("20% off", None), ("A great, B ok [[mycelium: A=95 B=72]]", None)],
            "finance": [("10% off", None), ("[[mycelium: A=30 B=90]]", None)],
            "legal": [("10% off", None), ("both fine [[mycelium: A=80 B=80]]", None)],
        }
    )

    outcome = await engine.run(ROOM, episode=THREAD, directive=directive, named=CAST)

    assert outcome == "converged"
    assert [(s, to) for s, to, _p in channel.ticks()] == [
        ("propose", "success"),
        ("propose", "finance"),
        ("propose", "legal"),
        ("score", "success"),
        ("score", "finance"),
        ("score", "legal"),
    ]
    # Everyone rated at once, with the options lettered and listed.
    assert "A. 20% off\nB. 10% off" in channel.ticks()[3][2]
    commit = channel.commit()
    assert commit.header.subkind == "converged"
    assert is_converged(commit)
    data = commit.payload.data
    # A conductor run files no rows: nothing on the commit for the compile
    # seam, and the decision is saved to memory instead.
    assert "assignments" not in data
    assert "within" not in data
    assert data["memory"] == "context/decision/acme-renewal"
    assert data["steps"] == 2
    assert data["select"]["pick"] == "B"
    assert data["metrics"]["min_satisfaction"] == 0.72
    said = [(x or {}).get("content", "") for e, x in channel.sent if e.header.kind == Kind.commit]
    assert said[0].startswith("✓ Everyone's on board: going with B: 10% off.")
    assert "The decision is saved as context/decision/acme-renewal." in said[0]
    (card,) = _selects(channel)
    assert card["outcome"] == "feasible"
    assert card["table"]["A"] == {"success": 95, "finance": 30, "legal": 80}


@pytest.mark.asyncio
async def test_concord_asks_only_the_least_happy_for_a_fix_then_everyone_rates_it(in_a_task):
    # B wins the first pick (lowest 50 beats A's 30), with success least happy.
    (engine, manager, channel), directive = _concord(
        {
            "success": [
                ("20% off", None),
                ("[[mycelium: A=95 B=50]]", None),
                ("15% off for a two-year term", None),  # its fix
                ("C works [[mycelium: C=85]]", None),
            ],
            "finance": [
                ("10% off", None),
                ("[[mycelium: A=30 B=90]]", None),
                ("[[mycelium: C=80]]", None),
            ],
            "legal": [
                ("10% off", None),
                ("[[mycelium: A=80 B=80]]", None),
                ("[[mycelium: C=75]]", None),
            ],
        }
    )

    outcome = await engine.run(ROOM, episode=THREAD, directive=directive, named=CAST)

    assert outcome == "converged"
    steps = [(s, to) for s, to, _p in channel.ticks()]
    assert steps[6] == ("repair", "success"), "only the least happy member is asked for a fix"
    assert [to for s, to in steps if s == "rescore"] == CAST
    fix_prompt = channel.ticks()[6][2]
    assert "You rated option B 50; the bar is 70" in fix_prompt
    # The fixer revises the pick, so it sees the pick and every option in full,
    # not just their letters in the table.
    assert "The best option so far for Decide the renewal offer is:\n\nB. 10% off" in fix_prompt
    assert "A. 20% off" in fix_prompt
    rescore_prompt = channel.ticks()[7][2]
    assert "C. 15% off for a two-year term" in rescore_prompt
    assert "A. 20% off" not in rescore_prompt, "only the new option is put to a rating"
    assert "[[mycelium: C=..]]" in rescore_prompt
    commit = channel.commit()
    assert commit.payload.data["select"]["text"] == "15% off for a two-year term"
    said = [(x or {}).get("content", "") for e, x in channel.sent if e.header.kind == Kind.commit]
    assert "success went from 50 to 85." in said[0]
    # The conductor talks about members, never to them: a mention in a post
    # would summon them mid-run.
    posted = [
        (x or {}).get("content", "")
        for e, x in channel.sent
        if "step" not in (e.payload.data or {})
    ]
    assert not any("@" in text for text in posted)
    assert [c["outcome"] for c in _selects(channel)] == ["infeasible", "feasible"]
    # The fix step held the floor for the fixer alone.
    assert ["success"] in [sorted(f.speakers) for f in manager.floor_log]


@pytest.mark.asyncio
async def test_concord_stops_after_two_fixes_and_says_who_is_still_short(in_a_task):
    # finance hates everything, including its own fixes, so it stays least happy.
    hates = ("[[mycelium: A=10 B=10 C=10 D=10]]", None)
    likes = ("[[mycelium: A=90 B=90 C=90 D=90]]", None)
    (engine, _manager, channel), directive = _concord(
        {
            "success": [("A text", None), likes, likes, likes],
            "finance": [
                ("B text", None),
                hates,
                ("fix one", None),
                hates,
                ("fix two", None),
                hates,
            ],
            "legal": [("A text", None), likes, likes, likes],
        }
    )

    outcome = await engine.run(ROOM, episode=THREAD, directive=directive, named=CAST)

    assert outcome == "rejected"
    assert [s for s, _to, _p in channel.ticks()].count("repair") == 2
    assert [c["outcome"] for c in _selects(channel)] == ["infeasible", "infeasible", "stuck"]
    commit = channel.commit()
    assert commit.header.subkind == "rejected"
    assert "assignments" not in commit.payload.data
    assert "memory" not in commit.payload.data, "only an agreement is saved"
    said = [(x or {}).get("content", "") for e, x in channel.sent if e.header.kind == Kind.commit]
    assert said[0].startswith("✗ Couldn't get everyone there. Best was")
    assert "finance at 10" in said[0]


@pytest.mark.asyncio
async def test_concord_re_asks_a_reply_without_ratings_once_and_never_asks_the_silent(in_a_task):
    (engine, manager, channel), directive = _concord(
        {
            "success": [
                ("A text", None),
                ("A is best, honestly", None),
                ("[[mycelium: A=90 B=80]]", None),
            ],
            "finance": [("B text", None), ("[[mycelium: A=75 B=90]]", None)],
            "legal": [("A text", None)],  # suggests, then goes quiet
        }
    )

    outcome = await engine.run(ROOM, episode=THREAD, directive=directive, named=CAST)

    ticks = [(s, to) for s, to, _p in channel.ticks()]
    again = ticks[6:]
    assert again == [("score", "success")], "one re-ask, to the member who replied without ratings"
    reask = channel.ticks()[6][2]
    assert "I couldn't read your ratings" in reask
    # The re-ask says what it wants rated, since it arrives on its own.
    assert "A. A text" in reask and "[[mycelium: A=.. B=..]]" in reask
    assert ["success"] in [sorted(f.speakers) for f in manager.floor_log]
    # legal never rated: missing, not zero, and a fix can't reach it.
    (card,) = _selects(channel)
    assert card["missing"] == ["legal"]
    assert "legal" not in card["ratings"]
    assert card["outcome"] == "stuck"
    assert outcome == "rejected"
    said = [(x or {}).get("content", "") for e, x in channel.sent if e.header.kind == Kind.commit]
    assert "no rating from legal" in said[0]


@pytest.mark.asyncio
async def test_a_fix_that_adds_nothing_skips_the_rating_round(in_a_task):
    """A silent fixer leaves nothing new to rate: nobody is asked to rate "(none)"."""
    likes = ("[[mycelium: A=90 B=90]]", None)
    (engine, _manager, channel), directive = _concord(
        {
            "success": [("A text", None), likes],
            "finance": [("B text", None), ("[[mycelium: A=30 B=30]]", None)],  # then silent
            "legal": [("A text", None), likes],
        }
    )

    outcome = await engine.run(ROOM, episode=THREAD, directive=directive, named=CAST)

    steps = [s for s, _to, _p in channel.ticks()]
    assert "rescore" not in steps
    assert steps.count("repair") == 2, "the fixes are still bounded"
    assert outcome == "rejected"
    assert not any("(none)" in p for _s, _to, p in channel.ticks())


def test_a_reply_that_is_only_a_marker_is_not_an_option():
    engine, _manager, _channel = _engine({})
    concord = protocols.builtin("concord")
    assert concord is not None
    run = conductor.Run(protocol=concord, ask="", handles=CAST, bound={}, episode=THREAD)
    run.answers = {"success": {}, "finance": {}}
    run.replies = {"success": "[[mycelium: A=95]]", "finance": "Offer 10% off"}
    engine._collect(run, concord.step("propose"), list(run.answers))
    assert [o.text for o in run.options] == ["Offer 10% off"]


@pytest.mark.asyncio
async def test_prompts_say_the_tasks_title_not_its_key(in_a_task):
    (engine, _manager, channel), directive = _concord(
        {h: [("same idea", None), ("[[mycelium: A=90]]", None)] for h in CAST}
    )
    await engine.run(ROOM, episode=THREAD, directive=directive, named=CAST)
    propose = channel.ticks()[0][2]
    assert "Decide the renewal offer" in propose
    assert TASK_KEY not in propose


def test_an_option_ending_in_a_full_stop_is_not_given_another():
    assert conductor._sentence("Renew for three years.") == "Renew for three years."
    assert conductor._sentence("Renew for three years") == "Renew for three years."


def test_options_are_lettered_in_cast_order_whatever_order_replies_arrive_in():
    engine, _manager, _channel = _engine({})
    concord = protocols.builtin("concord")
    assert concord is not None
    run = conductor.Run(protocol=concord, ask="", handles=CAST, bound={}, episode=THREAD)
    # Replies landed legal first, then success, then finance.
    run.answers = {"legal": {}, "success": {}, "finance": {}}
    run.replies = {
        "legal": "C text",
        "success": "A text",
        "finance": "B text [[mycelium: stance=accept]]",
    }
    engine._collect(run, concord.step("propose"), list(run.answers))
    assert [(o.label, o.text, o.authors) for o in run.options] == [
        ("A", "A text", ["success"]),
        ("B", "B text", ["finance"]),
        ("C", "C text", ["legal"]),
    ]


@pytest.mark.asyncio
async def test_the_record_traces_each_pick(in_a_task):
    from app.services.episode_records import episode_summary

    (engine, _manager, channel), directive = _concord(
        {h: [("same idea", None), ("[[mycelium: A=90]]", None)] for h in CAST}
    )
    before = set(_records())

    await engine.run(ROOM, episode=THREAD, directive=directive, named=CAST)

    (key,) = set(_records()) - before
    found = read_memory_file(get_room_dir(ROOM), key)
    assert found is not None
    summary = episode_summary(key, *found)
    picks = [t for t in summary["trace"] if "select" in t]
    assert [(t["step"], t["select"]["outcome"], t["next"]) for t in picks] == [
        ("pick", "feasible", "agreed")
    ]
    # One suggestion three ways is one option, credited to all three.
    assert channel.commit().payload.data["select"]["options"][0]["authors"] == CAST


@pytest.mark.asyncio
async def test_no_other_built_in_can_converge():
    for name in ("fan-out", "gated", "review", "round-robin", "swarm", "accord"):
        spec = protocols.builtin(name)
        assert spec is not None
        assert all(s.end != "converged" for s in spec.steps), name


# ── accord: labelled points merged in code, words checked, the summary saved ──

TEAM = ["a", "b", "c"]
SUMMARY_KEY = "context/summary/acme-renewal"
NOTHING_MORE = ("Nothing more to add.", None)


def _accord(script: dict[str, list[tuple]]):
    return _engine(script), "accord @a @b @c: agree what the renewal is"


def _commit_text(channel: ScriptedChannel) -> str:
    (said,) = [
        (x or {}).get("content", "") for e, x in channel.sent if e.header.kind == Kind.commit
    ]
    return said


def _saved(key: str = SUMMARY_KEY) -> tuple[dict[str, Any], str]:
    found = read_memory_file(get_room_dir(ROOM), key)
    assert found is not None, f"{key} was not saved"
    return found[0], found[1]


#: A run where everyone frames, one more point arrives in the second round,
#: nothing in the third, and the one word two members define means the same.
AGREEING = {
    "a": [
        (
            "[[mycelium: objective]] Renew Acme on terms finance can sign.\n"
            "[[mycelium: constraint about=pricing]] A discount of at most 15%.",
            None,
        ),
        NOTHING_MORE,
        NOTHING_MORE,
        (
            "[[mycelium: term=renewal]] The same product for a new 12-month term.\n\n"
            "[[mycelium: check covers=p1]] Finance signs the order form.",
            None,
        ),
    ],
    "b": [
        (
            "[[mycelium: objective]] Renew Acme on terms   finance can sign.\n"
            "[[mycelium: out_of_scope]] Changing the product tier.",
            None,
        ),
        NOTHING_MORE,
        NOTHING_MORE,
        ("[[mycelium: term=Renewal]] the same product for a new 12-month term.", None),
    ],
    "c": [
        ("[[mycelium: constraint about=pricing]] A discount of up to 20% is fine.", None),
        ("[[mycelium: deliverable]] A signed order form.", None),
        NOTHING_MORE,
        ("Nothing to add.", None),
    ],
}


@pytest.mark.asyncio
async def test_accord_merges_what_everyone_labelled_with_no_lead_and_saves_it(in_a_task):
    (engine, _manager, channel), directive = _accord(AGREEING)

    outcome = await engine.run(ROOM, episode=THREAD, directive=directive, named=TEAM)

    assert outcome == "resolved"
    steps = [s for s, _to, _p in channel.ticks()]
    # Everyone is asked every round: nobody leads, nobody merges, nobody votes.
    assert steps == ["frame"] * 3 + ["more"] * 3 + ["more"] * 3 + ["ground"] * 3
    meta, body = _saved()
    made = meta["contract"]
    assert meta["relates-to"] == TASK_KEY
    assert made["cast"] == TEAM
    points = {p["id"]: p for p in made["points"]}
    # Equal text folds (case and spacing aside) and is credited to both.
    assert points["p1"]["type"] == "objective"
    assert points["p1"]["authors"] == ["a", "b"]
    assert points["p1"]["support"] == 2
    assert [p["type"] for p in made["points"]] == [
        "objective",
        "constraint",
        "out_of_scope",
        "constraint",
        "deliverable",
    ]
    # Two different things said about pricing: both kept, both flagged.
    assert points["p2"]["text"] == "A discount of at most 15%."
    assert points["p4"]["text"] == "A discount of up to 20% is fine."
    assert "conflict" in points["p2"]["flags"]
    assert "conflict" in points["p4"]["flags"]
    assert "single" in points["p3"]["flags"]
    assert made["glossary"] == [
        {
            "term": "renewal",
            "status": "agreed",
            "meanings": [
                {"text": "The same product for a new 12-month term.", "members": ["a", "b"]}
            ],
        }
    ]
    assert made["checks"] == [
        {"text": "Finance signs the order form.", "covers": ["p1"], "owner": "a"}
    ]
    assert made["unchecked"] == ["p2", "p4", "p5"]
    kinds = [f["kind"] for f in made["flags"]]
    assert "conflict" in kinds
    assert "unchecked" in kinds
    assert "ambiguous" not in kinds
    assert "## Out of scope" in body
    assert "People said different things about pricing: p2, p4" in body
    assert "- Only one person said this: p2, p3, p4, p5" in body
    commit = channel.commit()
    assert commit.header.subkind == "resolved"
    assert commit.payload.data["memory"] == SUMMARY_KEY
    assert "assignments" not in commit.payload.data
    said = _commit_text(channel)
    assert said.startswith("✓ accord: resolved after 4 step(s).")
    assert "5 point(s), 1 stated by more than one person" in said
    assert f"The shared summary is saved as {SUMMARY_KEY}." in said
    lines = _lines(channel)
    tallies = [line["tally"]["outcome"] for line in lines if line.get("event") == "tally"]
    assert tallies == ["grew", "grew", "settled", "clear"]
    (lock,) = [line for line in lines if line.get("event") == "lock"]
    assert lock["lock"]["memory"] == SUMMARY_KEY
    assert lock["lock"]["points"] == 5
    assert lines[-1]["memory"] == SUMMARY_KEY, "the close line says where it went"


@pytest.mark.asyncio
async def test_accord_shows_the_frame_so_far_and_asks_only_for_what_is_missing(in_a_task):
    (engine, _manager, channel), directive = _accord(AGREEING)

    await engine.run(ROOM, episode=THREAD, directive=directive, named=TEAM)

    more = channel.ticks()[3][2]
    assert "p1 (objective, stated by 2 of 3): Renew Acme on terms finance can sign." in more
    assert "Is something important missing" in more
    ground = channel.ticks()[9][2]
    assert "p5 (deliverable, stated by 1 of 3): A signed order form." in ground
    assert "[[mycelium: term=<word>]]" in ground


@pytest.mark.asyncio
async def test_a_second_accord_in_the_same_task_updates_the_same_summary(in_a_task):
    (engine, _m, _c), directive = _accord(AGREEING)
    await engine.run(ROOM, episode=THREAD, directive=directive, named=TEAM)
    (engine, _m, channel), directive = _accord(AGREEING)

    await engine.run(ROOM, episode=THREAD, directive=directive, named=TEAM)

    meta, _body = _saved()
    assert meta["version"] == 2
    # The second run's prompts carry the first run's summary.
    assert "What the team already agreed for this task" in channel.ticks()[0][2]
    assert f"From {SUMMARY_KEY}:" in channel.ticks()[0][2]


@pytest.mark.asyncio
async def test_a_word_used_in_different_senses_is_asked_of_those_members_once_then_kept_apart(
    in_a_task,
):
    framing_ = [
        ("[[mycelium: objective]] Renew Acme.", None),
        NOTHING_MORE,
    ]
    (engine, manager, channel), directive = _accord(
        {
            "a": [
                *framing_,
                ("[[mycelium: term=renewal]] A new 12-month term.", None),
                ("[[mycelium: term=renewal]] A new 12-month term, nothing else.", None),
            ],
            "b": [
                *framing_,
                ("[[mycelium: term=renewal]] Any contract signed after the old one ends.", None),
                ("[[mycelium: term=renewal]] Any contract after the old one ends.", None),
            ],
            "c": [*framing_, ("No special words from me.", None)],
        }
    )

    outcome = await engine.run(ROOM, episode=THREAD, directive=directive, named=TEAM)

    assert outcome == "resolved"
    restated = [(to, p) for s, to, p in channel.ticks() if s == "restate"]
    assert [to for to, _p in restated] == ["a", "b"], "only the members whose meanings differ"
    assert "renewal is used in different senses" in restated[0][1]
    assert ["a", "b"] in [sorted(f.speakers) for f in manager.floor_log]
    made = _saved()[0]["contract"]
    (word,) = made["glossary"]
    assert word["status"] == "contested"
    # Never picked between, never merged: both restated meanings, side by side.
    assert word["meanings"] == [
        {"text": "A new 12-month term, nothing else.", "members": ["a"]},
        {"text": "Any contract after the old one ends.", "members": ["b"]},
    ]
    assert {
        "kind": "ambiguous",
        "text": "A word used in different senses: renewal",
        "term": "renewal",
    } in made["flags"]
    assert "1 word(s) used in different senses" in _commit_text(channel)


@pytest.mark.asyncio
async def test_a_reply_in_plain_words_is_asked_once_then_kept_as_written(in_a_task):
    """A person who answers without labels is never lost, never mistyped, and
    never counted as agreeing with anyone else."""
    (engine, manager, channel), directive = _accord(
        {
            "a": [("[[mycelium: objective]] Renew Acme.", None), NOTHING_MORE],
            "b": [("[[mycelium: objective]] Renew Acme.", None), NOTHING_MORE],
            "c": [
                ("I think we should renew Acme, but not below list price.", None),
                ("Same as before: renew, not below list price.", None),
                NOTHING_MORE,
            ],
        }
    )

    await engine.run(ROOM, episode=THREAD, directive=directive, named=TEAM)

    steps = [(s, to) for s, to, _p in channel.ticks()]
    assert steps[3] == ("frame", "c"), "only the reply with no label is asked again"
    assert "I couldn't find a label in your reply" in channel.ticks()[3][2]
    assert ["c"] in [sorted(f.speakers) for f in manager.floor_log]
    made = _saved()[0]["contract"]
    statement = made["points"][1]
    assert statement["type"] == "statement"
    assert statement["text"] == "Same as before: renew, not below list price."
    assert statement["authors"] == ["c"]
    assert made["points"][0]["authors"] == ["a", "b"], "c's words joined nobody's point"


@pytest.mark.asyncio
async def test_a_silent_member_is_recorded_as_not_answering_never_as_agreeing(in_a_task):
    (engine, _manager, channel), directive = _accord(
        {
            "a": [("[[mycelium: objective]] Renew Acme.", None), NOTHING_MORE],
            "b": [("[[mycelium: objective]] Renew Acme.", None), NOTHING_MORE],
            "c": [],
        }
    )

    outcome = await engine.run(ROOM, episode=THREAD, directive=directive, named=TEAM)

    assert outcome == "resolved"
    made = _saved()[0]["contract"]
    assert made["points"][0]["authors"] == ["a", "b"]
    assert {"kind": "quiet_member", "text": "No answer from c", "members": ["c"]} in made["flags"]
    assert "No answer from c." in _commit_text(channel)


@pytest.mark.asyncio
async def test_accord_with_nobody_answering_ends_rejected_and_saves_nothing(in_a_task):
    (engine, _manager, channel), directive = _accord({"a": [], "b": [], "c": []})

    outcome = await engine.run(ROOM, episode=THREAD, directive=directive, named=TEAM)

    assert outcome == "rejected"
    assert read_memory_file(get_room_dir(ROOM), SUMMARY_KEY) is None
    commit = channel.commit()
    assert "memory" not in commit.payload.data
    said = _commit_text(channel)
    assert "reached `nothing`" in said
    assert "No answer from a, b, c." in said


@pytest.mark.asyncio
async def test_a_failed_save_leaves_the_outcome_and_says_so(in_a_task, monkeypatch):
    async def fails(*_a: Any, **_k: Any) -> bool:
        return False

    monkeypatch.setattr(conductor.agreed, "save", fails)
    (engine, _manager, channel), directive = _accord(AGREEING)

    outcome = await engine.run(ROOM, episode=THREAD, directive=directive, named=TEAM)

    assert outcome == "resolved"
    assert channel.commit().payload.data["memory"] is None
    assert "The shared summary could not be saved." in _commit_text(channel)
    assert any("could not be saved; it is in this thread" in s for s in channel.said())


@pytest.mark.asyncio
async def test_points_still_arriving_when_the_rounds_run_out_are_flagged(in_a_task):
    def keeps_adding(who: str) -> list[tuple]:
        return [(f"[[mycelium: sub_goal]] {who} part {n}.", None) for n in range(1, 4)]

    (engine, _manager, channel), directive = _accord(
        {h: [*keeps_adding(h), ("Nothing to add.", None)] for h in TEAM}
    )

    outcome = await engine.run(ROOM, episode=THREAD, directive=directive, named=TEAM)

    assert outcome == "resolved"
    assert [s for s, _to, _p in channel.ticks()].count("more") == 6, "three rounds, no more"
    made = _saved()[0]["contract"]
    assert "frame_cap_reached" in [f["kind"] for f in made["flags"]]


@pytest.mark.asyncio
async def test_labels_lifted_onto_the_payload_by_the_reply_route_are_read(in_a_task):
    """An agent's reply arrives with its markers stripped from the prose and its
    pieces on the payload; the conductor reads them there."""
    lifted = {
        "pieces": [{"label": "objective", "text": "Renew Acme."}],
        "note": "lifted by the reply route",
    }
    (engine, _manager, _channel), directive = _accord(
        {h: [("Renew Acme.", lifted), NOTHING_MORE] for h in TEAM}
    )

    outcome = await engine.run(ROOM, episode=THREAD, directive=directive, named=TEAM)

    assert outcome == "resolved"
    (point,) = _saved()[0]["contract"]["points"]
    assert point == {
        "id": "p1",
        "type": "objective",
        "text": "Renew Acme.",
        "support": 3,
        "authors": TEAM,
        "flags": ["unchecked"],
    }


@pytest.mark.asyncio
async def test_near_duplicates_fold_by_similarity_and_an_unavailable_model_falls_back(in_a_task):
    script = {
        "a": [("[[mycelium: objective]] Renew Acme for a year.", None), NOTHING_MORE],
        "b": [("[[mycelium: objective]] Renew the Acme account for one year.", None), NOTHING_MORE],
        "c": [],
    }
    (engine, _m, _c), directive = _accord(script)
    engine.similarity = lambda: lambda _x, _y: 0.97
    await engine.run(ROOM, episode=THREAD, directive=directive, named=TEAM)
    (folded,) = _saved()[0]["contract"]["points"]
    assert folded["authors"] == ["a", "b"]

    def broken(_x: str, _y: str) -> float:
        raise RuntimeError("no model")

    (engine, _m, _c), directive = _accord(script)
    engine.similarity = lambda: broken
    await engine.run(ROOM, episode=THREAD, directive=directive, named=TEAM)
    made = _saved()[0]["contract"]
    assert len(made["points"]) == 2, "equal text only, once the model fails"
    assert "similarity_unavailable" in [f["kind"] for f in made["flags"]]


@pytest.mark.asyncio
async def test_the_same_replies_in_the_same_order_give_the_same_summary(in_a_task):
    (engine, _m, _c), directive = _accord(AGREEING)
    await engine.run(ROOM, episode=THREAD, directive=directive, named=TEAM)
    first = _saved()[0]["contract"]
    (engine, _m, _c), directive = _accord(AGREEING)
    await engine.run(ROOM, episode=THREAD, directive=directive, named=TEAM)

    assert _saved()[0]["contract"] == first


@pytest.mark.asyncio
async def test_a_later_concord_in_the_task_is_shown_what_was_agreed(in_a_task):
    (engine, _m, _c), directive = _accord(AGREEING)
    await engine.run(ROOM, episode=THREAD, directive=directive, named=TEAM)
    (engine, _m, channel), directive = _concord(
        {
            "success": [("20% off", None), ("[[mycelium: A=90]]", None)],
            "finance": [("20% off", None), ("[[mycelium: A=90]]", None)],
            "legal": [("20% off", None), ("[[mycelium: A=90]]", None)],
        }
    )

    outcome = await engine.run(ROOM, episode=THREAD, directive=directive, named=CAST)

    assert outcome == "converged"
    propose = channel.ticks()[0][2]
    assert "What the team already agreed for this task" in propose
    assert "Renew Acme on terms finance can sign." in propose
    meta, body = _saved("context/decision/acme-renewal")
    assert meta["decision"]["text"] == "20% off"
    assert meta["relates-to"] == TASK_KEY
    assert "Going with A: 20% off" in body


@pytest.mark.asyncio
async def test_a_room_override_of_accord_in_the_old_shape_still_runs(in_a_task):
    """A room that saved the lead-and-confirm accord keeps running its own."""
    old = {
        "roles": ["lead"],
        "max_steps": 8,
        "steps": [
            {"id": "frame", "to": "all", "prompt": "Frame {title}.", "next": "merge"},
            {
                "id": "merge",
                "to": "lead",
                "prompt": "Everyone's take:\n\n{replies}\n\nWrite one summary.",
                "next": {"silent": "no_summary", "default": "lock"},
            },
            {
                "id": "lock",
                "to": "all",
                "require": "stance",
                "prompt": "The summary:\n\n{reply}\n\nCan you work to this?",
                "next": {
                    "accept": "locked",
                    "reject": "merge",
                    "silent": "merge",
                    "default": "locked",
                },
            },
            {"id": "locked", "end": "resolved"},
            {"id": "no_summary", "end": "rejected"},
        ],
    }
    write_memory_file(
        get_room_dir(ROOM), "protocols/accord", yaml.safe_dump(old), created_by="julia"
    )
    (engine, _manager, channel), _directive = _accord(
        {
            "lead": [("my take", None), ("the summary", None), ("works", "accept")],
            "a": [("a take", None), ("fine", "accept")],
            "b": [("b take", None), ("fine", "accept")],
        }
    )

    outcome = await engine.run(
        ROOM, episode=THREAD, directive="accord @lead @a @b: plan it", named=["lead", "a", "b"]
    )

    assert outcome == "resolved"
    assert [s for s, _to, _p in channel.ticks()] == ["frame"] * 3 + ["merge"] + ["lock"] * 3
    assert read_memory_file(get_room_dir(ROOM), SUMMARY_KEY) is None, "it locks no summary"
