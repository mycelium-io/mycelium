# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Backend-as-moderator SLIM channel provisioning for rooms (Step 3, bible §9).

Creating/opening a room **provisions a SLIM group channel**, and the always-on
backend is its **moderator** — it creates the group session and invites members
as they join. This registry holds one long-lived moderator session per room,
tracks membership (SLIM's built-in presence), and enforces the episode↔channel
lifecycle (a mid-episode membership change aborts the episode; the channel is
untouched).

Everything here is **best-effort**. When no node is reachable (or no wheel is
installed), the calls degrade to no-ops so room CRUD and the unit suite stay
green without a live fabric — the sole failure mode is "no SLIM channel," never
"room create failed." A node-reachability pre-flight keeps the no-node path fast.

Out of scope (Step 4): the durable inbox/persister that records the transcript
and re-serves missed messages. This module provisions and invites; it does **not**
run a receive loop.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from app.config import settings
from app.services import l9
from app.services.l9_slim import (
    EpisodeLifecycle,
    L9SlimChannel,
    build_episode_abort_envelope,
)
from app.services.slim_client import (
    SlimClient,
    SlimIdentity,
    node_reachable,
    to_channel_name,
    to_slim_name,
)

logger = logging.getLogger(__name__)

# The moderator's app id (third Name segment) on every room channel. Distinct
# from any real agent handle so it never collides with a participant, and
# filtered out of presence.
BACKEND_AGENT = "backend"


@dataclass
class ManagedRoomChannel:
    """One backend-moderated room channel and its live membership/episode state."""

    room: str
    workspace: str
    client: SlimClient
    channel: L9SlimChannel
    members: set[str] = field(default_factory=set)
    lifecycle: EpisodeLifecycle = field(default_factory=EpisodeLifecycle)


class RoomChannelManager:
    """Registry of backend-moderated room channels (one per room, per process)."""

    def __init__(self, *, endpoint: str, default_workspace: str) -> None:
        self._endpoint = endpoint
        self._default_workspace = default_workspace
        self._channels: dict[str, ManagedRoomChannel] = {}
        self._lock = asyncio.Lock()
        # Strong refs to in-flight background invites (see invite_in_background).
        self._tasks: set[asyncio.Task[bool]] = set()

    def get(self, room: str) -> ManagedRoomChannel | None:
        return self._channels.get(room)

    def is_live(self, room: str) -> bool:
        """True when a SLIM channel is provisioned for ``room``."""
        return room in self._channels

    def members(self, room: str) -> list[str]:
        """Agent handles currently on the room channel (moderator excluded)."""
        managed = self._channels.get(room)
        return sorted(managed.members) if managed is not None else []

    async def provision(
        self, room: str, *, workspace: str | None = None
    ) -> ManagedRoomChannel | None:
        """Provision (idempotently) the moderated group channel for ``room``.

        Returns the managed channel, or ``None`` when SLIM is disabled/unreachable
        or the handshake fails — in every ``None`` case the caller carries on
        without a fabric. Never raises.
        """
        if not settings.SLIM_ENABLED:
            return None
        existing = self._channels.get(room)
        if existing is not None:
            return existing
        if not node_reachable(self._endpoint):
            logger.debug(
                "SLIM node unreachable at %s; skipping channel for %s", self._endpoint, room
            )
            return None

        async with self._lock:
            existing = self._channels.get(room)
            if existing is not None:
                return existing
            ws = workspace or self._default_workspace
            try:
                identity = SlimIdentity(ws, room, BACKEND_AGENT)
                client = await SlimClient(identity).connect(self._endpoint)
                session = await client.create_group(to_channel_name(ws, room))
            except Exception as exc:
                logger.warning("SLIM channel provisioning failed for room %s: %s", room, exc)
                return None
            managed = ManagedRoomChannel(
                room=room, workspace=ws, client=client, channel=L9SlimChannel(client, session)
            )
            self._channels[room] = managed
            logger.info("Provisioned SLIM channel for room %s (workspace=%s)", room, ws)
            return managed

    async def invite(self, room: str, agent: str) -> bool:
        """Invite ``agent`` into the room channel. Best-effort; returns success."""
        managed = self._channels.get(room)
        if managed is None or agent == BACKEND_AGENT:
            return False
        try:
            member = to_slim_name(managed.workspace, room, agent)
            await managed.client.invite(managed.channel.session, member)
        except Exception as exc:
            # Expected in Step 3: agents don't hold a SLIM connection until the
            # daemon is retargeted (Step 5), so the moderator can't reach them to
            # invite. Presence then falls back to local_state. Debug, not warn.
            logger.debug("SLIM invite skipped (room=%s agent=%s): %s", room, agent, exc)
            return False
        managed.members.add(agent)
        await self._enforce_membership_change(managed)
        return True

    def invite_in_background(self, room: str, agent: str) -> None:
        """Schedule :meth:`invite` without blocking the caller.

        The SLIM invite handshake retries against an absent member before
        failing, so awaiting it in an HTTP join would stall the request for the
        whole retry budget. Until agents hold their own SLIM connection (Step 5),
        that failure is the norm — so fire-and-forget: the join returns at once
        and ``members`` updates if/when the invite lands. ``invite`` swallows its
        own errors, so the task never raises.
        """
        if self._channels.get(room) is None:
            return
        task = asyncio.create_task(self.invite(room, agent))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def remove(self, room: str, agent: str) -> bool:
        """Remove ``agent`` from the room channel. Best-effort; returns success."""
        managed = self._channels.get(room)
        if managed is None or agent not in managed.members:
            return False
        try:
            member = to_slim_name(managed.workspace, room, agent)
            await managed.client.remove_member(managed.channel.session, member)
        except Exception as exc:
            logger.debug("SLIM remove skipped (room=%s agent=%s): %s", room, agent, exc)
            return False
        managed.members.discard(agent)
        await self._enforce_membership_change(managed)
        return True

    def open_episode(self, room: str, episode: str) -> bool:
        """Open a negotiation episode over the room's current membership.

        Freezes membership: a subsequent join/leave aborts it (bible §9, §12).
        """
        managed = self._channels.get(room)
        if managed is None:
            return False
        managed.lifecycle.open(episode, managed.members)
        return True

    async def _enforce_membership_change(self, managed: ManagedRoomChannel) -> None:
        """Abort the active episode if membership changed under it."""
        if not managed.lifecycle.on_membership_change(managed.members):
            return
        episode = managed.lifecycle.episode
        managed.lifecycle.close()
        if not episode:
            return
        logger.info("Membership change aborted episode %s on room %s", episode, managed.room)
        try:
            envelope = build_episode_abort_envelope(
                episode, recipients=sorted(managed.members), topic=l9.topic_urn(managed.room)
            )
            await managed.channel.send(envelope)
        except Exception as exc:  # pragma: no cover - best-effort notify
            logger.warning("Failed to publish episode abort for %s: %s", episode, exc)

    async def close(self, room: str) -> None:
        """Tear down the room's channel (moderator leaves; connection dropped)."""
        managed = self._channels.pop(room, None)
        if managed is None:
            return
        await managed.client.close()
        logger.info("Closed SLIM channel for room %s", room)

    async def close_all(self) -> None:
        """Tear down every channel and drop the shared connection (shutdown)."""
        for task in list(self._tasks):
            task.cancel()
        self._tasks.clear()
        for room in list(self._channels):
            await self.close(room)
        from app.services.slim_client import close_connection

        await close_connection(self._endpoint)


# Process-wide registry: the backend is a single always-on process, so one
# moderator per room lives here.
manager = RoomChannelManager(
    endpoint=settings.SLIM_NODE_ENDPOINT,
    default_workspace=settings.SLIM_WORKSPACE,
)
