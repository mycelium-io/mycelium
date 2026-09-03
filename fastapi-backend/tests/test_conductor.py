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


def _reply(handle: str, prose: str, *, episode: str, action: str | None, role: str = "agent"):
    """A member's reply as the transcript records it."""
    env = l9.build_envelope(
        kind=Kind.exchange,
        episode=episode,
        sender=handle,
        sender_role=role,
        recipients=["conductor"],
        topic=l9.topic_urn(ROOM),
        payload_type="reply",
        payload_data={"action": action} if action else {"note": "no stance"},
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
        if envelope.header.kind != Kind.exchange or envelope.payload.type != "tick":
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
            if env.header.kind == Kind.exchange and env.payload.type == "tick"
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


# ── the record, and what it does not do ───────────────────────────────────────


@pytest.mark.asyncio
async def test_the_run_leaves_an_episode_record_on_the_thread():
    from app.services.episode_records import episode_summary, parse_envelopes

    engine, _manager, _channel = _engine(
        {"api": [("do the thing", None)], "sec": [("approved", "accept")]}
    )
    before = set(_records())

    await engine.run(ROOM, episode=THREAD, directive="gated: go", named=["api", "sec"])

    new = set(_records()) - before
    assert len(new) == 1
    key = new.pop()
    found = read_memory_file(get_room_dir(ROOM), key)
    assert found is not None
    meta, content = found
    summary = episode_summary(key, meta, content)
    assert summary["episode"] == THREAD, "the record is the thread's, not a new episode's"
    assert summary["outcome"] == "resolved"
    assert {"api", "sec"} <= set(summary["participants"])
    # Intent, two ticks, two replies, the commit.
    assert len(parse_envelopes(content)) == 6


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

    outcome = await engine.run(
        ROOM, episode=THREAD, summoned_in=LIVE, directive="waltz @a @b: go", named=["a", "b"]
    )

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
async def test_a_summon_runs_in_the_thread_it_was_made_in():
    _register("conductor", "conductor")
    engine, _manager, channel = _engine(
        {"api": [("do the thing", None)], "sec": [("approved", "accept")]}
    )
    env, summons, text = _summon("@conductor gated @api @sec: rotate the key", episode=THREAD)

    engine.handle_summon(ROOM, "conductor", env, summons, text)
    await asyncio.sleep(0.1)

    assert channel.commit().header.message.episode == THREAD
    assert channel.commit().payload.data["roles"] == {"proposer": "api", "guardian": "sec"}


@pytest.mark.asyncio
async def test_a_summon_from_the_room_opens_a_thread_of_its_own():
    _register("conductor", "conductor")
    engine, _manager, channel = _engine(
        {"api": [("do the thing", None)], "sec": [("approved", "accept")]}
    )
    env, summons, text = _summon("@conductor gated @api @sec: rotate the key", episode=LIVE)

    engine.handle_summon(ROOM, "conductor", env, summons, text)
    await asyncio.sleep(0.1)

    ran_in = channel.commit().header.message.episode
    assert ran_in != LIVE
    assert ran_in.startswith(l9.episode_urn(ROOM, ""))


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
    await asyncio.sleep(0.5)

    assert len([e for e, _x in channel.sent if e.header.kind == Kind.commit]) == 1


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
async def test_a_built_in_the_room_ran_becomes_the_rooms_own_memory(monkeypatch):
    monkeypatch.setattr("app.routes.memory.embed_text", lambda _text: [0.0])
    engine, _manager, _channel = _engine(
        {"api": [("do the thing", None)], "sec": [("approved", "accept")]}
    )
    assert read_memory_file(get_room_dir(ROOM), "protocols/gated") is None

    await engine.run(ROOM, episode=THREAD, directive="gated: go", named=["api", "sec"])

    found = read_memory_file(get_room_dir(ROOM), "protocols/gated")
    assert found is not None
    written = protocols.parse_protocol("gated", found[1])
    assert written.roles == ["proposer", "guardian"]
    assert [s.id for s in written.steps] == ["propose", "review", "approved"]
    # The room's copy is what runs next, so editing it reshapes the protocol.
    assert protocols.room_protocol_names(ROOM) == ["gated"]


@pytest.mark.asyncio
async def test_list_says_what_it_can_run():
    engine, manager, channel = _engine({})

    outcome = await engine.run(ROOM, episode=THREAD, summoned_in=LIVE, directive="list")

    assert outcome is None
    assert manager.floor_log == []
    said = channel.said()[0]
    for name in protocols.builtin_names():
        assert f"**{name}**" in said
    assert "(built in)" in said
    assert channel.sent[0][0].header.message.episode == LIVE


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

    held = manager.floor(ROOM, THREAD)
    assert held is not None
    assert held.holder == "conductor"
    assert not held.admits("api") and not held.admits("sec")
    await asyncio.sleep(0.1)
    assert manager.floor(ROOM, THREAD) is None, "released once the run ends"
    assert channel.commit().header.subkind == "resolved"


@pytest.mark.asyncio
async def test_a_summon_that_cannot_start_lets_the_floor_go():
    _register("conductor", "conductor")
    engine, manager, channel = _engine({})
    env, summons, text = _summon("@conductor waltz @api @sec: go", episode=THREAD)

    engine.handle_summon(ROOM, "conductor", env, summons, text)
    assert manager.floor(ROOM, THREAD) is not None
    await asyncio.sleep(0.05)

    assert manager.floor(ROOM, THREAD) is None
    assert "Built in:" in channel.said()[0]
