# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Integration-contract conformance — the CI enforcement for #173.

#173's acceptance criterion: "CI fails when a new capability is added to one
adapter without either an implementation or a documented opt-out in the
other." Because every runtime family is now one ``Integration`` subclass, an
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
def test_install_facet_is_implemented(family: str) -> None:
    """Both facets of the contract are present on every family.

    These are the install-facet methods relocated from the old
    ``commands/adapter.py`` ``if adapter_type ==`` branches. If a family is
    missing one, the class stays abstract and ``get_integration`` (above)
    raises — but assert the surface explicitly so the contract is documented.
    """
    impl = get_integration(family)
    for method in (
        "install",
        "uninstall",
        "reinstall_targets",
        "dry_run_lines",
        "post_install_banner",
        "run_step",
        "status_check",
        # dispatch facet
        "build_manifest",
        "register",
        "destroy",
    ):
        assert callable(getattr(impl, method)), f"{family} missing {method}"
    assert isinstance(impl.STEPS, dict)


def test_no_if_family_branching_left_in_command_layer() -> None:
    """The command layer must dispatch via the registry, not branch on family.

    A literal ``adapter_type ==`` / ``name ==`` comparison creeping back into
    ``commands/adapter.py`` is the exact #173 regression — fail loudly on it.
    """
    import pathlib

    repo = pathlib.Path(__file__).resolve().parents[1]
    src = (repo / "src/mycelium/commands/adapter.py").read_text()
    assert 'adapter_type == "openclaw"' not in src
    assert 'adapter_type == "claude-code"' not in src


def test_manifest_literal_matches_registry() -> None:
    """``AgentManifest.adapter`` literal == ``AGENT_ADAPTERS`` == registry keys.

    Drift here is exactly the silent-degradation failure mode #173 targets.
    """
    literal_values = set(typing.get_args(AgentManifest.model_fields["adapter"].annotation))
    assert literal_values == set(AGENT_ADAPTERS)
    for family in AGENT_ADAPTERS:
        assert get_integration(family).name == family


def test_normalize_family_id_is_the_only_translation_boundary() -> None:
    """Hyphen (CLI arg + asset dir) → underscore (persisted) and idempotent."""
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
    """The collision is gone: neither ``agent_adapters`` nor a top-level
    ``mycelium.adapters`` package exists — one ``integrations`` concept only."""
    import importlib

    for legacy in ("mycelium.agent_adapters", "mycelium.adapters"):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(legacy)
