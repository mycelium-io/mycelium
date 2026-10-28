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
        "hubs_here",
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
        "hubs_here",
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
    assert "embedding_model" not in names
    # The app's own UI runs here in both modes: a joined hub is reached through it.
    assert "ui" in names
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


def test_a_hub_reached_at_its_ui_answers_under_api(monkeypatch: pytest.MonkeyPatch):
    import httpx

    tried: list[str] = []

    def get(url: str, *_a, **_k):
        tried.append(url)
        return httpx.Response(200 if url.endswith("/api/health") else 404)

    monkeypatch.setattr(checks, "_get", get)
    assert checks.hub("https://hub.example.com/").status == "ok"
    assert tried == ["https://hub.example.com/health", "https://hub.example.com/api/health"]


@pytest.mark.parametrize(
    ("server", "client", "status", "fix"),
    [
        ("0.9.3", "0.9.3", "ok", None),
        ("0.8.0", "0.9.3", "error", "herdr server stop"),
        ("0.8.0", "0.8.0", "error", "herdr update"),
    ],
)
def test_herdr_older_than_mycelium_needs_is_an_error_with_its_fix(
    monkeypatch: pytest.MonkeyPatch, server: str, client: str, status: str, fix: str | None
):
    from mycelium.desktop import herdr_server
    from mycelium.integrations.herdr import HerdrBridge

    monkeypatch.setattr(HerdrBridge, "binary_present", lambda _self: True)
    monkeypatch.setattr(HerdrBridge, "available", lambda _self: True)
    monkeypatch.setattr(HerdrBridge, "server_version", lambda _self: server)
    monkeypatch.setattr(HerdrBridge, "version", lambda _self: client)
    monkeypatch.setattr(herdr_server, "stale", lambda _app: None)
    result = checks.herdr()
    assert result.status == status
    if fix:
        assert "needs 0.9.3 or newer" in result.message
        assert any(fix in d for d in result.details)


def _hubs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, found: list) -> None:
    from mycelium import hubs
    from mycelium.config import MyceliumConfig

    monkeypatch.setattr(hubs, "find_hubs", lambda *_a, **_k: found)
    monkeypatch.setattr(MyceliumConfig, "get_data_dir", lambda _self: tmp_path)


def test_one_hub_on_this_macs_own_store_checks_out(monkeypatch, tmp_path: Path):
    from mycelium import __version__
    from mycelium.hubs import Hub

    own = Hub(source="process", port=8000, pid=7, version=__version__, data_path=str(tmp_path))
    own.answering = True
    _hubs(monkeypatch, tmp_path, [own])
    result = checks.hubs_here()
    assert result.status == "ok"
    assert "process 7" in result.message


def test_a_second_stack_on_another_store_is_a_warning_that_names_it(monkeypatch, tmp_path: Path):
    from mycelium.hubs import Hub

    eval_stack = Hub(
        source="docker",
        port=8000,
        image="mycelium-backend:dev",
        project="mycelium-concord-eval",
        data_path="/Users/julia/.mycelium-concord-eval",
        answering=True,
    )
    other = Hub(source="process", port=8001, pid=9, data_path=str(tmp_path))
    _hubs(monkeypatch, tmp_path, [eval_stack, other])
    result = checks.hubs_here()
    assert result.status == "warning"
    text = " ".join([result.message, *result.details])
    assert "2 Mycelium hubs" in result.message
    assert "mycelium-concord-eval" in text
    assert "/Users/julia/.mycelium-concord-eval" in text
    assert "development build" in text


def test_a_client_mac_only_mentions_hubs_here(monkeypatch, tmp_path: Path):
    _hubs(monkeypatch, tmp_path, [])
    assert checks.hubs_here(client=True).status == "info"


def test_the_way_to_start_the_hub_follows_who_runs_it(setting):
    assert checks.start_hub() == "mycelium up"
    setting({"mode": "client", "hubUrl": "https://hub.example.com"})
    assert checks.start_hub() == "mycelium up"
    setting({"mode": "hub"})
    assert checks.start_hub() == "open the Mycelium app"


def test_doctor_checks_what_the_app_runs_once_it_is_set_up(setting, monkeypatch):
    from typer.testing import CliRunner

    from mycelium.cli import app
    from mycelium.commands import doctor

    setting({"mode": "client", "hubUrl": "https://hub.example.com"})
    monkeypatch.setattr(doctor, "_check_docker_containers", _ok("Docker containers"))
    monkeypatch.setattr(checks, "pairings", lambda: None)
    result = CliRunner().invoke(app, ["--json", "doctor"])
    assert '"mode": "desktop"' in result.output
    assert "Docker containers" not in result.output


def _hub_answers(monkeypatch: pytest.MonkeyPatch, status: int, body: dict) -> list[dict]:
    import httpx

    asked: list[dict] = []

    def get(url: str, **kw):
        asked.append(kw.get("headers") or {})
        return httpx.Response(status, json=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", get)
    monkeypatch.setattr("mycelium.runner.daemon.runner_id", lambda: "julias-mbp-ab12")
    return asked


def test_the_runner_check_asks_as_this_machine_and_says_when_it_is_connected(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "mycelium.client.auth_headers", lambda *_a, **_k: {"Authorization": "Bearer me"}
    )
    asked = _hub_answers(monkeypatch, 200, {"connected": True})
    found = checks.runner("https://hub.example.com")
    assert (found.status, found.message) == ("ok", "connected as julias-mbp-ab12")
    assert asked == [{"Authorization": "Bearer me"}]


def test_the_runner_check_takes_the_running_runners_word_before_the_hubs(
    monkeypatch: pytest.MonkeyPatch,
):
    """Run from an agent's pane, the hub would answer 404: it shows a runner only
    to its owner. The runner says it's connected, and that's the answer."""
    asked = _hub_answers(monkeypatch, 404, {"detail": "not found"})
    monkeypatch.setattr("mycelium.runner.daemon.read_sync", lambda: {"hub": {"connected": True}})
    found = checks.runner("https://hub.example.com")
    assert (found.status, found.message) == ("ok", "connected as julias-mbp-ab12")
    assert asked == []


def test_a_hub_that_refuses_this_machine_says_to_sign_in_not_stopped_checking_in(
    monkeypatch: pytest.MonkeyPatch,
):
    _hub_answers(monkeypatch, 401, {"detail": "missing bearer token"})
    found = checks.runner("https://hub.example.com/")
    assert found.status == "error"
    assert found.message == "this computer isn't signed in to the hub"
    assert found.details == [
        "This computer isn't signed in to https://hub.example.com. "
        "Run `mycelium login` in a terminal here."
    ]
