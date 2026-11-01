# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for ``mycelium theme``: files in the temp ``~/.mycelium``, no hub."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from mycelium import themes
from mycelium.commands import theme as theme_cmd

runner = CliRunner()

CONTRACT = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts" / "custom-theme.json").read_text()
)
COLORS = {
    "bg": "#0f1a14",
    "surface": "#13211a",
    "paper": "#172820",
    "elevated": "#1d3127",
    "muted-bg": "#1d3127",
    "text": "#e6f2ea",
    "muted-foreground": "#a9c2b2",
    "faint": "#86a090",
    "accent": "#7EE0A1",
    "accent-fg": "#0a1f12",
    "green": "#7ee0a1",
    "yellow": "#e3c46b",
    "red": "#f08a7e",
}
FERN: dict[str, Any] = {"name": "Fern", "mode": "dark", "colors": COLORS}


@pytest.fixture(autouse=True)
def _home(isolated_home) -> None:
    """Every test runs under the temp ``~/.mycelium``."""


def _run(*args: str):
    return runner.invoke(theme_cmd.app, list(args))


def test_the_rules_are_the_contract_s() -> None:
    assert list(themes.REQUIRED_COLORS) == CONTRACT["required"]
    assert list(themes.OPTIONAL_COLORS) == CONTRACT["optional"]
    assert set(themes.TRANSLUCENT) == set(CONTRACT["translucent"])
    assert CONTRACT["name_max"] == themes.NAME_MAX
    assert [list(b) for b in themes.BUILTIN] == [
        [b["id"], b["label"], b["mode"]] for b in CONTRACT["builtin"]
    ]


def test_add_writes_the_theme_into_the_folder_and_use_picks_it(tmp_path) -> None:
    src = tmp_path / "fern.json"
    src.write_text(json.dumps(FERN))
    result = _run("add", str(src), "--use")
    assert result.exit_code == 0, result.output
    stored = json.loads((themes.folder() / "fern.json").read_text())
    assert stored["name"] == "Fern"
    assert stored["colors"]["accent"] == "#7ee0a1"
    assert json.loads(themes.pick_file().read_text()) == {"theme": "custom-fern"}


def test_add_takes_json_and_refuses_a_bad_theme_with_every_reason() -> None:
    assert _run("add", "--body", json.dumps(FERN)).exit_code == 0
    bad = _run("add", "--body", json.dumps({**FERN, "mode": "dim", "colors": {}}))
    assert bad.exit_code == 1
    assert '"mode"' in bad.output
    assert "missing" in bad.output


def test_add_downloads_a_theme_from_a_url(monkeypatch) -> None:
    monkeypatch.setattr(themes, "download", lambda url: json.dumps(FERN).encode())
    result = _run("add", "https://example.com/themes/fern.json")
    assert result.exit_code == 0, result.output
    assert [t.name for t in themes.custom_themes()] == ["Fern"]


def test_a_download_is_http_only() -> None:
    with pytest.raises(themes.ThemeError):
        themes.download("file:///etc/passwd")


def test_ls_marks_the_one_in_use_and_skips_a_file_that_isn_t_a_theme() -> None:
    _run("add", "--body", json.dumps(FERN))
    (themes.folder() / "broken.json").write_text('{"name": "Broken"}')
    _run("use", "Dracula")
    result = _run("ls", "--json")
    data = json.loads(result.output)
    assert data["current"] == "dracula"
    assert [t["name"] for t in data["themes"]] == ["Fern"]


def test_use_takes_a_name_an_id_or_system_and_refuses_an_unknown_one() -> None:
    _run("add", "--body", json.dumps(FERN))
    for name, picked in (
        ("tokyo night", "tokyo-night"),
        ("fern", "custom-fern"),
        ("system", "system"),
    ):
        assert _run("use", name).exit_code == 0
        assert themes.current() == picked
    nope = _run("use", "sparkly")
    assert nope.exit_code == 1
    assert "theme ls" in nope.output


def test_show_prints_a_theme_and_rm_removes_it() -> None:
    _run("add", "--body", json.dumps(FERN))
    shown = json.loads(_run("show", "Fern").output)
    assert shown["name"] == "Fern"
    assert _run("rm", "fern").exit_code == 0
    assert themes.custom_themes() == []
    assert _run("rm", "fern").exit_code == 1


def test_a_switch_says_which_app_follows_it() -> None:
    result = _run("use", "nord")
    assert "desktop app follows this" in result.output
    assert "Docker" in result.output


def test_a_downloaded_theme_is_named_by_its_own_name_never_the_url(monkeypatch) -> None:
    sneaky = {**FERN, "name": "../../escape"}
    monkeypatch.setattr(themes, "download", lambda url: json.dumps(sneaky).encode())
    assert _run("add", "https://example.com/../../.bashrc").exit_code == 0
    assert [p.name for p in themes.folder().iterdir()] == ["escape.json"]


def test_a_download_that_isn_t_a_theme_is_refused_and_nothing_is_saved(monkeypatch) -> None:
    monkeypatch.setattr(themes, "download", lambda url: b"<html>not a theme</html>")
    result = _run("add", "https://example.com/fern.json")
    assert result.exit_code == 1
    assert "isn't JSON" in result.output
    assert not themes.folder().exists() or not list(themes.folder().iterdir())


def test_a_missing_or_broken_pick_file_reads_as_no_pick() -> None:
    assert themes.current() is None
    themes.pick_file().parent.mkdir(parents=True, exist_ok=True)
    themes.pick_file().write_text("{broken")
    assert themes.current() is None
    _run("use", "dark")
    assert themes.current() == "dark"
