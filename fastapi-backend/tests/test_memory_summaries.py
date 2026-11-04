# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The light memory list: each memory's title and frontmatter, not its text.

A list of many reads this; one memory's text is read by its key.
"""

import pytest
from httpx import AsyncClient

from app.routes.memory import memory_title

ROOM = "checkout"
LONG = "Fix the double charge " * 20


async def _write(client: AsyncClient, *items: dict) -> None:
    await client.post("/api/rooms", json={"name": ROOM})
    resp = await client.post(
        f"/api/rooms/{ROOM}/memory",
        json={"items": [{"created_by": "builder", "embed": False, **i} for i in items]},
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_a_summary_names_each_memory_and_carries_none_of_its_text(client: AsyncClient):
    await _write(
        client,
        {"key": "context/refunds", "value": "# Refund policy\n\nRefund a double charge in full."},
        {"key": "context/tax", "value": {"title": "Tax on large orders", "rate": 0.2}},
        {"key": "context/limits", "value": {"max_items": 40}},
        {"key": "context/long", "value": LONG, "tags": ["checkout"], "meta": {"owner": "design"}},
    )
    resp = await client.get(f"/api/rooms/{ROOM}/memory/summaries", params={"limit": 50})
    assert resp.status_code == 200, resp.text
    assert "Refund a double charge in full" not in resp.text
    by_key = {s["key"]: s for s in resp.json()}
    # Named by its rendered first line, as the app names it.
    assert by_key["context/limits"]["title"] == "max_items: 40"
    assert by_key["context/refunds"]["title"] == "Refund policy"
    assert by_key["context/refunds"]["structured"] is False
    assert by_key["context/tax"]["title"] == "Tax on large orders"
    assert by_key["context/tax"]["structured"] is True
    assert by_key["context/limits"]["structured"] is True
    long = by_key["context/long"]
    assert long["title"] == LONG.strip()[:120]
    assert long["tags"] == ["checkout"]
    assert long["meta"] == {"owner": "design"}
    assert long["version"] == 1
    assert long["created_by"] == "builder"
    assert "value" not in long
    assert "content_text" not in long


@pytest.mark.asyncio
async def test_summaries_page_filter_and_cache_like_the_full_list(client: AsyncClient):
    await _write(
        client,
        {"key": "work/refund-webhook", "value": "Write tests for the refund webhook"},
        {"key": "work/receipt-email", "value": "Fix the receipt email"},
        {"key": "context/notes", "value": "Notes"},
    )
    full = (await client.get(f"/api/rooms/{ROOM}/memory", params={"prefix": "work/"})).json()
    resp = await client.get(f"/api/rooms/{ROOM}/memory/summaries", params={"prefix": "work/"})
    assert [s["key"] for s in resp.json()] == [m["key"] for m in full]

    first = await client.get(
        f"/api/rooms/{ROOM}/memory/summaries", params={"limit": 1, "offset": 0}
    )
    second = await client.get(
        f"/api/rooms/{ROOM}/memory/summaries", params={"limit": 1, "offset": 1}
    )
    assert first.json()[0]["key"] != second.json()[0]["key"]

    etag = resp.headers["etag"]
    again = await client.get(
        f"/api/rooms/{ROOM}/memory/summaries",
        params={"prefix": "work/"},
        headers={"If-None-Match": etag},
    )
    assert again.status_code == 304


@pytest.mark.asyncio
async def test_summaries_of_a_room_that_isnt_there_are_a_404(client: AsyncClient):
    resp = await client.get("/api/rooms/no-such-room/memory/summaries")
    assert resp.status_code == 404


@pytest.mark.parametrize(
    ("value", "content", "title"),
    [
        ({"title": "  Tax on large orders  ", "text": "x"}, "x", "Tax on large orders"),
        ({"title": "   ", "text": "Refund policy"}, "Refund policy", "Refund policy"),
        ("\n\n---\n## Receipt email\nbody", None, "Receipt email"),
        ({"text": "\n---\n# Coupons\n"}, None, "Coupons"),
        ({"rate": 0.2}, "rate: 0.2", "rate: 0.2"),
        ({}, None, "context/empty"),
        (["refunds", "tax"], "- refunds\n- tax", "- refunds"),
        ({"text": "---\n---\n"}, None, "context/empty"),
    ],
)
def test_a_title_is_derived_as_the_app_derives_it(value, content, title):
    assert memory_title("context/empty", value, content) == title
