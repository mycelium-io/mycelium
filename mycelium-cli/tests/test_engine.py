# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for the first-party ``engine`` cognition-engine family.

Covers the protocol contract (engine manifests require a valid ``kind``), the
integration factory (``get_integration("engine")`` → an ``EngineIntegration``
that the daemon skips), and ``build_manifest``. Node-free; no filesystem/backend.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mycelium.integrations import AddOptions, get_integration
from mycelium.integrations.base import Integration
from mycelium.integrations.engine import EngineIntegration
from mycelium.protocol import AGENT_ADAPTERS, ENGINE_KINDS, AgentManifest


def test_engine_is_a_registered_family() -> None:
    assert "engine" in AGENT_ADAPTERS
    assert "aligner" in ENGINE_KINDS


def test_manifest_requires_a_kind() -> None:
    with pytest.raises(ValidationError, match="require a 'kind'"):
        AgentManifest(handle="mediator-1", adapter="engine")


def test_manifest_rejects_unknown_kind() -> None:
    with pytest.raises(ValidationError, match="unknown engine kind"):
        AgentManifest(handle="mediator-1", adapter="engine", kind="nonsense")


def test_manifest_accepts_aligner() -> None:
    m = AgentManifest(handle="mediator-1", adapter="engine", kind="aligner")
    assert m.adapter == "engine"
    assert m.kind == "aligner"
    # engines need no cwd (unlike cold-spawn families) — validates clean.


def test_get_integration_returns_engine_backend_run() -> None:
    impl = get_integration("engine", engine_kind="aligner")
    assert isinstance(impl, EngineIntegration)
    # backend_engine ⇒ the daemon skips it (only cold_spawn families are dispatched).
    assert impl.lifecycle == "backend_engine"
    # a non-cold-spawn family must NOT provide spawn logic.
    assert type(impl).spawn is Integration.spawn


def test_build_manifest_threads_kind() -> None:
    impl = get_integration("engine", engine_kind="aligner")
    m = impl.build_manifest(
        handle="mediator-1",
        opts=AddOptions(room="portfolio"),
        description="SAO mediator",
        budget=0.0,
        allow_from=[],
    )
    assert m.adapter == "engine"
    assert m.kind == "aligner"
    assert m.handle == "mediator-1"
