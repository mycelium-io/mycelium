# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The verifier: spotting claims, checking them against the room's records, the
model's say, the flags it keeps, the routes, and the line a wake carries.

Node-free and model-free: the claim spotter and the Pi turn are patched where a
test is about what comes after them.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pytest
import yaml

from app.config import settings
from app.services import (
    message_format,
    verifier,
    verifier_claims,
    verifier_learn,
    verifier_records,
    wake_digest,
)
from app.services.filesystem import get_room_dir, write_memory_file
from app.services.persister import TranscriptRecord, stored_message_from_record

ROOM = "verify-room"
NOW = datetime(2026, 10, 13, 20, 30, tzinfo=UTC)
LIVE = message_format.live_episode_urn(ROOM)
THREAD = message_format.episode_urn(ROOM, "449efcf4")


def _said(
    n: int, sender: str, text: str, minutes_ago: float, episode: str = LIVE
) -> TranscriptRecord:
    return TranscriptRecord(
        message_id=f"m{n}",
        sender=sender,
        kind="exchange",
        subkind=None,
        content={
            "content": text,
            "l9": {
                "header": {"kind": "exchange", "message": {"episode": episode}},
                "payload": {"type": "message"},
            },
        },
        recorded_at=(NOW - timedelta(minutes=minutes_ago)).isoformat(),
    )


def _upstream(n: int, change: str, ref: str, minutes_ago: float) -> TranscriptRecord:
    record = _said(n, "status", "", minutes_ago)
    record.content["l9"]["payload"] = {
        "type": message_format.NOTICE_PAYLOAD_TYPE,
        "data": {
            "subkind": "upstream",
            "change": change,
            "ref": ref,
            "at": (NOW - timedelta(minutes=minutes_ago)).isoformat(),
        },
    }
    return record


def _check(
    sentence: str,
    records: list[TranscriptRecord],
    *,
    kinds: frozenset[str] = frozenset({"approval"}),
    speaker: str = "builder",
    thread: str | None = LIVE,
) -> list[verifier_records.Finding]:
    return verifier_records.check(
        sentence, kinds, speaker=speaker, at=NOW, thread=thread, records=records
    )


def _register(handle: str, kind: str | None = None) -> None:
    body = yaml.safe_dump({"adapter": "engine", "kind": kind} if kind else {"adapter": "claude"})
    write_memory_file(get_room_dir(ROOM), f"agents/{handle}", body, created_by="cli-user")


# ── Step 1: spotting claims ──────────────────────────────────────────────────


def test_sentences_split_on_ends_and_lines_and_drop_list_marks() -> None:
    text = "Merged #12. Tests pass!\n- approved by @a\n\nok"
    assert verifier_claims.split_sentences(text) == ["Merged #12.", "Tests pass!", "approved by @a"]


def test_the_shipped_starting_model_loads_for_the_search_model(tmp_path) -> None:
    model = verifier_claims.load(tmp_path)
    assert model is not None
    assert model.source == "starting"
    assert set(model.weights) == set(verifier_claims.KINDS)
    assert all(w.shape == (384,) for w in model.weights.values())


def test_a_learned_model_is_preferred_and_one_for_another_embedding_is_not(tmp_path) -> None:
    shipped = verifier_claims.load(tmp_path)
    assert shipped is not None
    learned = shipped.to_json()
    path = verifier_claims.learned_path(tmp_path, shipped.embedding_model)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(learned))
    assert verifier_claims.load(tmp_path).source == "learned"  # type: ignore[union-attr]

    learned["embedding_model"] = "someone/else"
    path.write_text(json.dumps(learned))
    assert verifier_claims.load(tmp_path).source == "starting"  # type: ignore[union-attr]


def test_spot_returns_sentences_over_their_kinds_threshold(monkeypatch) -> None:
    model = verifier_claims.ClaimModel(
        embedding_model="m",
        weights={"approval": np.array([1.0, 0.0], dtype=np.float32)},
        intercepts={"approval": 0.0},
        thresholds={"approval": 0.7},
        source="starting",
    )
    monkeypatch.setattr(
        verifier_claims.embedding,
        "embed_texts",
        lambda texts: [[5.0, 0.0] if "approved" in t else [-5.0, 0.0] for t in texts],
    )
    claims = verifier_claims.spot(model, "Hello there. It was approved by Hay.")
    assert [(c.index, c.sentence, c.kinds) for c in claims] == [
        (1, "It was approved by Hay.", frozenset({"approval"}))
    ]


