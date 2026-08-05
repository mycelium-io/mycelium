# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""SLIM naming / identity + shared-secret derivation (daemon side).

A byte-for-byte mirror of the naming half of
``fastapi-backend/app/services/slim_client.py``. **Keep the constants and the
derivation in sync with the backend** — the shared secret is the channel's
authentication PSK, so a connector that derives a different value fails identity
verification and cannot join the moderator's group. The values below are the same
ones the backend defaults to
(``SLIM_WORKSPACE = "mycelium"``, the dev master secret, the ``room`` channel
topic).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import socket
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    import slim_bindings

# The node's default listen address (matches ghcr.io/agntcy/slim's default port).
DEFAULT_NODE_ENDPOINT = "http://127.0.0.1:46357"

# Default port used when a node endpoint URL omits one (reachability probe).
DEFAULT_NODE_PORT = 46357

# The org segment (workspace/tenant) a room channel lives under. Matches the
# backend's ``settings.SLIM_WORKSPACE`` default — a member must share it with the
# moderator to resolve the same channel Name.
DEFAULT_WORKSPACE = "mycelium"

# Minimum length of the shared-secret identity PSK required by SLIM's dev auth.
MIN_SECRET_LEN = 32

# Default third segment for a room's group-channel Name when no explicit topic
# is given. Mirrors the backend's ``DEFAULT_CHANNEL_TOPIC``.
DEFAULT_CHANNEL_TOPIC = "room"

# Master secret from which per-channel shared secrets are derived. The built-in
# literal is a **public dev default** (debt D1) — anyone with the repo can derive
# it, so it protects nothing on its own. A real deployment sets
# ``MYCELIUM_SLIM_MASTER_SECRET`` to a private value; every host that shares rooms
# must set the **same** value (it's shared, not per-host). Both the env var name
# and the literal match the backend's ``slim_client`` so moderator and members
# reconstruct the identical credential offline (MVP identity tier; JWT/SPIRE is
# the production path). ``MYCELIUM_SLIM_REQUIRE_SECRET=1`` hard-refuses the dev
# default so a misconfigured host fails closed.
_MASTER_SECRET_ENV = "MYCELIUM_SLIM_MASTER_SECRET"
_REQUIRE_SECRET_ENV = "MYCELIUM_SLIM_REQUIRE_SECRET"
_DEV_MASTER_SECRET = "mycelium-dev-shared-secret-v1-do-not-use-in-prod"

logger = logging.getLogger("mycelium.slim")

# Warn only once per process when falling back to the public dev secret.
_dev_secret_warned = False


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() not in ("", "0", "false", "no")


def resolve_master_secret() -> str:
    """The master secret to derive channel secrets from.

    Prefers ``MYCELIUM_SLIM_MASTER_SECRET``; otherwise falls back to the public
    dev literal with a one-time warning, or refuses when
    ``MYCELIUM_SLIM_REQUIRE_SECRET`` is set. Mirrors the backend
    ``slim_client.resolve_master_secret`` so both sides agree.
    """
    secret = os.getenv(_MASTER_SECRET_ENV, "").strip()
    if secret:
        return secret
    if _truthy(os.getenv(_REQUIRE_SECRET_ENV)):
        raise RuntimeError(
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


class SlimNameError(ValueError):
    """A ``workspace/room/agent`` segment is not a valid SLIM Name part."""


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

    A cheap pre-flight so the daemon skips the full connect handshake (and the
    unit suite stays fast) when no node is up. Mirrors the backend probe.
    """
    parsed = urlparse(endpoint)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or DEFAULT_NODE_PORT
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _validate_segment(value: str, *, label: str) -> str:
    """Reject Name segments that would corrupt the ``org/ns/app`` encoding."""
    if not value or not value.strip():
        raise SlimNameError(f"{label} must be non-empty")
    if "/" in value:
        raise SlimNameError(f"{label} must not contain '/': {value!r}")
    return value


def to_slim_name(workspace: str, room: str, agent: str) -> slim_bindings.Name:
    """Map ``workspace/room/agent`` → a SLIM :class:`Name` (``org/ns/app``)."""
    from mycelium.slim.client import require_bindings

    sb = require_bindings()
    _validate_segment(workspace, label="workspace")
    _validate_segment(room, label="room")
    _validate_segment(agent, label="agent")
    return sb.Name(workspace, room, agent)


def to_channel_name(
    workspace: str, room: str, topic: str = DEFAULT_CHANNEL_TOPIC
) -> slim_bindings.Name:
    """Map a room to its group-channel :class:`Name` (``workspace/room/topic``)."""
    from mycelium.slim.client import require_bindings

    sb = require_bindings()
    _validate_segment(workspace, label="workspace")
    _validate_segment(room, label="room")
    _validate_segment(topic, label="topic")
    return sb.Name(workspace, room, topic)


def mint_shared_secret(identity: SlimIdentity, *, master_secret: str | None = None) -> str:
    """Mint the shared secret for a channel (``workspace/room``), ≥32 chars.

    Keyed on the channel scope (``workspace/room``) — the ``agent`` field is
    intentionally ignored — so every member of a room derives the *same* value
    (the channel's authentication PSK; a different value fails identity
    verification, so MLS handles the group key agreement separately). HMAC-SHA256
    hex digest, matching the backend so moderator and members agree offline.
    ``master_secret`` defaults to
    :func:`resolve_master_secret` (env or dev literal).
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
