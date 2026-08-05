# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Step 3 DoD harness: an L9 envelope round-trips over a SLIM group channel.

Runs a moderator and a participant in one process against a running ``slim``
node. The moderator creates a room channel and invites the participant; the
participant publishes two causally-linked L9 ``exchange`` envelopes (a root and a
child parented on it); the moderator receives them through :class:`L9SlimChannel`
and parses them back, in causal order, with the envelope intact. Prints ``OK``
and exits 0 on success.

Usage (with a node on :46357, e.g. via ``mycelium hub host``)::

    cd fastapi-backend
    uv run python scripts/l9_slim_roundtrip.py
    # or point at another node:
    uv run python scripts/l9_slim_roundtrip.py http://127.0.0.1:46357

This is a manual DoD aid; the guarded pytest equivalent lives in
``tests/test_l9_over_slim_roundtrip.py``.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Allow `python scripts/l9_slim_roundtrip.py` from the backend root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import l9
from app.services.l9_models import L9, Kind
from app.services.l9_slim import L9SlimChannel
from app.services.room_channels import RoomChannelManager
from app.services.slim_client import (
    DEFAULT_NODE_ENDPOINT,
    SlimClient,
    SlimIdentity,
    to_channel_name,
    to_slim_name,
)

_WORKSPACE = "acme"
_ROOM = "l9-room"
_EPISODE = l9.episode_urn(_ROOM, "roundtrip")
_TOPIC = l9.topic_urn(_ROOM)
_ROOT_ID = "root-envelope-id"
_CHILD_ID = "child-envelope-id"


def _root_envelope() -> L9:
    return l9.build_envelope(
        kind=Kind.exchange,
        episode=_EPISODE,
        topic=_TOPIC,
        message_id=_ROOT_ID,
        payload_type="tick",
        payload_data={"round": 1, "action": "offer"},
    )


def _child_envelope() -> L9:
    return l9.build_envelope(
        kind=Kind.exchange,
        episode=_EPISODE,
        parents=[_ROOT_ID],
        topic=_TOPIC,
        message_id=_CHILD_ID,
        payload_type="reply",
        payload_data={"round": 1, "action": "accept"},
    )


async def run_roundtrip(endpoint: str = DEFAULT_NODE_ENDPOINT) -> list[L9]:
    """Exchange two L9 envelopes participant→moderator; return what the moderator parsed."""
    moderator = await SlimClient(SlimIdentity(_WORKSPACE, _ROOM, "backend")).connect(endpoint)
    participant = await SlimClient(SlimIdentity(_WORKSPACE, _ROOM, "agent-a")).connect(endpoint)

    channel = to_channel_name(_WORKSPACE, _ROOM)
    session = await moderator.create_group(channel)
    mod_channel = L9SlimChannel(moderator, session)

    participant_name = to_slim_name(_WORKSPACE, _ROOM, "agent-a")

    async def participant_side() -> None:
        joined = await participant.listen_for_session()
        part_channel = L9SlimChannel(participant, joined)
        await part_channel.send(_root_envelope())
        await part_channel.send(_child_envelope())

    participant_task = asyncio.create_task(participant_side())
    received: list[L9] = []
    try:
        await moderator.invite(session, participant_name)
        # Two publishes → collect until both root and child have been released.
        while len(received) < 2:
            received.extend(await mod_channel.receive(timeout_s=15.0))
    finally:
        await participant_task
        await moderator.close()
        await participant.close()

    return received


_ABORT_ROOM = "l9-abort-room"
_ABORT_EPISODE = l9.episode_urn(_ABORT_ROOM, "abort-run")


