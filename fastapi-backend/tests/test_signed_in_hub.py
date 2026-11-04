# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Two people, each with a machine and agents, sharing one hub with sign-in on.

Julia and Bob each sign in to the same hub with a token from one identity
provider, which names them under ``preferred_username`` and gives each an
opaque ``sub``. Each runs a runner on their own laptop with their own agents,
in one room. Everything goes through the real app and the real gate with real
signed tokens; only the provider's JWKS fetch is stubbed, and the room's SLIM
channel is one that sends nothing.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from httpx import AsyncClient

from app.routes.runners import runner_manifest
from app.services import room_channels, runners
from app.services.agent_registry import write_agent_manifest
from app.services.joins import joins
from app.services.persister import RoomPersister
from tests.issuer import SignedInHub, generate_key, sign
from tests.wake_paths import _QuietChannel

ROOM = "workshop"
JULIA, BOB = "julia", "bob"
JULIA_RUNNER, BOB_RUNNER = "julias-mbp", "bobs-laptop"
JULIA_AGENT, BOB_AGENT = "julia-coder", "bob-coder"
RUNNER_OF = {JULIA: JULIA_RUNNER, BOB: BOB_RUNNER}
AGENT_OF = {JULIA: JULIA_AGENT, BOB: BOB_AGENT}
KEY = {"x": "x" * 43, "y": "y" * 43}


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    runners.registry.clear()
    joins.clear()
    monkeypatch.setattr("app.routes.memory.embed_text", lambda _text: [0.0])
    yield
    runners.registry.clear()
    joins.clear()


def _hello(person: str, **over: Any) -> dict[str, Any]:
    """What ``mycelium runner`` on ``person``'s laptop says when it dials in."""
    body: dict[str, Any] = {
        "id": RUNNER_OF[person],
        "label": f"{person.title()}'s laptop",
        "owner": person,
        "platform": "darwin-arm64",
        "version": "3.0.75",
        "herdr": True,
        "roots": [f"/Users/{person}/code"],
        "frameworks": [
            {
                "id": "claude",
                "name": "Claude Code",
                "command": "claude",
                "installed": True,
                "launchable": True,
            }
        ],
        "agents": [],
    }
    body.update(over)
    return body


class Hub:
    """The shared hub, as Julia and Bob reach it from their own machines."""

    def __init__(self, client: AsyncClient, idp: SignedInHub) -> None:
        self.client = client
        self.idp = idp

    def as_(self, person: str) -> dict[str, str]:
        return self.idp.headers(person)

    async def get(self, person: str, path: str, **kw: Any):
        return await self.client.get(path, headers=self.as_(person), **kw)

    async def post(self, person: str, path: str, body: Any = None, **kw: Any):
        return await self.client.post(path, json=body, headers=self.as_(person), **kw)

    async def patch(self, person: str, path: str, body: Any, **kw: Any):
        return await self.client.patch(path, json=body, headers=self.as_(person), **kw)

    async def delete(self, person: str, path: str, **kw: Any):
        return await self.client.delete(path, headers=self.as_(person), **kw)

    async def hello(self, person: str, **over: Any) -> dict[str, Any]:
        resp = await self.post(person, "/api/runners", _hello(person, **over))
        assert resp.status_code == 200, resp.text
        return resp.json()

    async def launch(self, person: str) -> dict[str, Any]:
        """Start ``person``'s agent on their own machine, from the app."""
        resp = await self.post(
            person,
            f"/api/runners/{RUNNER_OF[person]}/agents",
            {"room": ROOM, "handle": AGENT_OF[person], "framework": "claude"},
        )
        assert resp.status_code == 201, resp.text
        return resp.json()

    async def say(self, person: str, text: str, *, token: str | None = None, sender=None):
        headers = {"Authorization": f"Bearer {token}"} if token else self.as_(person)
        return await self.client.post(
            f"/api/rooms/{ROOM}/messages",
            json={
                "sender_handle": sender or person,
                "message_type": "broadcast",
                "content": text,
            },
            headers=headers,
        )


@pytest.fixture
async def hub(client: AsyncClient, signed_in_hub: SignedInHub) -> Hub:
    """Julia's room on the shared hub, and both laptops dialed in."""
    shared = Hub(client, signed_in_hub)
    made = await shared.post(JULIA, "/api/rooms", {"name": ROOM, "is_public": True})
    assert made.status_code in (200, 201), made.text
    await shared.hello(JULIA)
    await shared.hello(BOB)
    return shared


