# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for the Pi mediator brain (app/services/pi_brain.py) + selection.

Node-free and Pi-free: no real ``pi`` process is ever spawned. We exercise the
three things that must be right for the Pi-brain seam to be trustworthy without a
live binary — the ``pi --mode json`` output parser, the command construction
(flags + OpenShell wrap), and the aligner's brain construction (Pi-only, or an
injected fake) — by monkeypatching :func:`subprocess.run` / :func:`shutil.which`.
A live Pi turn
is a separate, guarded integration step (see the doc's honest caveats).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from app.services import pi_brain
from app.services.pi_brain import PiBrain, PiBrainError, parse_pi_json_output


def _stream(*events: dict[str, Any]) -> str:
    """Render events as a ``pi --mode json`` stdout stream (one JSON line each)."""
    return "\n".join(json.dumps(e) for e in events)


# ── output parsing ──────────────────────────────────────────────────────────


def test_parse_prefers_agent_end_assistant_text() -> None:
    stdout = _stream(
        {"type": "session", "version": 3},
        {"type": "agent_start"},
        {"type": "message_end", "message": {"role": "assistant", "content": "partial"}},
        {
            "type": "agent_end",
            "messages": [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": [{"type": "text", "text": '{"action":"accept"}'}]},
            ],
        },
    )
    assert parse_pi_json_output(stdout) == '{"action":"accept"}'


def test_parse_falls_back_to_message_end_without_agent_end() -> None:
    """A truncated stream (no agent_end) still yields the latest assistant turn."""
    stdout = _stream(
        {"type": "turn_start"},
        {"type": "message_end", "message": {"role": "assistant", "content": "the answer"}},
    )
    assert parse_pi_json_output(stdout) == "the answer"


def test_parse_joins_multiple_text_parts() -> None:
    stdout = _stream(
        {
            "type": "agent_end",
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "part-one "},
                        {"type": "tool_call", "name": "bash"},
                        {"type": "text", "text": "part-two"},
                    ],
                }
            ],
        }
    )
    assert parse_pi_json_output(stdout) == "part-one part-two"


def test_parse_skips_non_json_and_non_dict_lines() -> None:
    stdout = "\n".join(
        [
            "startup log line, not json",
            "[1, 2, 3]",  # valid json but not a dict
            json.dumps({"type": "message_end", "message": {"role": "assistant", "content": "ok"}}),
        ]
    )
    assert parse_pi_json_output(stdout) == "ok"


def test_parse_empty_on_no_assistant_message() -> None:
    assert parse_pi_json_output(_stream({"type": "agent_start"})) == ""
    assert parse_pi_json_output("") == ""


# ── command construction ────────────────────────────────────────────────────


def _brain(tmp_path: Path, **kw: Any) -> PiBrain:
    kw.setdefault("session_path", tmp_path / "s.jsonl")
    kw.setdefault("model", "anthropic/claude-sonnet-4-6")
    return PiBrain(**kw)


def test_build_command_core_flags(tmp_path: Path) -> None:
    cmd = _brain(tmp_path, api_key="secret")._build_command("do it", system="be terse")
    assert cmd[0] == "pi"
    assert "--print" in cmd
    assert cmd[cmd.index("--mode") + 1] == "json"
    assert cmd[cmd.index("--session") + 1] == str(tmp_path / "s.jsonl")
    assert "--no-tools" in cmd
    assert cmd[cmd.index("--model") + 1] == "anthropic/claude-sonnet-4-6"
    assert cmd[cmd.index("--api-key") + 1] == "secret"
    assert cmd[cmd.index("--append-system-prompt") + 1] == "be terse"
    # The prompt is the final positional argument.
    assert cmd[-1] == "do it"


def test_build_command_omits_optional_flags(tmp_path: Path) -> None:
    cmd = _brain(tmp_path)._build_command("prompt", system="")
    assert "--api-key" not in cmd  # no key configured
    assert "--append-system-prompt" not in cmd  # no system prompt
    assert cmd[-1] == "prompt"


def test_build_command_custom_binary(tmp_path: Path) -> None:
    cmd = _brain(tmp_path, binary="/opt/pi/bin/pi")._build_command("p", system="")
    assert cmd[0] == "/opt/pi/bin/pi"


def test_openshell_wrap(tmp_path: Path) -> None:
    cmd = _brain(tmp_path, openshell=True)._build_command("p", system="")
    assert cmd[:6] == ["openshell", "sandbox", "exec", "--from", "pi", "--"]
    assert "pi" in cmd[6:]  # the real pi invocation follows the sandbox prefix


# ── custom endpoint (LLM_BASE_URL → models.json provider) ───────────────────


def test_split_provider_model() -> None:
    assert pi_brain.split_provider_model("ollama/llama3.3") == ("ollama", "llama3.3")
    assert pi_brain.split_provider_model("anthropic/claude-sonnet-4-6") == (
        "anthropic",
        "claude-sonnet-4-6",
    )
    # A bare id (no provider prefix) is filed under "custom".
    assert pi_brain.split_provider_model("my-model") == ("custom", "my-model")


def test_base_url_uses_provider_flag_not_api_key(tmp_path: Path) -> None:
    """With a base URL, pi is addressed by --provider/--model; the key rides in models.json."""
    cmd = _brain(
        tmp_path, model="ollama/llama3.3", base_url="http://host.docker.internal:11434"
    )._build_command("p", system="")
    assert cmd[cmd.index("--provider") + 1] == "ollama"
    assert cmd[cmd.index("--model") + 1] == "ollama/llama3.3"
    assert "--api-key" not in cmd
    assert "--base-url" not in cmd  # pi has no such flag


