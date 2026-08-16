# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Thin async wrapper around ``slim-bindings`` for mycelium's SLIM fabric.

This module provides two things:

1. **Naming / identity** — map a mycelium ``workspace/room/agent`` triple to a
   SLIM :class:`Name` (``org/namespace/app``, with org = workspace/tenant,
   namespace = room, app = agent id) and back, plus a dev shared-secret minter.
2. **A small client** (:class:`SlimClient`) that stands up a SLIM app, connects
   to a node, creates/joins a **group** channel, and exchanges broadcasts. It
   carries membership (invite/remove) and a close/teardown path for the
   long-lived room connections.

The L9↔SLIM binding that rides envelopes over these group sessions lives in
``l9_slim.py``; the backend-as-moderator room provisioning that drives it lives
in ``room_channels.py``. The durable inbox/persister lives in ``persister.py``.

The ``slim_bindings`` import is **lazy** (native Rust wheel, availability is
per-platform): modules that never touch SLIM import cleanly even where no wheel
exists, and a missing wheel degrades to a clear :class:`SlimUnavailableError`
rather than an import-time crash across every backend module.

Ground truth for the binding API is the cloned examples under
``~/Documents/GitHub/_slim-research/slim-bindings/python/examples/`` (``group.py``
+ ``common.py``); this wrapper follows their lifecycle.
"""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import hmac
import logging
import os
import socket
from dataclasses import dataclass
from types import ModuleType
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from app.services import slim_identity

if TYPE_CHECKING:
    import slim_bindings

# The node's default listen address (matches ghcr.io/agntcy/slim's default port).
DEFAULT_NODE_ENDPOINT = "http://127.0.0.1:46357"

# Default port used when a node endpoint URL omits one (reachability probe).
DEFAULT_NODE_PORT = 46357

# Minimum length of the shared-secret identity PSK required by SLIM's dev auth.
MIN_SECRET_LEN = 32

# Default third segment for a room's group-channel Name when no explicit topic
# is given. A channel is a Name whose app segment is the topic; the members'
# own apps are their agent ids.
DEFAULT_CHANNEL_TOPIC = "room"

# Master secret from which per-channel shared secrets are *deterministically*
# derived, so every agent on a room's channel and the always-on backend
# independently reconstruct the same credential (which seeds the group key)
# without a key-exchange round-trip. The shared secret is the MVP identity tier;
# JWT/SPIRE is the production path (debt D1) and is out of scope here.
#
# The built-in literal below is a **public dev default** — anyone with the repo
# can derive it, so it protects nothing on its own (debt D1). A real deployment
# sets ``MYCELIUM_SLIM_MASTER_SECRET`` to a private value; every host that shares
# rooms must set the *same* value (it's a shared secret, not per-host). Set
# ``MYCELIUM_SLIM_REQUIRE_SECRET=1`` to hard-refuse the dev default (fail closed
# on a host that forgot to configure a real secret).
_MASTER_SECRET_ENV = "MYCELIUM_SLIM_MASTER_SECRET"
_REQUIRE_SECRET_ENV = "MYCELIUM_SLIM_REQUIRE_SECRET"
_DEV_MASTER_SECRET = "mycelium-dev-shared-secret-v1-do-not-use-in-prod"

logger = logging.getLogger(__name__)

# Warn only once per process when falling back to the public dev secret.
_dev_secret_warned = False

# Warn only once per (mode, handle) when a selected identity degrades to the PSK.
_identity_degraded_warned: set[tuple[str, str]] = set()

# Per-mode hint for the degrade warning / fail-closed error: what material is
# missing and how to provision it.
_IDENTITY_MISSING_HINT = {
    slim_identity.MODE_SIGNERJWT: (
        "no signing key/roster resolved — register the agent's key (ensure_agent_keypair)"
    ),
    slim_identity.MODE_SPIRE: (
        "no SPIRE Workload API socket present — start the co-located SPIRE agent "
        "and set MYCELIUM_SLIM_SPIRE_SOCKET"
    ),
}


def _warn_identity_degraded(mode: str, handle: str) -> None:
    """One-time warning that a selected identity mode fell back to the PSK.

    A silent downgrade is a security smell, so the fallback is announced even
    though it is the specified off-by-default behavior (#567). Set
    ``MYCELIUM_SLIM_IDENTITY_REQUIRE=1`` to refuse the fallback instead.
    """
    if (mode, handle) in _identity_degraded_warned:
        return
    _identity_degraded_warned.add((mode, handle))
    hint = _IDENTITY_MISSING_HINT.get(mode, "no identity material resolved")
    logger.warning(
        "MYCELIUM_SLIM_IDENTITY=%s but %s for %r — falling back to the shared-secret "
        "PSK. Set MYCELIUM_SLIM_IDENTITY_REQUIRE=1 to fail closed.",
        mode,
        hint,
        handle,
    )


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() not in ("", "0", "false", "no")


def resolve_master_secret() -> str:
    """The master secret to derive channel secrets from.

    Prefers ``MYCELIUM_SLIM_MASTER_SECRET``; otherwise falls back to the public
    dev literal with a one-time warning, or — when ``MYCELIUM_SLIM_REQUIRE_SECRET``
    is set — refuses outright so a misconfigured production host fails closed
    instead of silently joining channels anyone could join.
    """
    secret = os.getenv(_MASTER_SECRET_ENV, "").strip()
    if secret:
        return secret
    if _truthy(os.getenv(_REQUIRE_SECRET_ENV)):
        raise SlimError(
            f"{_REQUIRE_SECRET_ENV} is set but {_MASTER_SECRET_ENV} is not: refusing "
            "to derive channel keys from the public dev secret. Set "
            f"{_MASTER_SECRET_ENV} to a private value shared across your hosts."
        )
    global _dev_secret_warned
    if not _dev_secret_warned:
        _dev_secret_warned = True
        logger.warning(
            "SLIM channel keys are derived from the built-in public dev secret — "
            "anyone with the repo can join. Set %s to a private value (the same on "
            "every host that shares rooms) before any hosted/multi-user use.",
            _MASTER_SECRET_ENV,
        )
    return _DEV_MASTER_SECRET


class SlimError(RuntimeError):
    """Base class for SLIM wrapper errors."""


class SlimUnavailableError(SlimError):
    """Raised when ``slim_bindings`` cannot be imported (no native wheel)."""


class SlimNameError(SlimError, ValueError):
    """Raised when a ``workspace/room/agent`` segment is not a valid Name part."""


@dataclass(frozen=True)
class SlimIdentity:
    """A mycelium coordination identity: ``workspace/room/agent``.

    Maps onto a SLIM :class:`Name` 3-tuple as
    ``org=workspace, namespace=room, app=agent``.
    """

    workspace: str
    room: str
    agent: str

    def as_tuple(self) -> tuple[str, str, str]:
        return (self.workspace, self.room, self.agent)

    def as_path(self) -> str:
        return f"{self.workspace}/{self.room}/{self.agent}"


def node_reachable(endpoint: str, *, timeout: float = 1.0) -> bool:
    """True if a TCP connection to the node ``endpoint`` succeeds quickly.

    A cheap pre-flight so best-effort callers (room provisioning) skip the full
    connect handshake when no node is up — keeping the unit suite fast and green
    without a live fabric. Mirrors the guard in ``tests/test_slim_roundtrip.py``.
    """
    parsed = urlparse(endpoint)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or DEFAULT_NODE_PORT
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _require_bindings() -> ModuleType:
    """Import ``slim_bindings`` lazily, or raise a clear error."""
    try:
        import slim_bindings
    except ImportError as exc:  # pragma: no cover - platform dependent
        raise SlimUnavailableError(
            "slim-bindings is not installed for this platform. It ships as a "
            "native wheel; install it (`uv add slim-bindings`) on a supported "
            "platform to use the SLIM fabric."
        ) from exc
    return slim_bindings


def _validate_segment(value: str, *, label: str) -> str:
    """Reject Name segments that would corrupt the ``org/ns/app`` encoding."""
    if not value or not value.strip():
        raise SlimNameError(f"{label} must be non-empty")
    if "/" in value:
        raise SlimNameError(f"{label} must not contain '/': {value!r}")
    return value


def to_slim_name(workspace: str, room: str, agent: str) -> slim_bindings.Name:
    """Map ``workspace/room/agent`` → a SLIM :class:`Name` (``org/ns/app``)."""
    sb = _require_bindings()
    _validate_segment(workspace, label="workspace")
    _validate_segment(room, label="room")
    _validate_segment(agent, label="agent")
    return sb.Name(workspace, room, agent)


def from_slim_name(name: slim_bindings.Name) -> SlimIdentity:
    """Recover the ``workspace/room/agent`` identity from a SLIM :class:`Name`."""
    org, namespace, app = name.components()
    return SlimIdentity(workspace=org, room=namespace, agent=app)


def to_channel_name(
    workspace: str, room: str, topic: str = DEFAULT_CHANNEL_TOPIC
) -> slim_bindings.Name:
    """Map a room to its group-channel :class:`Name` (``workspace/room/topic``).

    The channel is the multicast destination the moderator creates and members
    are invited into; its third segment is the topic, distinct from each
    member's own agent id.
    """
    sb = _require_bindings()
    _validate_segment(workspace, label="workspace")
    _validate_segment(room, label="room")
    _validate_segment(topic, label="topic")
    return sb.Name(workspace, room, topic)


def mint_shared_secret(identity: SlimIdentity, *, master_secret: str | None = None) -> str:
    """Mint the shared secret for a channel (``workspace/room``), ≥32 chars.

    The secret is **shared by every member of a room**: it is the channel's
    **authentication credential** (a pre-shared key SLIM HMACs each member's
    identity token with — ``create_app_with_secret``). Every member must derive
    the *same* value or its identity fails to verify and it can't join the group.
    It does **not** seed the group's encryption key — MLS runs its own group key
    agreement on top (Welcome/Commit/epoch, RFC 9420). It is therefore keyed on
    the channel scope (workspace/room), **not** the agent id — the ``agent`` field
    of *identity* is
    intentionally ignored. Derived via HMAC-SHA256 so any member can reconstruct
    it offline; the 64-char hex digest comfortably exceeds :data:`MIN_SECRET_LEN`.

    ``master_secret`` defaults to :func:`resolve_master_secret` (the
    ``MYCELIUM_SLIM_MASTER_SECRET`` env or the public dev literal); pass it
    explicitly only to derive a secret for a specific master (e.g. in tests).
    """
    if master_secret is None:
        master_secret = resolve_master_secret()
    scope = f"{identity.workspace}/{identity.room}"
    digest = hmac.new(
        master_secret.encode("utf-8"),
        scope.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    assert len(digest) >= MIN_SECRET_LEN
    return digest


def _ensure_service_initialized(sb: ModuleType) -> None:
    """Initialize the process-global SLIM service exactly once.

    ``initialize_with_defaults`` sets up tracing/runtime/service config. It is a
    process-global, so we guard on ``is_initialized()``. Safe under asyncio:
    there is no ``await`` between the check and the call, so no interleaving.
    """
    if not sb.is_initialized():
        sb.initialize_with_defaults()


# The global SLIM service permits only ONE dataplane connection per endpoint per
# process ("client already connected" otherwise). Multiple apps in the same
# process — the daemon hosting several agent connectors, or a moderator+member
# test — must share that connection and multiplex their apps over its conn_id.
# Cache it per endpoint. (In production the backend moderator and each agent
# connector are separate processes, so each owns its own connection.)
_connections: dict[str, int] = {}


async def _shared_connection(service: slim_bindings.Service, sb: ModuleType, endpoint: str) -> int:
    """Return the process-wide conn_id for ``endpoint``, connecting once.

    Callers connect sequentially (there is no first-connect race in the
    moderator→member handshake), so no lock is needed here.
    """
    conn_id = _connections.get(endpoint)
    if conn_id is None:
        client_config = sb.new_insecure_client_config(endpoint)
        # Enable idle keepalive. ``new_insecure_client_config`` leaves
        # ``keepalive=None`` → the binding's ``keep_alive_while_idle`` defaults to
        # False, so the node drops a connection after ~30s of silence (its
        # RecoveryTable TTL). For the always-on moderator that means a quiet
        # room's group session silently dies and every member's route with it.
        # Keep idle connections alive so long-lived channels survive gaps.
        client_config.keepalive = sb.KeepaliveConfig(
            tcp_keepalive=datetime.timedelta(seconds=90),
            http2_keepalive=datetime.timedelta(seconds=45),
            timeout=datetime.timedelta(seconds=20),
            keep_alive_while_idle=True,
        )
        conn_id = await service.connect_async(client_config)
        _connections[endpoint] = conn_id
    return conn_id


async def close_connection(endpoint: str) -> None:
    """Drop and disconnect the cached dataplane connection for ``endpoint``.

    Long-lived room connections need a teardown path: without one the
    ``_connections`` cache would hand back a stale conn_id
    after a node bounce. Best-effort — a missing binding or already-closed conn
    is not an error. ``Service.disconnect`` is blocking, so it runs off-loop.
    """
    conn_id = _connections.pop(endpoint, None)
    if conn_id is None:
        return
    try:
        sb = _require_bindings()
    except SlimUnavailableError:  # pragma: no cover - platform dependent
        return
    service = sb.get_global_service()
    await asyncio.to_thread(service.disconnect, conn_id)


class SlimClient:
    """A single SLIM app bound to one node connection.

    Lifecycle (mirrors the binding examples)::

        client = await SlimClient(identity).connect(endpoint)
        # moderator:
        session = await client.create_group(channel_name)
        await client.invite(session, member_name)
        # participant:
        session = await client.listen_for_session()
        # either side:
        await SlimClient.publish(session, b"hello")
        payload = await SlimClient.receive(session)

    Reusable by both the backend (moderator) and the daemon (per-agent
    connectors).
    """

    def __init__(self, identity: SlimIdentity, *, secret: str | None = None) -> None:
        self.identity = identity
        self._secret = secret or mint_shared_secret(identity)
        self._sb: ModuleType | None = None
        self._app: slim_bindings.App | None = None
        self._conn_id: int | None = None
        self._local_name: slim_bindings.Name | None = None
        # Sessions this app created (moderator) or joined (member), so close()
        # can leave them — rooms are long-lived, not one-shot.
        self._sessions: list[slim_bindings.Session] = []

    async def connect(self, endpoint: str = DEFAULT_NODE_ENDPOINT) -> SlimClient:
        """Connect to the node and register this app under its local Name."""
        sb = _require_bindings()
        _ensure_service_initialized(sb)
        service = sb.get_global_service()

        self._sb = sb
        self._local_name = to_slim_name(*self.identity.as_tuple())
        self._conn_id = await _shared_connection(service, sb, endpoint)
        self._app = self._create_app(service)
        await self._app.subscribe_async(self._local_name, self._conn_id)
        return self

    def _create_app(self, service: slim_bindings.Service) -> slim_bindings.App:
        """Register the local app, selecting the identity tier (PSK default).

        ``psk`` (default, #567) is the shared-secret credential — the try-it path,
        untouched. ``signerjwt`` (the floor, #476) presents a per-member self-signed
        ES256 identity; ``spire`` (#579) presents a SPIRE-attested JWT-SVID. Both
        resolve to an ``IdentityProviderConfig``/``IdentityVerifierConfig`` pair so
        members are cryptographically distinct MLS participants; both share one
        degrade/fail-closed path. Absent the mode's material it degrades to PSK with
        a one-time warning, unless ``MYCELIUM_SLIM_IDENTITY_REQUIRE=1`` fails closed.
        """
        assert self._local_name is not None
        mode = slim_identity.resolve_identity_mode()
        if mode != slim_identity.MODE_PSK:
            material = slim_identity.resolve_identity_material(mode, self.identity.agent)
            if material is not None:
                provider, verifier = material
                return service.create_app(self._local_name, provider, verifier)
            if slim_identity.identity_required():
                hint = _IDENTITY_MISSING_HINT.get(mode, "no identity material resolved")
                raise SlimError(
                    f"MYCELIUM_SLIM_IDENTITY={mode} but {hint} for "
                    f"{self.identity.agent!r}, and MYCELIUM_SLIM_IDENTITY_REQUIRE is "
                    "set: refusing to fall back to the shared-secret PSK."
                )
            _warn_identity_degraded(mode, self.identity.agent)
        return service.create_app_with_secret(self._local_name, self._secret)

    @property
    def app(self) -> slim_bindings.App:
        if self._app is None:
            raise SlimError("SlimClient.connect() has not been called")
        return self._app

    def _group_session_config(self) -> slim_bindings.SessionConfig:
        sb = self._sb
        assert sb is not None
        # MLS ON for real room channels: intermediate nodes see only ciphertext,
        # which is what the hosted-rendezvous story rests on. The shared secret
        # (create_app_with_secret) is the identity PSK that
        # authenticates each member; MLS itself performs the group key agreement
        # (Welcome/Commit/epoch, RFC 9420) — the node never holds the group key.
        return sb.SessionConfig(
            session_type=sb.SessionType.GROUP,
            # SLIM 2.0 replaced the ``enable_mls`` bool with ``mls_settings`` —
            # MLS is on iff settings are present. 100% header-integrity validation
            # keeps the old always-on posture. Matched pair with the CLI member.
            mls_settings=sb.MlsSettings(
                header_integrity_validation_percent=100,
                max_seen_control_message_ids_size=None,  # None → SLIM core default
            ),
            max_retries=5,
            interval=datetime.timedelta(seconds=5),
            metadata={},
        )

    async def create_group(self, channel: slim_bindings.Name) -> slim_bindings.Session:
        """Create (and become moderator of) the group session for ``channel``."""
        session = await self.app.create_session_and_wait_async(
            self._group_session_config(), channel
        )
        self._sessions.append(session)
        return session

    async def invite(self, session: slim_bindings.Session, member: slim_bindings.Name) -> None:
        """Route to and invite ``member`` into the moderated group ``session``."""
        assert self._conn_id is not None
        await self.app.set_route_async(member, self._conn_id)
        handle = await session.invite_async(member)
        await handle.wait_async()

    async def listen_for_session(self) -> slim_bindings.Session:
        """Block until this app is invited into a group, then return the session."""
        session = await self.app.listen_for_session_async(None)
        self._sessions.append(session)
        return session

    async def remove_member(
        self, session: slim_bindings.Session, member: slim_bindings.Name
    ) -> None:
        """Remove ``member`` from the moderated group ``session`` (a leave)."""
        handle = await session.remove_async(member)
        await handle.wait_async()

    async def close(self) -> None:
        """Leave every session this app holds. Best-effort; never raises.

        Does **not** drop the shared dataplane connection — sibling apps in the
        process may still use it. Use :func:`close_connection` for that.
        """
        for session in self._sessions:
            try:
                await self.app.delete_session_and_wait_async(session)
            except Exception:  # pragma: no cover - best-effort teardown
                pass
        self._sessions.clear()

    @staticmethod
    async def publish(session: slim_bindings.Session, data: bytes) -> None:
        """Broadcast ``data`` to every current member of the group ``session``.

        Matches the binding example: ``publish_async`` is awaited and its
        completion handle ignored (best-effort send; SLIM has no durable inbox).
        """
        await session.publish_async(data, None, None)

    @staticmethod
    async def publish_to(
        session: slim_bindings.Session, context: slim_bindings.MessageContext, data: bytes
    ) -> None:
        """Send ``data`` to the single member that produced ``context``.

        Point-to-point over the group session (``publish_to_async``): the reply
        is routed to ``context``'s source only, not fanned out to the whole
        group. This is the transport the durable-inbox persister uses to
        **re-serve** missed messages to one reconnecting agent without
        re-delivering to everyone. ``context`` is a ``MessageContext`` captured
        from an earlier inbound message from that member (see
        :meth:`receive_message`). Best-effort, like :meth:`publish`.
        """
        await session.publish_to_async(context, data, None, None)

    @staticmethod
    async def receive(session: slim_bindings.Session, *, timeout_s: float = 30.0) -> bytes:
        """Block for the next inbound broadcast on ``session`` and return its bytes.

        This blocking pull is the wake monitor.
        """
        message = await session.get_message_async(timeout=datetime.timedelta(seconds=timeout_s))
        return message.payload

    @staticmethod
    async def receive_message(
        session: slim_bindings.Session, *, timeout_s: float = 30.0
    ) -> slim_bindings.ReceivedMessage:
        """Block for the next inbound message and return the whole message.

        Unlike :meth:`receive` (payload bytes only), this preserves the
        ``.context`` (a ``MessageContext`` carrying the sender's routable
        source) so the persister can later :meth:`publish_to` that sender. The
        returned object exposes ``.payload`` (bytes) and ``.context``.
        """
        return await session.get_message_async(timeout=datetime.timedelta(seconds=timeout_s))
