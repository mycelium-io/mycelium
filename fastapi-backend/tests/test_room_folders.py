# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A person's room folders: stored per handle, theirs alone on a gated hub."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.services.filesystem import get_data_dir

LAYOUT = {
    "folders": [
        {"id": "f1", "name": "Payments", "rooms": ["checkout", "refunds"]},
        {"id": "f2", "name": " Side projects ", "rooms": ["scratch"], "collapsed": True},
    ]
}


def _url(handle: str) -> str:
    return f"/api/users/{handle}/room-folders"


@pytest.mark.asyncio
async def test_no_folders_yet_reads_as_empty(client: AsyncClient):
    resp = await client.get(_url("avery"))
    assert resp.status_code == 200
    assert resp.json() == {"folders": []}


@pytest.mark.asyncio
async def test_folders_round_trip(client: AsyncClient):
    put = await client.put(_url("avery"), json=LAYOUT)
    assert put.status_code == 200, put.text
    got = (await client.get(_url("avery"))).json()
    assert [f["name"] for f in got["folders"]] == ["Payments", "Side projects"]
    assert got["folders"][0]["rooms"] == ["checkout", "refunds"]
    assert got["folders"][1]["collapsed"] is True
    # Stored beside the user store, not in it.
    assert (get_data_dir() / "preferences" / "avery" / "room-folders.json").exists()


@pytest.mark.asyncio
async def test_each_person_has_their_own(client: AsyncClient):
    await client.put(_url("avery"), json=LAYOUT)
    assert (await client.get(_url("blake"))).json() == {"folders": []}


@pytest.mark.asyncio
async def test_a_room_is_filed_once(client: AsyncClient):
    """Two racing moves can't leave one room in two folders."""
    layout = {
        "folders": [
            {"id": "a", "name": "A", "rooms": ["checkout", "checkout"]},
            {"id": "b", "name": "B", "rooms": ["checkout", "scratch"]},
        ]
    }
    got = (await client.put(_url("avery"), json=layout)).json()
    assert got["folders"][0]["rooms"] == ["checkout"]
    assert got["folders"][1]["rooms"] == ["scratch"]


@pytest.mark.asyncio
async def test_a_handle_that_is_not_one_is_refused(client: AsyncClient):
    """The handle names a directory, so it has to be a handle."""
    resp = await client.put(_url("..%2Fescape"), json=LAYOUT)
    assert resp.status_code in (403, 404, 422)
    assert not (get_data_dir().parent / "escape").exists()


@pytest.mark.asyncio
async def test_a_gated_hub_keeps_your_folders_yours(client: AsyncClient, as_principal):
    as_principal("avery", role="user")
    assert (await client.put(_url("avery"), json=LAYOUT)).status_code == 200

    as_principal("mallory")
    assert (await client.get(_url("avery"))).status_code == 403
    assert (await client.put(_url("avery"), json={"folders": []})).status_code == 403

    as_principal("avery", role="user")
    assert len((await client.get(_url("avery"))).json()["folders"]) == 2
