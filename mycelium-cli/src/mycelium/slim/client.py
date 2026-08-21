# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Thin async wrapper around ``slim-bindings`` for the daemon connector.

The daemon-side twin of ``fastapi-backend/app/services/slim_client.py``. A
connector is a SLIM **member**: it registers an app, waits to be invited into
the room's group by the always-on backend moderator, then pulls broadcasts and
publishes its replies. The moderator methods (:meth:`create_group`,
:meth:`invite`) are included too so tests can stand up a fake backend against a
live node, but a connector never creates a group: one moderator per room, and
it's the backend.

``slim_bindings`` is imported **lazily** (native Rust wheel, per-platform): the
pure L9 helpers and the daemon's dispatch logic import cleanly where no wheel
exists, and a missing wheel degrades to a clear :class:`SlimUnavailableError`
rather than an import-time crash.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
from types import ModuleType
from typing import TYPE_CHECKING

from mycelium.slim import identity as slim_identity
from mycelium.slim.naming import (
    DEFAULT_NODE_ENDPOINT,
    SlimIdentity,
    mint_shared_secret,
    to_slim_name,
)

if TYPE_CHECKING:
    import slim_bindings

logger = logging.getLogger("mycelium.slim")

_identity_degraded_warned: set[tuple[str, str]] = set()

# Per-mode hint for the degrade warning / fail-closed error: what material is
# missing and how to provision it.
_IDENTITY_MISSING_HINT = {
    slim_identity.MODE_SIGNERJWT: (
        "no signing key/roster resolved; register the agent's key (ensure_agent_keypair)"
    ),
}


def _warn_identity_degraded(mode: str, handle: str) -> None:
    """One-time warning that a selected identity mode fell back to the PSK.

    A silent downgrade is a security smell, so the fallback is announced even
    though it is the specified off-by-default behavior. Set
    ``MYCELIUM_SLIM_IDENTITY_REQUIRE=1`` to refuse the fallback instead.
    """
    if (mode, handle) in _identity_degraded_warned:
        return
    _identity_degraded_warned.add((mode, handle))
    hint = _IDENTITY_MISSING_HINT.get(mode, "no identity material resolved")
    logger.warning(
        "MYCELIUM_SLIM_IDENTITY=%s but %s for %r; falling back to the shared-secret "
        "PSK. Set MYCELIUM_SLIM_IDENTITY_REQUIRE=1 to fail closed.",
        mode,
        hint,
        handle,
    )


class SlimError(RuntimeError):
    pass


class SlimUnavailableError(SlimError):
    """Raised when ``slim_bindings`` cannot be imported (no native wheel)."""


class SlimReceiveTimeout(SlimError):
    """A receive timed out with no message: a benign idle tick, not a fault.

    The binding raises a generic ``SessionError`` for both a real transport
    fault and a plain "no message within the window" timeout. On an idle channel
    the latter is normal, so the connector must keep waiting on the same session
    rather than treating it as a dropped session and reconnecting (which churns
    the group membership every timeout window). Callers catch this and loop.
    """


# Substring the binding puts in a timeout ``SessionError`` message. Matched
# because the binding exposes no distinct timeout type; a real transport fault
# carries different text.
_RECEIVE_TIMEOUT_MARKER = "receive timeout"


def require_bindings() -> ModuleType:
    """Import ``slim_bindings`` lazily, or raise a clear error."""
    try:
        import slim_bindings
    except ImportError as exc:  # pragma: no cover - platform dependent
        raise SlimUnavailableError(
            "slim-bindings is not installed for this platform. It ships as a "
            "native wheel; install it (`uv add slim-bindings`) on a supported "
            "platform to run a SLIM connector."
        ) from exc
    return slim_bindings


def _ensure_service_initialized(sb: ModuleType) -> None:
    """Initialize the process-global SLIM service exactly once."""
    if not sb.is_initialized():
        sb.initialize_with_defaults()


# The global SLIM service permits only ONE dataplane connection per endpoint per
# process. A daemon hosting several owned handles multiplexes its per-handle apps
# over that one connection; cache the conn_id per endpoint. (Callers connect
# sequentially, so no lock is needed here.)
_connections: dict[str, int] = {}


