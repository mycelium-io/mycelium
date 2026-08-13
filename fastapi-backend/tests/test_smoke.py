# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Non-interactive smoke: the core protocol over the fake stack.

One scriptable check that the happy path still works end to end —
**room → engine → await → respond → converge → plan** — with **no SLIM node, no
Pi binary, and no live LLM**. The mediator runs the real NEGMAS SAO loop; only its
brain (the deterministic ``fake_brain_factory``), the agents (the ``FakeChannel``
reply simulation, i.e. the await/respond turns), and the plan compiler are faked.

Run it alone with ``make smoke`` (or ``uv run pytest -m smoke``). If this goes red,
the protocol itself broke — not a corner case.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services import aligner, l9, plan, plan_sync
from app.services.filesystem import ensure_room_structure, get_room_dir, read_memory_file
from app.services.l9_models import Kind
from tests.fakes import (
    FakeChannel,
    FakeManaged,
    FakeManager,
    FakePersister,
    fake_brain_factory,
)

_ROOM = "smoke-room"


@pytest.mark.smoke
@pytest.mark.asyncio
async def test_core_protocol_room_to_plan_over_fakes() -> None:
    # ── room ── a persistent room namespace on disk.
    ensure_room_structure(get_room_dir(_ROOM))

    # ── engine + await/respond ── the aligner negotiates over a fake channel whose
    # prompted participants always reply (the simulated await→respond turns), with a
    # deterministic Pi brain. NEGMAS owns termination, so it stops at agreement.
    persister = FakePersister()
    channel = FakeChannel(persister, reply_conf=0.9)
    managed = FakeManaged(_ROOM, "mycelium", channel, persister)
    manager = FakeManager(managed, ["growth", "risk", "aligner"])

    engine = aligner.AlignerEngine(
        manager,  # type: ignore[arg-type]
        handle="aligner",
        round_timeout_s=0.2,
        poll_interval_s=0.01,
        max_steps=12,
        brain_factory=fake_brain_factory,
    )

    # ── converge ── a commit:converged verdict carrying the agreed issue=value map.
    verdict = await engine.mediate(_ROOM)
    assert verdict is not None
    assert verdict["header"]["subkind"] == "converged"
    assignments = verdict["payload"]["data"]["assignments"]
    assert assignments  # the negotiation actually agreed on something

    # ── plan ── the converged map compiles into the room's shared plan. The compiler
    # is the one remaining LLM stage, faked here to a deterministic checklist.
    converged = l9.build_envelope(
        kind=Kind.commit,
        subkind="converged",
        episode=l9.episode_urn(_ROOM, "live"),
        recipients=["growth", "risk"],
        topic=l9.topic_urn(_ROOM),
        payload_type="consensus",
        payload_data={"assignments": assignments},
    )
    compiled = "# Smoke Plan\n\n- [ ] ship the agreed cap @growth\n- [ ] sign off @risk"
    plan_engine = plan_sync.PlanSyncEngine(manager)  # type: ignore[arg-type]
    with patch.object(plan_sync.plan_compiler, "compile_plan", AsyncMock(return_value=compiled)):
        write = await plan_engine.compile_and_sync(_ROOM, converged)

    # The plan file exists with the agreed tasks, the title is set, and the plan was
    # broadcast as a knowledge push — the protocol's observable end state.
    got = read_memory_file(get_room_dir(_ROOM), plan_sync.PLAN_TASKS_KEY)
    assert got is not None
    _meta, body = got
    assert "ship the agreed cap @growth" in body
    assert plan.get_title(_ROOM) == "Smoke Plan"
    assert write is not None and write.content.startswith("# Smoke Plan")
    assert manager.channel.sent  # a knowledge broadcast went out
