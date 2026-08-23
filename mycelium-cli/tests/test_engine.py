# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for the first-party ``engine`` cognition-engine family.

Covers the protocol contract (engine manifests require a valid ``kind``), the
integration factory (``get_integration("engine")`` → an ``EngineIntegration``
the backend runs), and ``build_manifest``. Node-free; no filesystem/backend.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mycelium.integrations import AddOptions, get_integration
from mycelium.integrations.engine import EngineIntegration
from mycelium.protocol import AGENT_ADAPTERS, ENGINE_KINDS, AgentManifest


def test_engine_is_a_registered_family() -> None:
    assert "engine" in AGENT_ADAPTERS
    assert "aligner" in ENGINE_KINDS
    assert "synthesizer" in ENGINE_KINDS
    assert "hello" in ENGINE_KINDS


def test_manifest_accepts_synthesizer() -> None:
    m = AgentManifest(handle="synth-1", adapter="engine", kind="synthesizer")
    assert m.adapter == "engine"
    assert m.kind == "synthesizer"


def test_manifest_accepts_hello() -> None:
    m = AgentManifest(handle="hi", adapter="engine", kind="hello")
    assert m.adapter == "engine"
    assert m.kind == "hello"


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
    # engines need no cwd — validates clean.


def test_get_integration_returns_engine_backend_run() -> None:
    impl = get_integration("engine", engine_kind="aligner")
    assert isinstance(impl, EngineIntegration)
    # backend_engine ⇒ the backend owns its run via the summon seam.
    assert impl.lifecycle == "backend_engine"


def test_build_manifest_threads_kind() -> None:
    impl = get_integration("engine", engine_kind="aligner")
    m = impl.build_manifest(
        handle="mediator-1",
        opts=AddOptions(room="portfolio"),
        description="SAO mediator",
        allow_from=[],
    )
    assert m.adapter == "engine"
    assert m.kind == "aligner"
    assert m.handle == "mediator-1"