async def _shared_connection(service: slim_bindings.Service, sb: ModuleType, endpoint: str) -> int:
    conn_id = _connections.get(endpoint)
    if conn_id is None:
        client_config = sb.new_insecure_client_config(endpoint)
        # Enable idle keepalive. ``new_insecure_client_config`` leaves
        # ``keepalive=None`` → the binding's ``keep_alive_while_idle`` defaults to
        # False, so the node drops a connection after ~30s of silence (its
        # RecoveryTable TTL), which silently kills a waiting connector's route
        # and the moderator's session on any quiet room. Keep idle connections
        # alive so long-lived members survive gaps between messages.
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

    Best-effort teardown so a node bounce doesn't leave a stale conn_id cached.
    ``Service.disconnect`` is blocking, so it runs off-loop.
    """
    conn_id = _connections.pop(endpoint, None)
    if conn_id is None:
        return
    try:
        sb = require_bindings()
    except SlimUnavailableError:  # pragma: no cover - platform dependent
        return
    service = sb.get_global_service()
    await asyncio.to_thread(service.disconnect, conn_id)


class SlimClient:
    """A single SLIM app bound to one node connection.

    Lifecycle (member side)::

        client = await SlimClient(identity).connect(endpoint)
        session = await client.listen_for_session()   # backend invites us
        await SlimClient.publish(session, b"hello")
        message = await SlimClient.receive_message(session)
    """

    def __init__(self, identity: SlimIdentity, *, secret: str | None = None) -> None:
        self.identity = identity
        self._secret = secret or mint_shared_secret(identity)
        self._sb: ModuleType | None = None
        self._app: slim_bindings.App | None = None
        self._conn_id: int | None = None
        self._local_name: slim_bindings.Name | None = None
        self._sessions: list[slim_bindings.Session] = []

    async def connect(self, endpoint: str = DEFAULT_NODE_ENDPOINT) -> SlimClient:
        """Connect to the node and register this app under its local Name."""
        sb = require_bindings()
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

        Twin of the backend seam: ``psk`` is the shared-secret credential, the
        try-it path. ``signerjwt`` presents this member's per-agent self-signed
        ES256 identity, resolving to a provider/verifier pair through the same
        dispatcher: absent that material it degrades to PSK with a one-time warning
        unless ``MYCELIUM_SLIM_IDENTITY_REQUIRE=1`` fails closed.
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
        # MLS ON: the member authenticates into the moderator's encrypted group
        # with the shared-secret identity PSK it derives (create_app_with_secret);
        # MLS itself does the group key agreement. Matched pair with the backend;
        # do not diverge.
        return sb.SessionConfig(
            session_type=sb.SessionType.GROUP,
            # MLS is on iff settings are present; 100% header-integrity validation
            # ensures strict validation. Matched pair with backend config.
            mls_settings=sb.MlsSettings(
                header_integrity_validation_percent=100,
                max_seen_control_message_ids_size=None,  # None → SLIM core default
            ),
            max_retries=5,
            interval=datetime.timedelta(seconds=5),
            metadata={},
        )

    async def create_group(self, channel: slim_bindings.Name) -> slim_bindings.Session:
        """Create (and become moderator of) a group session (**tests only**).

        A connector never calls this; the backend is the sole moderator. It
        exists so a test can play the backend against a live node.
        """
        session = await self.app.create_session_and_wait_async(
            self._group_session_config(), channel
        )
        self._sessions.append(session)
        return session

    async def invite(self, session: slim_bindings.Session, member: slim_bindings.Name) -> None:
        """Route to and invite ``member`` into a moderated group (**tests only**)."""
        assert self._conn_id is not None
        await self.app.set_route_async(member, self._conn_id)
        handle = await session.invite_async(member)
        await handle.wait_async()

    async def listen_for_session(self) -> slim_bindings.Session:
        """Block until this app is invited into a group, then return the session."""
        session = await self.app.listen_for_session_async(None)
        self._sessions.append(session)
        return session

    async def close(self) -> None:
        """Leave every session this app holds. Best-effort; never raises.

        Does **not** drop the shared dataplane connection; sibling apps (other
        owned handles) in the process may still use it. Use
        :func:`close_connection` for that.
        """
        for session in self._sessions:
            try:
                await self.app.delete_session_and_wait_async(session)
            except Exception:  # noqa: BLE001 - best-effort teardown
                pass
        self._sessions.clear()

    @staticmethod
    async def publish(session: slim_bindings.Session, data: bytes) -> None:
        """Broadcast ``data`` to every current member of the group ``session``."""
        await session.publish_async(data, None, None)

    @staticmethod
    async def receive_message(
        session: slim_bindings.Session, *, timeout_s: float = 30.0
    ) -> slim_bindings.ReceivedMessage:
        """Block for the next inbound message and return the whole message.

        Preserves ``.payload`` (bytes) and ``.context`` (a ``MessageContext``
        carrying the sender's routable source).
        """
        try:
            return await session.get_message_async(timeout=datetime.timedelta(seconds=timeout_s))
        except Exception as exc:
            if _RECEIVE_TIMEOUT_MARKER in str(exc).lower():
                raise SlimReceiveTimeout(str(exc)) from exc
            raise
