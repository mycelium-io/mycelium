"""Unit tests for the provisioner factory + base protocol."""

from __future__ import annotations

import pytest

from libs.provisioners import (
    AgentRef,
    PrereqMissing,
    Provisioner,
    get_provisioner,
    registered_adapters,
)


def test_openclaw_is_registered():
    assert "openclaw" in registered_adapters()


def test_get_provisioner_returns_openclaw_instance():
    prov = get_provisioner("openclaw")
    assert prov.name == "openclaw"
    assert isinstance(prov, Provisioner)


def test_get_provisioner_unknown_raises_with_known_list():
    with pytest.raises(KeyError, match="cursor"):
        get_provisioner("cursor")


def test_agent_ref_metadata_defaults_to_dict():
    ref = AgentRef(handle="h-alpha", adapter="openclaw", device_name="hub")
    assert ref.metadata == {}


def test_prereq_missing_is_runtime_error():
    assert issubclass(PrereqMissing, RuntimeError)