# ── Step 2: the room's records ───────────────────────────────────────────────


def test_an_approval_nobody_gave_cannot_be_found() -> None:
    records = [_said(1, "builder", "Opened #1278 for the tax fix.", 30)]
    (finding,) = _check("#1278 is approved, merging.", records)
    assert finding.claim == "approval"
    assert finding.ref == "#1278"
    assert finding.sure is False
    assert finding.line == "Can't find an approval for #1278."
    assert finding.quotes == ["#1278", "approved"]


def test_an_approval_someone_else_gave_backs_the_claim() -> None:
    records = [_said(1, "reviewer", "#1278 looks good, approved.", 10)]
    assert _check("#1278 is approved, merging.", records) == []


def test_a_github_review_the_watcher_reported_backs_the_claim() -> None:
    records = [_upstream(1, "approved", "mycelium-io/mycelium#1278", 10)]
    assert _check("#1278 is approved, merging.", records) == []


def test_the_speakers_own_approval_does_not_count() -> None:
    records = [_said(1, "builder", "#1278 approved.", 10)]
    assert len(_check("#1278 is approved, merging.", records)) == 1


def test_an_approval_said_after_the_claim_does_not_count() -> None:
    records = [_said(1, "reviewer", "#1278 approved.", -5)]
    assert len(_check("#1278 is approved.", records)) == 1


def test_an_approval_in_the_tasks_thread_counts_without_its_number() -> None:
    records = [_said(1, "reviewer", "Approved, CI passes.", 10, THREAD)]
    assert _check("#1273 is approved.", records, thread=THREAD) == []
    # The same words about another pull request don't count for this one.
    records = [_said(1, "reviewer", "#1270 approved, CI passes.", 10, THREAD)]
    assert len(_check("#1273 is approved.", records, thread=THREAD)) == 1


def test_plans_and_negations_are_not_approval_claims() -> None:
    records: list[TranscriptRecord] = []
    assert _check("Once #1278 is approved I'll merge.", records) == []
    assert _check("#1278 isn't approved yet.", records) == []
    assert _check("I approve #1278.", records) == []


def test_treating_a_merged_pr_as_open_is_sure_and_says_when() -> None:
    records = [_upstream(1, "merged", "mycelium-io/mycelium#1266", 22)]
    (finding,) = _check("Next I'll merge #1266.", records, kinds=frozenset({"pr_state"}))
    assert finding.claim == "open"
    assert finding.sure is True
    assert finding.line == "#1266 was already merged, at 20:08."
    assert finding.checked[0]["found"] == "merged at 20:08 (GitHub)"


def test_a_merge_within_the_grace_window_is_not_flagged() -> None:
    records = [_upstream(1, "merged", "mycelium-io/mycelium#1266", 1)]
    assert _check("#1266 still needs review.", records, kinds=frozenset({"pr_state"})) == []


def test_a_merge_an_agent_reported_counts_as_a_record() -> None:
    records = [_said(1, "reviewer", "Merged #1266.", 30)]
    (finding,) = _check("Stacked on #1266.", records, kinds=frozenset({"pr_state"}))
    assert finding.checked[0]["found"].endswith("(@reviewer)")


def test_another_repositorys_number_is_not_this_ones_merge() -> None:
    records = [
        _upstream(1, "merged", "mycelium-io/mycelium#1", 120),
        _upstream(2, "merged", "mycelium-io/mycelium#14", 120),
        _said(3, "hay", "The website#3 copy is in.", 100),
    ]
    pr_state = frozenset({"pr_state"})
    assert _check("mycelium-classifier#1 is ready to merge.", records, kinds=pr_state) == []
    assert (
        _check(
            "https://github.com/mycelium-io/mycelium-classifier/pull/1 still needs review.",
            records,
            kinds=pr_state,
        )
        == []
    )
    # A bare number in a sentence naming another repository the room knows is that one's.
    assert _check("The website's #14 is open.", records, kinds=pr_state) == []
    # The same words about the room's own repository are still checked.
    (finding,) = _check("mycelium#14 is open.", records, kinds=pr_state)
    assert finding.line == "mycelium#14 was already merged, at 18:30."
    (finding,) = _check("#14 is open.", records, kinds=pr_state)
    assert finding.ref == "#14"


