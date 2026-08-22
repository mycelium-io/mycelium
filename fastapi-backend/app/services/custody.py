# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Server-side custodial SLIM/MLS sessions (#666).

Under the PSK default the backend is a single MLS member per room and acts for every
actor: attribution ("@alice said this") is added application-side and is forgeable,
and access control is application logic. This module is the alternative proven in the
#662/#665 spike: the backend holds one genuine MLS-member session per ``(room,
actor)``, keeping that actor's own SignerJwt key and MLS state on its behalf.
``respond(@alice, ...)`` sends through @alice's session, so the wire sender is
@alice's own MLS identity, and room access is enforced by MLS group membership rather
than application logic.

"Custodial" is used in the key-management sense: the hub holds the keys on the
actor's behalf (server-side). A native client holding its own session would be the
non-custodial case, which is out of scope here.

Off by default (#567): custodial sessions engage only when ``slim.identity`` is
``signerjwt``, never under the PSK default, where the try-it path is unchanged. This is structural, not just policy: ``create_app_with_persistence_async``
requires the identity provider/verifier pair, so a custodial session cannot run on
the PSK tier.

Scope boundary: because the hub holds every session's private key and plaintext, all
backend cognition (aligner, plan compiler, memory-sync, L9) still reads plaintext.
This hardens attribution and access-by-membership and makes per-agent identity real
at the MLS layer, but it is not end-to-end encryption from the hub: a compromised hub
can still read and impersonate everything. Client-held (non-custodial) sessions are a
separate, later step.

Per-session MLS state is persisted at rest via ``agntcy-slim-persistence`` (SQLite),
one directory per session under ``<data>/custody/{room}/{handle}/``. The at-rest
passphrase is ``HMAC(server session secret, workspace/room/handle)``, so each store
has a distinct key and one leaked passphrase does not open every session. The session
secret is server-held (``MYCELIUM_CUSTODY_STORE_SECRET``), not the actor's
OIDC/SignerJwt token (which rotates and is not a durable at-rest key). On backend
restart ``restore_sessions`` revives every session from its store without a
re-invite; SLIM resumes crypto state only, never missed messages, so the durable
transcript/inbox (:mod:`app.services.persister`) stays the offline-replay layer.
"""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import hmac
import logging
import os
import shutil
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from app.services import slim_identity
from app.services.slim_client import (
    SlimError,
    _ensure_service_initialized,
    _require_bindings,
    _shared_connection,
    to_slim_name,
)

if TYPE_CHECKING:
    from types import ModuleType

    import slim_bindings

logger = logging.getLogger(__name__)

# The server-held secret the per-session at-rest passphrase is derived from. Like
# ``MYCELIUM_SLIM_MASTER_SECRET`` it falls back to a public dev literal (which
# protects nothing) with a one-time warning; a real deployment sets a private
# value and — with ``MYCELIUM_CUSTODY_REQUIRE_SECRET=1`` — fails closed rather than
# persisting custodial state under a key anyone with the repo can derive.
_STORE_SECRET_ENV = "MYCELIUM_CUSTODY_STORE_SECRET"
_REQUIRE_STORE_SECRET_ENV = "MYCELIUM_CUSTODY_REQUIRE_SECRET"
_DEV_STORE_SECRET = "mycelium-dev-custody-store-secret-v1-do-not-use-in-prod"

# Escape hatch to force custody off even when an identity mode is selected — the
# migration is additive to, not a replacement of, the server-held-membership
# model, so a host can fall back to the single-moderator path without switching
# identity off. Absent this, custody follows the identity mode (on iff not PSK).
_DISABLE_ENV = "MYCELIUM_CUSTODY_DISABLE"

# Per-session MLS-state stores live under ``<data>/custody/`` (sibling to the
# ``slim-identity`` keys/roster). One directory per session; the persistence crate
# writes a real SQLite DB (+ WAL) inside the ``mls-state.sqlite`` path it is given.
_STORE_SUBDIR = "custody"
_STORE_DB_NAME = "mls-state.sqlite"

_dev_store_secret_warned = False


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() not in ("", "0", "false", "no")


def custody_enabled() -> bool:
    """True when per-actor custodial sessions should carry room traffic.

    They engage only under a real identity tier (``signerjwt``): the PSK
    default is untouched (#567), and persistence structurally requires the identity
    provider/verifier pair anyway (spike finding C). ``MYCELIUM_CUSTODY_DISABLE``
    forces the single-moderator path even under identity, so the migration stays
    reversible without switching identity off.
    """
    if _truthy(os.getenv(_DISABLE_ENV)):
        return False
    return slim_identity.resolve_identity_mode() != slim_identity.MODE_PSK


def resolve_store_secret() -> str:
    """The server-held secret the per-session at-rest passphrase derives from.

    Prefers ``MYCELIUM_CUSTODY_STORE_SECRET``; else the public dev literal with a
    one-time warning, or — when ``MYCELIUM_CUSTODY_REQUIRE_SECRET`` is set — refuses
    outright so a host that forgot to configure a real secret fails closed rather
    than persisting custodial MLS state under a key anyone can reconstruct.
    """
    secret = os.getenv(_STORE_SECRET_ENV, "").strip()
    if secret:
        return secret
    if _truthy(os.getenv(_REQUIRE_STORE_SECRET_ENV)):
        raise SlimError(
            f"{_REQUIRE_STORE_SECRET_ENV} is set but {_STORE_SECRET_ENV} is not: "
            "refusing to derive custodial at-rest keys from the public dev secret. Set "
            f"{_STORE_SECRET_ENV} to a private, server-held value."
        )
    global _dev_store_secret_warned
    if not _dev_store_secret_warned:
        _dev_store_secret_warned = True
        logger.warning(
            "custodial MLS-state stores are encrypted with the built-in public dev "
            "secret — anyone with the repo can derive it. Set %s to a private, "
            "server-held value before any hosted/multi-user use.",
            _STORE_SECRET_ENV,
        )
    return _DEV_STORE_SECRET


def store_passphrase(workspace: str, room: str, handle: str) -> str:
    """At-rest passphrase for a store: ``HMAC(secret, ws/room/handle)``.

    Keyed on the full ``(workspace, room, handle)`` scope so every store gets a
    distinct key — one leaked passphrase opens one session, not the fleet. Derived
    with HMAC-SHA256; the hex digest is the passphrase the persistence crate uses
    for AES-256-GCM value-level encryption of the stored MLS state.
    """
    scope = f"{workspace}/{room}/{handle}"
    return hmac.new(
        resolve_store_secret().encode("utf-8"),
        scope.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def store_root(data_dir: Path | None = None) -> Path:
    """Root directory holding every custodial store (``<data>/custody``)."""
    return (data_dir or slim_identity.resolve_data_dir()) / _STORE_SUBDIR


def store_dir(room: str, handle: str, data_dir: Path | None = None) -> Path:
    """The per-session store directory (``<data>/custody/{room}/{handle}``)."""
    return store_root(data_dir) / slim_identity._safe(room) / slim_identity._safe(handle)


def store_path(room: str, handle: str, data_dir: Path | None = None) -> str:
    """The ``path`` handed to :class:`PersistenceConfig` for a session.

    The persistence crate treats this as a **directory** it writes a SQLite DB
    (+ WAL/SHM sidecars) into; it is created eagerly so the crate can open it.
    """
    path = store_dir(room, handle, data_dir) / _STORE_DB_NAME
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def iter_persisted_sessions(data_dir: Path | None = None) -> Iterator[tuple[str, str]]:
    """Yield ``(room_dir, handle_dir)`` for every custodial store on disk.

    The durable source of truth for "which sessions to restore on startup" — a
    session exists iff its store directory does. The yielded names are the
    filesystem-safe forms written by :func:`store_dir`; the caller maps them back
    to live rooms/handles (a room whose name survives :func:`slim_identity._safe`
    unchanged, which room names must to be valid SLIM Name segments).
    """
    root = store_root(data_dir)
    if not root.is_dir():
        return
    for room_entry in sorted(root.iterdir()):
        if not room_entry.is_dir():
            continue
        for handle_entry in sorted(room_entry.iterdir()):
            if handle_entry.is_dir():
                yield room_entry.name, handle_entry.name


def delete_store(room: str, handle: str, data_dir: Path | None = None) -> bool:
    """Delete a session's at-rest store — the backend half of revocation (#590).

    A graceful group leave purges the crate's own state; this removes the store
    directory so a torn-down session can never be revived by :func:`restore_session`.
    Best-effort; returns whether a directory was removed.
    """
    path = store_dir(room, handle, data_dir)
    if not path.exists():
        return False
    shutil.rmtree(path, ignore_errors=True)
    return not path.exists()


def wire_sender(context: slim_bindings.MessageContext) -> str | None:
    """Recover the sender's cryptographic Name leaf from an inbound context.

    Under custody the sender on the wire is the actor's own MLS identity, so this
    is the non-forgeable attribution the moderator can cross-check against the L9
    envelope's stamped ``sender`` — the whole point of #666. Best-effort across the
    binding's context shape; ``None`` if no source Name is exposed.
    """
    for attr in ("source_name", "source", "name"):
        val = getattr(context, attr, None)
        if val is None:
            continue
        for meth in ("components", "as_tuple"):
            fn = getattr(val, meth, None)
            if callable(fn):
                try:
                    return fn()[-1]
                except Exception:
                    pass
        return str(val)
    return None


def _resolve_material(
    handle: str,
) -> tuple[slim_bindings.IdentityProviderConfig, slim_bindings.IdentityVerifierConfig]:
    """Resolve the actor's own provider/verifier pair for its custodial session.

    A custodial session is a genuine MLS member carrying the *actor's* credential,
    so — under ``signerjwt`` — the backend custodies the actor's signing key: mint+
    register it if absent (idempotent) so the backend can sign as the actor and the
    roster includes it. Raises :class:`SlimError` when no material resolves
    (persistence cannot run on the PSK tier, so there is no degrade path here).
    """
    mode = slim_identity.resolve_identity_mode()
    if mode == slim_identity.MODE_SIGNERJWT:
        # Custody the actor's signing key server-side (the honest scope boundary):
        # the backend holds it so it can sign as the actor. Idempotent.
        slim_identity.ensure_agent_keypair(handle)
    material = slim_identity.resolve_identity_material(mode, handle)
    if material is None:
        raise SlimError(
            f"cannot open a custodial session for {handle!r}: MYCELIUM_SLIM_IDENTITY={mode} "
            "but no signing key/roster resolved. Custody requires signerjwt material "
            "(persistence cannot run on the PSK tier)."
        )
    return material


def _persistence_config(sb: ModuleType, room: str, handle: str, workspace: str):
    return sb.PersistenceConfig(
        path=store_path(room, handle),
        passphrase=store_passphrase(workspace, room, handle),
    )


@dataclass
class CustodialSession:
    """One backend-custodied MLS-member session for a single ``(room, actor)``.

    Holds the actor's persistence-backed App and — once the moderator has invited
    it (or ``restore_sessions`` has revived it) — the group session it publishes
    on. All custodial sessions in a process multiplex over the one shared dataplane
    connection.
    """

    workspace: str
    room: str
    handle: str
    app: slim_bindings.App
    name: slim_bindings.Name
    session: slim_bindings.Session | None = None
    # Set once a listen/restore has bound the group session, so a double-ensure is
    # a cheap no-op rather than a second invite.
    joined: bool = field(default=False)
    # A background task that consumes and discards inbound (see :meth:`drain`). The
    # manager owns its start; the session owns its stop.
    drain_task: asyncio.Task[None] | None = field(default=None)

    async def publish(self, data: bytes) -> None:
        """Broadcast ``data`` to the group as the actor (a real MLS send)."""
        if self.session is None:
            raise SlimError(
                f"custodial session for {self.handle!r} in {self.room!r} has no group session"
            )
        await self.session.publish_async(data, None, None)

    async def drain(self) -> None:
        """Consume and discard inbound to keep the session's buffer bounded.

        A custodial session is a live MLS group member, so SLIM queues every room
        broadcast on it. The **moderator** is the authoritative reader (it records
        the transcript that ``await`` serves); the session never needs its own copy
        — but an undrained one would grow unbounded over a room's life. Timeouts are
        benign idle ticks; a burst of genuine faults ends the task (the session is
        re-ensured on its next send).
        """
        errors = 0
        while self.session is not None:
            try:
                await self.session.get_message_async(timeout=datetime.timedelta(seconds=30))
                errors = 0
            except asyncio.CancelledError:
                raise
            except Exception:  # timeout/churn are benign; discard and keep draining
                errors += 1
                if errors > 50:
                    logger.debug("custodial %s drain giving up after repeated faults", self.handle)
                    return
                await asyncio.sleep(0.2)

    async def close(self, *, graceful: bool) -> None:
        """Drop the App. ``graceful`` leaves the MLS group (a real remove).

        A graceful close (revocation) removes the member from the group *and*
        purges its persisted state — the opposite of a crash. A non-graceful close
        (shutdown) leaves the store intact so ``restore_sessions`` can revive it.
        Best-effort; never raises.
        """
        if self.drain_task is not None:
            self.drain_task.cancel()
            self.drain_task = None
        if graceful and self.session is not None:
            try:
                await self.app.delete_session_and_wait_async(self.session)
            except Exception:  # pragma: no cover - best-effort teardown
                logger.debug("graceful leave failed for %s in %s", self.handle, self.room)
        self.session = None
        self.joined = False


async def create_session(endpoint: str, workspace: str, room: str, handle: str) -> CustodialSession:
    """Create (or re-open) the persistence-backed App for a session and subscribe.

    Does **not** join the group — the caller either drives the moderator invite +
    :func:`join_session`, or calls :func:`restore_session` to revive persisted state.
    """
    sb = _require_bindings()
    _ensure_service_initialized(sb)
    service = sb.get_global_service()
    conn_id = await _shared_connection(service, sb, endpoint)
    provider, verifier = _resolve_material(handle)
    name = to_slim_name(workspace, room, handle)
    app = await service.create_app_with_persistence_async(
        name,
        provider,
        verifier,
        sb.Direction.BIDIRECTIONAL,
        _persistence_config(sb, room, handle, workspace),
    )
    await app.subscribe_async(name, conn_id)
    return CustodialSession(workspace=workspace, room=room, handle=handle, app=app, name=name)


async def join_session(cs: CustodialSession, *, timeout_s: float = 30.0) -> None:
    """Block until the moderator's invite lands, binding the group session.

    Started concurrently with the moderator invite: ``listen_for_session_async``
    blocks until this member is admitted into the group, then yields the session it
    publishes on.
    """
    cs.session = await cs.app.listen_for_session_async(datetime.timedelta(seconds=timeout_s))
    cs.joined = True


async def restore_session(
    endpoint: str, workspace: str, room: str, handle: str
) -> CustodialSession | None:
    """Revive a persisted session from its store — no re-invite, no MLS Welcome.

    Re-opens the App against the same store path + passphrase and calls
    ``restore_sessions``: each restored session rejoins its MLS group from disk at
    the group's current epoch. The always-draining moderator processes the
    ``rejoin`` so inbound resumes too (spike D1). Returns ``None`` when nothing was
    persisted for this session.
    """
    cs = await create_session(endpoint, workspace, room, handle)
    sb = _require_bindings()
    service = sb.get_global_service()
    conn_id = await _shared_connection(service, sb, endpoint)
    sessions = await cs.app.restore_sessions_async(conn_id)
    if not sessions:
        return None
    # A session lives in exactly the rooms its actor belongs to; each store holds
    # one room's session here (the store dir is per (room, handle)), so take the first.
    cs.session = sessions[0]
    cs.joined = True
    return cs
