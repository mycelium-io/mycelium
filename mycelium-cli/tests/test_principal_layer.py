# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Self-asserted principal layer: the owner/team slug rules on both manifests.

The stores these point into are the hub's, so the roll-up and the user-record
round-trip are covered in ``test_agent_hub_reads.py`` and
``test_user_hub_store.py``.
"""

from __future__ import annotations

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
