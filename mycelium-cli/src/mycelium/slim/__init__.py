# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Daemon-side SLIM fabric + packet layer.

The backend (``fastapi-backend/app/services/{slim_client,packet,packet_slim}.py``) is the
room **moderator**; this package is the **member** half a connector needs so a
Claude Code agent can ride the same channel. It is a deliberately small,
self-contained mirror of the backend's wrappers: the CLI installs as a thin
``uv tool`` and must not drag in the FastAPI/ML backend just to hold a SLIM
connection.

Two invariants keep the two halves interoperable and MUST match the backend:

- **Naming + shared secret** (:mod:`mycelium.slim.naming`): the
  ``workspace/room/agent`` → SLIM ``Name`` mapping and the shared-secret
  (authentication PSK) derivation are byte-for-byte the backend's, or a member
  fails identity verification and can't join the moderator's group.
- **Packet shape** (:mod:`mycelium.slim.packet`): a packet rides under the
  additive ``l9`` key of a message's content JSON, in the exact shape the
  backend's ``packet.envelope_to_dict`` emits, so ``packet.parse_envelope`` accepts a
  connector's reply.
"""

from __future__ import annotations

from mycelium.slim.client import SlimClient, SlimUnavailableError
from mycelium.slim.naming import (
    DEFAULT_NODE_ENDPOINT,
    DEFAULT_WORKSPACE,
    SlimIdentity,
    mint_shared_secret,
    node_reachable,
    to_channel_name,
    to_slim_name,
)

__all__ = [
    "DEFAULT_NODE_ENDPOINT",
    "DEFAULT_WORKSPACE",
    "SlimClient",
    "SlimIdentity",
    "SlimUnavailableError",
    "mint_shared_secret",
    "node_reachable",
    "to_channel_name",
    "to_slim_name",
]
