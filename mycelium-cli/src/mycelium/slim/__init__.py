# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Daemon-side SLIM fabric + L9 envelope layer.

The backend (``fastapi-backend/app/services/{slim_client,l9,l9_slim}.py``) is the
room **moderator**; this package is the **member** half a connector needs so a
Claude Code agent can ride the same channel. It is a deliberately small,
self-contained mirror of the backend's wrappers — the CLI installs as a thin
``uv tool`` and must not drag in the FastAPI/ML backend just to hold a SLIM
connection.

Two invariants keep the two halves interoperable and MUST match the backend:

- **Naming + shared secret** (:mod:`mycelium.slim.naming`) — the
  ``workspace/room/agent`` → SLIM ``Name`` mapping and the MLS shared-secret
  derivation are byte-for-byte the backend's, or a member can't join the
  moderator's MLS group.
- **L9 wire shape** (:mod:`mycelium.slim.l9`) — an envelope rides under the
  additive ``l9`` key of a message's content JSON, in the exact shape the
  backend's ``l9.envelope_to_dict`` emits, so ``l9.parse_envelope`` accepts a
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
