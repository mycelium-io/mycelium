# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
L9-over-SLIM binding — the seam between :mod:`app.services.l9` (envelope
construction) and :mod:`app.services.slim_client` (transport).

The room bus is **L9 straight over SLIM group sessions — no A2A**.
This module owns three things the *app* must, not SLIM:

1. **Serialize / deserialize.** An L9 envelope is embedded under the additive
   ``l9`` key of a message's content JSON (agents never speak L9; the ``l9`` key
   is invisible to anything that ignores it). :func:`serialize_envelope` writes
   that content to bytes for :meth:`SlimClient.publish`; :func:`deserialize_envelope`
   parses inbound bytes back to an :class:`L9` (validating the subkind table).

2. **Causal ordering by ``message.parents``.** SLIM group delivery is not
   causally ordered, so :class:`CausalOrderBuffer` holds back an envelope until
   every id in its ``message.parents`` has been delivered, then releases it (and
   any dependents it unblocks) in causal order.

3. **Episode ↔ channel lifecycle.** The channel is durable for the room's life;
   an *episode* is one negotiation inside it. :class:`EpisodeLifecycle` enforces
   L9's stable-membership rule: a membership change mid-episode **aborts** the
   episode (emitted as ``commit:rejected``), without tearing down the channel.

:class:`L9SlimChannel` composes 1-2 over a single SLIM group session: one call
to :meth:`send` publishes an envelope; :meth:`receive` pulls one broadcast and
returns the envelopes it makes deliverable (usually one, more when a held-back
arrival unblocks).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.services import l9
from app.services.l9_models import Kind

if TYPE_CHECKING:
    import slim_bindings

    from app.services.l9_models import L9
    from app.services.slim_client import SlimClient

# The additive key an L9 envelope rides under inside a message's content JSON.
CONTENT_L9_KEY = "l9"


class L9SlimError(RuntimeError):
    """A message on the room channel could not be bound to/from L9."""


class ChannelReceiveTimeout(L9SlimError):
    """A receive timed out with no message — a benign idle tick, not a failure.

    The SLIM binding raises a generic ``SessionError`` both for a real transport
    fault and for a plain "no message arrived within the window" timeout. On an
    idle room the latter is the norm, so the persister must treat it as "keep
    waiting" rather than counting it toward the give-up budget (a room that goes
    quiet for a few windows must not have its channel silently die).
    """


# Substring the SLIM binding puts in a timeout ``SessionError`` message. Matched
# because the binding exposes no distinct timeout exception type (all session
# faults are ``SessionError``); a real transport fault carries a different text.
_RECEIVE_TIMEOUT_MARKER = "receive timeout"


def serialize_envelope(envelope: L9, *, extra: dict[str, Any] | None = None) -> bytes:
    """Serialize ``envelope`` (plus any ``extra`` content) to publishable bytes.

    The envelope goes under the ``l9`` key so the wire shape matches every other
    coordination message; ``extra`` carries the human-facing payload agents read.
    """
    return json.dumps(serialize_content(envelope, extra=extra)).encode("utf-8")


