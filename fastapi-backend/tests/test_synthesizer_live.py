# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Live-LLM slice for the synthesizer engine.

Guarded by ``MYCELIUM_LLM_TESTS=1`` (costs tokens). Exercises the real path end
to end: a real room transcript on disk → a real ``pi`` turn against the
configured model → a real ``context/synthesis`` memory written through the
canonical (versioned + indexed) write. Only the embedding vector is stubbed — it
is orthogonal to the synthesis and would otherwise load the ONNX model.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from app.services import l9, persister, synthesizer
from app.services.filesystem import get_room_dir, read_memory_file
from app.services.l9_models import Kind
from app.services.l9_slim import serialize_content
from tests.fakes import FakeChannel, FakeManaged, FakeManager, FakePersister

_ROOM = "synth-live"
_T0 = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)


def _say(message_id: str, *, sender: str, text: str, minute: int) -> None:
    env = l9.build_envelope(
        kind=Kind.exchange,
        episode=l9.episode_urn(_ROOM, "live"),
        sender=sender,
        recipients=[l9.SYSTEM_ACTOR_ID],
        topic=l9.topic_urn(_ROOM),
        message_id=message_id,
        payload_type="message",
    )
    record = persister.record_from(env, serialize_content(env, extra={"content": text}))
    record.recorded_at = (_T0 + timedelta(minutes=minute)).isoformat()
    persister.append_transcript(_ROOM, record)


@pytest.mark.skipif(
    os.getenv("MYCELIUM_LLM_TESTS") != "1",
    reason="live LLM test — set MYCELIUM_LLM_TESTS=1 to run",
)
@pytest.mark.asyncio
async def test_synthesize_live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.routes.memory.embed_text", lambda _text: [0.0])

    _say(
        "m-1",
        sender="operator",
        text="We need the Atlas catalog off the legacy store with zero downtime.",
        minute=0,
    )
    _say(
        "m-2",
        sender="growth",
        text="Then it has to be phased — dual-write for 48h, flip reads after.",
        minute=1,
    )
    _say(
        "m-3",
        sender="operator",
        text="Agreed, phased cutover it is. Rehearsal came back green.",
        minute=2,
    )
    _say("m-4", sender="growth", text="Scheduling the production flip Thursday.", minute=3)

    managed = FakeManaged(_ROOM, "mycelium", FakeChannel(), FakePersister())
    engine = synthesizer.SynthesizerEngine(FakeManager(managed, []))  # type: ignore[arg-type]

    summary = await engine.synthesize(_ROOM)

    assert summary is not None and summary.strip()
    written = read_memory_file(get_room_dir(_ROOM), synthesizer.SYNTHESIS_KEY)
    assert written is not None
    _meta, body = written
    # The real briefing should reflect the seeded facts, not fabricate.
    assert "cutover" in body.lower() or "atlas" in body.lower()
    print(f"\n--- live synthesis ({len(body)} chars) ---\n{body}\n")
