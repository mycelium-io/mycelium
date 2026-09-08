# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Live-LLM slice for the product's cognition: negotiate, then compile the work.

``test_smoke.py`` with the fakes taken out of the cognition path — the LLM session is
a real ``pi`` session and the compiler a real one-shot ``pi`` turn, so this
covers what only a live model can: structuring prose into issues, reading an
agreement as an agreement, and emitting an owned checklist.

The *participants* stay scripted: two agents whose replies are prose written in
advance, conceding toward each other and ending in plain acceptance. Simulating
them with a second model would test that model's agreeableness, not this one's
mediation.

The assertion that matters is the anti-theater property — agreement from the
mechanism terminating at unanimity, not from exhausting the cap.

Guarded by ``MYCELIUM_LLM_TESTS=1`` (costs tokens) and needs ``pi`` on PATH.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from app.services import aligner, l9, task_sync
from app.services.filesystem import ensure_room_structure, get_room_dir, read_memory_file
from app.services.l9_models import Kind
from tests.fakes import FakeChannel, FakeManaged, FakeManager, FakePersister, position_record

_ROOM = "cognition-live"

# Two agents disagreeing over scope against timeline, with a scripted path to
# agreement. One line is consumed per tick; the last is an unambiguous
# acceptance, and the tail repeats so an extra round is still answered in the
# same terms.
_SCRIPTS: dict[str, list[str]] = {
    "growth": [
        "Ship the full catalog cutover in one 3-month push. Adoption is the whole "
        "point and a staged release loses us the launch window.",
        "I hear the risk argument. I can live with a reduced first scope if the "
        "timeline stays tight — 3 months on a smaller cut.",
        "Agreed: reduced scope, and I will take 6 months if that is what makes it "
        "safe. I accept that as the plan.",
        "Still agreed — reduced scope over 6 months. I accept.",
    ],
    "risk": [
        "A single 3-month cutover of the whole catalog is how we take the store "
        "down. Reduced scope, 6 months, with a rollback at every step.",
        "Reduced scope is the part I need. On timeline I will hold at 6 months.",
        "Then we agree: reduced scope, 6 months. I accept that as the plan.",
        "Still agreed — reduced scope over 6 months. I accept.",
    ],
}


class ScriptedAgents(FakeChannel):
    """Participants that answer each `@`-mention with the next line of a script.

    ``FakeChannel``'s ``reply_conf`` mode answers with a stub. A live LLM session reads
    the prose — discovering issues from it and interpreting each reply as an
    offer — so a reply has to be a sentence somebody could have written.
    """

    def __init__(self, persister: FakePersister, scripts: dict[str, list[str]]) -> None:
        super().__init__(persister)
        self._scripts = scripts
        self._turn: dict[str, int] = dict.fromkeys(scripts, 0)
        self._seq = 0

    async def send(self, envelope: Any, *, extra: dict[str, Any] | None = None) -> None:
        self.sent.append((envelope, extra))
        if envelope.header.kind != Kind.exchange:
            return
        # actors[0] is the sender; everyone after it was addressed.
        for actor in envelope.header.participants.actors[1:]:
            script = self._scripts.get(actor.id)
            if not script:
                continue
            turn = min(self._turn[actor.id], len(script) - 1)
            self._turn[actor.id] += 1
            self._seq += 1
            assert self._persister is not None
            self._persister.log.record(
                position_record(
                    actor.id,
                    confidence=0.9,
                    message_id=f"scripted-{self._seq}",
                    prose=script[turn],
                ),
                delivered_to=set(),
            )


@pytest.mark.skipif(
    os.getenv("MYCELIUM_LLM_TESTS") != "1",
    reason="live LLM test — set MYCELIUM_LLM_TESTS=1 to run",
)
@pytest.mark.asyncio
async def test_negotiation_converges_and_compiles_work(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.routes.memory.embed_text", lambda _text: [0.0])
    ensure_room_structure(get_room_dir(_ROOM))

    persister = FakePersister()
    channel = ScriptedAgents(persister, _SCRIPTS)
    managed = FakeManaged(_ROOM, "mycelium", channel, persister)
    manager = FakeManager(managed, [*_SCRIPTS, "aligner"])

    # Opening positions, on the transcript before the summon: what the LLM session
    # reads to discover the issues.
    for handle, script in _SCRIPTS.items():
        persister.log.record(
            position_record(handle, confidence=0.9, message_id=f"open-{handle}", prose=script[0]),
            delivered_to=set(),
        )

    # No llm_session_factory, so the engine builds its real Pi session.
    engine = aligner.AlignerEngine(
        manager,  # type: ignore[arg-type]
        handle="aligner",
        round_timeout_s=5.0,
        poll_interval_s=0.05,
        max_steps=12,
    )

    verdict = await engine.mediate(_ROOM)

    assert verdict is not None, "the aligner produced no verdict at all"
    assert verdict["header"]["subkind"] == "converged", (
        f"negotiation did not converge: {verdict['payload']['data']}"
    )
    assignments = verdict["payload"]["data"]["assignments"]
    assert assignments, "converged with an empty agreement"

    # Rounds were actually brokered.
    assert len(channel.sent) > 2, "no rounds were brokered"

    # ── work ── the real compiler, against the real agreement.
    converged = l9.build_envelope(
        kind=Kind.commit,
        subkind="converged",
        episode=l9.episode_urn(_ROOM, "live"),
        recipients=list(_SCRIPTS),
        topic=l9.topic_urn(_ROOM),
        payload_type="consensus",
        payload_data={"assignments": assignments},
    )
    keys = await task_sync.TaskSyncEngine(manager).compile_and_write(_ROOM, converged)  # type: ignore[arg-type]

    assert keys, "the compiler produced no work"
    rows = [read_memory_file(get_room_dir(_ROOM), key) for key in keys]
    assert all(row is not None for row in rows), f"a compiled task was not written: {keys}"
    assert all(row[0].get("status") == "open" for row in rows if row), (
        "a compiled task did not land as open work"
    )
    assert any(
        str(row[0].get(task_sync.ASSIGNEE_FIELD, "")).lstrip("@") in _SCRIPTS for row in rows if row
    ), f"no compiled task names a real handle: {[row[0] for row in rows if row]}"
