"""Unit tests for :mod:`libs.agent_pools`."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from libs.agent_pools import (
    DEFAULT_AGENT_POOLS,
    ensure_pool_slots,
    load_agent_pools,
    provision_roles_for_wants,
    reset_openclaw_pools_for_wants,
    resolve_role_handle,
)
from libs.provisioners.base import AgentRef


def test_resolve_role_handle_openclaw_hub_alpha():
    pools = DEFAULT_AGENT_POOLS
    assert resolve_role_handle("alpha", "openclaw", "hub", pools) == "agent-alpha"
    assert resolve_role_handle("planner", "openclaw", "hub", pools) == "agent-gamma"


def test_resolve_role_handle_spoke_beta():
    pools = DEFAULT_AGENT_POOLS
    assert resolve_role_handle("beta", "openclaw", "spoke1", pools) == "claire-agent"


def test_resolve_role_handle_hermes_identity():
    pools = DEFAULT_AGENT_POOLS
    assert resolve_role_handle("alpha-he", "hermes", "hub", pools) == "alpha-he"


def test_resolve_role_handle_openclaw_unknown_raises():
    with pytest.raises(KeyError, match="no pool mapping"):
        resolve_role_handle("unknown", "openclaw", "hub", DEFAULT_AGENT_POOLS)


def test_load_agent_pools_uses_defaults_when_missing():
    assert load_agent_pools({}) == DEFAULT_AGENT_POOLS


def test_load_agent_pools_merges_datafile():
    custom = {
        "hub": {
            "openclaw": {
                "slots": ["agent-alpha"],
                "roles": {"alpha": "agent-alpha"},
            }
        }
    }
    pools = load_agent_pools({"agent_pools": custom})
    assert pools["hub"]["openclaw"]["slots"] == ["agent-alpha"]


def test_provision_roles_for_wants_maps_openclaw_roles(monkeypatch):
    calls: list[tuple[str, str]] = []

    class _OpenClawProvisioner:
        def check_prereqs(self, device):
            return None

        def discover_available(self, device, **kwargs):
            return [
                AgentRef(handle="agent-alpha", adapter="openclaw", device_name="hub"),
                AgentRef(handle="agent-beta", adapter="openclaw", device_name="hub"),
            ]

        def ensure_runtime(self, device, handle, **kwargs):
            calls.append(("ensure", handle))
            return AgentRef(handle=handle, adapter="openclaw", device_name="hub")

    monkeypatch.setattr(
        "libs.agent_pools.get_provisioner",
        lambda name: _OpenClawProvisioner() if name == "openclaw" else (_ for _ in ()).throw(KeyError(name)),
    )

    hub = SimpleNamespace(name="hub")
    testbed = SimpleNamespace(devices={"hub": hub})
    wants = {("openclaw", "alpha", "hub"), ("openclaw", "beta", "hub")}

    provisioned, failures = provision_roles_for_wants(testbed, wants, DEFAULT_AGENT_POOLS)

    assert failures == []
    assert provisioned[("openclaw", "alpha", "hub")].handle == "agent-alpha"
    assert provisioned[("openclaw", "beta", "hub")].handle == "agent-beta"
    assert calls == []


def test_reset_openclaw_pools_resets_only_used_slots(monkeypatch):
    """Reset is scoped to the roles in wants, not the full pool."""
    reset_calls: list[list[str]] = []

    class _OpenClawProvisioner:
        def reset_device_gateway_sessions(self, device, *, handles=None, idle_wait_seconds=None):
            reset_calls.append(list(handles or []))

    monkeypatch.setattr("libs.agent_pools.get_provisioner", lambda _: _OpenClawProvisioner())

    hub = SimpleNamespace(name="hub")
    testbed = SimpleNamespace(devices={"hub": hub})
    wants = {("openclaw", "alpha", "hub"), ("openclaw", "beta", "hub")}

    reset_openclaw_pools_for_wants(testbed, wants, DEFAULT_AGENT_POOLS)

    # Only agent-alpha and agent-beta should be reset, not gamma/delta.
    assert reset_calls == [["agent-alpha", "agent-beta"]]


def test_reset_openclaw_pools_falls_back_to_full_pool_for_unknown_role(monkeypatch):
    """Unknown roles that aren't in the pool trigger a full-pool reset."""
    reset_calls: list[list[str]] = []

    class _OpenClawProvisioner:
        def reset_device_gateway_sessions(self, device, *, handles=None, idle_wait_seconds=None):
            reset_calls.append(sorted(handles or []))

    monkeypatch.setattr("libs.agent_pools.get_provisioner", lambda _: _OpenClawProvisioner())

    hub = SimpleNamespace(name="hub")
    testbed = SimpleNamespace(devices={"hub": hub})
    # "unknown-role" is not in the pool roles dict
    wants = {("openclaw", "unknown-role", "hub")}

    reset_openclaw_pools_for_wants(testbed, wants, DEFAULT_AGENT_POOLS)

    assert reset_calls == [["agent-alpha", "agent-beta", "agent-delta", "agent-gamma"]]


def test_ensure_pool_slots_skips_discovered(monkeypatch):
    ensure_calls: list[str] = []

    class _OpenClawProvisioner:
        def check_prereqs(self, device):
            return None

        def discover_available(self, device, **kwargs):
            return [AgentRef(handle="agent-alpha", adapter="openclaw", device_name="hub")]

        def ensure_runtime(self, device, handle, **kwargs):
            ensure_calls.append(handle)
            return AgentRef(handle=handle, adapter="openclaw", device_name="hub")

    monkeypatch.setattr("libs.agent_pools.get_provisioner", lambda _: _OpenClawProvisioner())

    hub = SimpleNamespace(name="hub")
    testbed = SimpleNamespace(devices={"hub": hub})
    wants = {("openclaw", "alpha", "hub")}

    failures = ensure_pool_slots(testbed, wants, DEFAULT_AGENT_POOLS)

    assert failures == []
    assert sorted(ensure_calls) == ["agent-beta", "agent-delta", "agent-gamma"]
