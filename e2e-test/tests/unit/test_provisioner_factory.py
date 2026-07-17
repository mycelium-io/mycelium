"""Unit tests for the provisioner factory + base protocol."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from libs.provisioners import (
    AgentRef,
    PrereqMissing,
    Provisioner,
    get_provisioner,
    registered_adapters,
)
from libs.provisioners.base import BOOTSTRAP_ROOM, HERMES_BOOTSTRAP_ROOM, ABCProvisioner


def test_all_three_adapters_are_registered():
    adapters = registered_adapters()
    assert "openclaw" in adapters
    assert "cursor" in adapters
    assert "hermes" in adapters


def test_get_provisioner_returns_correct_instances():
    for name in ("openclaw", "cursor", "hermes"):
        prov = get_provisioner(name)
        assert prov.name == name
        assert isinstance(prov, Provisioner)


def test_get_provisioner_unknown_raises_with_known_list():
    with pytest.raises(KeyError, match="matrix"):
        get_provisioner("matrix")


def test_agent_ref_metadata_defaults_to_dict():
    ref = AgentRef(handle="h-alpha", adapter="openclaw", device_name="hub")
    assert ref.metadata == {}


def test_prereq_missing_is_runtime_error():
    assert issubclass(PrereqMissing, RuntimeError)


# ── ABCProvisioner defaults ─────────────────────────────────────────


class _DummyProvisioner(ABCProvisioner):
    """Minimal subclass that only overrides ``create_agent`` /
    ``cleanup_agent``; everything else falls through to the
    :class:`ABCProvisioner` defaults — exactly what cursor/hermes
    look like after migration."""

    name = "dummy"

    def __init__(self):
        self.create_calls: list[tuple[str, str, str | None]] = []
        self.cleanup_calls: list[tuple[str, str]] = []

    def check_prereqs(self, device):
        return None

    def create_agent(self, device, handle, room, *, opening=None):
        self.create_calls.append((handle, room, opening))
        return AgentRef(handle=handle, adapter=self.name, device_name="dummy")

    def cleanup_agent(self, device, agent, room):
        self.cleanup_calls.append((agent.handle, room))


def test_ensure_runtime_default_is_no_op():
    """Default ``ensure_runtime`` returns a minimal ref so cursor /
    hermes work without overriding (they cold-spawn per-test)."""
    prov = _DummyProvisioner()
    device = SimpleNamespace(name="hub")

    ref = prov.ensure_runtime(device, handle="alpha")

    assert ref.handle == "alpha"
    assert ref.adapter == "dummy"
    # No create or cleanup work happened.
    assert prov.create_calls == []
    assert prov.cleanup_calls == []


def test_register_in_room_default_forwards_to_create_agent():
    """The default register_in_room forwards to legacy
    ``create_agent``. Migrated provisioners override directly; the
    default keeps cursor/hermes working without code changes."""
    prov = _DummyProvisioner()
    device = SimpleNamespace(name="hub")

    prov.register_in_room(device, handle="alpha", room="r1", opening="hi")

    assert prov.create_calls == [("alpha", "r1", "hi")]


def test_unregister_from_room_default_forwards_to_cleanup_agent():
    prov = _DummyProvisioner()
    device = SimpleNamespace(name="hub")
    ref = AgentRef(handle="alpha", adapter="dummy", device_name="hub")

    prov.unregister_from_room(device, ref, room="r1")

    assert prov.cleanup_calls == [("alpha", "r1")]


def test_teardown_runtime_default_is_no_op():
    """Default teardown is a no-op — cursor/hermes have no
    runtime state to remove."""
    prov = _DummyProvisioner()
    device = SimpleNamespace(name="hub")
    ref = AgentRef(handle="alpha", adapter="dummy", device_name="hub")

    # Should not raise, should not call anything.
    prov.teardown_runtime(device, ref)
    assert prov.create_calls == []
    assert prov.cleanup_calls == []


def test_wake_agent_default_is_no_op():
    """Default wake is a no-op — hermes pattern. Concrete classes
    that need a wake (openclaw, cursor) override directly."""
    prov = _DummyProvisioner()
    device = SimpleNamespace(name="hub")
    ref = AgentRef(handle="alpha", adapter="dummy", device_name="hub")

    # Should return cleanly without touching anything.
    prov.wake_agent(device, ref, session_room="rs")


def test_bootstrap_room_is_canonical_string():
    """Sanity check: openclaw and hermes each have a holding-pen room."""
    assert isinstance(BOOTSTRAP_ROOM, str)
    assert BOOTSTRAP_ROOM == "mycelium_room"
    assert isinstance(HERMES_BOOTSTRAP_ROOM, str)
    assert HERMES_BOOTSTRAP_ROOM == "mycelium_room"
