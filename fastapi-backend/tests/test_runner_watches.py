# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Watching an agent's terminal: asked of the machine as a job, screens only after a yes.

The hub carries the newest screen and nothing older; a watch ends when the
viewer closes it, when the machine declines, or when the runner says the pane
went, and the runner hears on its next send.
"""

from __future__ import annotations

import pytest

from app.services import runners
from app.services.watches import watches

ROOM = "general-engineering"
RUNNER = "julias-mbp"

SCOUT = {
    "handle": "scout",
    "room": ROOM,
    "framework": "claude",
    "status": "idle",
    "pane": "w1-p2",
    "started_at": "2026-09-28T10:00:00Z",
}


@pytest.fixture(autouse=True)
def _fresh():
    runners.registry.clear()
    watches.clear()
    yield
    runners.registry.clear()
    watches.clear()


@pytest.fixture
async def runner(client) -> str:
    body = {
        "id": RUNNER,
        "label": "Julia's MacBook",
        "owner": "julia",
        "platform": "darwin-arm64",
        "version": "1.0.0",
        "herdr": True,
        "roots": ["/Users/julia/code"],
        "frameworks": [],
        "agents": [SCOUT],
    }
    resp = await client.post("/api/runners", json=body)
    assert resp.status_code == 200, resp.text
    return RUNNER


async def _watch(client) -> str:
    resp = await client.post(f"/api/runners/{RUNNER}/agents/{ROOM}/scout/watch")
    assert resp.status_code == 201, resp.text
    job = resp.json()
    assert job["kind"] == "watch"
    assert job["spec"] == {"room": ROOM, "handle": "scout"}
    return job["id"]


async def _read(client, job_id: str, after: int = 0) -> dict:
    resp = await client.get(
        f"/api/runners/{RUNNER}/watches/{job_id}", params={"after": after, "timeout": 0}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _send(client, job_id: str, text: str, ended: str | None = None) -> bool:
    resp = await client.put(
        f"/api/runners/{RUNNER}/watches/{job_id}", json={"text": text, "ended": ended}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["keep"]


@pytest.mark.asyncio
async def test_watching_is_a_job_for_the_machine_and_shows_nothing_before_a_yes(client, runner):
    job_id = await _watch(client)
    taken = (await client.get(f"/api/runners/{RUNNER}/jobs/next", params={"timeout": 0})).json()
    assert taken["id"] == job_id

    # Asked on the machine; nothing has been sent.
    assert await _read(client, job_id) == {"id": job_id, "screen": None, "ended": None}


@pytest.mark.asyncio
async def test_a_watch_names_an_agent_the_runner_runs(client, runner):
    resp = await client.post(f"/api/runners/{RUNNER}/agents/{ROOM}/someone-else/watch")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_the_viewer_reads_each_newer_screen_and_only_the_newest(client, runner):
    job_id = await _watch(client)
    assert await _send(client, job_id, "\x1b[1mone\x1b[0m")
    assert await _send(client, job_id, "two")

    read = await _read(client, job_id)
    assert read["screen"]["seq"] == 2
    assert read["screen"]["text"] == "two"
    # Nothing newer yet: no screen, and not over.
    assert (await _read(client, job_id, after=2))["screen"] is None


@pytest.mark.asyncio
async def test_closing_a_watch_stops_the_runner_on_its_next_send(client, runner):
    job_id = await _watch(client)
    assert await _send(client, job_id, "one")
    assert (await client.delete(f"/api/runners/{RUNNER}/watches/{job_id}")).status_code == 204

    assert await _send(client, job_id, "two") is False
    assert (await _read(client, job_id, after=1))["ended"] == "Closed."


@pytest.mark.asyncio
async def test_a_declined_watch_tells_the_viewer_why(client, runner):
    job_id = await _watch(client)
    await client.get(f"/api/runners/{RUNNER}/jobs/next", params={"timeout": 0})
    await client.patch(
        f"/api/runners/{RUNNER}/jobs/{job_id}",
        json={"status": "failed", "error": "Declined on Julia's MacBook."},
    )
    assert (await _read(client, job_id))["ended"] == "Declined on Julia's MacBook."


@pytest.mark.asyncio
async def test_the_runner_says_when_the_pane_went(client, runner):
    job_id = await _watch(client)
    assert await _send(client, job_id, "last screen", ended="@scout's pane closed.") is False
    read = await _read(client, job_id)
    assert read["screen"]["text"] == "last screen"
    assert read["ended"] == "@scout's pane closed."


@pytest.mark.asyncio
async def test_a_watch_nobody_reads_ends(client, runner, monkeypatch):
    from datetime import timedelta

    from app.services import watches as watch_module

    job_id = await _watch(client)
    monkeypatch.setattr(watch_module, "VIEWER_GONE_AFTER", timedelta(seconds=-1))
    assert await _send(client, job_id, "anyone?") is False


@pytest.mark.asyncio
async def test_another_runner_cant_send_into_a_watch(client, runner):
    job_id = await _watch(client)
    resp = await client.put(f"/api/runners/someone-else/watches/{job_id}", json={"text": "x"})
    assert resp.json()["keep"] is False
    assert (await _read(client, job_id))["screen"] is None