async def run_episode_abort(endpoint: str = DEFAULT_NODE_ENDPOINT) -> L9:
    """Prove episode-abort-on-membership-change end-to-end.

    The backend (via :class:`RoomChannelManager`) provisions a channel, invites
    ``agent-a``, and opens an episode over that membership. Inviting ``agent-b``
    mid-episode is a membership change: the manager aborts the episode and
    publishes a ``commit:rejected``. ``agent-a`` receives it. Returns that
    envelope.
    """
    manager = RoomChannelManager(endpoint=endpoint, default_workspace=_WORKSPACE)
    await manager.provision(_ABORT_ROOM)

    agent_a = await SlimClient(SlimIdentity(_WORKSPACE, _ABORT_ROOM, "agent-a")).connect(endpoint)
    agent_b = await SlimClient(SlimIdentity(_WORKSPACE, _ABORT_ROOM, "agent-b")).connect(endpoint)

    try:
        # agent-a joins the channel (listen concurrently with the invite).
        a_listen = asyncio.create_task(agent_a.listen_for_session())
        await manager.invite(_ABORT_ROOM, "agent-a")
        a_session = await a_listen
        a_channel = L9SlimChannel(agent_a, a_session)

        # Open an episode frozen over {agent-a}; then agent-b joins mid-episode.
        manager.open_episode(_ABORT_ROOM, _ABORT_EPISODE)
        b_listen = asyncio.create_task(agent_b.listen_for_session())
        await manager.invite(_ABORT_ROOM, "agent-b")
        await b_listen  # ensure b is fully in the group

        # The membership change published a commit:rejected onto the channel.
        received: list[L9] = []
        while not received:
            received.extend(await a_channel.receive(timeout_s=15.0))
        return received[0]
    finally:
        await agent_a.close()
        await agent_b.close()
        await manager.close_all()


_INBOX_ROOM = "durable-inbox-room"
_INBOX_EPISODE = l9.episode_urn(_INBOX_ROOM, "inbox-run")
_HELLO_ID = "hello-from-a"
_MISSED_ID = "missed-while-offline"


def _agent_reply(sender: str, message_id: str) -> L9:
    return l9.build_envelope(
        kind=Kind.exchange,
        episode=_INBOX_EPISODE,
        sender=sender,
        recipients=[l9.SYSTEM_ACTOR_ID],
        topic=l9.topic_urn(_INBOX_ROOM),
        message_id=message_id,
        payload_type="reply",
        payload_data={"action": "offer"},
    )


async def _wait_for(pred, *, timeout: float = 10.0) -> None:
    """Poll ``pred`` until true (the persister processes on its own task)."""
    waited = 0.0
    while not pred():
        if waited >= timeout:
            raise TimeoutError("condition not met in time")
        await asyncio.sleep(0.1)
        waited += 0.1


async def run_durable_inbox(endpoint: str = DEFAULT_NODE_ENDPOINT) -> list[L9]:
    """Prove the durable inbox end-to-end (Step 4 DoD).

    The backend provisions a channel (starting its persister). ``agent-a`` joins
    and speaks once — so the persister has a reply route to it — then goes offline
    (dropped from membership). ``agent-b`` broadcasts a message while ``agent-a``
    is gone; SLIM does *not* retain it (bible §7d). ``agent-a`` reconnects
    (re-invited): the persister recognizes the reconnect and **re-serves** the
    missed message point-to-point. Returns what ``agent-a`` received on rejoin —
    the message it missed while offline.
    """
    manager = RoomChannelManager(endpoint=endpoint, default_workspace=_WORKSPACE)
    managed = await manager.provision(_INBOX_ROOM)
    assert managed is not None and managed.persister is not None
    persister = managed.persister

    agent_a = await SlimClient(SlimIdentity(_WORKSPACE, _INBOX_ROOM, "agent-a")).connect(endpoint)
    agent_b = await SlimClient(SlimIdentity(_WORKSPACE, _INBOX_ROOM, "agent-b")).connect(endpoint)

    try:
        # agent-a joins and speaks once so the persister caches its reply route.
        a_listen = asyncio.create_task(agent_a.listen_for_session())
        await manager.invite(_INBOX_ROOM, "agent-a")
        a_session = await a_listen
        await L9SlimChannel(agent_a, a_session).send(_agent_reply("agent-a", _HELLO_ID))
        await _wait_for(lambda: "agent-a" in persister._contexts)

        # agent-a goes offline: dropped from the channel membership.
        await manager.remove(_INBOX_ROOM, "agent-a")

        # agent-b joins and broadcasts while agent-a is gone.
        b_listen = asyncio.create_task(agent_b.listen_for_session())
        await manager.invite(_INBOX_ROOM, "agent-b")
        b_session = await b_listen
        await L9SlimChannel(agent_b, b_session).send(_agent_reply("agent-b", _MISSED_ID))
        await _wait_for(
            lambda: any(r.message_id == _MISSED_ID for r in persister.log.undelivered("agent-a"))
        )

        # agent-a reconnects (same app, new group session): the re-invite is a
        # membership add for a known handle → the persister re-serves the tail.
        a_relisten = asyncio.create_task(agent_a.listen_for_session())
        await manager.invite(_INBOX_ROOM, "agent-a")
        a_session2 = await a_relisten
        a_channel2 = L9SlimChannel(agent_a, a_session2)

        received: list[L9] = []
        while not received:
            received.extend(await a_channel2.receive(timeout_s=15.0))
        return received
    finally:
        await agent_a.close()
        await agent_b.close()
        await manager.close_all()


