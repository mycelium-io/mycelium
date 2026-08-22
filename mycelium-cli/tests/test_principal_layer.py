# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Self-asserted principal layer: agent owner/team and the user store.

The owned-agent roll-up over those fields resolves against the hub, so its
coverage lives in ``test_agent_hub_reads.py``.
"""

from __future__ import annotations

from mycelium.commands import user as user_cmd
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
