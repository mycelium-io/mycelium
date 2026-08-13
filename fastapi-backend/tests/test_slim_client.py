# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for the SLIM naming + shared-secret mechanics (slim_client.py).

Node-free: these cover the pure pieces — the ``workspace/room/agent`` ↔ Name
mapping, segment validation, the deterministic per-channel secret derivation, and
the master-secret resolution policy — none of which need a live node. The connect
/ group / publish lifecycle is the live-node slice (``test_slim_roundtrip.py``).
"""

from __future__ import annotations

import pytest

from app.services import slim_client
from app.services.slim_client import (
    MIN_SECRET_LEN,
    SlimError,
    SlimIdentity,
    SlimNameError,
    from_slim_name,
    mint_shared_secret,
    node_reachable,
    resolve_master_secret,
    to_slim_name,
)


def test_identity_roundtrips_through_a_slim_name() -> None:
    identity = SlimIdentity("ws", "room-a", "agent-a")
    assert identity.as_tuple() == ("ws", "room-a", "agent-a")
    assert identity.as_path() == "ws/room-a/agent-a"
    # workspace/room/agent → Name(org/ns/app) → back to the same identity.
    assert from_slim_name(to_slim_name(*identity.as_tuple())) == identity


@pytest.mark.parametrize("bad", ["", "  ", "has/slash"])
def test_name_segments_reject_invalid_values(bad: str) -> None:
    with pytest.raises(SlimNameError):
        to_slim_name(bad, "room", "agent")


def test_shared_secret_is_deterministic_and_scoped_to_the_channel() -> None:
    a1 = SlimIdentity("ws", "room-a", "agent-a")
    a2 = SlimIdentity("ws", "room-a", "agent-b")  # different agent, same channel
    b = SlimIdentity("ws", "room-b", "agent-a")  # different room

    secret = mint_shared_secret(a1, master_secret="master")
    # Every member of a channel derives the SAME secret (agent id is ignored).
    assert secret == mint_shared_secret(a2, master_secret="master")
    # A different channel (room) derives a different secret.
    assert secret != mint_shared_secret(b, master_secret="master")
    # A different master derives a different secret.
    assert secret != mint_shared_secret(a1, master_secret="other")
    assert len(secret) >= MIN_SECRET_LEN


def test_resolve_master_secret_prefers_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MYCELIUM_SLIM_MASTER_SECRET", "my-private-secret")
    assert resolve_master_secret() == "my-private-secret"


def test_resolve_master_secret_falls_back_to_dev_literal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MYCELIUM_SLIM_MASTER_SECRET", raising=False)
    monkeypatch.delenv("MYCELIUM_SLIM_REQUIRE_SECRET", raising=False)
    assert resolve_master_secret() == slim_client._DEV_MASTER_SECRET


def test_resolve_master_secret_fails_closed_when_required(monkeypatch: pytest.MonkeyPatch) -> None:
    """REQUIRE_SECRET without a secret must refuse the public dev literal."""
    monkeypatch.delenv("MYCELIUM_SLIM_MASTER_SECRET", raising=False)
    monkeypatch.setenv("MYCELIUM_SLIM_REQUIRE_SECRET", "1")
    with pytest.raises(SlimError, match="refusing"):
        resolve_master_secret()


def test_node_reachable_is_false_for_a_dead_port() -> None:
    # Nothing is listening on this port on localhost → a fast, clean False.
    assert node_reachable("http://127.0.0.1:1", timeout=0.2) is False