_ALIGN_ROOM = "aligner-room"
_ALIGN_EPISODE = l9.episode_urn(_ALIGN_ROOM, "live")


def _align_position(sender: str, confidence: float, message_id: str) -> L9:
    return l9.build_envelope(
        kind=Kind.exchange,
        episode=_ALIGN_EPISODE,
        sender=sender,
        sender_role="agent",
        recipients=[l9.SYSTEM_ACTOR_ID],
        topic=l9.topic_urn(_ALIGN_ROOM),
        message_id=message_id,
        payload_type="reply",
        payload_data={"action": "accept", "confidence": confidence},
    )


def _align_summon() -> L9:
    """A human's ``@aligner`` summon (role human → not scored as a position)."""
    return l9.build_envelope(
        kind=Kind.exchange,
        episode=_ALIGN_EPISODE,
        sender="human",
        sender_role="human",
        recipients=["aligner"],
        topic=l9.topic_urn(_ALIGN_ROOM),
        payload_type="message",
    )


async def run_aligner_observe(endpoint: str = DEFAULT_NODE_ENDPOINT) -> L9:
    """Prove the Step 7 observer DoD over a live node.

    The backend provisions a channel with the SIEP aligner wired to its summon
    seam. Two agents each publish a high-confidence position; a human then
    ``@aligner``-summons the engine. The engine (observer mode) reads the
    transcript, scores it via ``l9_episode``, and broadcasts an L9
    ``commit:converged`` onto the channel. Returns the commit envelope a
    participant receives.
    """
    from app.services.aligner import AlignerEngine

    manager = RoomChannelManager(endpoint=endpoint, default_workspace=_WORKSPACE)
    engine = AlignerEngine(manager, handle="aligner", mode="observer", threshold=0.6)
    manager.on_summon = engine.handle_summon  # wire BEFORE provision so the persister picks it up
    managed = await manager.provision(_ALIGN_ROOM)
    assert managed is not None and managed.persister is not None
    persister = managed.persister

    agent_a = await SlimClient(SlimIdentity(_WORKSPACE, _ALIGN_ROOM, "agent-a")).connect(endpoint)
    agent_b = await SlimClient(SlimIdentity(_WORKSPACE, _ALIGN_ROOM, "agent-b")).connect(endpoint)

    try:
        a_listen = asyncio.create_task(agent_a.listen_for_session())
        b_listen = asyncio.create_task(agent_b.listen_for_session())
        await manager.invite(_ALIGN_ROOM, "agent-a")
        await manager.invite(_ALIGN_ROOM, "agent-b")
        a_channel = L9SlimChannel(agent_a, await a_listen)
        b_channel = L9SlimChannel(agent_b, await b_listen)

        # Two agents state a high-confidence position; wait until both are recorded.
        await a_channel.send(_align_position("agent-a", 0.8, "align-a"))
        await b_channel.send(_align_position("agent-b", 0.9, "align-b"))
        positions = {"align-a", "align-b"}
        await _wait_for(
            lambda: positions <= {r.message_id for r in persister.log.records}, timeout=15.0
        )

        # The human summons the aligner → the engine observes and emits the verdict.
        await a_channel.send(_align_summon(), extra={"content": "@aligner please converge"})

        commit: L9 | None = None
        while commit is None:
            for env in await b_channel.receive(timeout_s=15.0):
                if env.header.kind.value == "commit":
                    commit = env
                    break
        return commit
    finally:
        await agent_a.close()
        await agent_b.close()
        await manager.close_all()


