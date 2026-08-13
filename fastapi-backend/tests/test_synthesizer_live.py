# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Live-LLM slice for the synthesizer engine.

Guarded by ``MYCELIUM_LLM_TESTS=1`` (costs tokens). Exercises the real path end
to end: real room memories on disk → a real ``pi`` turn against the configured
model → a real ``context/synthesis`` memory written through the canonical
(versioned + indexed) write. Only the embedding vector is stubbed — it is
orthogonal to the synthesis and would otherwise load the ONNX model.
"""

from __future__ import annotations

import os

import pytest

from app.services import synthesizer
from app.services.filesystem import get_room_dir, read_memory_file, write_memory_file
from tests.fakes import FakeChannel, FakeManaged, FakeManager, FakePersister

_ROOM = "synth-live"


@pytest.mark.skipif(
    os.getenv("MYCELIUM_LLM_TESTS") != "1",
    reason="live LLM test — set MYCELIUM_LLM_TESTS=1 to run",
)
@pytest.mark.asyncio
async def test_synthesize_live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.routes.memory.embed_text", lambda _text: [0.0])

    write_memory_file(
        get_room_dir(_ROOM),
        "context/goal",
        "Move the Atlas catalog off the legacy store with zero downtime.",
        created_by="operator",
    )
    write_memory_file(
        get_room_dir(_ROOM),
        "decisions/cutover",
        "Phased cutover over a 48h window; dual-write then flip reads.",
        created_by="aligner",
    )
    write_memory_file(
        get_room_dir(_ROOM),
        "status/sprint",
        "Cutover rehearsal green; production flip scheduled Thursday.",
        created_by="growth",
    )

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