# ── 1. who the hub says you are ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_handle_comes_from_preferred_username_not_the_opaque_sub(hub: Hub):
    resp = await hub.get(JULIA, "/api/whoami")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    sub = hub.idp.subject(JULIA)
    assert body["gated"] is True
    assert body["handle"] == JULIA
    assert body["subject"] == sub
    assert body["role"] == "user"
    assert sub != JULIA

    def note(created_by: str) -> dict:
        return {"items": [{"key": "notes/plan", "value": "v", "created_by": created_by}]}

    memory = f"/api/rooms/{ROOM}/memory"
    # The write is hers by name, as whoami says it; her opaque id isn't a
    # handle she can write as.
    assert (await hub.post(JULIA, memory, note(sub))).status_code == 403
    wrote = await hub.post(JULIA, memory, note(body["handle"]))
    assert wrote.status_code == 201, wrote.text
    assert wrote.json()[0]["created_by"] == JULIA

    posted = await hub.say(JULIA, "morning")
    assert posted.status_code == 201, posted.text
    assert posted.json()["sender_handle"] == JULIA
    # Her token can't post as Bob.
    assert (await hub.say(JULIA, "hi", sender=BOB)).status_code == 403


# ── 2. each person's machine is theirs ───────────────────────────────────────


@pytest.mark.asyncio
async def test_each_person_lists_only_their_own_machine(hub: Hub):
    for person in (JULIA, BOB):
        listed = (await hub.get(person, "/api/runners")).json()
        assert [r["id"] for r in listed] == [RUNNER_OF[person]]
        assert listed[0]["owner"] == person


@pytest.mark.asyncio
async def test_julias_machine_is_not_found_for_bob(hub: Hub):
    await hub.launch(JULIA)
    runner = f"/api/runners/{JULIA_RUNNER}"
    stop = f"{runner}/agents/{ROOM}/{JULIA_AGENT}/stop"
    refused = {
        "read": await hub.get(BOB, runner),
        "jobs": await hub.get(BOB, f"{runner}/jobs"),
        "scan": await hub.post(BOB, f"{runner}/scan"),
        "restart": await hub.post(BOB, f"{runner}/restart", {"all": True}),
        "launch": await hub.post(
            BOB, f"{runner}/agents", {"room": ROOM, "handle": "sneaky", "framework": "claude"}
        ),
        "adopt": await hub.post(
            BOB, f"{runner}/adopt", {"room": ROOM, "handle": "sneaky", "pane": "w1:p1"}
        ),
        "stop": await hub.post(BOB, stop),
        "swarm": await hub.post(
            BOB, f"/api/rooms/{ROOM}/swarms", {"task": "x", "size": 2, "runner": JULIA_RUNNER}
        ),
    }
    assert {k: r.status_code for k, r in refused.items()} == dict.fromkeys(refused, 404)
    # Nothing Bob asked for was queued on Julia's machine, or written to the room.
    jobs = (await hub.get(JULIA, f"{runner}/jobs")).json()
    assert [j["kind"] for j in jobs] == ["launch"]
    assert (await hub.get(JULIA, f"/api/rooms/{ROOM}/memory/agents/sneaky")).status_code == 404

    # Julia herself is let through each of them.
    assert (await hub.post(JULIA, f"{runner}/scan")).status_code == 201


@pytest.mark.asyncio
async def test_bob_cannot_pair_with_julias_machine(hub: Hub):
    await hub.hello(JULIA, pairing_offers=["K7QM"])
    pair = {"code_id": "K7QM", "name": "bobs phone", "key": KEY, "proof": "p" * 43}
    assert (await hub.post(BOB, "/api/runners/pair", pair)).status_code == 404
    assert (await hub.post(JULIA, "/api/runners/pair", pair)).status_code == 201


# ── 3. the runner's own side is the runner's person's ────────────────────────


@pytest.mark.asyncio
async def test_bob_cannot_take_julias_jobs(hub: Hub):
    job = (await hub.post(JULIA, f"/api/runners/{JULIA_RUNNER}/scan")).json()
    taken = await hub.get(BOB, f"/api/runners/{JULIA_RUNNER}/jobs/next", params={"timeout": 0})
    assert taken.status_code == 404
    # Still queued for Julia's machine, which takes it.
    mine = await hub.get(JULIA, f"/api/runners/{JULIA_RUNNER}/jobs/next", params={"timeout": 0})
    assert mine.status_code == 200
    assert mine.json()["id"] == job["id"]