def serialize_content(envelope: L9, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """The content dict an envelope rides in (``{**extra, "l9": <envelope>}``).

    :func:`serialize_envelope` is this plus a JSON encode; the persister keeps
    the dict form to record and re-serve.
    """
    content: dict[str, Any] = dict(extra or {})
    content[CONTENT_L9_KEY] = l9.envelope_to_dict(envelope)
    return content


def deserialize_envelope(data: bytes) -> tuple[L9, dict[str, Any]]:
    """Parse published bytes back into ``(envelope, full_content_dict)``.

    Raises :class:`L9SlimError` if the bytes aren't JSON or carry no ``l9`` key;
    re-raises :class:`l9.L9ValidationError` for a structurally-invalid envelope.
    """
    try:
        content = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise L9SlimError("channel message is not JSON") from exc
    if not isinstance(content, dict) or CONTENT_L9_KEY not in content:
        raise L9SlimError("channel message carries no L9 envelope")
    envelope = l9.parse_envelope(content[CONTENT_L9_KEY])
    return envelope, content


class CausalOrderBuffer:
    """Reorders envelopes into causal order by ``message.parents``.

    :meth:`add` takes one arrived envelope and returns the list (possibly empty)
    now deliverable in causal order: an envelope is released only once every id
    in its parents has been released. Out-of-order and duplicate arrivals are
    handled; an envelope whose parent never arrives stays held (correct — it has
    no causal predecessor to follow).
    """

    def __init__(self) -> None:
        self._delivered: set[str] = set()
        self._pending: list[L9] = []

    def _ready(self, envelope: L9) -> bool:
        message = envelope.header.message
        parents = message.parents if message is not None else []
        return all(parent in self._delivered for parent in parents)

    @staticmethod
    def _message_id(envelope: L9) -> str | None:
        message = envelope.header.message
        return message.id if message is not None else None

    def add(self, envelope: L9) -> list[L9]:
        """Buffer ``envelope`` and return everything it makes deliverable."""
        self._pending.append(envelope)
        released: list[L9] = []
        progressed = True
        while progressed:
            progressed = False
            for pending in list(self._pending):
                mid = self._message_id(pending)
                if mid is not None and mid in self._delivered:
                    self._pending.remove(pending)  # duplicate id already released
                    continue
                if self._ready(pending):
                    self._pending.remove(pending)
                    if mid is not None:
                        self._delivered.add(mid)
                    released.append(pending)
                    progressed = True
        return released

    def mark_delivered(self, message_id: str) -> None:
        """Record ``message_id`` as already delivered, out of band.

        Used for messages the moderator ingests locally (the human proxy — see
        :meth:`RoomPersister.ingest_local`) that never pass through :meth:`add`.
        Without this, a reply causally parented on such a message can never
        satisfy :meth:`_ready` and would be held in ``_pending`` forever.
        """
        self._delivered.add(message_id)

    @property
    def pending_count(self) -> int:
        """Envelopes held back awaiting an undelivered parent."""
        return len(self._pending)


@dataclass
class EpisodeLifecycle:
    """Tracks one negotiation (episode) within a durable room channel.

    An episode freezes the membership it opened with. A membership change while
    the episode is active violates L9's stable-membership rule and **aborts** the
    episode — the channel itself is untouched. A new episode can
    be opened afterward with the changed membership.
    """

    episode: str | None = None
    members: frozenset[str] = field(default_factory=frozenset)
    active: bool = False

    def open(self, episode: str, members: set[str] | frozenset[str]) -> None:
        """Begin an episode over the given frozen membership."""
        self.episode = episode
        self.members = frozenset(members)
        self.active = True

    def on_membership_change(self, members: set[str] | frozenset[str]) -> bool:
        """Record a membership change; return True if it aborts an active episode.

        When no episode is active the new membership is simply adopted as the
        baseline (so the *next* episode opens clean).
        """
        new_members = frozenset(members)
        if self.active and new_members != self.members:
            self.active = False
            return True
        self.members = new_members
        return False

    def close(self) -> None:
        """Close the episode normally (converged/rejected reached)."""
        self.active = False
        self.episode = None


def build_episode_abort_envelope(
    episode: str,
    *,
    recipients: list[str],
    topic: str | None = None,
    reason: str = "membership_change",
) -> L9:
    """The ``commit:rejected`` envelope that closes an aborted episode."""
    return l9.build_envelope(
        kind=Kind.commit,
        subkind="rejected",
        episode=episode,
        recipients=recipients,
        topic=topic,
        payload_type="consensus",
        payload_data={"aborted": True, "reason": reason},
    )


class L9SlimChannel:
    """An L9 envelope pipe over one SLIM group session.

    Composes serialization + causal ordering: :meth:`send` publishes an envelope
    to the group; :meth:`receive` pulls one broadcast and returns the envelopes
    it makes deliverable in causal order. Non-L9 broadcasts on the channel raise
    :class:`L9SlimError` so callers can log and skip rather than crash.
    """

    def __init__(self, client: SlimClient, session: slim_bindings.Session) -> None:
        self._client = client
        self._session = session
        self._buffer = CausalOrderBuffer()
        # message id -> full inbound content dict, so a released envelope can be
        # paired back with the human-facing payload it arrived with (the buffer
        # itself only holds envelopes). Popped as envelopes release.
        self._content_by_id: dict[str, dict[str, Any]] = {}

    @property
    def session(self) -> slim_bindings.Session:
        return self._session

    def note_delivered(self, envelope: L9) -> None:
        """Mark ``envelope`` delivered in the causal buffer without receiving it.

        For messages the moderator ingests locally (never arriving via
        :meth:`receive_with_context`), so a later reply parented on them can be
        released rather than held forever.
        """
        message = envelope.header.message
        if message is not None and message.id is not None:
            self._buffer.mark_delivered(message.id)

    async def send(self, envelope: L9, *, extra: dict[str, Any] | None = None) -> None:
        """Serialize ``envelope`` and broadcast it to the group."""
        from app.services.slim_client import SlimClient

        await SlimClient.publish(self._session, serialize_envelope(envelope, extra=extra))

    async def send_content_to(
        self, context: slim_bindings.MessageContext, content: dict[str, Any]
    ) -> None:
        """Point-to-point re-send of a whole ``content`` dict to one member.

        Used by the durable-inbox persister to re-serve a missed message: the
        stored ``content`` already carries its ``l9`` envelope, so it is
        republished verbatim (the receiver's own :class:`CausalOrderBuffer`
        re-orders and de-duplicates it). ``context`` targets the reconnecting
        member (see :meth:`SlimClient.publish_to`).
        """
        from app.services.slim_client import SlimClient

        await SlimClient.publish_to(self._session, context, json.dumps(content).encode("utf-8"))

    async def receive(self, *, timeout_s: float = 30.0) -> list[L9]:
        """Pull one broadcast; return the envelopes it makes causally deliverable."""
        released, _arrived, _ctx = await self.receive_with_context(timeout_s=timeout_s)
        return [env for env, _content in released]

    async def receive_with_context(
        self, *, timeout_s: float = 30.0
    ) -> tuple[list[tuple[L9, dict[str, Any]]], L9, slim_bindings.MessageContext]:
        """Pull one message; return ``(released, arrived, context)``.

        ``released`` is the list of ``(envelope, content)`` pairs the arrival
        makes causally deliverable (each content is the full inbound dict,
        including its ``l9`` key — what the persister records and re-serves).
        ``arrived`` is the envelope that just arrived (whose sender the persister
        keys the reply ``context`` by, so it can later re-serve to that member).
        ``context`` is the raw ``MessageContext`` for point-to-point replies.
        """
        from app.services.slim_client import SlimClient

        try:
            message = await SlimClient.receive_message(self._session, timeout_s=timeout_s)
        except Exception as exc:
            if _RECEIVE_TIMEOUT_MARKER in str(exc).lower():
                raise ChannelReceiveTimeout(str(exc)) from exc
            raise
        arrived, content = deserialize_envelope(message.payload)
        mid = arrived.header.message.id if arrived.header.message is not None else None
        if mid is not None:
            self._content_by_id[mid] = content
        released: list[tuple[L9, dict[str, Any]]] = []
        for env in self._buffer.add(arrived):
            rid = env.header.message.id if env.header.message is not None else None
            paired = self._content_by_id.pop(rid, None) if rid is not None else None
            if paired is None:
                paired = serialize_content(env)
            released.append((env, paired))
        return released, arrived, message.context
