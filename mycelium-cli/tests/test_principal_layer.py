# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Self-asserted principal layer: agent owner/team, the user store, roll-up."""

from __future__ import annotations

import yaml

from mycelium.commands import user as user_cmd
from mycelium.commands.agent import load_owned_agents
from mycelium.filesystem import get_room_dir, write_memory
from mycelium.protocol import AgentManifest, UserManifest


def test_manifest_owner_team_default_none() -> None:
    """Backward compatible: a manifest with no principal is anonymous."""
    m = AgentManifest(handle="bot", cwd="/tmp")
    assert m.owner is None
    assert m.team is None


def test_manifest_normalizes_owner_and_team() -> None:
    """Owner/team are slug pointers — lowercased, @-stripped, like the handle."""
    m = AgentManifest(handle="Bot", cwd="/tmp", owner="@Avery", team="Core")
    assert m.owner == "avery"
    assert m.team == "core"


def test_manifest_blank_owner_becomes_none() -> None:
    m = AgentManifest(handle="bot", cwd="/tmp", owner="  ")
    assert m.owner is None


def test_user_manifest_normalizes() -> None:
    u = UserManifest(handle="@Avery", display_name="Avery Quinn", teams=["@Core", "Infra"])
    assert u.handle == "avery"
    assert u.teams == ["core", "infra"]


def test_user_store_roundtrip(isolated_home) -> None:  # noqa: ANN001
    """A user written to the global store loads back as a validated model."""
    user_cmd._write_user(
        UserManifest(handle="avery", display_name="Avery", teams=["core"]),
        created_by="tester",
    )
    loaded = user_cmd.load_user("@Avery")  # normalization on read too
    assert loaded is not None
    assert loaded.display_name == "Avery"
    assert loaded.teams == ["core"]
    assert [u.handle for u in user_cmd.list_users()] == ["avery"]


def _seed_agent(room: str, handle: str, *, owner: str | None) -> None:
    manifest = AgentManifest(handle=handle, cwd="/tmp", owner=owner)
    body = yaml.safe_dump(manifest.model_dump(exclude={"handle"}), sort_keys=False)
    write_memory(get_room_dir(room), manifest.memory_key, body, created_by="tester")


def test_load_owned_agents_collects_across_rooms(isolated_home) -> None:  # noqa: ANN001
    """Owned agents are collected across every local room."""
    _seed_agent("alpha", "a1", owner="avery")
    _seed_agent("beta", "a2", owner="avery")
    _seed_agent("beta", "a3", owner="sam")

    owned = load_owned_agents(owner="@Avery")
    handles = sorted(m.handle for _room, m in owned)
    assert handles == ["a1", "a2"]
