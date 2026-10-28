# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for the first-party ``engine`` cognition-engine family.

Covers the protocol contract (engine manifests require a valid ``kind``), the
integration factory (``get_integration("engine")`` → an ``EngineIntegration``
the backend runs), and ``build_manifest``. Node-free; no filesystem/backend.
"""

from __future__ import annotations

from typing import Any

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
    assert "conductor" in ENGINE_KINDS
    assert "persona" in ENGINE_KINDS


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


# ── mycelium engine stop ──────────────────────────────────────────────────────


def _patch_stop(monkeypatch: pytest.MonkeyPatch, sync_fn: object) -> None:
    from types import SimpleNamespace
    from unittest.mock import MagicMock, Mock

    from mycelium.commands import engine as engine_cmd

    fake_config = SimpleNamespace(server=SimpleNamespace(api_url="http://localhost:8000"))
    monkeypatch.setattr(engine_cmd.MyceliumConfig, "load", classmethod(lambda _cls: fake_config))
    monkeypatch.setattr(engine_cmd, "_resolve_room", lambda _c, _r: "portfolio")
    monkeypatch.setattr(engine_cmd.identity, "resolve_actor", lambda *_a, **_kw: "julia")
    fake_cm = MagicMock()
    fake_cm.__enter__.return_value = Mock(name="client")
    fake_cm.__exit__.return_value = None
    monkeypatch.setattr(engine_cmd, "_typed_client", lambda _c: fake_cm)
    monkeypatch.setattr(
        "mycelium_backend_client.api.engines.stop_negotiation_api_rooms_room_name_engines_stop_post.sync_detailed",
        sync_fn,
    )


def test_engine_stop_stops_the_rooms_negotiation_as_you(monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from mycelium.commands import engine as engine_cmd
    from mycelium_backend_client.models import NegotiationStopped
    from tests.hub_answers import ok

    sent: dict[str, Any] = {}

    def fake_sync(**kwargs: Any):
        sent.update(kwargs)
        return ok(NegotiationStopped(stopped=True))

    _patch_stop(monkeypatch, fake_sync)
    result = CliRunner().invoke(engine_cmd.app, ["stop", "--room", "portfolio"])

    assert result.exit_code == 0, result.output
    assert "Stopped the negotiation in portfolio" in result.output
    assert sent["room_name"] == "portfolio"
    assert sent["body"].by == "julia"


def test_engine_stop_says_when_nothing_is_running(monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from mycelium.commands import engine as engine_cmd
    from mycelium_backend_client.errors import UnexpectedStatus

    def conflict(**_kwargs: object) -> None:
        raise UnexpectedStatus(409, b'{"detail": "No negotiation is running in portfolio."}')

    _patch_stop(monkeypatch, conflict)
    result = CliRunner().invoke(engine_cmd.app, ["stop", "--room", "portfolio"])

    assert result.exit_code == 1
    assert "No negotiation is running in portfolio" in result.output
