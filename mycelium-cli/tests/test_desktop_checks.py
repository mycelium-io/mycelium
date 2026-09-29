# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium doctor --mode desktop``: checks that follow what the app runs.

Nothing live: the app's setting is a file in a temp home, and each check's
probe is replaced. These hold which checks a hub Mac and a client Mac get,
and what a failing check tells the person.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mycelium.desktop import checks
from mycelium.ui_status import CheckResult


def _ok(name: str):
    return lambda *_a, **_k: CheckResult(name=name, status="ok", message="")


@pytest.fixture
def setting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "desktop.json"
    monkeypatch.setattr(checks, "SETTINGS", path)
    for fn in (
        "slim_node",
        "hub",
        "ui",
        "runner",
        "herdr",
        "agent_clis",
        "on_path",
        "embedding_model",
    ):
        monkeypatch.setattr(checks, fn, _ok(fn))

    def write(data: dict | None) -> None:
        if data is not None:
            path.write_text(json.dumps(data))

    return write


def _names(sections) -> list[str]:
    return [c.name for _title, group in sections for c in group]


def test_a_hub_mac_checks_everything_it_runs(setting):
    setting({"mode": "hub", "hubUrl": None, "roots": ["/Users/julia"]})
    names = _names(checks.desktop_checks())
    assert names == [
        "Desktop app",
        "slim_node",
        "hub",
        "ui",
        "runner",
        "herdr",
        "agent_clis",
        "on_path",
        "embedding_model",
    ]


def test_a_client_mac_skips_what_runs_elsewhere(setting):
    setting({"mode": "client", "hubUrl": "https://hub.example.com", "roots": []})
    names = _names(checks.desktop_checks())
    assert "slim_node" not in names
    assert "ui" not in names
    assert "embedding_model" not in names
    assert checks.app_setting().message == "joins https://hub.example.com"


def test_before_the_first_run_it_says_to_open_the_app(setting):
    setting(None)
    result = checks.app_setting()
    assert result.status == "warning"
    assert "Open Mycelium" in result.details[0]


def test_missing_commands_say_how_to_get_them_on_path(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(checks.shutil, "which", lambda name: None if name == "herdr" else "/x")
    result = checks.on_path()
    assert result.status == "error"
    assert result.message == "missing: herdr"
    assert any(".local/bin" in d for d in result.details)


def test_the_hub_check_names_the_address_it_tried(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(checks, "_get", lambda *_a, **_k: None)
    result = checks.hub("http://127.0.0.1:8000")
    assert result.status == "error"
    assert "http://127.0.0.1:8000" in result.message
