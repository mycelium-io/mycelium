"""Unit tests for :mod:`libs.suite_lifecycle`."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from libs.provisioners.base import AgentRef
from libs.sessions import SessionError
from libs.suite_lifecycle import setup_shared_suite_room, teardown_shared_suite_room


def _testscript():
    return SimpleNamespace(parameters={})


def _testbed(*devices: tuple[str, SimpleNamespace]):
    return SimpleNamespace(devices=dict(devices))


def _device(name: str) -> SimpleNamespace:
    return SimpleNamespace(name=name)


def test_setup_shared_suite_room_registers_all_agents():
    testscript = _testscript()
    hub = _device("hub")
    spoke1 = _device("spoke1")
    testbed = _testbed(("hub", hub), ("spoke1", spoke1))

    wants = {
        ("hermes", "alpha-he", "hub"),
        ("hermes", "beta-he", "spoke1"),
    }
    testscript.parameters["provisioned_agents"] = {
        ("hermes", "alpha-he", "hub"): AgentRef(handle="alpha-he", adapter="hermes", device_name="hub"),
        ("hermes", "beta-he", "spoke1"): AgentRef(handle="beta-he", adapter="hermes", device_name="spoke1"),
    }

    register_calls: list[tuple[str, str, str]] = []

    class _HermesProvisioner:
        def register_in_room(self, device, handle, room, **kwargs):
            register_calls.append((handle, device.name, room))
            return AgentRef(
                handle=handle,
                adapter="hermes",
                device_name=device.name,
                metadata={"room": room},
            )

    with patch("libs.suite_lifecycle.sessions.create_room") as create_room:
        with patch("libs.suite_lifecycle.get_provisioner", return_value=_HermesProvisioner()):
            with patch("libs.suite_lifecycle._chown_mycelium_on_hosts"):
                room = setup_shared_suite_room(testscript, testbed, wants, room_prefix="scn-he-suite")

    assert room.startswith("scn-he-suite-")
    assert testscript.parameters["suite_shared_room"] == room
    create_room.assert_called_once_with(hub, room)
    assert sorted(register_calls) == [
        ("alpha-he", "hub", room),
        ("beta-he", "spoke1", room),
    ]
    refs = testscript.parameters["provisioned_agents"]
    assert refs[("hermes", "alpha-he", "hub")].metadata.get("room") == room


def test_setup_shared_suite_room_raises_when_ref_missing():
    testscript = _testscript()
    testbed = _testbed(("hub", _device("hub")))
    wants = {("hermes", "alpha-he", "hub")}
    testscript.parameters["provisioned_agents"] = {}

    with patch("libs.suite_lifecycle.sessions.create_room"):
        with patch("libs.suite_lifecycle._chown_mycelium_on_hosts"):
            with pytest.raises(SessionError, match="missing ensure_runtime ref"):
                setup_shared_suite_room(testscript, testbed, wants)


def test_setup_shared_suite_room_updates_provisioned_ref_from_register():
    """register_in_room may enrich metadata (e.g. cursor workspace); teardown needs it."""
    testscript = _testscript()
    hub = _device("hub")
    testbed = _testbed(("hub", hub))
    wants = {("cursor", "alpha-cu", "hub")}
    stale_ref = AgentRef(
        handle="alpha-cu",
        adapter="cursor",
        device_name="hub",
        metadata={"runtime": "no-op"},
    )
    testscript.parameters["provisioned_agents"] = {("cursor", "alpha-cu", "hub"): stale_ref}

    class _CursorProvisioner:
        def register_in_room(self, device, handle, room, **kwargs):
            return AgentRef(
                handle=handle,
                adapter="cursor",
                device_name=device.name,
                metadata={"workspace": "/tmp/cursor-e2e-abc123", "room": room},
            )

    with patch("libs.suite_lifecycle.sessions.create_room"):
        with patch("libs.suite_lifecycle._chown_mycelium_on_hosts"):
            with patch("libs.suite_lifecycle.get_provisioner", return_value=_CursorProvisioner()):
                setup_shared_suite_room(testscript, testbed, wants)

    updated = testscript.parameters["provisioned_agents"][("cursor", "alpha-cu", "hub")]
    assert updated.metadata["workspace"] == "/tmp/cursor-e2e-abc123"


def test_setup_shared_suite_room_uses_actual_handle_not_spec():
    """register_in_room must be called with ref.handle (actual), not the spec handle.

    When discover_available reuses an existing agent (e.g. spec='alpha' →
    actual='agent-alpha'), the suite room must register under the real
    openclaw handle so that tick participant_id matching works.
    """
    testscript = _testscript()
    hub = _device("hub")
    testbed = _testbed(("hub", hub))
    # Spec handle is "alpha"; actual discovered handle is "agent-alpha"
    wants = {("openclaw", "alpha", "hub")}
    testscript.parameters["provisioned_agents"] = {
        ("openclaw", "alpha", "hub"): AgentRef(
            handle="agent-alpha",  # actual handle differs from spec
            adapter="openclaw",
            device_name="hub",
        ),
    }

    register_calls: list[str] = []

    class _OpenClawProvisioner:
        def register_in_room(self, device, handle, room, **kwargs):
            register_calls.append(handle)
            return AgentRef(handle=handle, adapter="openclaw", device_name=device.name)

    with patch("libs.suite_lifecycle.sessions.create_room"):
        with patch("libs.suite_lifecycle._chown_mycelium_on_hosts"):
            with patch("libs.suite_lifecycle.get_provisioner", return_value=_OpenClawProvisioner()):
                setup_shared_suite_room(testscript, testbed, wants)

    # Must use the actual handle, not the spec handle
    assert register_calls == ["agent-alpha"], (
        f"expected register_in_room called with 'agent-alpha', got {register_calls}"
    )
    ref = testscript.parameters["provisioned_agents"][("openclaw", "alpha", "hub")]
    assert ref.handle == "agent-alpha"


def test_teardown_shared_suite_room_unregisters_and_deletes():
    testscript = _testscript()
    hub = _device("hub")
    testbed = _testbed(("hub", hub))
    testscript.parameters["suite_shared_room"] = "scn-suite-deadbeef"
    testscript.parameters["suite_control_host"] = "hub"
    testscript.parameters["provisioned_agents"] = {
        ("hermes", "alpha-he", "hub"): AgentRef(handle="alpha-he", adapter="hermes", device_name="hub"),
    }

    unregister_calls: list[str] = []

    class _HermesProvisioner:
        def unregister_from_room(self, device, ref, room):
            unregister_calls.append(room)

    with patch("libs.suite_lifecycle.sessions.wait_for_no_active_sessions"):
        with patch("libs.suite_lifecycle.sessions.delete_room") as delete_room:
            with patch("libs.suite_lifecycle.get_provisioner", return_value=_HermesProvisioner()):
                teardown_shared_suite_room(
                    testscript,
                    testbed,
                    backend_url="http://localhost:8000",
                )

    assert unregister_calls == ["scn-suite-deadbeef"]
    delete_room.assert_called_once_with(hub, "scn-suite-deadbeef")
