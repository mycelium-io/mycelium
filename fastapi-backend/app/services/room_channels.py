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

Step 4 adds the durable inbox/persister: on provision the moderator starts a
long-lived :class:`~app.services.persister.RoomPersister` that consumes the
channel — recording the transcript, re-serving missed messages to reconnecting
members, and watching for ``@``-summon / ``commit:converged`` triggers. This
module owns that task's start/stop lifecycle and surfaces the reconnect signal
(a membership add for a handle the persister has seen before) into a re-serve.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.config import settings
from app.services import l9
from app.services.invites import ACCEPTED, DECLINED, QUEUED, PendingInvite, PendingInviteRegistry
from app.services.l9_models import Kind
from app.services.l9_slim import (
    EpisodeLifecycle,
    L9SlimChannel,
    build_episode_abort_envelope,
    serialize_content,
)
from app.services.persister import ConvergedHook, RoomPersister, SummonHook, parse_mentions
from app.services.slim_client import (
    SlimClient,
    SlimIdentity,
    node_reachable,
    to_channel_name,
    to_slim_name,
)

if TYPE_CHECKING:
    from app.services.l9_models import L9

# The room-aware summon hook the manager holds: unlike the persister's
# per-message ``SummonHook`` (which knows only the handle + envelope), this
# carries the ``room`` so the engine wired to it (Step 7's aligner) knows which
# channel to judge. ``_start_persister`` adapts it down to the persister's
# signature by binding the room.
RoomSummonHook = Callable[[str, str, "L9"], None]

# The room-aware converged hook, same shape reasoning as ``RoomSummonHook``: the
# persister's ``ConvergedHook`` is ``(envelope)`` only, but the consumer wired to
# it (Step 8's plan-sync) needs the room to compile that room's plan + sync its
# memory. ``_converged_adapter`` binds the room down to the persister signature.
RoomConvergedHook = Callable[[str, "L9"], None]

logger = logging.getLogger(__name__)

# The moderator's app id (third Name segment) on every room channel. Distinct
# from any real agent handle so it never collides with a participant, and
# filtered out of presence.
BACKEND_AGENT = "backend"

# Delay before a supervised persister/channel is re-provisioned after an
# unexpected exit (H3/§D) — long enough to avoid a hot restart loop against a
# flapping node, short enough that a room recovers quickly.
_PERSISTER_RESTART_BACKOFF_S = 5.0


@dataclass
class ManagedRoomChannel:
    """One backend-moderated room channel and its live membership/episode state."""

    room: str
    workspace: str
    client: SlimClient
    channel: L9SlimChannel
    members: set[str] = field(default_factory=set)
    lifecycle: EpisodeLifecycle = field(default_factory=EpisodeLifecycle)
    persister: RoomPersister | None = None
    persister_task: asyncio.Task[None] | None = None


@dataclass
class HumanPublishResult:
    """The outcome of publishing a human's message onto a room channel.

    ``recipients`` are the L9 recipients the ``@``-parse resolved (present members
    that get woken); ``invites`` are the consent-gated invites raised for mentioned
    agents that are **not** on the channel yet.
    """

    mentioned: list[str]
    recipients: list[str]
    invites: list[PendingInvite]


@dataclass
class ChannelMetrics:
    """Process-wide coordination counters, surfaced by the health endpoint (H1).

    The first smoke test spent hours on failures that were silent; these make the
    fabric's health inspectable at a glance instead of by log spelunking.
    """

    provisions_ok: int = 0
    provisions_failed: int = 0
    invite_failures: int = 0