@pytest.mark.asyncio
async def test_bob_cannot_report_a_job_on_julias_machine(hub: Hub):
    job = (await hub.post(JULIA, f"/api/runners/{JULIA_RUNNER}/scan")).json()
    path = f"/api/runners/{JULIA_RUNNER}/jobs/{job['id']}"
    assert (await hub.patch(BOB, path, {"status": "failed", "error": "no"})).status_code == 404
    assert (await hub.get(JULIA, path)).json()["status"] == "queued"
    assert (await hub.patch(JULIA, path, {"status": "done"})).status_code == 200


@pytest.mark.asyncio
async def test_bob_cannot_say_goodbye_for_julias_machine(hub: Hub):
    assert (await hub.delete(BOB, f"/api/runners/{JULIA_RUNNER}")).status_code == 404
    assert [r["id"] for r in (await hub.get(JULIA, "/api/runners")).json()] == [JULIA_RUNNER]
    assert (await hub.delete(JULIA, f"/api/runners/{JULIA_RUNNER}")).status_code == 204
    assert (await hub.get(JULIA, "/api/runners")).json() == []


@pytest.mark.asyncio
async def test_a_runner_is_owned_by_its_token_not_by_what_it_declares(hub: Hub):
    said = await hub.hello(BOB, owner=JULIA)
    assert said["owner"] == BOB
    assert [r["id"] for r in (await hub.get(JULIA, "/api/runners")).json()] == [JULIA_RUNNER]
    # A runner that names no owner is still its person's.
    assert (await hub.hello(BOB, owner=None))["owner"] == BOB


@pytest.mark.asyncio
async def test_bob_cannot_take_over_julias_runner_id(hub: Hub):
    resp = await hub.post(BOB, "/api/runners", _hello(BOB, id=JULIA_RUNNER))
    assert resp.status_code == 409
    listed = (await hub.get(JULIA, "/api/runners")).json()
    assert [(r["id"], r["owner"]) for r in listed] == [(JULIA_RUNNER, JULIA)]


# ── 4. agents, join codes and member tokens ──────────────────────────────────


@pytest.mark.asyncio
async def test_each_persons_agent_is_theirs_and_only_they_get_its_code(hub: Hub):
    for person in (JULIA, BOB):
        await hub.launch(person)
    agents = (await hub.get(JULIA, f"/api/rooms/{ROOM}/agents")).json()
    owners = {a["handle"]: a.get("owner") for a in agents}
    assert owners[JULIA_AGENT] == JULIA
    assert owners[BOB_AGENT] == BOB

    joins_path = f"/api/rooms/{ROOM}/joins"
    assert (await hub.post(BOB, joins_path, {"handle": JULIA_AGENT})).status_code == 403
    invites = f"/api/rooms/{ROOM}/invites"
    assert (await hub.post(BOB, invites, {"handle": JULIA_AGENT})).status_code == 403
    made = await hub.post(JULIA, joins_path, {"handle": JULIA_AGENT})
    assert made.status_code == 201, made.text

    redeemed = await hub.client.post("/api/joins/redeem", json={"code": made.json()["code"]})
    assert redeemed.status_code == 200, redeemed.text
    member = redeemed.json()
    assert member["handle"] == JULIA_AGENT
    token = member["token"]
    assert token

    who = await hub.client.get("/api/whoami", headers={"Authorization": f"Bearer {token}"})
    assert (who.json()["handle"], who.json()["role"]) == (JULIA_AGENT, "agent")

    # The agent's token posts as the agent, never as the person who made its code.
    posted = await hub.say(JULIA_AGENT, "on it", token=token)
    assert posted.status_code == 201, posted.text
    assert posted.json()["sender_handle"] == JULIA_AGENT
    assert (await hub.say(JULIA, "as julia", token=token)).status_code == 403


# ── 5. a token the hub can't take is a readable 401 ──────────────────────────


def _expired(hub: Hub) -> dict[str, str]:
    now = int(time.time())
    return hub.idp.headers(JULIA, exp=now - 3600, iat=now - 7200)


