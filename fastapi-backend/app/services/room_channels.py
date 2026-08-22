# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Backend-as-moderator SLIM channel provisioning for rooms.

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

On provision the moderator starts a
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
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.config import settings
from app.services import custody, l9, slim_identity
from app.services.engine_events import RoomEvent, lifecycle
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
    from app.services.custody import CustodialSession
    from app.services.l9_models import L9

# The room-aware summon hook the manager holds: unlike the persister's
# per-message ``SummonHook`` (which knows only the handle + envelope), this
# carries the ``room`` so the engine wired to it (the aligner) knows which
# channel to judge. ``_start_persister`` adapts it down to the persister's
# signature by binding the room.
RoomSummonHook = Callable[[str, str, "L9", list[str], str], None]

# The room-aware converged hook, same shape reasoning as ``RoomSummonHook``: the
# persister's ``ConvergedHook`` is ``(envelope)`` only, but the consumer wired to
# it (the plan-sync consumer) needs the room to compile that room's plan + sync its
# memory. ``_converged_adapter`` binds the room down to the persister signature.
RoomConvergedHook = Callable[[str, "L9"], None]

logger = logging.getLogger(__name__)

# The moderator's app id (third Name segment) on every room channel. Distinct
# from any real agent handle so it never collides with a participant, and
# filtered out of presence.
BACKEND_AGENT = "backend"

# Delay before a supervised persister/channel is re-provisioned after an
# unexpected exit — long enough to avoid a hot restart loop against a flapping
# node, short enough that a room recovers quickly.
_PERSISTER_RESTART_BACKOFF_S = 5.0


def _is_own_registered_agent(room: str, handle: str) -> bool:
    """True if ``handle`` is an agent registered in ``room`` (manifest on disk).

    Its manifest lives at ``agents/{handle}.md`` in the room dir. Used to decide
    auto-invite (own agent) vs a consent prompt (foreign/cross-host).
    """
    from app.services.filesystem import get_room_dir

    return (get_room_dir(room) / "agents" / f"{handle}.md").exists()


def _registered_agent_handles(room: str) -> list[str]:
    """Every agent handle with a manifest in ``room`` (``agents/*.md`` stems)."""
    from app.services.filesystem import get_room_dir

    agents_dir = get_room_dir(room) / "agents"
    if not agents_dir.is_dir():
        return []
    return sorted(p.stem for p in agents_dir.glob("*.md"))


def _prebuild_signerjwt_roster(room: str) -> None:
    """Register every known member's signing key before the moderator App exists.

    A SignerJwt moderator snapshots the roster JWKS into its verifier at app
    creation, so a session whose JWK is absent then can't be MLS-verified when it is
    later admitted. Registering the backend + every registered agent up front makes
    the verifier complete for the room's known members. A session for an agent
    registered *after* provisioning still self-registers on admit; the
    moderator picks up such late arrivals on its next channel (re)provision.
    """
    slim_identity.ensure_agent_keypair(BACKEND_AGENT)
    for handle in _registered_agent_handles(room):
        try:
            slim_identity.ensure_agent_keypair(handle)
        except Exception:
            logger.debug("roster pre-build skipped for @%s in room %s", handle, room)


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
    # Per-actor custodial MLS sessions this backend holds for the room (#666), keyed by
    # handle. Populated only under an identity tier (``custody.custody_enabled()``);
    # empty under the PSK default, where the moderator is the single member.
    custody: dict[str, CustodialSession] = field(default_factory=dict)


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
    # The published envelope's L9 message id — the correlation key the POST route
    # stamps on its ``local_state`` row so a cold read from the durable transcript
    # dedups against it instead of showing the human's message twice.
    message_id: str | None = None


@dataclass
class MemberPresence:
    """How a present room member is connected, for the presence surface.

    ``kind`` is ``"slim"`` (live socket) or ``"lease"`` (server-held
    ``await``/``reply`` poll). ``last_seen`` is the wall-clock epoch of a lease
    member's most recent poll; ``None`` for SLIM members (continuously present).
    """

    kind: str
    last_seen: float | None = None