async def run_aligner_converge_and_sync(
    endpoint: str = DEFAULT_NODE_ENDPOINT,
) -> tuple[L9, L9]:
    """Prove the Step 8 same-machine DoD over a live node.

    Extends :func:`run_aligner_observe`: after the aligner emits
    ``commit:converged``, the backend's plan-sync consumer (wired on
    ``on_converged``) compiles ``plan/tasks.md`` and broadcasts the compiled plan
    as an L9 ``knowledge`` message that **carries the content**. A participant
    receives both the ``commit`` and the ``knowledge`` push. Returns
    ``(commit_envelope, knowledge_envelope)`` — the caller asserts the plan file
    exists and applies the knowledge write to a *second* local store.
    """
    from app.services.aligner import AlignerEngine
    from app.services.plan_sync import PlanSyncEngine

    manager = RoomChannelManager(endpoint=endpoint, default_workspace=_WORKSPACE)
    aligner = AlignerEngine(manager, handle="aligner", mode="observer", threshold=0.6)
    plan_sync = PlanSyncEngine(manager)
    # Wire BOTH seams before provision so the persister picks them up.
    manager.on_summon = aligner.handle_summon
    manager.on_converged = plan_sync.handle_converged
    managed = await manager.provision(_ALIGN_ROOM)
    assert managed is not None and managed.persister is not None
    persister = managed.persister

    agent_a = await SlimClient(SlimIdentity(_WORKSPACE, _ALIGN_ROOM, "agent-a")).connect(endpoint)
    agent_b = await SlimClient(SlimIdentity(_WORKSPACE, _ALIGN_ROOM, "agent-b")).connect(endpoint)

    try:
        a_listen = asyncio.create_task(agent_a.listen_for_session())
        b_listen = asyncio.create_task(agent_b.listen_for_session())
        await manager.invite(_ALIGN_ROOM, "agent-a")
        await manager.invite(_ALIGN_ROOM, "agent-b")
        a_channel = L9SlimChannel(agent_a, await a_listen)
        b_channel = L9SlimChannel(agent_b, await b_listen)

        await a_channel.send(_align_position("agent-a", 0.8, "align-a"))
        await b_channel.send(_align_position("agent-b", 0.9, "align-b"))
        positions = {"align-a", "align-b"}
        await _wait_for(
            lambda: positions <= {r.message_id for r in persister.log.records}, timeout=15.0
        )

        await a_channel.send(_align_summon(), extra={"content": "@aligner please converge"})

        # Collect until BOTH the commit verdict and the knowledge plan-push land.
        commit: L9 | None = None
        knowledge: L9 | None = None
        while commit is None or knowledge is None:
            for env in await b_channel.receive(timeout_s=15.0):
                kind = env.header.kind.value
                if kind == "commit" and commit is None:
                    commit = env
                elif kind == "knowledge" and knowledge is None:
                    knowledge = env
        return commit, knowledge
    finally:
        await agent_a.close()
        await agent_b.close()
        await manager.close_all()


