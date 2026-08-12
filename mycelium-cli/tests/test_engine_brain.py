# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The Pi brain's custom-endpoint handling (LLM_BASE_URL → pi models.json).

Pi has no ``--base-url`` flag, so a mycelium ``LLM_BASE_URL`` (Ollama, vLLM, a
proxy) is translated into a ``providers`` entry in pi's ``models.json`` and
addressed via ``--provider``/``--model``. Direct-key providers are untouched.
"""

from __future__ import annotations

import json
from pathlib import Path

from mycelium.engine import brain
from mycelium.engine.brain import PiBrain


def _brain(tmp_path: Path, **kw: object) -> PiBrain:
    kw.setdefault("session_path", tmp_path / "s.jsonl")
    kw.setdefault("model", "anthropic/claude-sonnet-4-6")
    return PiBrain(**kw)  # type: ignore[arg-type]


def test_split_provider_model() -> None:
    assert brain.split_provider_model("ollama/llama3.3") == ("ollama", "llama3.3")
    assert brain.split_provider_model("my-model") == ("custom", "my-model")


def test_direct_key_provider_uses_model_and_api_key(tmp_path: Path) -> None:
    cmd = _brain(tmp_path, api_key="secret")._build_command("p", system="")
    assert cmd[cmd.index("--model") + 1] == "anthropic/claude-sonnet-4-6"
    assert cmd[cmd.index("--api-key") + 1] == "secret"
    assert "--provider" not in cmd


def test_base_url_uses_provider_flag_not_api_key(tmp_path: Path) -> None:
    cmd = _brain(
        tmp_path, model="ollama/llama3.3", base_url="http://host.docker.internal:11434"
    )._build_command("p", system="")
    assert cmd[cmd.index("--provider") + 1] == "ollama"
    assert cmd[cmd.index("--model") + 1] == "ollama/llama3.3"
    assert "--api-key" not in cmd
    assert "--base-url" not in cmd


def test_ensure_custom_provider_openai_compatible(tmp_path: Path) -> None:
    brain.ensure_custom_provider(
        provider="ollama",
        model_id="llama3.3",
        base_url="http://host.docker.internal:11434",
        api_key=None,
        agent_dir=tmp_path,
    )
    entry = json.loads((tmp_path / "models.json").read_text())["providers"]["ollama"]
    assert entry["api"] == "openai-completions"
    assert entry["baseUrl"] == "http://host.docker.internal:11434/v1"
    assert entry["apiKey"] == "unused"
    assert entry["models"] == [{"id": "llama3.3"}]


def test_ensure_custom_provider_merges_existing(tmp_path: Path) -> None:
    models_path = tmp_path / "models.json"
    models_path.write_text(json.dumps({"providers": {"kept": {"baseUrl": "http://keep"}}}))
    brain.ensure_custom_provider(
        provider="ollama",
        model_id="qwen2.5",
        base_url="http://localhost:11434/v1",
        api_key=None,
        agent_dir=tmp_path,
    )
    providers = json.loads(models_path.read_text())["providers"]
    assert providers["kept"] == {"baseUrl": "http://keep"}
    assert providers["ollama"]["models"] == [{"id": "qwen2.5"}]
