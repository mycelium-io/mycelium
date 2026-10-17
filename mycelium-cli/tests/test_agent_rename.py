# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium agent rename`` asks the hub to rename an agent; the herdr tab it
was in is renamed with it. The restart under the new handle is the runner's
(``test_runner.py``)."""

from __future__ import annotations

import contextlib
import json
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from typer.testing import CliRunner

from mycelium.cli import app
from mycelium.integrations.herdr import HerdrBridge, HerdrRegistry
from tests.test_herdr_bridge import ScriptedRunner, _ok, _proc

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


def _bridge(label: str) -> tuple[HerdrBridge, ScriptedRunner]:
    scripted = ScriptedRunner(
        {
            "pane list": _proc(
                _ok({"panes": [{"pane_id": "w5:p3", "tab_id": "w5:t1", "workspace_id": "w5"}]})
            ),
            "tab list": _proc(_ok({"tabs": [{"tab_id": "w5:t1", "label": label}]})),
            "tab rename": _proc(_ok({})),
        }
    )
    return HerdrBridge(runner=scripted, registry=HerdrRegistry()), scripted


def test_the_tab_mycelium_named_says_the_new_name(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/herdr")
    bridge, scripted = _bridge("@voice-model @hay")
    bridge.rename_in_tab("w5:p3", "voice-model", "docs-writer")
    assert ["tab", "rename", "w5:t1", "@docs-writer @hay"] in scripted.calls


def test_a_tab_a_person_named_keeps_its_name(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/herdr")
    bridge, scripted = _bridge("Release notes")
    bridge.rename_in_tab("w5:p3", "voice-model", "docs-writer")
    assert not [c for c in scripted.calls if c[:2] == ["tab", "rename"]]


def _hub(monkeypatch: pytest.MonkeyPatch, answer: httpx.Response) -> list[tuple[str, Any]]:
    seen: list[tuple[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, json.loads(request.content)))
        return answer

    @contextlib.contextmanager
    def client(_config: Any = None, **_kw: Any):
        with httpx.Client(base_url="http://hub", transport=httpx.MockTransport(handler)) as c:
            yield c

    monkeypatch.setattr("mycelium.commands.agent.hub_client", client)
    return seen


def _renamed(**over: Any) -> dict:
    body = {
        "handle": "docs-writer",
        "was": "voice-model",
        "memories": [],
        "rows": ["work/a"],
        "restart_runner": "julias-mbp",
        "restart_job": "a1b2c3",
    }
    body.update(over)
    return body


def test_agent_rename_asks_the_hub(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _hub(monkeypatch, httpx.Response(200, json=_renamed()))
    result = runner.invoke(
        app,
        ["agent", "rename", "@voice-model", "docs-writer", "--room", "general", "--as", "julia"],
    )
    assert result.exit_code == 0, result.output
    assert seen == [
        ("/api/rooms/general/agents/voice-model/rename", {"to": "docs-writer", "by": "julia"})
    ]
    assert "@voice-model is @docs-writer in general" in result.output
    assert "1 task now names it" in result.output
    assert "restarted under its new name on julias-mbp" in result.output


def test_agent_rename_says_when_nothing_restarts_it(monkeypatch: pytest.MonkeyPatch) -> None:
    _hub(
        monkeypatch,
        httpx.Response(200, json=_renamed(rows=[], restart_runner=None, restart_job=None)),
    )
    result = runner.invoke(
        app, ["agent", "rename", "voice-model", "docs-writer", "--room", "general", "--as", "julia"]
    )
    assert result.exit_code == 0, result.output
    assert "Restart it yourself" in result.output


def test_agent_rename_says_why_the_hub_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _hub(monkeypatch, httpx.Response(409, json={"detail": "@hay is already a member of general."}))
    result = runner.invoke(
        app, ["agent", "rename", "voice-model", "hay", "--room", "general", "--as", "julia"]
    )
    assert result.exit_code == 1
    assert "@hay is already a member of general." in result.output
