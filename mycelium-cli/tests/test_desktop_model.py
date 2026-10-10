# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium desktop model``: the hub's model settings, as the desktop app reads and writes them."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from mycelium.cli import app
from mycelium.config import MyceliumConfig

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


def _run(*args: str, stdin: str | None = None) -> tuple[int, dict]:
    result = runner.invoke(app, ["desktop", "model", *args], input=stdin)
    body = json.loads(result.stdout) if result.exit_code == 0 else {}
    return result.exit_code, body


def test_it_says_whether_a_key_is_saved_and_never_the_key(isolated_home: Path):
    assert _run() == (0, {"model": None, "base_url": None, "has_key": False, "key_hint": None})

    code, body = _run(
        "--set",
        stdin=json.dumps(
            {"model": "anthropic/claude-sonnet-4-6", "api_key": "sk-ant-test-1234abcd"}
        ),
    )
    assert code == 0
    assert body == {
        "model": "anthropic/claude-sonnet-4-6",
        "base_url": None,
        "has_key": True,
        "key_hint": "abcd",
    }
    # Saved where the hub reads it, and printed nowhere.
    assert MyceliumConfig.load().llm.api_key == "sk-ant-test-1234abcd"
    assert "sk-ant-test" not in json.dumps(body)


def test_a_field_left_out_keeps_its_value_and_an_empty_one_clears_it(isolated_home: Path):
    _run(
        "--set",
        stdin=json.dumps(
            {"model": "anthropic/claude-sonnet-4-6", "api_key": "sk-ant-test-1234abcd"}
        ),
    )

    # The app changes the model without resending a key it was never shown.
    _, body = _run("--set", stdin=json.dumps({"model": "openai/gpt-4.1"}))
    assert body["model"] == "openai/gpt-4.1"
    assert body["has_key"] is True

    _, body = _run("--set", stdin=json.dumps({"api_key": "", "base_url": "http://localhost:11434"}))
    assert body["has_key"] is False
    assert body["base_url"] == "http://localhost:11434"


def test_a_model_without_its_provider_is_refused(isolated_home: Path):
    code, _ = _run("--set", stdin=json.dumps({"model": "gpt-4.1"}))
    assert code == 2
    assert MyceliumConfig.load().llm.model is None


def test_set_wants_a_json_object(isolated_home: Path):
    assert _run("--set", stdin="not json")[0] == 2
    assert _run("--set", stdin="[1, 2]")[0] == 2