def _unknown_issuer() -> dict[str, str]:
    """Julia's name, from a provider this hub doesn't trust."""
    stranger = sign(
        generate_key("stranger"),
        iss="https://elsewhere.test/realms/other",
        preferred_username=JULIA,
    )
    return {"Authorization": f"Bearer {stranger}"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("what", "says"),
    [("missing", "missing bearer token"), ("expired", "expired"), ("unknown", "untrusted issuer")],
)
async def test_a_bad_token_is_a_readable_401(hub: Hub, what: str, says: str):
    headers = {"missing": {}, "expired": _expired(hub), "unknown": _unknown_issuer()}[what]
    read = await hub.client.get(f"/api/rooms/{ROOM}/messages", headers=headers)
    write = await hub.client.post(
        f"/api/rooms/{ROOM}/messages",
        json={"sender_handle": JULIA, "message_type": "broadcast", "content": "hi"},
        headers=headers,
    )
    for resp in (read, write):
        assert resp.status_code == 401, resp.text
        assert says in resp.json()["detail"].lower()
        assert resp.headers["WWW-Authenticate"].startswith("Bearer ")


# ── 6. a mention wakes the other person's agent, on their machine ────────────


def _live_room(monkeypatch: pytest.MonkeyPatch) -> None:
    """The room's channel as the hub runs it, over a channel that sends nothing."""
    manager = room_channels.manager
    monkeypatch.setattr(manager, "_herdr_wakes", {})
    monkeypatch.setattr(manager, "_herdr", {})
    monkeypatch.setattr(manager, "invite_in_background", lambda *_a, **_k: None)
    managed = room_channels.ManagedRoomChannel(
        room=ROOM,
        workspace="workshop",
        client=None,  # ty: ignore[invalid-argument-type]  # nothing here dials SLIM
        channel=_QuietChannel(),  # ty: ignore[invalid-argument-type]
    )
    managed.persister = RoomPersister(
        ROOM,
        channel=managed.channel,
        members_provider=lambda: set(),
        on_summon=manager._summon_adapter(ROOM),
        on_asked=manager._asked_adapter(ROOM),
        on_recorded=manager._recorded_adapter(ROOM),
        feed_bus=False,
    )
    monkeypatch.setitem(manager._channels, ROOM, managed)


async def _push(hub: Hub, person: str) -> None:
    """``person``'s machine's sync pass: its own agent's presence, as itself."""
    resp = await hub.post(
        person,
        f"/api/rooms/{ROOM}/sessions/herdr-presence",
        {
            "statuses": {AGENT_OF[person]: {"status": "idle", "title": None}},
            "ttl_s": 90,
            "source": RUNNER_OF[person],
        },
    )
    assert resp.status_code == 204, resp.text


async def _drain(hub: Hub, person: str) -> list[str]:
    """``person``'s machine taking its wakes, as its sync pass does."""
    resp = await hub.get(
        person,
        f"/api/rooms/{ROOM}/sessions/herdr-wakes",
        params={"source": RUNNER_OF[person]},
    )
    assert resp.status_code == 200, resp.text
    return [w["handle"] for w in resp.json()["wakes"]]


