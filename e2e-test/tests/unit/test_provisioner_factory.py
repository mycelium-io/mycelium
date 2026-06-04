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