@dataclass
class ChannelMetrics:
    """Process-wide coordination counters, surfaced by the health endpoint.

    These make the fabric's health inspectable at a glance instead of by log
    spelunking.
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
        # The moderator only invites on accept.
        self._invites = PendingInviteRegistry()
        # Trigger hooks handed to every persister, both room-aware and wired at
        # startup (``main.py``): ``on_summon`` → the SIEP aligner's
        # ``handle_summon``; ``on_converged`` → the plan-sync consumer's
        # ``handle_converged``. Unset → the persister's log-only defaults.
        self.on_summon: RoomSummonHook | None = None
        self.on_converged: RoomConvergedHook | None = None
        self._metrics = ChannelMetrics()
        # Server-held presence: a handle that participates over HTTP (the CLI
        # ``await``/``respond`` long-poll) never holds a client SLIM connection,
        # so it isn't in ``managed.members``. The backend keeps it "present" via a
        # lease (room → handle → monotonic expiry), refreshed on every await/reply,
        # and unions it into ``members`` so the mediator's roster includes it. This
        # is how a turn-based agent (a Claude session) is a first-class member
        # without holding a socket between turns.
        self._leases: dict[str, dict[str, float]] = {}
        # Wall-clock epoch of each handle's most recent await/reply, keyed like
        # ``_leases``. Monotonic time drives expiry (skew-proof); this parallel
        # wall-clock stamp is only for surfacing "last seen 5s ago" in the UI.
        self._last_seen: dict[str, dict[str, float]] = {}
        # Tracks which handles have had a coordination_join notice emitted for each
        # room. Cleared on leave/disconnect so a returning member re-announces.
        self._announced: dict[str, set[str]] = {}
        # Set during teardown so a persister task ending is recognized as
        # intentional (no restart) rather than a crash to recover from.
        self._closing = False
        # Strong refs to in-flight channel-restart tasks so they aren't GC'd.
        self._restart_tasks: set[asyncio.Task[None]] = set()

    def get(self, room: str) -> ManagedRoomChannel | None:
        return self._channels.get(room)

    def status(self) -> dict:
        """A snapshot of coordination health for the ``/health`` surface.

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
                    # Union of SLIM-connected members and live server-held `await`
                    # leases — the same roster `members()` serves the mediator, so
                    # a bare-CLI participant long-polling `await` is visible here.
                    "members": self.members(room),
                    "pending_invites": len(self.pending_invites(room)),
                    "episode_active": managed.lifecycle.active,
                    "reserves": managed.persister.reserves if managed.persister else 0,
                    "reserve_failures": (
                        managed.persister.reserve_failures if managed.persister else 0
                    ),
                    "reserve_skipped": (
                        managed.persister.reserve_skipped if managed.persister else 0
                    ),
                    "receive_errors": managed.persister.receive_errors if managed.persister else 0,
                    "transient_errors": (
                        managed.persister.transient_errors if managed.persister else 0
                    ),
                    "knowledge_applied": (
                        managed.persister.knowledge_applied if managed.persister else 0
                    ),
                    "knowledge_conflicts": (
                        managed.persister.knowledge_conflicts if managed.persister else 0
                    ),
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
        """Agent handles present in ``room`` — SLIM members plus server-held leases.

        A client-connected agent shows up in ``managed.members`` (SLIM presence); a
        server-held agent (HTTP ``await`` long-poll) shows up via a live lease. The
        mediator's roster is this union, so both kinds are first-class participants.
        """
        managed = self._channels.get(room)
        slim_members = set(managed.members) if managed is not None else set()
        return sorted(slim_members | self._live_leases(room))

    def presence(self, room: str) -> dict[str, MemberPresence]:
        """Live presence breakdown: handle → :class:`MemberPresence` per member.

        SLIM-socket members and server-held ``await``/``reply`` lease members are
        both first-class; the ``kind`` distinguishes them and ``last_seen`` gives
        a lease member's most recent poll time (``None`` for SLIM — a live socket
        is continuously present).
        """
        managed = self._channels.get(room)
        slim = set(managed.members) if managed is not None else set()
        lease_only = self._live_leases(room) - slim
        seen = self._last_seen.get(room, {})
        out: dict[str, MemberPresence] = {h: MemberPresence(kind="slim") for h in slim}
        for h in lease_only:
            out[h] = MemberPresence(kind="lease", last_seen=seen.get(h))
        return out

    def _live_leases(self, room: str) -> set[str]:
        """Handles with an unexpired presence lease in ``room``."""
        now = time.monotonic()
        leases = self._leases.get(room)
        if not leases:
            return set()
        live = {h for h, exp in leases.items() if exp > now}
        # Opportunistically drop expired leases so the map doesn't grow forever.
        # Also clear from _announced so a returning handle re-announces its arrival.
        expired = set(leases) - live
        if expired:
            self._leases[room] = {h: leases[h] for h in live}
            self._announced.get(room, set()).difference_update(expired)
            seen = self._last_seen.get(room)
            if seen:
                for h in expired:
                    seen.pop(h, None)
        return live

    def refresh_lease(self, room: str, handle: str, ttl_s: float = 180.0) -> None:
        """Mark ``handle`` server-held-present in ``room`` for ``ttl_s`` seconds.

        Called on every ``await``/``reply`` so an actively-participating agent stays
        in the roster; a generous TTL keeps it present through its own think time
        (and avoids a mid-episode membership flap) while a truly-gone agent lapses.
        Emits a coordination_join notice on the not-present → present edge.
        """
        was_present = handle in self._live_leases(room)
        self._leases.setdefault(room, {})[handle] = time.monotonic() + ttl_s
        self._last_seen.setdefault(room, {})[handle] = time.time()
        if not was_present:
            self.announce_join(room, handle)

    def announce_join(self, room: str, handle: str, intent: str = "") -> bool:
        """Emit a coordination_join notice on the first not-present → present transition.

        Idempotent: returns False (and does nothing) if the handle is already
        announced for this room. Clears on leave/disconnect so a returning member
        re-announces. Called from every join path so the channel feed shows arrivals
        consistently regardless of whether the agent joined via HTTP session, SLIM
        invite, or server-held await lease.
        """
        announced = self._announced.setdefault(room, set())
        if handle in announced:
            return False
        announced.add(handle)
        content = json.dumps({"handle": handle, "intent": intent})
        try:
            from app.services import local_state

            local_state.add_message(
                room,
                local_state.StoredMessage(
                    room_name=room,
                    sender_handle=l9.SYSTEM_ACTOR_ID,
                    message_type="coordination_join",
                    content=content,
                ),
            )
        except Exception:
            logger.debug("join notice persist failed for %s in room %s", handle, room)
        try:
            from app.bus import bus, room_channel

            bus.publish(
                room_channel(room),
                {
                    "room_name": room,
                    "sender_handle": l9.SYSTEM_ACTOR_ID,
                    "message_type": "coordination_join",
                    "content": content,
                    "created_at": datetime.now(UTC).isoformat(),
                },
            )
        except Exception:
            logger.debug("join notice bus publish failed for %s in room %s", handle, room)
        return True

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
                if slim_identity.resolve_identity_mode() == slim_identity.MODE_SIGNERJWT:
                    # The moderator is a first-class identity (#476): self-register
                    # its own signing key + roster entry before presenting a
                    # SignerJwt identity. Under custody (#666) also register every
                    # known member up front so the moderator's verifier — snapshotted
                    # here — can MLS-verify their sessions on admit. No-op under PSK.
                    if custody.custody_enabled():
                        _prebuild_signerjwt_roster(room)
                    else:
                        slim_identity.ensure_agent_keypair(BACKEND_AGENT)
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
            # Let engines that install room behaviour (a summon filter) re-attach
            # to a room whose manifests were written while this process was down.
            lifecycle.emit(RoomEvent.ROOM_PROVISIONED, room)
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
        """A member dropped off the channel — update presence.

        Removing on disconnect keeps ``members`` in sync with real SLIM presence,
        so a later ``@``-mention re-raises a consent invite (instead of assuming
        the stale member is still present) and a re-join doesn't hit 'already in
        group'. Local bookkeeping only — the member is already gone from SLIM.
        Clears the announced flag so the handle re-announces if they return.
        """
        managed = self._channels.get(room)
        if managed is None or handle not in managed.members:
            return
        managed.members.discard(handle)
        self._announced.get(room, set()).discard(handle)
        logger.info("dropped absent member %s from room %s membership", handle, room)

    def _on_persister_done(self, room: str, task: asyncio.Task) -> None:
        """Supervise the persister: restart it if it died unexpectedly.

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
        """Tear down a dead channel and re-provision it fresh.

        Retries with backoff until it succeeds: if the persister died because the
        node went away, re-provision keeps failing until the node returns — a
        one-shot attempt would leave the room a zombie for the rest of the outage.
        """
        managed = self._channels.pop(room, None)
        workspace = managed.workspace if managed else None
        # Clear announcements so agents re-announce when they reconnect to the
        # fresh channel — the old channel's membership record is gone.
        self._announced.pop(room, None)
        if managed is not None:
            for cs in managed.custody.values():
                with contextlib.suppress(Exception):
                    await cs.close(graceful=False)
            with contextlib.suppress(Exception):
                await managed.client.close()
        while not self._closing:
            await asyncio.sleep(_PERSISTER_RESTART_BACKOFF_S)
            if self._closing or room in self._channels:
                return
            # provision() re-connects, re-creates the group session, and starts a
            # fresh supervised persister; None means the node is still unreachable.
            if await self.provision(room, workspace=workspace) is not None:
                # Revive custodial sessions against the fresh connection from their stores — the
                # old Apps died with the dropped connection (spike D3/restart shape).
                await self.restore_custody(room)
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

        def adapter(
            handle: str,
            envelope: L9,
            co_summons: list[str],
            message_text: str = "",
            _room: str = room,
        ) -> None:
            hook(_room, handle, envelope, co_summons, message_text)

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
        """Invite ``agent`` into the room channel. Best-effort; returns success.

        Under an identity tier (#666) this stands up the agent's **custodial session** — a
        genuine per-actor MLS member the backend custodies — instead of inviting a
        bare Name; under the PSK default it is byte-for-byte the prior single-member
        invite.
        """
        managed = self._channels.get(room)
        if managed is None or agent == BACKEND_AGENT:
            return False
        if custody.custody_enabled():
            return await self._ensure_custody(managed, agent) is not None
        try:
            member = to_slim_name(managed.workspace, room, agent)
            await managed.client.invite(managed.channel.session, member)
        except Exception as exc:
            # A registered agent's connector holds a live SLIM
            # subscription, so a failed invite means it will NOT be woken — a real
            # failure. Surface it loudly.
            logger.warning("SLIM invite failed (room=%s agent=%s): %s", room, agent, exc)
            self._metrics.invite_failures += 1
            return False
        await self._register_member(managed, agent)
        return True

    async def _register_member(self, managed: ManagedRoomChannel, agent: str) -> None:
        """Post-admit bookkeeping shared by the PSK invite and the custody path.

        Records presence, announces the join, re-serves a reconnecting member's
        missed tail, and lets a mid-episode membership change abort the episode.
        """
        managed.members.add(agent)
        self.announce_join(managed.room, agent)
        # Durable inbox: a membership add for a handle the persister has already
        # seen is a *reconnect* — re-serve its missed tail. Kept separate from the
        # episode-abort path below: transcript continuity and episode lifecycle
        # are orthogonal (a reconnect re-serves regardless of episode state, and a
        # re-serve must not resurrect an aborted episode).
        if managed.persister is not None and managed.persister.note_join(agent):
            await managed.persister.reserve(agent)
        await self._enforce_membership_change(managed)

    # -- per-actor custodial sessions (#666; identity tiers only) --

    async def _ensure_custody(
        self, managed: ManagedRoomChannel, agent: str
    ) -> CustodialSession | None:
        """Stand up (or reuse) ``agent``'s custodial session and admit it into the group.

        The session's App subscribes and starts listening *before* the moderator invite
        lands (they run concurrently, single process), so the MLS Welcome is
        received. Idempotent: an already-joined session is returned as-is. Best-effort
        — a failure returns ``None`` and the caller degrades (respond falls back to
        a moderator send), never raising into the request path.
        """
        existing = managed.custody.get(agent)
        if existing is not None and existing.joined:
            return existing
        try:
            cs = await custody.create_session(
                self._endpoint, managed.workspace, managed.room, agent
            )
            member = to_slim_name(managed.workspace, managed.room, agent)
            join_task = asyncio.create_task(custody.join_session(cs))
            try:
                await managed.client.invite(managed.channel.session, member)
                await join_task
            except Exception:
                join_task.cancel()
                await cs.close(graceful=False)
                raise
        except Exception as exc:
            logger.warning(
                "custodial admit failed (room=%s agent=%s): %s", managed.room, agent, exc
            )
            self._metrics.invite_failures += 1
            return None
        cs.drain_task = asyncio.create_task(cs.drain())
        managed.custody[agent] = cs
        await self._register_member(managed, agent)
        logger.info("admitted custodial session for @%s into room %s", agent, managed.room)
        return cs

    async def send_as_custodian(self, room: str, handle: str, data: bytes) -> bool:
        """Publish ``data`` to the room as ``handle`` via its custodial session (real MLS send).

        The wire sender is the actor's own MLS identity, not the backend's. Ensures the session on first participation. Returns whether
        the send went out as the actor; ``False`` (with the caller falling back to a
        moderator send) preserves liveness when a session can't be stood up.
        """
        if not custody.custody_enabled() or handle == BACKEND_AGENT:
            return False
        managed = self._channels.get(room)
        if managed is None:
            return False
        try:
            cs = managed.custody.get(handle)
            if cs is None or not cs.joined:
                cs = await self._ensure_custody(managed, handle)
            if cs is None:
                return False
            await cs.publish(data)
            return True
        except Exception as exc:
            logger.warning("custodial send failed (room=%s handle=%s): %s", room, handle, exc)
            return False

    async def restore_custody(self, room: str) -> int:
        """Revive every persisted custodial session for ``room`` after a backend restart (#666).

        Each session resumes from its own encrypted store via ``restore_sessions`` —
        no re-invite, no MLS Welcome — and the always-draining moderator heals its
        ``rejoin`` (spike D1). The durable transcript replays any gap; SLIM
        persistence resumes crypto state only. Returns the count revived.
        """
        if not custody.custody_enabled():
            return 0
        managed = self._channels.get(room)
        if managed is None:
            return 0
        restored = 0
        for room_name, handle in custody.iter_persisted_sessions():
            if room_name != room or handle in managed.custody:
                continue
            try:
                cs = await custody.restore_session(self._endpoint, managed.workspace, room, handle)
            except Exception as exc:
                logger.warning(
                    "custodial restore failed (room=%s handle=%s): %s", room, handle, exc
                )
                continue
            if cs is None:
                continue
            cs.drain_task = asyncio.create_task(cs.drain())
            managed.custody[handle] = cs
            managed.members.add(handle)
            self.announce_join(room, handle)
            restored += 1
        if restored:
            logger.info(
                "restored %d custodial session(s) for room %s (no re-invite)", restored, room
            )
        return restored

    def invite_in_background(self, room: str, agent: str) -> None:
        """Schedule :meth:`invite` without blocking the caller.

        The SLIM invite handshake retries against an absent member before
        failing, so awaiting it in an HTTP join would stall the request for the
        whole retry budget. Until agents hold their own SLIM connection, that
        failure is the norm — so fire-and-forget: the join returns at once
        and ``members`` updates if/when the invite lands. ``invite`` swallows its
        own errors, so the task never raises.
        """
        if self._channels.get(room) is None:
            return
        task = asyncio.create_task(self.invite(room, agent))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # -- human-in-the-room --

    async def publish_human(
        self, room: str, *, sender: str, text: str
    ) -> HumanPublishResult | None:
        """Publish a human's message onto the room channel as their proxy.

        The human runs no connector: the backend builds an L9 ``exchange`` on
        their behalf, maps ``@agent-x`` tokens to L9 recipients, and broadcasts
        it. In-room mentions wake through the connector's recipient match;
        mentions of agents **not** on the channel raise a consent-gated invite
        instead. Returns ``None`` when no channel is live.

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
        message_id = envelope.header.message.id if envelope.header.message else None
        try:
            await managed.channel.send(envelope, extra={"content": text})
        except Exception as exc:  # best-effort broadcast
            logger.warning("failed to publish human message on room %s: %s", room, exc)
        if managed.persister is not None:
            # Transcript-only here (``list_write=False``): the POST route owns the
            # ``local_state`` row (its id/ledger), stamped with this envelope's id so
            # a cold read dedups the two.
            managed.persister.ingest_local(envelope, content, list_write=False)

        # Consent gate: an @-mention of an agent not on the channel invites
        # it — but the user's OWN registered agents in this room are pre-authorized
        # and joined directly (no prompt). Consent-to-be-woken is for FOREIGN /
        # cross-host agents (not registered here), so a CLI-only user can still
        # wake their own agent, and the consent surface is reserved for the
        # genuinely external case it's meant for.
        # "Present" is SLIM-connected members plus live server-held `await` leases. A
        # bare-CLI agent long-polling `await` is a first-class participant — its
        # turn is delivered via the durable transcript cursor its poll reads, not a
        # SLIM broadcast — so an @-mention of it is a wake, not a consent invite.
        present = set(self.members(room))
        invites: list[PendingInvite] = []
        for handle in mentioned:
            if handle in present or handle == BACKEND_AGENT:
                continue
            if _is_own_registered_agent(room, handle):
                if managed.lifecycle.active:
                    # Inviting a new member mid-episode would abort it (L9's
                    # stable-membership rule), so queue like a consent accept —
                    # flush_queued_invites applies it once the episode closes.
                    queued = self._invites.request(
                        room, handle, requested_by=sender, trigger_text=text
                    )
                    self._invites.mark(queued.id, QUEUED)
                else:
                    self.invite_in_background(room, handle)
                continue
            invite = self.request_invite(room, handle, requested_by=sender, trigger_text=text)
            if invite is not None:
                invites.append(invite)

        recipients = [h for h in mentioned if h != BACKEND_AGENT]
        return HumanPublishResult(
            mentioned=mentioned, recipients=recipients, invites=invites, message_id=message_id
        )

    # -- consent-gated invites --

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
        **queued** and applied when the episode closes.
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
        # Schedule the SLIM invite off the request path. The group invite
        # handshake retries against an absent member before failing, so awaiting it
        # here would stall the HTTP accept for the whole retry budget (observed as a
        # hung/timed-out accept). Mark accepted now; `members` updates if/when the
        # invite lands, exactly as it does for a background join.
        self.invite_in_background(invite.room, invite.agent)
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
        """Remove ``agent`` from the room channel. Best-effort; returns success.

        Under an identity tier this is revocation (#590/#666): the custodial session gracefully
        leaves the MLS group (one Commit; the other members heal with **no
        room-wide re-key**) and its at-rest store is deleted so it can't be
        revived. Under the PSK default it is the prior moderator-side remove.
        """
        managed = self._channels.get(room)
        if managed is None or agent not in managed.members:
            return False
        cs = managed.custody.pop(agent, None)
        if cs is not None:
            await cs.close(graceful=True)
            custody.delete_store(room, agent)
        else:
            try:
                member = to_slim_name(managed.workspace, room, agent)
                await managed.client.remove_member(managed.channel.session, member)
            except Exception as exc:
                logger.debug("SLIM remove skipped (room=%s agent=%s): %s", room, agent, exc)
                return False
        managed.members.discard(agent)
        self._announced.get(room, set()).discard(agent)
        await self._enforce_membership_change(managed)
        return True

    def open_episode(self, room: str, episode: str) -> bool:
        """Open a negotiation episode over the room's current membership.

        Freezes membership: a subsequent join/leave aborts it.
        """
        managed = self._channels.get(room)
        if managed is None:
            return False
        managed.lifecycle.open(episode, managed.members)
        return True

    async def close_episode(self, room: str) -> bool:
        """Close the room's active episode normally and flush queued invites.

        The membership-freeze that an episode holds is released here, so invites
        an ``@``-mention deferred mid-episode are now safe to apply.
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
            # Record the abort locally so the transcript/UI see it — SLIM may not
            # loop a broadcast back to its own sender.
            if managed.persister is not None:
                managed.persister.ingest_local(envelope, serialize_content(envelope))
        except Exception as exc:  # pragma: no cover - best-effort notify
            logger.warning("Failed to publish episode abort for %s: %s", episode, exc)
        # The episode is closed now, so invites deferred while it was active can be
        # applied — the normal close_episode path flushes for the same reason.
        await self.flush_queued_invites(managed.room)

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
        # Non-graceful custody teardown: leave the encrypted stores intact so a
        # restart revives every session via ``restore_sessions`` (no re-invite).
        for cs in managed.custody.values():
            await cs.close(graceful=False)
        managed.custody.clear()
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