def test_a_bare_number_two_repositories_were_reported_for_is_not_called_merged() -> None:
    records = [
        _upstream(1, "merged", "mycelium-io/mycelium#7", 120),
        _upstream(2, "opened", "juliarvalenti/shotkit#7", 110),
    ]
    assert _check("#7 is open.", [*records], kinds=frozenset({"pr_state"})) == []


def test_an_approval_of_another_repositorys_number_does_not_count() -> None:
    records = [_upstream(1, "approved", "mycelium-io/mycelium#3", 10)]
    (finding,) = _check("mycelium-classifier#3 is approved.", records)
    assert finding.line == "Can't find an approval for mycelium-classifier#3."
    assert finding.quotes == ["mycelium-classifier#3", "approved"]


def test_a_merge_still_to_come_is_not_a_merge() -> None:
    pr_state = frozenset({"pr_state"})
    for future in (
        "Merge this after #1266 is merged.",
        "Once #1266 is merged I'll rebase.",
        "#1266 isn't merged yet.",
        "Hold until #1266 is merged.",
        "#1266 will be merged tonight.",
    ):
        records = [_said(1, "reviewer", future, 30)]
        assert _check("#1266 still needs review.", records, kinds=pr_state) == [], future
    assert verifier_records.merged_in("Merged #1266.") == [(None, "1266")]
    assert verifier_records.merged_in("Once #1266 is merged, ship it.") == []


def test_a_sentence_without_a_pr_number_is_not_checked() -> None:
    assert _check("Everything is approved and merged.", []) == []


# ── The engine: steps in order, flags, notices ───────────────────────────────


class _Manager:
    def __init__(self) -> None:
        self.notices: list[dict[str, Any]] = []

    async def raise_notice(self, room: str, **data: Any) -> None:
        self.notices.append({"room": room, **data})


@pytest.fixture
def engine(monkeypatch) -> tuple[verifier.VerifierEngine, _Manager]:
    _register("verifier", "verifier")
    _register("builder")
    monkeypatch.setattr(settings, "VERIFIER_ENABLED", True)
    monkeypatch.setattr(settings, "VERIFIER_CONFIRM", True)
    model = verifier_claims.ClaimModel("m", {}, {}, {}, "starting")
    manager = _Manager()
    eng = verifier.VerifierEngine(manager)
    monkeypatch.setattr(eng, "model", lambda: model)
    monkeypatch.setattr(
        verifier_claims,
        "spot",
        lambda _m, text: [
            verifier_claims.Claim(i, s, frozenset({"approval"}))
            for i, s in enumerate(verifier_claims.split_sentences(text))
        ],
    )
    return eng, manager


def _transcript(monkeypatch, records: list[TranscriptRecord]) -> None:
    monkeypatch.setattr(verifier, "load_transcript", lambda _room: records)


@pytest.mark.asyncio
async def test_a_kept_flag_is_stored_and_raised_as_a_check_notice(engine, monkeypatch) -> None:
    eng, manager = engine
    claim = _said(2, "builder", "#1278 is approved, merging now.", 0, THREAD)
    _transcript(monkeypatch, [_said(1, "builder", "Opened #1278.", 30, THREAD), claim])
    prompts: list[str] = []

    def fake_model(prompt: str, room: str) -> str:
        prompts.append(prompt)
        return '{"show": true, "quote": "#1278 is approved", "why": "nobody approved it"}'

    monkeypatch.setattr(verifier, "_ask_model", fake_model)

    (flag,) = await eng.check_message(ROOM, claim)

    assert "Can't find an approval for #1278." in prompts[0]
    assert "@builder" in prompts[0] and "Opened #1278." in prompts[0]
    assert flag["quotes"] == ["#1278 is approved"]
    assert flag["key"] == "449efcf4"
    assert flag["by"] == "verifier"
    assert verifier.load_flags(ROOM) == [flag]
    (notice,) = manager.notices
    assert notice["subkind"] == "check"
    # The line names its message by the id the room's history read gives it.
    read = stored_message_from_record(ROOM, claim)
    assert read is not None
    assert notice["message_id"] == flag["message_id"] == str(read.id)
    assert notice["about"] == "builder"
    assert notice["sure"] == "false"
    assert notice["state"] == "shown"


