# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The other paginated lists (issue #654).

Pagination is one primitive with one vocabulary — ``cursor`` in, ``next_cursor``
and ``has_more`` out — so a client that can walk one list can walk any of them.
Memory keeps a bare-list body, so it carries the same two values as headers;
these assert both spellings of the same contract.
"""

import pytest

from app.services import l9_episode


async def _seed_memories(client, room: str, count: int) -> None:
    await client.post("/api/rooms", json={"name": room})
    for i in range(count):
        await client.post(
            f"/api/rooms/{room}/memory",
            json={
                "items": [
                    {
                        "key": f"notes/n{i:02d}",
                        "value": f"note {i}",
                        "created_by": "avery",
                        "embed": False,
                    }
                ]
            },
        )


async def _seed_episodes(client, room: str, count: int) -> None:
    await client.post("/api/rooms", json={"name": room})
    for i in range(count):
        ep = l9_episode.open_episode(
            parent_room=room,
            short_id=f"ep{i:04d}",
            workspace_id="ws-1",
            mas_id="mas-1",
            agents=["alice"],
            joined_intents="- alice: ship it",
        )
        l9_episode.write_episode_record(ep, outcome="converged", metrics=None, plan_file=None)


@pytest.mark.asyncio
async def test_a_memory_walk_reaches_every_memory_exactly_once(client):
    await _seed_memories(client, "mem-room", 12)

    seen: list[str] = []
    cursor: str | None = None
    for _ in range(20):
        url = "/api/rooms/mem-room/memory?limit=5"
        if cursor:
            url += f"&cursor={cursor}"
        resp = await client.get(url)
        seen.extend(m["key"] for m in resp.json())
        if resp.headers["x-has-more"] == "false":
            break
        cursor = resp.headers["x-next-cursor"]
    else:
        pytest.fail("cursor walk did not terminate")

    assert sorted(seen) == [f"notes/n{i:02d}" for i in range(12)]
    assert len(seen) == len(set(seen))


@pytest.mark.asyncio
async def test_the_memory_list_reports_the_full_count_not_the_page(client):
    await _seed_memories(client, "mem-count-room", 7)

    resp = await client.get("/api/rooms/mem-count-room/memory?limit=3")

    assert len(resp.json()) == 3
    assert resp.headers["x-total-count"] == "7"
    assert resp.headers["x-has-more"] == "true"


@pytest.mark.asyncio
async def test_a_memory_page_past_the_end_reports_no_more(client):
    await _seed_memories(client, "mem-short-room", 2)

    resp = await client.get("/api/rooms/mem-short-room/memory?limit=50")

    assert resp.headers["x-has-more"] == "false"
    assert "x-next-cursor" not in resp.headers


@pytest.mark.asyncio
async def test_an_episode_walk_reaches_every_episode_exactly_once(client):
    await _seed_episodes(client, "ep-room", 9)

    seen: list[str] = []
    cursor: str | None = None
    for _ in range(20):
        url = "/api/rooms/ep-room/episodes?limit=4"
        if cursor:
            url += f"&cursor={cursor}"
        body = (await client.get(url)).json()
        seen.extend(e["short_id"] for e in body["episodes"])
        if not body["has_more"]:
            break
        cursor = body["next_cursor"]
    else:
        pytest.fail("cursor walk did not terminate")

    assert sorted(seen) == [f"ep{i:04d}" for i in range(9)]
    assert len(seen) == len(set(seen))


def test_an_in_progress_episode_sorts_ahead_of_every_closed_one():
    """The episode list's one ordering quirk has to be part of the sort, not an
    insert after it — otherwise a live episode drifts onto a later page mid-walk."""
    from app.routes.episodes import _episode_sort_key

    live = {"short_id": "livexx", "outcome": "open", "updated_at": ""}
    newest_closed = {"short_id": "ep0009", "outcome": "converged", "updated_at": "2099-01-01"}

    assert sorted([newest_closed, live], key=_episode_sort_key, reverse=True)[0] is live


@pytest.mark.asyncio
async def test_a_bad_cursor_is_rejected_by_every_list(client):
    await _seed_memories(client, "bad-room", 2)
    await _seed_episodes(client, "bad-ep-room", 2)

    assert (await client.get("/api/rooms/bad-room/memory?cursor=%%%")).status_code == 400
    assert (await client.get("/api/rooms/bad-ep-room/episodes?cursor=%%%")).status_code == 400
