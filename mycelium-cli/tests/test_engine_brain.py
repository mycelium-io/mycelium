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
from typing import Any

from mycelium.engine import brain
from mycelium.engine.brain import PiBrain


def _brain(tmp_path: Path, **kw: Any) -> PiBrain:
    kw.setdefault("session_path", tmp_path / "s.jsonl")
    kw.setdefault("model", "anthropic/claude-sonnet-4-6")
    return PiBrain(**kw)


def test_split_provider_model() -> None:
    assert brain.split_provider_model("ollama/llama3.3") == ("ollama", "llama3.3")
    assert brain.split_provider_model("my-model") == ("custom", "my-model")


def test_direct_key_provider_uses_model_and_api_key(tmp_path: Path) -> None:
    cmd = _brain(tmp_path, api_key="secret")._build_command("p", system="")
    assert cmd[cmd.index("--model") + 1] == "anthropic/claude-sonnet-4-6"
    assert cmd[cmd.index("--api-key") + 1] == "secret"
    assert "--provider" not in cmd


def test_prompt_leading_at_and_dash_are_neutralized(tmp_path: Path) -> None:
    """A prompt opening with @ or - must not be parsed by pi as a file/flag."""
    assert _brain(tmp_path)._build_command("@growth propose.", system="")[-1] == " @growth propose."
    assert _brain(tmp_path)._build_command("-5 counter.", system="")[-1] == " -5 counter."
    assert _brain(tmp_path)._build_command("propose.", system="")[-1] == "propose."


def test_custom_provider_base_url_uses_provider_flag(tmp_path: Path) -> None:
    cmd = _brain(
        tmp_path, model="ollama/llama3.3", base_url="http://host.docker.internal:11434"
    )._build_command("p", system="")
    assert cmd[cmd.index("--provider") + 1] == "ollama"
    assert cmd[cmd.index("--model") + 1] == "ollama/llama3.3"
    assert "--api-key" not in cmd
    assert "--base-url" not in cmd


def test_standard_endpoint_stays_direct(tmp_path: Path) -> None:
    """A base URL naming the provider's own endpoint is a no-op: direct mode, no override."""
    brain_ = _brain(
        tmp_path,
        model="anthropic/claude-haiku-4-5",
        base_url="https://api.anthropic.com",
        api_key="sk-ant-xyz",
    )
    assert brain_._endpoint_mode == "direct"
    cmd = brain_._build_command("p", system="")
    assert "--provider" not in cmd
    assert cmd[cmd.index("--model") + 1] == "anthropic/claude-haiku-4-5"


def test_builtin_provider_proxy_writes_override(tmp_path: Path) -> None:
    """A proxy base URL on a built-in provider → baseUrl override, still --model/--api-key."""
    brain_ = _brain(
        tmp_path,
        model="anthropic/claude-haiku-4-5",
        base_url="https://proxy.internal.corp/anthropic",
        api_key="sk-ant-xyz",
    )
    assert brain_._endpoint_mode == "builtin"
    cmd = brain_._build_command("p", system="")
    assert "--provider" not in cmd
    assert cmd[cmd.index("--api-key") + 1] == "sk-ant-xyz"


def test_is_standard_endpoint() -> None:
    assert brain.is_standard_endpoint("anthropic", "https://api.anthropic.com")
    assert brain.is_standard_endpoint("openai", "https://api.openai.com/v1")
    assert not brain.is_standard_endpoint("anthropic", "https://proxy.corp/anthropic")


def test_ensure_config_custom_openai_compatible(tmp_path: Path) -> None:
    brain.ensure_provider_config(
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


def test_ensure_config_builtin_baseurl_only(tmp_path: Path) -> None:
    brain.ensure_provider_config(
        provider="anthropic",
        model_id="claude-haiku-4-5",
        base_url="https://api.anthropic.com",
        api_key="sk-ant-xyz",
        agent_dir=tmp_path,
    )
    entry = json.loads((tmp_path / "models.json").read_text())["providers"]["anthropic"]
    assert entry == {"baseUrl": "https://api.anthropic.com"}


def test_ensure_config_merges_existing(tmp_path: Path) -> None:
    models_path = tmp_path / "models.json"
    models_path.write_text(json.dumps({"providers": {"kept": {"baseUrl": "http://keep"}}}))
    brain.ensure_provider_config(
        provider="ollama",
        model_id="qwen2.5",
        base_url="http://localhost:11434/v1",
        api_key=None,
        agent_dir=tmp_path,
    )
    providers = json.loads(models_path.read_text())["providers"]
    assert providers["kept"] == {"baseUrl": "http://keep"}
    assert providers["ollama"]["models"] == [{"id": "qwen2.5"}]
