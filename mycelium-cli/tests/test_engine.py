# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for the first-party ``engine`` cognition-engine family.

Covers the protocol contract (engine manifests require a valid ``kind``), the
integration factory (``get_integration("engine")`` → an ``EngineIntegration``
the backend runs), ``build_manifest``, and how ``engine create`` and
``engine invoke`` answer a retired kind. Node-free; no filesystem/backend.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from mycelium.commands import engine as engine_cmd
from mycelium.config import MyceliumConfig
from mycelium.integrations import AddOptions, get_integration
from mycelium.integrations.engine import EngineIntegration
from mycelium.protocol import AGENT_ADAPTERS, ENGINE_KINDS, RETIRED_ENGINE_KINDS, AgentManifest

CONTRACT = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts" / "engine-kinds.json").read_text()
)


def test_engine_is_a_registered_family() -> None:
    assert "engine" in AGENT_ADAPTERS
    assert sorted(ENGINE_KINDS) == CONTRACT["kinds"]
    assert CONTRACT["retired"] == RETIRED_ENGINE_KINDS


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
        AgentManifest(handle="conductor", adapter="engine")


def test_manifest_rejects_unknown_kind() -> None:
    with pytest.raises(ValidationError, match="unknown engine kind"):
        AgentManifest(handle="conductor", adapter="engine", kind="nonsense")


def test_an_old_aligner_manifest_still_loads() -> None:
    """A room made before the aligner was retired can still hold its manifest;
    it loads so it can be listed and removed."""
    m = AgentManifest(handle="aligner", adapter="engine", kind="aligner")
    assert m.kind == "aligner"


def test_get_integration_returns_engine_backend_run() -> None:
    impl = get_integration("engine", engine_kind="conductor")
    assert isinstance(impl, EngineIntegration)
    # backend_engine ⇒ the backend owns its run via the summon seam.
    assert impl.lifecycle == "backend_engine"


def test_build_manifest_threads_kind() -> None:
    impl = get_integration("engine", engine_kind="conductor")
    m = impl.build_manifest(
        handle="conductor",
        opts=AddOptions(room="portfolio"),
        description="walks flows",
        allow_from=[],
    )
    assert m.adapter == "engine"
    assert m.kind == "conductor"
    assert m.handle == "conductor"


# ── a retired kind ────────────────────────────────────────────────────────────


def test_engine_create_refuses_the_aligner_with_what_to_run_instead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_write(**_kwargs: object) -> None:
        raise AssertionError("a retired kind is never written")

    monkeypatch.setattr(engine_cmd, "_persist_and_describe", no_write)
    result = CliRunner().invoke(
        engine_cmd.app, ["create", "aligner", "--kind", "aligner", "--room", "portfolio"]
    )

    assert result.exit_code == 1
    assert "The aligner was retired" in result.output
    assert "mycelium board coordinate <row> conductor" in result.output


def test_engine_create_needs_a_kind() -> None:
    result = CliRunner().invoke(engine_cmd.app, ["create", "conductor", "--room", "portfolio"])
    assert result.exit_code == 2


def test_engine_invoke_of_an_old_aligner_says_what_to_run_instead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_config = MyceliumConfig()
    monkeypatch.setattr(
        engine_cmd.MyceliumConfig, "load", classmethod(lambda _cls, *_a, **_k: fake_config)
    )
    monkeypatch.setattr(engine_cmd, "_resolve_room", lambda _c, _r: "portfolio")
    fake_cm = MagicMock()
    fake_cm.__enter__.return_value = Mock(name="client")
    fake_cm.__exit__.return_value = None
    monkeypatch.setattr(engine_cmd, "_typed_client", lambda _c: fake_cm)
    monkeypatch.setattr(
        engine_cmd,
        "_load_manifest_remote",
        lambda *_a: AgentManifest(handle="aligner", adapter="engine", kind="aligner"),
    )

    def no_send(**_kwargs: object) -> None:
        raise AssertionError("a retired engine is not summoned")

    monkeypatch.setattr(
        "mycelium_backend_client.api.messages.send_message_api_rooms_room_name_messages_post.sync_detailed",
        no_send,
    )
    result = CliRunner().invoke(
        engine_cmd.app, ["invoke", "aligner", "agree on the cap", "--room", "portfolio"]
    )

    assert result.exit_code == 1
    assert RETIRED_ENGINE_KINDS["aligner"].split(",")[0] in result.output
