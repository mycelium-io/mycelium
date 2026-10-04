# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""POST /rooms/{room}/agents/draft-notes — a member's notes from a short brief.

What Pi is asked (the brief, the kind of member, the room's other members as
the only handles it may name), how its answer is cleaned, and that the route
returns the draft without writing anything, or says plainly when Pi failed.
"""

from __future__ import annotations

import pytest

from app.services import notes_draft
from app.services.filesystem import get_room_dir


def test_prompt_carries_brief_room_and_teammates() -> None:
    prompt = notes_draft.build_prompt(
        "reviews my PRs",
        handle="rev",
        room_title="Checkout",
        teammates=["rev", "builder", "tester"],
    )
    assert "reviews my PRs" in prompt
    assert "@rev" in prompt
    assert "Checkout" in prompt
    # Itself is not its own teammate.
    assert "the only handles you may name): @builder, @tester\n" in prompt
    assert "coding agent" in prompt


def test_prompt_without_teammates_names_nobody() -> None:
    prompt = notes_draft.build_prompt("plays a skeptical CFO", kind="persona")
    assert "Do not name any @handle." in prompt
    assert "in character" in prompt


def test_clean_strips_fence_and_heading() -> None:
    assert notes_draft.clean("```markdown\n# Notes\nYou review.\n```") == "You review."
    assert notes_draft.clean("  You review.\n") == "You review."


async def _make_room(client, name: str = "checkout") -> None:
    resp = await client.post("/api/rooms", json={"name": name})
    assert resp.status_code in (200, 201)


@pytest.mark.asyncio
async def test_route_returns_the_draft_and_writes_nothing(client, monkeypatch) -> None:
    await _make_room(client)
    asked: list[str] = []

    def fake(prompt: str, room: str) -> str:
        asked.append(prompt)
        return "```\nYou review every pull request.\n```"

    monkeypatch.setattr(notes_draft, "complete", fake)
    before = sorted(p.name for p in get_room_dir("checkout").rglob("*"))
    resp = await client.post(
        "/api/rooms/checkout/agents/draft-notes",
        json={"brief": "reviews PRs", "handle": "@Rev"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"notes": "You review every pull request."}
    assert "@rev" in asked[0]
    assert sorted(p.name for p in get_room_dir("checkout").rglob("*")) == before


@pytest.mark.asyncio
async def test_route_reports_a_failed_turn(client, monkeypatch) -> None:
    await _make_room(client)

    def boom(prompt: str, room: str) -> str:
        raise RuntimeError("pi exited 1")

    monkeypatch.setattr(notes_draft, "complete", boom)
    resp = await client.post("/api/rooms/checkout/agents/draft-notes", json={"brief": "x"})
    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_route_refuses_unknown_room_and_blank_brief(client) -> None:
    resp = await client.post("/api/rooms/nope/agents/draft-notes", json={"brief": "x"})
    assert resp.status_code == 404
    await _make_room(client)
    resp = await client.post("/api/rooms/checkout/agents/draft-notes", json={"brief": "   "})
    assert resp.status_code == 422