@pytest.mark.asyncio
async def test_the_model_can_dismiss_a_flag(engine, monkeypatch) -> None:
    eng, manager = engine
    claim = _said(1, "builder", "#1278 is approved.", 0)
    _transcript(monkeypatch, [claim])
    monkeypatch.setattr(verifier, "_ask_model", lambda *_: '{"show": false, "why": "quoting"}')
    assert await eng.check_message(ROOM, claim) == []
    assert manager.notices == []


@pytest.mark.asyncio
async def test_a_failed_model_step_shows_nothing(engine, monkeypatch) -> None:
    eng, manager = engine
    claim = _said(1, "builder", "#1278 is approved.", 0)
    _transcript(monkeypatch, [claim])

    def broken(*_: Any) -> str:
        raise RuntimeError("pi is down")

    monkeypatch.setattr(verifier, "_ask_model", broken)
    assert await eng.check_message(ROOM, claim) == []
    assert manager.notices == []


@pytest.mark.asyncio
async def test_without_the_model_step_the_records_finding_is_shown(engine, monkeypatch) -> None:
    eng, _manager = engine
    monkeypatch.setattr(settings, "VERIFIER_CONFIRM", False)
    claim = _said(1, "builder", "#1278 is approved.", 0)
    _transcript(monkeypatch, [claim])
    (flag,) = await eng.check_message(ROOM, claim)
    assert flag["quotes"] == ["#1278", "approved"]


@pytest.mark.asyncio
async def test_the_same_message_is_not_flagged_twice(engine, monkeypatch) -> None:
    eng, manager = engine
    monkeypatch.setattr(settings, "VERIFIER_CONFIRM", False)
    claim = _said(1, "builder", "#1278 is approved.", 0)
    _transcript(monkeypatch, [claim])
    await eng.check_message(ROOM, claim)
    assert await eng.check_message(ROOM, claim) == []
    assert len(manager.notices) == 1


@pytest.mark.asyncio
async def test_marking_fine_hides_the_flag_and_keeps_the_answer(engine, monkeypatch) -> None:
    eng, manager = engine
    monkeypatch.setattr(settings, "VERIFIER_CONFIRM", False)
    claim = _said(1, "builder", "#1278 is approved.", 0)
    _transcript(monkeypatch, [claim])
    (flag,) = await eng.check_message(ROOM, claim)

    marked = await eng.mark_fine(ROOM, flag["flag_id"], "hay")

    assert marked is not None
    assert marked["state"] == "fine"
    assert marked["fine_by"] == "hay"
    assert manager.notices[-1]["state"] == "fine"
    assert manager.notices[-1]["fine_by"] == "hay"
    assert verifier_learn.answers_since(None) == 1
    assert await eng.mark_fine(ROOM, "nope", "hay") is None


def test_the_hook_ignores_engines_people_and_rooms_without_a_verifier(engine) -> None:
    eng, _manager = engine
    scheduled: list[str] = []
    eng._serial = lambda room, record: scheduled.append(record.sender)
    # No running loop here, so even a message it would check is dropped quietly.
    eng.handle_recorded(ROOM, _said(1, "builder", "#1 approved", 0))
    eng.handle_recorded(ROOM, _said(2, "verifier", "#1 approved", 0))
    eng.handle_recorded(ROOM, _said(3, "hay", "#1 approved", 0))
    eng.handle_recorded("other-room", _said(4, "builder", "#1 approved", 0))
    assert scheduled == []


