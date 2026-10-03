# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Reads that print JSON with ``--json`` after the command: the traces views,
``metrics status``, ``herdr ls``/``status``, ``runner status``, ``ui status``,
``openshell status`` and ``machine integrations``. Each answer must parse."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
from typer.testing import CliRunner

from mycelium.cli import app

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

runner = CliRunner()


def _json(args: list[str]) -> Any:
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


# ── metrics traces ──────────────────────────────────────────────────────────


@pytest.fixture
def traces_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A traces.db with two spans of one trace, one of them an error with an event."""
    from mycelium.collector import _TRACES_SCHEMA

    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    path = tmp_path / "metrics" / "traces.db"
    path.parent.mkdir(parents=True)
    conn = sqlite3.connect(path)
    conn.executescript(_TRACES_SCHEMA)
    attrs = {
        "gen_ai.agent.id": "scout",
        "gen_ai.conversation.id": "agent:scout:mycelium-room:channel:checkout",
        "gen_ai.request.model": "anthropic/claude-sonnet-4-6",
        "gen_ai.usage.input_tokens": 10,
        "gen_ai.usage.output_tokens": 4,
        "gen_ai.tool.name": "grep",
    }
    event = [
        {
            "time": "2026-10-02T10:00:01Z",
            "name": "exception",
            "attributes": {"exception.message": "boom"},
        }
    ]
    conn.executemany(
        "INSERT INTO spans (trace_id, span_id, parent_span_id, name, host, start_time,"
        " duration_ms, status, status_message, attributes, events) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("t1", "s1", "", "chat", "build-3", "2026-10-02T10:00:00Z", 120.0, "ok", "", json.dumps(attrs), "[]"),
            ("t1", "s2", "s1", "execute_tool", "build-3", "2026-10-02T10:00:01Z", 30.0, "error", "boom",
             json.dumps(attrs), json.dumps(event)),
        ],
    )  # fmt: skip
    conn.commit()
    conn.close()
    return path


@pytest.mark.parametrize(
    "command",
    [
        ["list"],
        ["errors"],
        ["slow"],
        ["events"],
        ["rooms"],
        ["agents"],
        ["by-host"],
        ["by-agent"],
        ["by-room"],
        ["by-channel"],
        ["by-model"],
        ["by-name"],
        ["by-tool"],
    ],
    ids=" ".join,
)
def test_trace_lists_print_json(traces_db: Path, command: list[str]) -> None:
    rows = _json(["metrics", "traces", *command, "--json"])
    assert isinstance(rows, list)
    assert rows


def test_trace_list_json_carries_the_spans_whole(traces_db: Path) -> None:
    rows = _json(["metrics", "traces", "list", "--json", "--room", "checkout", "-n", "1"])
    assert len(rows) == 1
    assert rows[0]["room"] == "checkout"
    assert rows[0]["agent"] == "scout"


def test_trace_room_filter_is_a_filter_not_the_active_room(traces_db: Path) -> None:
    # No --room means every room, even with a room in the environment.
    rows = _json(["metrics", "traces", "list", "--json"])
    assert {r["span_id"] for r in rows} == {"s1", "s2"}
    assert _json(["metrics", "traces", "list", "--json", "-r", "elsewhere"]) == []


def test_trace_summary_show_and_schema_print_json(traces_db: Path) -> None:
    summary = _json(["metrics", "traces", "summary", "--json"])
    assert summary["spans"] == 2
    assert summary["errors"] == 1

    trace = _json(["metrics", "traces", "show", "s2", "--json"])
    assert trace["trace_id"] == "t1"
    assert [s["depth"] for s in trace["spans"]] == [0, 1]
    assert trace["spans"][1]["events"][0]["name"] == "exception"

    schema = _json(["metrics", "traces", "schema", "--json"])
    assert "CREATE TABLE" in schema["schema"]

    attrs = _json(["metrics", "traces", "show-attrs", "s1", "--json"])
    assert attrs["span_id"] == "s1"


def test_traces_with_no_subcommand_honors_the_global_json(traces_db: Path) -> None:
    summary = _json(["--json", "metrics", "traces"])
    assert summary["spans"] == 2


# ── metrics status ──────────────────────────────────────────────────────────


def test_metrics_status_prints_json(monkeypatch: pytest.MonkeyPatch) -> None:
    from mycelium.commands import metrics

    monkeypatch.setattr(metrics, "_get_collector_url", lambda: None)
    monkeypatch.setattr(metrics, "_docker_collector_running", lambda: False)
    monkeypatch.setattr(metrics, "_port_in_use", lambda _port: False)
    report = _json(["metrics", "status", "--json"])
    assert report["collector"] == {"running": False, "via": None}
    assert report["healthy"] is False


# ── herdr ───────────────────────────────────────────────────────────────────


class _FakeRegistry:
    def __init__(self, mappings: list) -> None:
        self.mappings = mappings

    def all(self) -> list:
        return list(self.mappings)


class _FakeBridge:
    def __init__(self, mappings: list) -> None:
        self.registry = _FakeRegistry(mappings)

    def binary_present(self) -> bool:
        return True

    def available(self) -> bool:
        return True

    def list_agents(self) -> list[dict]:
        return [{"pane_id": "w2:pV", "agent_status": "idle"}]


@pytest.fixture
def herdr(monkeypatch: pytest.MonkeyPatch) -> None:
    from mycelium.commands import herdr as herdr_cmd
    from mycelium.integrations.herdr import HerdrPaneMapping

    mappings = [
        HerdrPaneMapping(room="checkout", handle="scout", pane="w2:pV", kind="claude"),
        HerdrPaneMapping(room="lobby", handle="other", pane="w2:pX", kind="pi"),
    ]
    monkeypatch.setattr(herdr_cmd, "_bridge", lambda: _FakeBridge(mappings))
    monkeypatch.setattr(herdr_cmd, "_room_members", lambda _config, _room: {"scout": "lease"})


def test_herdr_ls_prints_json(herdr: None) -> None:
    rows = _json(["herdr", "ls", "--json"])
    assert [(r["room"], r["handle"]) for r in rows] == [("checkout", "scout"), ("lobby", "other")]
    assert rows[0]["herdr"] == "idle"
    assert rows[0]["verdict"] == "✓ in sync"


def test_herdr_ls_room_is_a_filter(herdr: None, monkeypatch: pytest.MonkeyPatch) -> None:
    # The active room in the environment doesn't narrow it; --room does.
    monkeypatch.setenv("MYCELIUM_ROOM_ID", "lobby")
    assert len(_json(["herdr", "ls", "--json"])) == 2
    assert [r["handle"] for r in _json(["herdr", "ls", "--json", "-r", "checkout"])] == ["scout"]


def test_herdr_status_prints_json(herdr: None) -> None:
    state = _json(["herdr", "status", "--json"])
    assert state == {"installed": True, "reachable": True, "live_agents": 1, "bindings": 2}
    assert _json(["--json", "herdr", "status"]) == state


# ── runner, ui, openshell ───────────────────────────────────────────────────


def test_runner_status_prints_json(monkeypatch: pytest.MonkeyPatch) -> None:
    import mycelium.client
    import mycelium.runner.daemon

    seen = {"connected": True, "herdr": True, "agents": []}

    @contextmanager
    def fake_hub_client(*_a: object, **_k: object) -> Iterator[SimpleNamespace]:
        yield SimpleNamespace(get=lambda _path: SimpleNamespace(status_code=200, json=lambda: seen))

    monkeypatch.setattr(mycelium.client, "hub_client", fake_hub_client)
    monkeypatch.setattr(mycelium.runner.daemon, "runner_id", lambda: "abc123")
    state = _json(["runner", "status", "--json"])
    assert state["runner"] == "abc123"
    assert state["hub"] == seen


def test_ui_status_prints_json(monkeypatch: pytest.MonkeyPatch) -> None:
    from mycelium.commands import ui

    monkeypatch.setattr(ui, "_container_running", lambda _name: True)
    state = _json(["ui", "status", "--json"])
    assert state["running"] is True
    assert state["url"].startswith("http://localhost:")


def test_openshell_status_prints_json(monkeypatch: pytest.MonkeyPatch) -> None:
    from mycelium import openshell

    monkeypatch.setattr(openshell, "cli_installed", lambda: True)
    monkeypatch.setattr(openshell, "gateway_running", lambda: False)
    state = _json(["openshell", "status", "--json"])
    assert state["cli_installed"] is True
    assert state["gateway_running"] is False
    assert state["metrics_wired"] is False


def test_machine_integrations_json_after_the_command(monkeypatch: pytest.MonkeyPatch) -> None:
    from mycelium.commands import machine as machine_cmd

    state = SimpleNamespace(wire=lambda: {"missing": ["claude"]}, missing=["claude"])
    monkeypatch.setattr(machine_cmd, "integrations", lambda: state)
    assert _json(["machine", "integrations", "--json"]) == {"missing": ["claude"]}