class RoomChannelManager:
    """Registry of backend-moderated room channels (one per room, per process)."""

    def __init__(self, *, endpoint: str, default_workspace: str) -> None:
        self._endpoint = endpoint
        self._default_workspace = default_workspace
        self._channels: dict[str, ManagedRoomChannel] = {}
        self._lock = asyncio.Lock()
        # Strong refs to in-flight background invites (see invite_in_background).
        self._tasks: set[asyncio.Task[bool]] = set()
        # Consent-gated invites raised by an @-mention of a not-present agent
        # (bible §12). The moderator only invites on accept.
        self._invites = PendingInviteRegistry()
        # Trigger hooks handed to every persister, both room-aware and wired at
        # startup (``main.py``): ``on_summon`` → the SIEP aligner's
        # ``handle_summon`` (Step 7); ``on_converged`` → the plan-sync consumer's
        # ``handle_converged`` (Step 8). Unset → the persister's log-only defaults.
        self.on_summon: RoomSummonHook | None = None
        self.on_converged: RoomConvergedHook | None = None
        self._metrics = ChannelMetrics()
        # Set during teardown so a persister task ending is recognized as
        # intentional (no restart) rather than a crash to recover from (§D).
        self._closing = False
        # Strong refs to in-flight channel-restart tasks (§D) so they aren't GC'd.
        self._restart_tasks: set[asyncio.Task[None]] = set()

    def get(self, room: str) -> ManagedRoomChannel | None:
        return self._channels.get(room)

    def status(self) -> dict:
        """A snapshot of coordination health for the ``/health`` surface (H1).

        Per-room: is the channel provisioned, is its persister task alive, who is
        present, how many consent invites are open, is an episode active. Plus
        process counters. Read-only and cheap — safe to call on every health hit.
        """
        rooms = []
        for room, managed in sorted(self._channels.items()):
            task = managed.persister_task
            rooms.append(
                {
                    "room": room,
                    "provisioned": True,
                    "persister_alive": task is not None and not task.done(),
                    "members": sorted(managed.members),
                    "pending_invites": len(self.pending_invites(room)),
                    "episode_active": managed.lifecycle.active,
                    "reserves": managed.persister.reserves if managed.persister else 0,
                    "receive_errors": managed.persister.receive_errors if managed.persister else 0,
                }
            )
        return {
            "endpoint": self._endpoint,
            "slim_enabled": settings.SLIM_ENABLED,
            "channels_live": len(self._channels),
            "provisions_ok": self._metrics.provisions_ok,
            "provisions_failed": self._metrics.provisions_failed,
            "invite_failures": self._metrics.invite_failures,
            "rooms": rooms,
        }

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
                self._metrics.provisions_failed += 1
                return None
            managed = ManagedRoomChannel(
                room=room, workspace=ws, client=client, channel=L9SlimChannel(client, session)
            )
            self._channels[room] = managed
            self._start_persister(managed)
            self._metrics.provisions_ok += 1
            logger.info("Provisioned SLIM channel for room %s (workspace=%s)", room, ws)
            return managed

    def _start_persister(self, managed: ManagedRoomChannel) -> None:
        """Attach and start the durable-inbox persister for a channel.

        The consumer loop is long-lived; the task ref is held on the managed
        channel so it isn't GC'd, and cancelled in :meth:`close`.
        """
        room = managed.room
        managed.persister = RoomPersister(
            room,
            managed.channel,
            members_provider=lambda: self.members(room),
            on_summon=self._summon_adapter(room),
            on_converged=self._converged_adapter(room),
            on_member_left=lambda handle, _room=room: self._drop_member(_room, handle),
        )
        managed.persister_task = asyncio.create_task(managed.persister.run())
        managed.persister_task.add_done_callback(
            lambda t, _room=room: self._on_persister_done(_room, t)
        )

    def _drop_member(self, room: str, handle: str) -> None:
        """A member dropped off the channel — update presence (H3/§B).

        Removing on disconnect keeps ``members`` in sync with real SLIM presence,
        so a later ``@``-mention re-raises a consent invite (instead of assuming
        the stale member is still present) and a re-join doesn't hit 'already in
        group'. Local bookkeeping only — the member is already gone from SLIM.
        """
        managed = self._channels.get(room)
        if managed is None or handle not in managed.members:
            return
        managed.members.discard(handle)
        logger.info("dropped absent member %s from room %s membership", handle, room)

    def _on_persister_done(self, room: str, task: asyncio.Task) -> None:
        """Supervise the persister: restart it if it died unexpectedly (H3/§D).

        A bare ``create_task(run())`` that ended left the channel a silent zombie
        (nothing served/recorded) until re-provisioned. Now an unexpected exit
        schedules a channel restart; an intentional teardown (cancel / ``close``)
        does not.
        """
        if task.cancelled() or self._closing:
            return
        if self._channels.get(room) is None:
            return
        exc = task.exception()
        logger.error(
            "persister for room %s exited unexpectedly (%s) — restarting channel in %.0fs",
            room,
            exc,
            _PERSISTER_RESTART_BACKOFF_S,
        )
        restart = asyncio.create_task(self._restart_channel(room))
        self._restart_tasks.add(restart)
        restart.add_done_callback(self._restart_tasks.discard)

    async def _restart_channel(self, room: str) -> None:
        """Tear down a dead channel and re-provision it fresh (H3/§D).

        Retries with backoff until it succeeds: if the persister died because the
        node went away, re-provision keeps failing until the node returns — a
        one-shot attempt would leave the room a zombie for the rest of the outage.
        """
        managed = self._channels.pop(room, None)
        workspace = managed.workspace if managed else None
        if managed is not None:
            with contextlib.suppress(Exception):
                await managed.client.close()
        while not self._closing:
            await asyncio.sleep(_PERSISTER_RESTART_BACKOFF_S)
            if self._closing or room in self._channels:
                return
            # provision() re-connects, re-creates the group session, and starts a
            # fresh supervised persister; None means the node is still unreachable.
            if await self.provision(room, workspace=workspace) is not None:
                logger.info("recovered room %s channel after persister exit", room)
                return

    def _summon_adapter(self, room: str) -> SummonHook | None:
        """Bind ``room`` onto the room-aware ``on_summon`` hook.

        The persister calls its ``SummonHook`` with only ``(handle, envelope)``;
        the engine wired to :attr:`on_summon` needs the room too. When no hook is
        wired, return ``None`` so the persister keeps its log-only default.
        """
        hook = self.on_summon
        if hook is None:
            return None

        def adapter(handle: str, envelope: L9, _room: str = room) -> None:
            hook(_room, handle, envelope)

        return adapter

    def _converged_adapter(self, room: str) -> ConvergedHook | None:
        """Bind ``room`` onto the room-aware ``on_converged`` hook.

        Mirrors :meth:`_summon_adapter`: the persister calls its ``ConvergedHook``
        with only ``(envelope)``, but the plan-sync consumer needs the room too.
        When no hook is wired, return ``None`` so the persister keeps its log-only
        default.
        """
        hook = self.on_converged
        if hook is None:
            return None

        def adapter(envelope: L9, _room: str = room) -> None:
            hook(_room, envelope)

        return adapter

    async def invite(self, room: str, agent: str) -> bool:
        """Invite ``agent`` into the room channel. Best-effort; returns success."""
        managed = self._channels.get(room)
        if managed is None or agent == BACKEND_AGENT:
            return False
        try:
            member = to_slim_name(managed.workspace, room, agent)
            await managed.client.invite(managed.channel.session, member)
        except Exception as exc:
            # Post-Step-5 a registered agent's connector holds a live SLIM
            # subscription, so a failed invite means it will NOT be woken — a real
            # failure, not the old Step-3 no-op. Surface it loudly (H1): a silent
            # invite drop was one of the smoke test's worst multi-hour hunts.
            logger.warning("SLIM invite failed (room=%s agent=%s): %s", room, agent, exc)
            self._metrics.invite_failures += 1
            return False
        managed.members.add(agent)
        # Durable inbox: a membership add for a handle the persister has already
        # seen is a *reconnect* — re-serve its missed tail. Kept separate from the
        # episode-abort path below: transcript continuity and episode lifecycle
        # are orthogonal (a reconnect re-serves regardless of episode state, and a
        # re-serve must not resurrect an aborted episode).
        if managed.persister is not None and managed.persister.note_join(agent):
            await managed.persister.reserve(agent)
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

    # -- human-in-the-room (Step 6) --

    async def publish_human(
        self, room: str, *, sender: str, text: str
    ) -> HumanPublishResult | None:
        """Publish a human's message onto the room channel as their proxy.

        The human runs no connector (bible §12): the backend builds an L9
        ``exchange`` on their behalf, maps ``@agent-x`` tokens to L9 recipients,
        and broadcasts it. In-room mentions wake through the connector's
        recipient match (Step 5); mentions of agents **not** on the channel raise
        a consent-gated invite instead. Returns ``None`` when no channel is live.

        The published message is ingested locally via the persister so the
        transcript and UI bus see it exactly once, independent of whether SLIM
        loops a broadcast back to its own sender.
        """
        managed = self._channels.get(room)
        if managed is None:
            return None

        mentioned = parse_mentions(text)
        # Every mention is an L9 recipient (the semantic "to"); everyone else on
        # the channel is an observer. Absent mentions stay recipients so the
        # intent is recorded, but only present ones actually receive the broadcast.
        envelope = l9.build_envelope(
            kind=Kind.exchange,
            episode=l9.episode_urn(room, "live"),
            sender=sender,
            sender_role="human",
            recipients=mentioned,
            topic=l9.topic_urn(room),
            payload_type="message",
        )
        content = serialize_content(envelope, extra={"content": text})
        try:
            await managed.channel.send(envelope, extra={"content": text})
        except Exception as exc:  # best-effort broadcast
            logger.warning("failed to publish human message on room %s: %s", room, exc)
        if managed.persister is not None:
            managed.persister.ingest_local(envelope, content)

        # Consent gate: an @-mention of an agent not on the channel is an invite.
        invites: list[PendingInvite] = []
        for handle in mentioned:
            if handle in managed.members or handle == BACKEND_AGENT:
                continue
            invite = self.request_invite(room, handle, requested_by=sender, trigger_text=text)
            if invite is not None:
                invites.append(invite)

        recipients = [h for h in mentioned if h != BACKEND_AGENT]
        return HumanPublishResult(mentioned=mentioned, recipients=recipients, invites=invites)

    # -- consent-gated invites (Step 6) --

    def request_invite(
        self, room: str, agent: str, *, requested_by: str, trigger_text: str = ""
    ) -> PendingInvite | None:
        """Raise a consent prompt to invite ``agent`` into ``room``.

        Returns ``None`` when there's nothing to consent to — no live channel, or
        the agent is already a member (that mention is a wake, not an invite).
        Otherwise records a pending invite and surfaces the accept/decline prompt
        on the room's UI bus. Does **not** invite; that waits for :meth:`accept_invite`.
        """
        managed = self._channels.get(room)
        if managed is None or agent == BACKEND_AGENT or agent in managed.members:
            return None
        invite = self._invites.request(
            room, agent, requested_by=requested_by, trigger_text=trigger_text
        )
        self._emit_consent_prompt(invite)
        return invite

    async def accept_invite(self, invite_id: str) -> PendingInvite | None:
        """Accept a consent prompt: invite the agent — or queue it mid-episode.

        Inviting a new member mid-episode violates L9's stable-membership rule
        (it would abort the episode), so an accept while an episode is active is
        **queued** and applied when the episode closes (bible §12 default).
        Returns the updated invite, or ``None`` if the id is unknown.
        """
        invite = self._invites.get(invite_id)
        if invite is None:
            return None
        managed = self._channels.get(invite.room)
        if managed is None:
            return self._invites.mark(invite_id, DECLINED)
        if managed.lifecycle.active:
            logger.info(
                "invite for @%s in %s queued until episode %s closes",
                invite.agent,
                invite.room,
                managed.lifecycle.episode,
            )
            return self._invites.mark(invite_id, QUEUED)
        await self.invite(invite.room, invite.agent)
        return self._invites.mark(invite_id, ACCEPTED)

    def decline_invite(self, invite_id: str) -> PendingInvite | None:
        """Decline a consent prompt: the agent does not join."""
        return self._invites.mark(invite_id, DECLINED)

    def pending_invites(self, room: str) -> list[PendingInvite]:
        """Open (pending or queued) consent requests for ``room``."""
        return self._invites.open_for_room(room)

    async def flush_queued_invites(self, room: str) -> None:
        """Apply invites deferred during an episode, now that it has closed."""
        for invite in self._invites.queued_for_room(room):
            await self.invite(room, invite.agent)
            self._invites.mark(invite.id, ACCEPTED)

    def _emit_consent_prompt(self, invite: PendingInvite) -> None:
        """Surface a consent prompt on the room's UI bus (best-effort)."""
        try:
            from app.bus import bus, room_channel

            bus.publish(
                room_channel(invite.room),
                {
                    "room_name": invite.room,
                    "sender_handle": l9.SYSTEM_ACTOR_ID,
                    "message_type": "consent_request",
                    "content": json.dumps(invite.to_json()),
                    "created_at": invite.created_at,
                },
            )
        except Exception:  # pragma: no cover - best-effort UI push
            logger.debug("consent prompt bus publish failed for room %s", invite.room)

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

    async def close_episode(self, room: str) -> bool:
        """Close the room's active episode normally and flush queued invites.

        The membership-freeze that an episode holds is released here, so invites
        an ``@``-mention deferred mid-episode (bible §12) are now safe to apply.
        The converged/rejected wiring that calls this lands in Steps 7-8; the
        method exists now so the mid-episode queue has a drain.
        """
        managed = self._channels.get(room)
        if managed is None:
            return False
        managed.lifecycle.close()
        await self.flush_queued_invites(room)
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
        """Tear down the room's channel (persister stopped; moderator leaves)."""
        managed = self._channels.pop(room, None)
        if managed is None:
            return
        if managed.persister_task is not None:
            managed.persister_task.cancel()
            try:
                await managed.persister_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # pragma: no cover - best-effort teardown
                logger.debug("persister task teardown error for room %s: %s", room, exc)
            managed.persister_task = None
        await managed.client.close()
        logger.info("Closed SLIM channel for room %s", room)

    async def close_all(self) -> None:
        """Tear down every channel and drop the shared connection (shutdown)."""
        self._closing = True  # a persister ending now is intentional, not a crash
        for task in (*self._tasks, *self._restart_tasks):
            task.cancel()
        self._tasks.clear()
        self._restart_tasks.clear()
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