@pytest.mark.asyncio
async def test_the_hook_checks_an_agents_message_when_on(engine, monkeypatch) -> None:
    eng, _manager = engine
    checked: list[str] = []

    async def fake_check(room: str, record: TranscriptRecord) -> list[dict[str, Any]]:
        checked.append(record.sender)
        return []

    monkeypatch.setattr(eng, "check_message", fake_check)
    eng.handle_recorded(ROOM, _said(1, "builder", "#1 approved", 0))
    eng.handle_recorded(ROOM, _said(2, "hay", "#1 approved", 0))  # a person, not an agent
    eng.handle_recorded(ROOM, _said(3, "verifier", "#1 approved", 0))  # an engine
    for task in list(eng._tasks):
        await task
    assert checked == ["builder"]

    monkeypatch.setattr(settings, "VERIFIER_ENABLED", False)
    eng.handle_recorded(ROOM, _said(4, "builder", "#1 approved", 0))
    assert not eng._tasks


# ── What the agent is told ───────────────────────────────────────────────────


def _check_notice(n: int, flag: dict[str, Any]) -> TranscriptRecord:
    record = _said(n, "verifier", "", 0)
    record.content["l9"]["payload"] = {
        "type": message_format.NOTICE_PAYLOAD_TYPE,
        "data": {"subkind": "check", "about": flag["about"], "flag_id": flag["flag_id"]},
    }
    return record


@pytest.mark.asyncio
async def test_a_wake_carries_a_check_line_for_a_shown_flag(engine, monkeypatch) -> None:
    eng, _manager = engine
    monkeypatch.setattr(settings, "VERIFIER_CONFIRM", False)
    claim = _said(1, "builder", "#1278 is approved.", 0)
    _transcript(monkeypatch, [claim])
    (flag,) = await eng.check_message(ROOM, claim)
    records = [claim, _check_notice(2, flag), _said(3, "hay", "@builder status?", 0)]

    digest = wake_digest.build(ROOM, {"handle": "builder", "from": "hay"}, records, NOW)

    assert (
        'Check:   You said "#1278 is approved.", but the verifier can\'t find an approval '
        "for #1278. Fix it in the room, or say where it came from." in digest
    )
    # Someone saying it's fine takes the line away.
    await eng.mark_fine(ROOM, flag["flag_id"], "hay")
    digest = wake_digest.build(ROOM, {"handle": "builder", "from": "hay"}, records, NOW)
    assert "Check:" not in digest


# ── Routes ───────────────────────────────────────────────────────────────────


@pytest.fixture
def app_verifier(engine):
    from app.main import app

    eng, _manager = engine
    app.state.verifier = eng
    return eng


@pytest.mark.asyncio
async def test_the_flags_route_lists_and_marks_fine(client, app_verifier, monkeypatch) -> None:
    monkeypatch.setattr(settings, "VERIFIER_CONFIRM", False)
    claim = _said(1, "builder", "#1278 is approved.", 0)
    _transcript(monkeypatch, [claim])
    (flag,) = await app_verifier.check_message(ROOM, claim)

    resp = await client.get(f"/api/rooms/{ROOM}/verifier/flags")
    assert resp.status_code == 200
    (read,) = resp.json()
    assert read["flag_id"] == flag["flag_id"]
    assert read["checked"][0]["found"] == "none"

    resp = await client.post(
        f"/api/rooms/{ROOM}/verifier/flags/{flag['flag_id']}/fine", json={"by": "hay"}
    )
    assert resp.status_code == 200
    assert resp.json()["state"] == "fine"
    resp = await client.post(f"/api/rooms/{ROOM}/verifier/flags/nope/fine", json={})
    assert resp.status_code == 404
    assert (await client.get("/api/rooms/no-such-room/verifier/flags")).status_code == 404


@pytest.mark.asyncio
async def test_the_settings_route_says_what_it_runs_on(client, app_verifier) -> None:
    resp = await client.get("/api/verifier/settings")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert body["rooms"] == [ROOM]
    assert body["learning"]["state"] == "idle"
    assert body["estimate"]["messages"] == 0