async def run_consent_and_knowledge_to_bus(
    endpoint: str = DEFAULT_NODE_ENDPOINT,
) -> set[str]:
    """Prove the Step 10 DoD's headless proxy for the browser demo.

    The UI never speaks SLIM: it reads the backend's in-process bus
    (``app.bus``), which the moderator's persister feeds every ingested channel
    message and onto which the consent path publishes ``consent_request``. This
    mirrors :func:`run_aligner_converge_and_sync` but subscribes to the bus and,
    once the compiled-plan ``knowledge`` push has crossed, raises a consent
    prompt for an absent agent. Returns the set of ``message_type`` values seen
    on the bus — the caller asserts ``l9_knowledge`` and ``consent_request`` are
    both present (the inspector's knowledge frame and the consent prompt).
    """
    from app.bus import bus, room_channel
    from app.services.aligner import AlignerEngine
    from app.services.plan_sync import PlanSyncEngine

    manager = RoomChannelManager(endpoint=endpoint, default_workspace=_WORKSPACE)
    aligner = AlignerEngine(manager, handle="aligner", mode="observer", threshold=0.6)
    plan_sync = PlanSyncEngine(manager)
    manager.on_summon = aligner.handle_summon
    manager.on_converged = plan_sync.handle_converged
    managed = await manager.provision(_ALIGN_ROOM)
    assert managed is not None and managed.persister is not None
    persister = managed.persister

    # Subscribe before inviting so no bus event is missed.
    queue = bus.subscribe(room_channel(_ALIGN_ROOM))
    seen: set[str] = set()

    agent_a = await SlimClient(SlimIdentity(_WORKSPACE, _ALIGN_ROOM, "agent-a")).connect(endpoint)
    agent_b = await SlimClient(SlimIdentity(_WORKSPACE, _ALIGN_ROOM, "agent-b")).connect(endpoint)
    try:
        a_listen = asyncio.create_task(agent_a.listen_for_session())
        b_listen = asyncio.create_task(agent_b.listen_for_session())
        await manager.invite(_ALIGN_ROOM, "agent-a")
        await manager.invite(_ALIGN_ROOM, "agent-b")
        a_channel = L9SlimChannel(agent_a, await a_listen)
        b_channel = L9SlimChannel(agent_b, await b_listen)

        await a_channel.send(_align_position("agent-a", 0.8, "align-a"))
        await b_channel.send(_align_position("agent-b", 0.9, "align-b"))
        await _wait_for(
            lambda: {"align-a", "align-b"} <= {r.message_id for r in persister.log.records},
            timeout=15.0,
        )

        await a_channel.send(_align_summon(), extra={"content": "@aligner please converge"})

        commit: L9 | None = None
        knowledge: L9 | None = None
        while commit is None or knowledge is None:
            for env in await b_channel.receive(timeout_s=15.0):
                kind = env.header.kind.value
                if kind == "commit" and commit is None:
                    commit = env
                elif kind == "knowledge" and knowledge is None:
                    knowledge = env

        # The human-in-the-room path: an @-invite of an absent agent raises the
        # consent prompt straight onto the bus (no SLIM hop needed).
        manager.request_invite(
            _ALIGN_ROOM, "ghost", requested_by="human", trigger_text="@ghost join us"
        )

        # Drain the bus until both events of interest have surfaced.
        while not {"l9_knowledge", "consent_request"} <= seen:
            payload = await asyncio.wait_for(queue.get(), timeout=15.0)
            mtype = str(payload.get("message_type") or "")
            if mtype:
                seen.add(mtype)
        return seen
    finally:
        bus.unsubscribe(room_channel(_ALIGN_ROOM), queue)
        await agent_a.close()
        await agent_b.close()
        await manager.close_all()


async def _main(endpoint: str) -> int:
    received = await run_roundtrip(endpoint)
    ids = [e.header.message.id for e in received if e.header.message is not None]
    if ids != [_ROOT_ID, _CHILD_ID]:
        print(f"MISMATCH — got {ids}, expected {[_ROOT_ID, _CHILD_ID]}", file=sys.stderr)
        return 1
    print(f"OK — moderator received in causal order: {ids}")

    abort = await run_episode_abort(endpoint)
    if abort.header.subkind != "rejected":
        print(f"MISMATCH — episode abort subkind {abort.header.subkind!r}", file=sys.stderr)
        return 1
    print(f"OK — mid-episode membership change aborted with commit:{abort.header.subkind}")

    inbox = await run_durable_inbox(endpoint)
    inbox_ids = [e.header.message.id for e in inbox if e.header.message is not None]
    if inbox_ids != [_MISSED_ID]:
        print(
            f"MISMATCH — durable inbox re-served {inbox_ids}, expected {[_MISSED_ID]}",
            file=sys.stderr,
        )
        return 1
    print(f"OK — durable inbox re-served missed message on reconnect: {inbox_ids}")

    commit = await run_aligner_observe(endpoint)
    if commit.header.subkind != "converged":
        print(f"MISMATCH — aligner verdict subkind {commit.header.subkind!r}", file=sys.stderr)
        return 1
    metrics = commit.payload.data.get("metrics") if commit.payload else None
    print(f"OK — aligner observed and emitted commit:{commit.header.subkind} (metrics={metrics})")
    return 0


if __name__ == "__main__":
    node = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_NODE_ENDPOINT
    raise SystemExit(asyncio.run(_main(node)))
