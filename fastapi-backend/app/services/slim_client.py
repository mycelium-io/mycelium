# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Thin async wrapper around ``slim-bindings`` for mycelium's SLIM fabric.

**Step 2 scope only.** This module provides two things:

1. **Naming / identity** — map a mycelium ``workspace/room/agent`` triple to a
   SLIM :class:`Name` (``org/namespace/app``, with org = workspace/tenant,
   namespace = room, app = agent id) and back, plus a dev shared-secret minter.
2. **A small client** (:class:`SlimClient`) that stands up a SLIM app, connects
   to a node, and creates/joins a **group** channel to exchange broadcasts.

It is deliberately **isolated** from the room/coordination flow — nothing here
is wired into routes or the bus yet. Room-becomes-a-channel and L9-over-SLIM are
Step 3; the durable inbox/persister is Step 4. Keeping this standalone is what
lets Step 1's green stay green.

The ``slim_bindings`` import is **lazy** (native Rust wheel, availability is
per-platform): modules that never touch SLIM import cleanly even where no wheel
exists, and a missing wheel degrades to a clear :class:`SlimUnavailableError`
rather than an import-time crash across every backend module.

Ground truth for the binding API is the cloned examples under
``~/Documents/GitHub/_slim-research/slim-bindings/python/examples/`` (``group.py``
+ ``common.py``); this wrapper follows their lifecycle.
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
from dataclasses import dataclass
from types import ModuleType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import slim_bindings

# The node's default listen address (matches ghcr.io/agntcy/slim's default port).
DEFAULT_NODE_ENDPOINT = "http://127.0.0.1:46357"

# Minimum shared-secret length required by SLIM's dev auth (also seeds MLS).
MIN_SECRET_LEN = 32

# Default third segment for a room's group-channel Name when no explicit topic
# is given. A channel is a Name whose app segment is the topic (bible §7b); the
# members' own apps are their agent ids.
DEFAULT_CHANNEL_TOPIC = "room"

# Dev-only master secret from which per-channel shared secrets are
# *deterministically* derived, so every agent on a room's channel and the
# always-on backend independently reconstruct the same credential (which seeds
# the group key) without a key-exchange round-trip. This is the MVP identity tier
# per the bible (Step 2 resolve-first: shared secret); JWT/SPIRE is the production
# path and is out of scope here. Override per deployment via the ``master_secret``
# argument to :func:`mint_shared_secret`.
_DEV_MASTER_SECRET = "mycelium-dev-shared-secret-v1-do-not-use-in-prod"


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


def mint_shared_secret(identity: SlimIdentity, *, master_secret: str = _DEV_MASTER_SECRET) -> str:
    """Mint the dev shared secret for a channel (``workspace/room``), ≥32 chars.

    The secret is **shared by every member of a room**: it seeds the group's MLS
    key, so all agents on the same channel must derive the *same* value or they
    can't join each other's group. It is therefore keyed on the channel scope
    (workspace/room), **not** the agent id — the ``agent`` field of *identity* is
    intentionally ignored. Derived via HMAC-SHA256 so any member can reconstruct
    it offline; the 64-char hex digest comfortably exceeds :data:`MIN_SECRET_LEN`.
    """
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
        conn_id = await service.connect_async(client_config)
        _connections[endpoint] = conn_id
    return conn_id


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
    connectors) in later steps.
    """

    def __init__(self, identity: SlimIdentity, *, secret: str | None = None) -> None:
        self.identity = identity
        self._secret = secret or mint_shared_secret(identity)
        self._sb: ModuleType | None = None
        self._app: slim_bindings.App | None = None
        self._conn_id: int | None = None
        self._local_name: slim_bindings.Name | None = None

    async def connect(self, endpoint: str = DEFAULT_NODE_ENDPOINT) -> SlimClient:
        """Connect to the node and register this app under its local Name."""
        sb = _require_bindings()
        _ensure_service_initialized(sb)
        service = sb.get_global_service()

        self._sb = sb
        self._local_name = to_slim_name(*self.identity.as_tuple())
        self._conn_id = await _shared_connection(service, sb, endpoint)
        self._app = service.create_app_with_secret(self._local_name, self._secret)
        await self._app.subscribe_async(self._local_name, self._conn_id)
        return self

    @property
    def app(self) -> slim_bindings.App:
        if self._app is None:
            raise SlimError("SlimClient.connect() has not been called")
        return self._app

    def _group_session_config(self) -> slim_bindings.SessionConfig:
        sb = self._sb
        assert sb is not None
        # MLS stays off for the Step 2 hello-world (optional in SLIM); the
        # shared secret already gates node admission. MLS group encryption is a
        # later hardening step.
        return sb.SessionConfig(
            session_type=sb.SessionType.GROUP,
            enable_mls=False,
            max_retries=5,
            interval=datetime.timedelta(seconds=5),
            metadata={},
        )

    async def create_group(self, channel: slim_bindings.Name) -> slim_bindings.Session:
        """Create (and become moderator of) the group session for ``channel``."""
        return await self.app.create_session_and_wait_async(self._group_session_config(), channel)

    async def invite(self, session: slim_bindings.Session, member: slim_bindings.Name) -> None:
        """Route to and invite ``member`` into the moderated group ``session``."""
        assert self._conn_id is not None
        await self.app.set_route_async(member, self._conn_id)
        handle = await session.invite_async(member)
        await handle.wait_async()

    async def listen_for_session(self) -> slim_bindings.Session:
        """Block until this app is invited into a group, then return the session."""
        return await self.app.listen_for_session_async(None)

    @staticmethod
    async def publish(session: slim_bindings.Session, data: bytes) -> None:
        """Broadcast ``data`` to every current member of the group ``session``.

        Matches the binding example: ``publish_async`` is awaited and its
        completion handle ignored (best-effort send; SLIM has no durable inbox).
        """
        await session.publish_async(data, None, None)

    @staticmethod
    async def receive(session: slim_bindings.Session, *, timeout_s: float = 30.0) -> bytes:
        """Block for the next inbound broadcast on ``session`` and return its bytes.

        This blocking pull is the wake monitor in later steps.
        """
        message = await session.get_message_async(timeout=datetime.timedelta(seconds=timeout_s))
        return message.payload