@pytest.mark.asyncio
async def test_with_sign_in_only_a_person_can_start_learn(client, app_verifier, monkeypatch):
    from app.services import actor
    from app.services.auth import Principal

    started: list[bool] = []
    monkeypatch.setattr(app_verifier, "start_learn", lambda: started.append(True) or True)
    # What the sign-in gate leaves on the request for a verified token.
    monkeypatch.setattr(
        actor, "current_principal", lambda _r: Principal("s", "builder", "agent", "iss")
    )
    assert (await client.post("/api/verifier/learn")).status_code == 403
    monkeypatch.setattr(actor, "current_principal", lambda _r: Principal("s", "hay", "user", "iss"))
    assert (await client.post("/api/verifier/learn")).status_code == 202
    assert started == [True]


@pytest.mark.asyncio
async def test_learn_needs_a_room_with_the_verifier(client, monkeypatch) -> None:
    from app.main import app

    app.state.verifier = verifier.VerifierEngine(_Manager())
    resp = await client.post("/api/verifier/learn")
    assert resp.status_code == 409


# ── Learn ────────────────────────────────────────────────────────────────────


def test_labels_are_read_per_sentence_and_bad_lines_skipped() -> None:
    batch = [
        {"room": ROOM, "message_id": "m1", "sentences": ["Merged #1.", "Thanks."]},
        {"room": ROOM, "message_id": "m2", "sentences": ["Shall I merge?"]},
    ]
    answer = "\n".join(
        [
            '{"m": 1, "claims": [{"s": 1, "kinds": ["completion", "made-up"]}]}',
            "not json",
            '{"m": 9, "claims": []}',
            '{"m": 2, "claims": []}',
        ]
    )
    labels = verifier_learn._parse(answer, batch)
    assert [(r["message_id"], r["s"], r["kinds"]) for r in labels] == [
        ("m1", 1, ["completion"]),
        ("m1", 2, []),
        ("m2", 1, []),
    ]


def test_train_fits_a_model_the_engine_then_loads(tmp_path, monkeypatch) -> None:
    def fake_embed(texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] if "approved" in t else [0.0, 1.0] for t in texts]

    monkeypatch.setattr(verifier_learn.embedding, "embed_texts", fake_embed)
    labels = [
        {
            "room": ROOM,
            "message_id": f"m{i}",
            "s": 1,
            "sentence": "it's approved" if i % 3 == 0 else "looking at it",
            "kinds": ["approval"] if i % 3 == 0 else [],
        }
        for i in range(60)
    ]
    model = verifier_learn.train(labels)
    assert model is not None
    assert set(model.weights) == {"approval"}
    assert model.trained_on == {"messages": 60, "sentences": 60}
    from pathlib import Path

    loaded = verifier_claims.load(Path(settings.MYCELIUM_DATA_DIR))
    assert loaded is not None
    assert loaded.source == "learned"
    probs = loaded.probabilities(np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32))
    assert probs["approval"][0] > loaded.thresholds["approval"] > probs["approval"][1]


def test_a_new_search_model_is_fitted_again_from_the_saved_labels(monkeypatch) -> None:
    # No starting model ships for this search model, so the engine fits one.
    monkeypatch.setattr(verifier_claims.embedding, "model_name", lambda: "someone/other-model")
    monkeypatch.setattr(
        verifier_learn.embedding,
        "embed_texts",
        lambda texts: [[1.0, 0.0] if "approved" in t else [0.0, 1.0] for t in texts],
    )
    eng = verifier.VerifierEngine(_Manager())
    assert eng.model() is None  # nothing learned yet, and nothing to learn from

    verifier_learn._append(
        "labels.jsonl",
        [
            {
                "room": ROOM,
                "message_id": f"m{i}",
                "s": 1,
                "sentence": "it's approved" if i % 2 else "looking",
                "kinds": ["approval"] if i % 2 else [],
            }
            for i in range(40)
        ],
    )
    eng.reload_model()
    model = eng.model()
    assert model is not None
    assert model.source == "learned"
    assert model.embedding_model == "someone/other-model"


def test_dropping_a_room_forgets_its_labels_and_answers() -> None:
    verifier_learn._append(
        "labels.jsonl",
        [
            {"room": ROOM, "message_id": "m1", "s": 1, "sentence": "x", "kinds": []},
            {"room": "keep", "message_id": "m2", "s": 1, "sentence": "y", "kinds": []},
        ],
    )
    verifier_learn.drop_room(ROOM)
    assert verifier_learn.labeled_rooms() == ["keep"]