def test_ensure_custom_provider_writes_openai_compatible_entry(tmp_path: Path) -> None:
    pi_brain.ensure_custom_provider(
        provider="ollama",
        model_id="llama3.3",
        base_url="http://host.docker.internal:11434",
        api_key=None,
        agent_dir=tmp_path,
    )
    data = json.loads((tmp_path / "models.json").read_text())
    entry = data["providers"]["ollama"]
    assert entry["api"] == "openai-completions"
    assert entry["baseUrl"] == "http://host.docker.internal:11434/v1"  # /v1 appended
    assert entry["apiKey"] == "unused"  # dummy — local servers ignore it
    assert entry["models"] == [{"id": "llama3.3"}]


def test_ensure_custom_provider_anthropic_messages_no_v1(tmp_path: Path) -> None:
    pi_brain.ensure_custom_provider(
        provider="anthropic",
        model_id="claude-sonnet-4-6",
        base_url="https://proxy.example.com",
        api_key="sk-ant-xyz",
        agent_dir=tmp_path,
    )
    entry = json.loads((tmp_path / "models.json").read_text())["providers"]["anthropic"]
    assert entry["api"] == "anthropic-messages"
    assert entry["baseUrl"] == "https://proxy.example.com"  # no /v1 for the Messages API
    assert entry["apiKey"] == "sk-ant-xyz"


def test_ensure_custom_provider_merges_existing(tmp_path: Path) -> None:
    """A pre-existing provider the user configured is preserved (merge, not clobber)."""
    models_path = tmp_path / "models.json"
    models_path.write_text(json.dumps({"providers": {"kept": {"baseUrl": "http://keep"}}}))
    pi_brain.ensure_custom_provider(
        provider="ollama",
        model_id="qwen2.5",
        base_url="http://localhost:11434/v1",
        api_key=None,
        agent_dir=tmp_path,
    )
    providers = json.loads(models_path.read_text())["providers"]
    assert providers["kept"] == {"baseUrl": "http://keep"}
    assert providers["ollama"]["baseUrl"] == "http://localhost:11434/v1"  # already had /v1


# ── __call__ (subprocess mocked) ────────────────────────────────────────────


def _patch_run(
    monkeypatch: pytest.MonkeyPatch, *, stdout: str, returncode: int = 0
) -> list[list[str]]:
    """Capture argv and return a canned CompletedProcess from subprocess.run."""
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="boom")

    monkeypatch.setattr(pi_brain.shutil, "which", lambda _b: "/usr/bin/pi")
    monkeypatch.setattr(pi_brain.subprocess, "run", fake_run)
    return calls


def test_call_returns_parsed_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stdout = _stream(
        {"type": "message_end", "message": {"role": "assistant", "content": "hello world"}}
    )
    calls = _patch_run(monkeypatch, stdout=stdout)
    out = _brain(tmp_path)("interpret this", system="sys")
    assert out == "hello world"
    assert calls and calls[0][-1] == "interpret this"


def test_call_raises_on_missing_binary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pi_brain.shutil, "which", lambda _b: None)
    with pytest.raises(PiBrainError, match="not found on PATH"):
        _brain(tmp_path)("p")


def test_call_raises_on_nonzero_exit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_run(monkeypatch, stdout="", returncode=2)
    with pytest.raises(PiBrainError, match="exited 2"):
        _brain(tmp_path)("p")


def test_call_raises_on_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(cmd: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd, 1.0)

    monkeypatch.setattr(pi_brain.shutil, "which", lambda _b: "/usr/bin/pi")
    monkeypatch.setattr(pi_brain.subprocess, "run", fake_run)
    with pytest.raises(PiBrainError, match="exceeded"):
        _brain(tmp_path, timeout_s=1.0)("p")


def test_call_ignores_temperature(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """temperature is accepted for brain-callable parity but never reaches the CLI."""
    calls = _patch_run(
        monkeypatch,
        stdout=_stream({"type": "message_end", "message": {"role": "assistant", "content": "x"}}),
    )
    _brain(tmp_path)("p", system="", temperature=0.9)
    assert "--temperature" not in calls[0]
    assert "0.9" not in calls[0]


# ── brain selection in the aligner ──────────────────────────────────────────


def test_make_brain_default_builds_pi_brain(monkeypatch: pytest.MonkeyPatch) -> None:
    """The mediator brain is Pi-only: the default factory builds a PiBrain."""
    from app.config import settings
    from app.services import aligner

    monkeypatch.setattr(settings, "LLM_MODEL", "anthropic/claude-sonnet-4-6")
    monkeypatch.setattr(settings, "ALIGNER_PI_BINARY", "pi")
    engine = aligner.AlignerEngine(object())  # type: ignore[arg-type]
    brain = engine._make_brain("urn:mycelium:episode:room:align")
    assert isinstance(brain, PiBrain)
    # The episode URN is slugged into a filesystem-safe per-negotiation session.
    assert brain._session_path.name == "urn-mycelium-episode-room-align.jsonl"
    assert brain._model == "anthropic/claude-sonnet-4-6"


def test_make_brain_uses_injected_factory() -> None:
    """A ``brain_factory`` overrides the default (how tests run node-free)."""
    from app.services import aligner

    def sentinel(*_a: object, **_k: object) -> str:
        return "x"

    engine = aligner.AlignerEngine(object(), brain_factory=lambda _ep: sentinel)  # type: ignore[arg-type]
    assert engine._make_brain("urn:x:align") is sentinel
