# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Every case in ``contracts/asks.json``, through every path that acts on it.

Each case is one message, written the way its sender writes it (``wake_paths``
sends it through the real route or engine call), and one agent. The doorbell,
``await`` and the wake digest must each give the contract's answer, and so
must ``asks()`` on the message as the transcript recorded it. A herdr agent
asked is rung with the reason, and a turn also goes to the members the hub
plays, which have no doorbell.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.services.asks import asks
from tests import wake_paths
from tests.wake_paths import AGENT, HERDR, Decided

_CONTRACT_PATH = Path(__file__).resolve().parent.parent.parent / "contracts" / "asks.json"
CASES: list[dict[str, Any]] = json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))["cases"]


def test_the_contract_names_each_case_once():
    names = [c["case"] for c in CASES]
    assert len(names) == len(set(names))
    assert {c["asks"] for c in CASES} == {None, "mention", "turn", "interrupt"}


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=[c["case"] for c in CASES])
async def test_every_path_gives_the_contract_s_answer(case: dict, client, monkeypatch) -> None:
    agent = case.get("agent", AGENT)
    reason = case["asks"]
    room = await wake_paths.open_room(client, monkeypatch)
    start = wake_paths.mark_read(room, agent)
    await wake_paths.say(
        room,
        case["sender"],
        case.get("text", ""),
        where=case.get("where", "room"),
        to=tuple(case.get("to", ())),
        shape=case.get("shape"),
    )

    # The rule itself, on what the transcript recorded.
    recorded = room.log.records[start:]
    assert recorded, "the case wrote nothing"
    found = {why for r in recorded if (why := asks(r.content, agent))}
    assert found == ({reason} if reason else set())

    turned = agent in room.turns
    got = await wake_paths.decided(room, agent)
    rung = reason if agent in HERDR else None
    assert got == Decided(doorbell=rung, awaited=bool(reason), digest=bool(reason))
    # The members the hub plays hear every turn (each answers its own); nothing
    # else is one.
    assert turned == (reason == "turn")