@pytest.mark.asyncio
async def test_a_mention_wakes_the_other_persons_agent_on_their_machine_every_round(
    hub: Hub, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr("app.config.settings.SLIM_ENABLED", True)
    _live_room(monkeypatch)
    for person in (JULIA, BOB):
        await hub.launch(person)

    for n in range(3):
        for asker, asked in ((JULIA, BOB), (BOB, JULIA)):
            for person in (JULIA, BOB):
                await _push(hub, person)
            said = await hub.say(asker, f"@{AGENT_OF[asked]} round {n}: can you take a look?")
            assert said.status_code == 201, said.text
            # The asker's machine drains first and is handed nothing.
            assert await _drain(hub, asker) == []
            assert await _drain(hub, asked) == [AGENT_OF[asked]]
            # Handed once: neither machine gets it again.
            assert await _drain(hub, asked) == []
            assert await _drain(hub, asker) == []


@pytest.mark.asyncio
async def test_bob_cannot_push_or_drain_as_julias_machine(
    hub: Hub, monkeypatch: pytest.MonkeyPatch
):
    """Naming another person's runner as ``source`` would replace its agents'
    presence or take its wakes; with sign-in on, a machine is only its person's."""
    _live_room(monkeypatch)
    await _push(hub, JULIA)
    presence = f"/api/rooms/{ROOM}/sessions/herdr-presence"
    pushed = await hub.post(
        BOB, presence, {"statuses": {BOB_AGENT: "idle"}, "ttl_s": 90, "source": JULIA_RUNNER}
    )
    assert pushed.status_code == 404
    room_channels.manager.enqueue_herdr_wake(ROOM, JULIA_AGENT, reason="assigned", key="work/x")
    drained = await hub.get(
        BOB, f"/api/rooms/{ROOM}/sessions/herdr-wakes", params={"source": JULIA_RUNNER}
    )
    assert drained.status_code == 404
    assert await _drain(hub, JULIA) == [JULIA_AGENT]


async def _member_token(hub: Hub, person: str) -> dict[str, str]:
    """The token ``person``'s agent holds once it has redeemed its join code."""
    made = await hub.post(person, f"/api/rooms/{ROOM}/joins", {"handle": AGENT_OF[person]})
    assert made.status_code == 201, made.text
    redeemed = await hub.client.post("/api/joins/redeem", json={"code": made.json()["code"]})
    assert redeemed.status_code == 200, redeemed.text
    return {"Authorization": f"Bearer {redeemed.json()['token']}"}


@pytest.mark.asyncio
async def test_a_persons_agent_can_sync_for_their_machine_and_no_one_elses(
    hub: Hub, monkeypatch: pytest.MonkeyPatch
):
    """``mycelium herdr sync`` run in an agent's pane carries the agent's token,
    not its person's. It is still that person's machine pushing, so their own
    agent may; another person's agent may not."""
    _live_room(monkeypatch)
    for person in (JULIA, BOB):
        await hub.launch(person)
    julias_agent, bobs_agent = await _member_token(hub, JULIA), await _member_token(hub, BOB)
    presence = f"/api/rooms/{ROOM}/sessions/herdr-presence"
    wakes = f"/api/rooms/{ROOM}/sessions/herdr-wakes"
    body = {"statuses": {JULIA_AGENT: {"status": "idle", "title": None}}, "ttl_s": 90}

    pushed = await hub.client.post(
        presence, json={**body, "source": JULIA_RUNNER}, headers=julias_agent
    )
    assert pushed.status_code == 204, pushed.text
    room_channels.manager.enqueue_herdr_wake(ROOM, JULIA_AGENT, reason="assigned", key="work/x")
    taken = await hub.client.get(wakes, params={"source": JULIA_RUNNER}, headers=julias_agent)
    assert taken.status_code == 200, taken.text
    assert [w["handle"] for w in taken.json()["wakes"]] == [JULIA_AGENT]

    refused = await hub.client.post(
        presence, json={**body, "source": JULIA_RUNNER}, headers=bobs_agent
    )
    assert refused.status_code == 404
    room_channels.manager.enqueue_herdr_wake(ROOM, JULIA_AGENT, reason="assigned", key="work/y")
    stolen = await hub.client.get(wakes, params={"source": JULIA_RUNNER}, headers=bobs_agent)
    assert stolen.status_code == 404
    assert await _drain(hub, JULIA) == [JULIA_AGENT]


@pytest.mark.asyncio
async def test_letting_julia_act_as_bobs_agent_doesnt_make_it_hers(
    hub: Hub, monkeypatch: pytest.MonkeyPatch
):
    """``allow_from`` lets julia act as bob's agent; it doesn't make bob's agent
    julia's, so it still can't sync for her machine."""
    _live_room(monkeypatch)
    for person in (JULIA, BOB):
        await hub.launch(person)
    manifest = runner_manifest(
        framework="claude", runner=BOB_RUNNER, cwd=None, description="", owner=BOB
    )
    await write_agent_manifest(
        ROOM, BOB_AGENT, {**manifest, "allow_from": [JULIA]}, created_by=BOB, principal=BOB
    )
    bobs_agent = await _member_token(hub, BOB)

    pushed = await hub.client.post(
        f"/api/rooms/{ROOM}/sessions/herdr-presence",
        json={"statuses": {BOB_AGENT: "idle"}, "ttl_s": 90, "source": JULIA_RUNNER},
        headers=bobs_agent,
    )
    assert pushed.status_code == 404
    drained = await hub.client.get(
        f"/api/rooms/{ROOM}/sessions/herdr-wakes",
        params={"source": JULIA_RUNNER},
        headers=bobs_agent,
    )
    assert drained.status_code == 404
