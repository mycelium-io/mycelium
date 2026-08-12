# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Offline unit tests for the SLIM naming/identity helpers (no node required)."""

import pytest

# The helpers need the native binding to build a Name; skip cleanly where no
# wheel exists so the default suite stays green when the binding is absent.
pytest.importorskip("slim_bindings")

from app.services.slim_client import (
    MIN_SECRET_LEN,
    SlimIdentity,
    SlimNameError,
    from_slim_name,
    mint_shared_secret,
    to_channel_name,
    to_slim_name,
)


def test_name_round_trip():
    """workspace/room/agent → Name → workspace/room/agent is lossless."""
    name = to_slim_name("acme", "planning", "agent-7")
    assert name.components() == ["acme", "planning", "agent-7"]

    identity = from_slim_name(name)
    assert identity == SlimIdentity("acme", "planning", "agent-7")
    assert identity.as_tuple() == ("acme", "planning", "agent-7")
    assert identity.as_path() == "acme/planning/agent-7"


def test_channel_name_uses_topic_as_app_segment():
    """A room's channel is workspace/room/<topic>, default topic 'room'."""
    default = to_channel_name("acme", "planning")
    assert default.components() == ["acme", "planning", "room"]

    explicit = to_channel_name("acme", "planning", "consensus")
    assert explicit.components() == ["acme", "planning", "consensus"]


@pytest.mark.parametrize(
    ("workspace", "room", "agent"),
    [
        ("", "room", "agent"),
        ("ws", "  ", "agent"),
        ("ws", "room", ""),
        ("ws/x", "room", "agent"),
        ("ws", "ro/om", "agent"),
        ("ws", "room", "ag/ent"),
    ],
)
def test_invalid_segments_rejected(workspace, room, agent):
    with pytest.raises(SlimNameError):
        to_slim_name(workspace, room, agent)


def test_mint_secret_is_deterministic_and_long_enough():
    identity = SlimIdentity("acme", "planning", "agent-7")
    secret = mint_shared_secret(identity)

    assert len(secret) >= MIN_SECRET_LEN
    # Deterministic so both ends derive the same credential offline.
    assert mint_shared_secret(identity) == secret


def test_mint_secret_is_shared_across_agents_in_a_room():
    """The secret seeds the group key, so every agent in a room shares it."""
    a7 = mint_shared_secret(SlimIdentity("acme", "planning", "agent-7"))
    a8 = mint_shared_secret(SlimIdentity("acme", "planning", "agent-8"))
    assert a7 == a8  # same channel (workspace/room) → same secret


def test_mint_secret_differs_per_channel_and_master():
    same_room = mint_shared_secret(SlimIdentity("acme", "planning", "agent-7"))
    other_room = mint_shared_secret(SlimIdentity("acme", "shipping", "agent-7"))
    other_ws = mint_shared_secret(SlimIdentity("other", "planning", "agent-7"))
    assert same_room != other_room != other_ws and same_room != other_ws

    scoped = mint_shared_secret(
        SlimIdentity("acme", "planning", "agent-7"), master_secret="another-master"
    )
    assert scoped != same_room
