# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Integration-contract conformance.

CI fails when a new capability is added to one adapter without either an
implementation or a documented opt-out in the other. Because every runtime
family is one ``Integration`` subclass, an
unimplemented contract method makes the class abstract and the
``get_integration`` instantiation below raises ``TypeError`` — so this test
fails the moment the contract and an implementation drift apart.

It also pins the family-id spelling invariants: the registry, the persisted
``sstp.AGENT_ADAPTERS`` set, and the ``AgentManifest.adapter`` literal must
agree, and the one hyphen→underscore translation boundary must hold.
"""

from __future__ import annotations

import typing

import pytest

from mycelium.integrations import (
    Integration,
    get_integration,
    normalize_family_id,
)
from mycelium.protocol import AGENT_ADAPTERS, AgentManifest

# Canonical family ids = the persisted spelling. Single source of truth.
FAMILIES = sorted(AGENT_ADAPTERS)


@pytest.mark.parametrize("family", FAMILIES)
def test_family_resolves_to_concrete_integration(family: str) -> None:
    """Every persisted family id resolves to an instantiable Integration.

    If a contract method were added to the ABC without an implementation in
    this family, the class would stay abstract and this call raises TypeError.
    """
    impl = get_integration(family)
    assert isinstance(impl, Integration)
    assert impl.name == family


@pytest.mark.parametrize("family", FAMILIES)
def test_family_declares_lifecycle(family: str) -> None:
    """Every family declares where its agents run (``resident``/``backend_engine``).

    This is the liveness distinction tooling/UI surface — a resident (user/herdr)
    runtime vs. a backend-run engine. A new family missing it is a bug.
    """
    cls = type(get_integration(family))
    assert hasattr(cls, "lifecycle"), f"{family} missing `lifecycle` ClassVar"
    assert cls.lifecycle in {"resident", "backend_engine"}, (
        f"{family} has invalid lifecycle: {cls.lifecycle!r}"
    )


@pytest.mark.parametrize("family", FAMILIES)
def test_the_contract_is_implemented(family: str) -> None:
    """The whole contract is present on every family.

    If a family is missing a method, the class stays abstract and
    ``get_integration`` (above) raises; assert the surface explicitly so the
    contract is documented.
    """
    impl = get_integration(family)
    for method in ("build_manifest", "register", "destroy", "describe"):
        assert callable(getattr(impl, method)), f"{family} missing {method}"


def test_there_is_no_host_install_step() -> None:
    """Agents learn the protocol from their notes and wake prompts, so nothing
    installs into an agent CLI's own settings any more."""
    import importlib

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("mycelium.commands.adapter")
    for family in FAMILIES:
        assert not hasattr(get_integration(family), "install"), family


def test_manifest_literal_matches_registry() -> None:
    """``AgentManifest.adapter`` literal == ``AGENT_ADAPTERS`` == registry keys.

    Drift here is exactly the silent-degradation failure mode #173 targets.
    """
    literal_values = set(typing.get_args(AgentManifest.model_fields["adapter"].annotation))
    assert literal_values == set(AGENT_ADAPTERS)
    for family in AGENT_ADAPTERS:
        assert get_integration(family).name == family


def test_normalize_family_id_is_the_only_translation_boundary() -> None:
    """Hyphen (what people type) → underscore (persisted) and idempotent."""
    assert normalize_family_id("claude-code") == "claude_code"
    for family in AGENT_ADAPTERS:
        # Canonical ids are fixed points.
        assert normalize_family_id(family) == family
    # Unknown names pass through so callers raise their own error.
    assert normalize_family_id("nope") == "nope"


def test_unknown_family_raises() -> None:
    with pytest.raises(ValueError, match="unknown integration"):
        get_integration("does-not-exist")


def test_no_legacy_adapter_packages() -> None:
    """Neither ``agent_adapters`` nor a top-level ``mycelium.adapters`` package
    exists — one ``integrations`` concept only."""
    import importlib

    for legacy in ("mycelium.agent_adapters", "mycelium.adapters"):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(legacy)
