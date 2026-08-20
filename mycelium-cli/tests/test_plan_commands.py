# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for ``mycelium plan`` (ls / show / tasks) + the fetch wiring.

Node-free: the rendering commands run against a stubbed ``_fetch_plan`` payload,
and one test drives the real ``_fetch_plan`` through the ``fake_httpx`` transport
to pin the HTTP wiring. No backend server.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from mycelium.commands import plan as plan_cmd
from tests.conftest import FakeHTTPX, FakeResp

runner = CliRunner()

_PLAN = {
    "room": "demo",
    "files": [
        {
            "slug": "tasks",
            "title": "MVP",
            "updated_at": "2026-06-01T10:00:00",
            "content": "# MVP\n\n- [ ] ship auth @a",
            "tasks": [
                {"id": "t1", "text": "ship auth @a", "done": False, "slug": "tasks"},
                {"id": "t2", "text": "write docs @b", "done": True, "slug": "tasks"},
            ],
        }
    ],
    "tasks": [
        {"id": "t1", "text": "ship auth @a", "done": False, "slug": "tasks"},
        {"id": "t2", "text": "write docs @b", "done": True, "slug": "tasks"},
    ],
}


def test_plan_ls_renders_file_table(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plan_cmd, "_fetch_plan", lambda room=None: _PLAN)
    result = runner.invoke(plan_cmd.app, ["ls"])
    assert result.exit_code == 0, result.output
    assert "demo plan" in result.output
    assert "tasks" in result.output


def test_plan_ls_empty_prints_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plan_cmd, "_fetch_plan", lambda room=None: {"room": "demo", "files": []})
    result = runner.invoke(plan_cmd.app, ["ls"])
    assert result.exit_code == 0, result.output
    assert "No plan files yet." in result.output


def test_plan_show_prints_body(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plan_cmd, "_fetch_plan", lambda room=None: _PLAN)
    result = runner.invoke(plan_cmd.app, ["show", "tasks"])
    assert result.exit_code == 0, result.output
    assert "ship auth @a" in result.output


def test_plan_show_unknown_slug_exits_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plan_cmd, "_fetch_plan", lambda room=None: _PLAN)
    result = runner.invoke(plan_cmd.app, ["show", "ghost"])
    assert result.exit_code == 1
    assert "Plan file not found" in result.output


def test_plan_tasks_lists_open_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plan_cmd, "_fetch_plan", lambda room=None: _PLAN)
    result = runner.invoke(plan_cmd.app, ["tasks"])
    assert result.exit_code == 0, result.output
    assert "1 open" in result.output and "1 done" in result.output
    assert "ship auth @a" in result.output
    assert "write docs @b" not in result.output  # done tasks hidden without --all


def test_plan_tasks_all_includes_done(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plan_cmd, "_fetch_plan", lambda room=None: _PLAN)
    result = runner.invoke(plan_cmd.app, ["tasks", "--all"])
    assert result.exit_code == 0, result.output
    assert "write docs @b" in result.output


def test_fetch_plan_hits_room_scoped_endpoint(
    fake_httpx: FakeHTTPX, monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    """The real ``_fetch_plan`` GETs the room-scoped plan endpoint.

    Needs ``isolated_home`` to avoid cached-token refresh crash on stubbed config.
    """
    del isolated_home  # only needed for its patching side effect
    from types import SimpleNamespace

    monkeypatch.setattr(
        plan_cmd.MyceliumConfig,
        "load",
        classmethod(lambda _cls: SimpleNamespace(server=SimpleNamespace(api_url="http://bk:8000"))),
    )
    monkeypatch.setattr(plan_cmd, "_resolve_room", lambda _cfg, _room: "demo")
    fake_httpx.respond_with(lambda *_a: FakeResp(_PLAN))

    data = plan_cmd._fetch_plan("demo")
    assert data["room"] == "demo"
    # base_url rides the client constructor; the recorded url is the request path.
    assert fake_httpx.calls == [("GET", "/api/rooms/demo/plan", {})]
