# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The CLI's half of ``contracts/hub-settings.json``.

The hub's Hub page saves a setting by running ``mycelium config set <key> -``
with the value on stdin, so every key the page may change must be a real
config field, and the restart marker the hub leaves must be the one the
desktop supervisor looks for.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mycelium.commands.config import app as config_app
from mycelium.config import MyceliumConfig
from mycelium.desktop import supervisor

_CONTRACT = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts" / "hub-settings.json").read_text()
)

runner = CliRunner()


@pytest.mark.parametrize("key", sorted(_CONTRACT["editable"]))
def test_each_editable_key_is_a_config_field(key: str):
    section, field = key.split(".")
    fields = type(getattr(MyceliumConfig(), section)).model_fields
    assert field in fields, f"{key} is not in MyceliumConfig"


def test_the_restart_marker_is_the_one_the_supervisor_looks_for():
    assert _CONTRACT["restart_marker"] == supervisor.HUB_RESTART_MARKER


def _saved(home: Path) -> dict:
    return tomllib.loads((home / ".mycelium" / "config.toml").read_text())


def test_a_value_on_stdin_is_saved_and_not_echoed(isolated_home: Path):
    result = runner.invoke(config_app, ["set", "llm.api_key", "-"], input="sk-secret\n")
    assert result.exit_code == 0, result.output
    assert "sk-secret" not in result.output
    assert _saved(isolated_home)["llm"]["api_key"] == "sk-secret"


def test_a_bool_and_a_number_on_stdin_keep_their_types(isolated_home: Path):
    assert runner.invoke(config_app, ["set", "verifier.enabled", "-"], input="true").exit_code == 0
    assert (
        runner.invoke(config_app, ["set", "worker.max_turns_per_room", "-"], input="30").exit_code
        == 0
    )
    saved = _saved(isolated_home)
    assert saved["verifier"]["enabled"] is True
    assert saved["worker"]["max_turns_per_room"] == 30


def test_a_save_keeps_every_key_it_was_not_asked_to_change(isolated_home: Path):
    # What the Hub page does: change one setting. The rest of config.toml, the
    # LLM key above all, must read back exactly as it was.
    path = isolated_home / ".mycelium" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "[server]\n"
        'api_url = "http://192.168.1.20:8000"\n'
        "[llm]\n"
        'model = "anthropic/claude-sonnet-4-6"\n'
        'api_key = "sk-ant-kept"\n'
        'base_url = "http://10.0.0.5:8080/v1"\n'
        "[slim]\n"
        f'master_secret = "{"k" * 64}"\n'
        "[worker]\n"
        "max_turns_per_room = 12\n"
    )
    before = _saved(isolated_home)
    result = runner.invoke(config_app, ["set", "verifier.enabled", "-"], input="true")
    assert result.exit_code == 0, result.output
    after = _saved(isolated_home)
    assert after["verifier"]["enabled"] is True
    for section, keys in before.items():
        for key, value in keys.items():
            assert after[section][key] == value, f"{section}.{key} changed"


def test_an_empty_value_on_stdin_clears_the_setting(isolated_home: Path):
    runner.invoke(config_app, ["set", "llm.base_url", "-"], input="http://10.0.0.5:8080/v1")
    assert _saved(isolated_home)["llm"]["base_url"] == "http://10.0.0.5:8080/v1"
    result = runner.invoke(config_app, ["set", "llm.base_url", "-"], input="")
    assert result.exit_code == 0, result.output
    assert MyceliumConfig.load().llm.base_url is None
