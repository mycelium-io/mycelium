# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium onboard`` — the guided tour, and the scenarios it runs.

Node-free and hub-free: the tour is glue over the real CLI, so these pin the
pieces that decide what it does (the scenario data, the briefing an agent is
handed, the hub address normalization, the verdict parse) and the sequence of
commands a ``--yes`` run issues, with every subprocess and hub call faked.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from typer.testing import CliRunner

from mycelium import client as client_mod
from mycelium import scenarios
from mycelium.cli import app
from mycelium.commands import onboard

runner = CliRunner()

_HANDLE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


# ── scenarios ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("scenario", list(scenarios.SCENARIOS.values()), ids=lambda s: s.id)
def test_every_scenario_is_two_people_with_a_real_disagreement(scenario: scenarios.Scenario):
    assert scenario.room == f"demo-{scenario.id}"
    assert len(scenario.agents) == 2
    handles = scenario.handles
    assert len(set(handles)) == 2
    for agent in scenario.agents:
        assert _HANDLE.match(agent.handle), agent.handle
        # Each brief says what the person wants, what they'd give, and where they stop.
        assert "You can give:" in agent.brief
        assert "Your hard line:" in agent.brief
    for _title, assignee in scenario.followups:
        assert assignee in handles
    assert scenario.question and not scenario.question.endswith(".")


def test_the_default_scenario_exists():
    assert scenarios.DEFAULT_SCENARIO in scenarios.SCENARIOS


def test_kickoff_mentions_nobody():
    """A mention would queue a wake for agents that are not in the room yet."""
    for scenario in scenarios.SCENARIOS.values():
        assert "@" not in scenarios.kickoff_text(scenario)


def test_briefing_is_self_contained():
    scenario = scenarios.SCENARIOS["release-plan"]
    maya = scenario.agents[0]
    text = scenarios.briefing(
        scenario,
        maya,
        room="demo-release-plan",
        row="work/plan-the-2-0-release",
        hub_url="https://hub.example",
        gated=True,
    )
    assert "@maya" in text
    assert "@theo" in text  # knows who else is at the table
    assert maya.brief in text
    assert "mycelium config set server.api_url https://hub.example" in text
    assert "mycelium room use demo-release-plan" in text
    assert "mycelium login --device" in text
    assert (
        "mycelium respond --room demo-release-plan --handle maya --task work/plan-the-2-0-release"
        in text
    )
    assert "mycelium await --room demo-release-plan --handle maya --json" in text
    assert "[[mycelium: confidence=" in text


def test_briefing_on_an_open_hub_does_not_ask_for_a_login():
    scenario = scenarios.SCENARIOS["cloud-costs"]
    text = scenarios.briefing(
        scenario, scenario.agents[1], room="r", row="work/x", hub_url="http://h", gated=False
    )
    assert "mycelium login" not in text
    assert "nothing to sign in to" in text


# ── the hub address ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("https://mycelium.outshift.io", "https://mycelium.outshift.io"),
        ("https://mycelium.outshift.io/", "https://mycelium.outshift.io"),
        ("https://mycelium.outshift.io/api", "https://mycelium.outshift.io"),
        ("hub.example.com:8000", "http://hub.example.com:8000"),
        ("  localhost:8000/ ", "http://localhost:8000"),
        ("", ""),
    ],
)
def test_normalize_hub(raw: str, want: str):
    assert onboard.normalize_hub(raw) == want


def test_ui_url_is_the_local_port_or_the_hub_origin():
    from mycelium.config import MyceliumConfig

    cfg = MyceliumConfig()
    assert onboard.ui_url(cfg, "demo") == "http://localhost:3000/room/demo"
    cfg.server.api_url = "https://mycelium.outshift.io"
    assert onboard.ui_url(cfg, "demo") == "https://mycelium.outshift.io/room/demo"


def test_default_handle_comes_from_the_login_name(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("USER", "Julia Valenti")
    assert onboard.default_handle() == "julia-valenti"
    monkeypatch.setenv("USER", "")
    monkeypatch.delenv("USERNAME", raising=False)
    assert onboard.default_handle() == "me"


# ── the health probe ────────────────────────────────────────────────────────


def _resp(url: str, status: int, *, payload: Any = None, text: str | None = None) -> httpx.Response:
    """A real ``httpx.Response`` with its request attached, so ``raise_for_status`` works."""
    request = httpx.Request("GET", url)
    if text is not None:
        return httpx.Response(status, text=text, request=request)
    return httpx.Response(status, json=payload, request=request)


def _stub_get(
    monkeypatch: pytest.MonkeyPatch, answers: dict[str, httpx.Response | Exception]
) -> list[str]:
    asked: list[str] = []

    def fake_get(url: str, timeout: float) -> httpx.Response:  # noqa: ARG001
        asked.append(url)
        answer = answers[url]
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(httpx, "get", fake_get)
    return asked


def test_probe_health_falls_back_to_the_api_prefix(monkeypatch: pytest.MonkeyPatch):
    """Behind a proxy the frontend owns /, and only /api/health is the backend's."""
    asked = _stub_get(
        monkeypatch,
        {
            "https://hub/health": _resp("https://hub/health", 404),
            "https://hub/api/health": _resp(
                "https://hub/api/health", 200, payload={"status": "ok", "auth": {"enabled": True}}
            ),
        },
    )
    body, why = client_mod.probe_health("https://hub/")
    assert body == {"status": "ok", "auth": {"enabled": True}}
    assert why == ""
    assert asked == ["https://hub/health", "https://hub/api/health"]


def test_probe_health_takes_the_bare_path_first(monkeypatch: pytest.MonkeyPatch):
    asked = _stub_get(
        monkeypatch, {"http://h/health": _resp("http://h/health", 200, payload={"status": "ok"})}
    )
    body, _ = client_mod.probe_health("http://h")
    assert body == {"status": "ok"}
    assert asked == ["http://h/health"]


def test_probe_health_reports_why_when_nothing_answers(monkeypatch: pytest.MonkeyPatch):
    _stub_get(
        monkeypatch,
        {
            "http://h/health": httpx.ConnectError("refused"),
            "http://h/api/health": httpx.ConnectError("refused"),
        },
    )
    body, why = client_mod.probe_health("http://h")
    assert body is None
    assert "couldn't reach http://h/api/health" in why


def test_probe_health_skips_an_answer_that_is_not_a_health_document(
    monkeypatch: pytest.MonkeyPatch,
):
    """A frontend that serves HTML with a 200 on every path is not the hub."""
    _stub_get(
        monkeypatch,
        {
            "http://h/health": _resp("http://h/health", 200, text="<html>not the hub</html>"),
            "http://h/api/health": _resp(
                "http://h/api/health", 200, payload=["not", "an", "object"]
            ),
        },
    )
    body, why = client_mod.probe_health("http://h")
    assert body is None
    assert "health document" in why


# ── the verdict ─────────────────────────────────────────────────────────────


def _commit(subkind: str, assignments: dict[str, str] | None = None, text: str = "") -> dict:
    record = {
        "content": text,
        "l9": {
            "header": {"kind": "commit", "subkind": subkind},
            "payload": {"data": {"assignments": assignments or {}}},
        },
    }
    return {
        "id": "m1",
        "sender_handle": "aligner",
        "message_type": "l9_commit",
        "content": json.dumps(record),
    }


def test_parse_verdict_reads_a_converged_commit():
    verdict = onboard.parse_verdict(
        _commit("converged", {"release date": "three weeks"}, "✓ agreement in 4 steps")
    )
    assert verdict == {
        "converged": True,
        "assignments": {"release date": "three weeks"},
        "text": "✓ agreement in 4 steps",
        "sender": "aligner",
    }


def test_parse_verdict_reads_a_rejected_commit():
    verdict = onboard.parse_verdict(_commit("rejected", text="✗ no agreement"))
    assert verdict is not None
    assert verdict["converged"] is False
    assert verdict["assignments"] == {}


def test_parse_verdict_ignores_everything_else():
    assert onboard.parse_verdict({"message_type": "broadcast", "content": "hi"}) is None
    assert onboard.parse_verdict({"message_type": "l9_commit", "content": "{not json"}) is None


def test_tail_prints_the_conversation_and_stops_at_the_verdict(capsys: pytest.CaptureFixture):
    from datetime import UTC, datetime

    from mycelium.config import MyceliumConfig

    feed = [
        {"id": "a", "sender_handle": "aligner", "message_type": "broadcast", "content": "@maya?"},
        {
            "id": "b",
            "sender_handle": "maya",
            "message_type": "broadcast",
            "content": "Three weeks.",
        },
        {"id": "c", "sender_handle": "sys", "message_type": "l9_knowledge", "content": "{}"},
        _commit("converged", {"date": "three weeks"}),
    ]
    with (
        patch.object(onboard, "_messages_since", return_value=feed),
        patch.object(onboard.time, "sleep"),
    ):
        verdict = onboard._tail_until_verdict(
            MyceliumConfig(), "r", datetime.now(UTC), ["maya", "theo"]
        )
    assert verdict is not None and verdict["converged"]
    out = capsys.readouterr().out
    assert "aligner: @maya?" in out
    assert "maya: Three weeks." in out
    assert "sys" not in out  # a control frame is not conversation


def test_wait_for_agents_needs_a_position_and_presence():
    """Posting and leaving is not enough: the aligner addresses who is present."""
    from mycelium.config import MyceliumConfig

    spoke = iter([set(), {"maya"}, {"maya", "theo"}, {"maya", "theo"}])
    present = iter([set(), set(), {"maya"}, {"maya", "theo"}])
    with (
        patch.object(onboard, "_thread_senders", side_effect=lambda *_: next(spoke)),
        patch.object(onboard, "_present", side_effect=lambda *_: next(present)),
        patch.object(onboard.time, "sleep"),
    ):
        onboard._wait_for_agents(MyceliumConfig(), "r", "urn:x", ["maya", "theo"])


# ── the command ─────────────────────────────────────────────────────────────


def test_list_prints_every_scenario():
    result = runner.invoke(app, ["onboard", "--list"])
    assert result.exit_code == 0
    for sid in scenarios.SCENARIOS:
        assert sid in result.stdout


def test_unknown_scenario_is_refused(isolated_home: Path):
    with patch.object(onboard, "probe_health", return_value=({"status": "ok"}, "")):
        result = runner.invoke(app, ["onboard", "--scenario", "nope", "--yes"])
    assert result.exit_code == 1
    assert "Unknown scenario" in result.stdout


def test_briefings_need_a_room_set_up_earlier(isolated_home: Path):
    result = runner.invoke(app, ["onboard", "--briefings"])
    assert result.exit_code == 1
    assert "No onboarding state" in result.stdout


def test_briefings_reprint_from_saved_state(isolated_home: Path):
    onboard._save_state("demo-release-plan", {"row": "work/plan", "gated": False})
    result = runner.invoke(app, ["onboard", "--briefings"])
    assert result.exit_code == 0, result.stdout
    assert "@maya" in result.stdout and "@theo" in result.stdout
    assert "--task work/plan" in result.stdout


def test_an_unreachable_hosted_hub_stops_the_tour(isolated_home: Path):
    with patch.object(onboard, "probe_health", return_value=(None, "couldn't reach it")):
        result = runner.invoke(app, ["onboard", "--hub", "https://hub.example", "--yes"])
    assert result.exit_code == 1
    assert "No hub answered at https://hub.example" in result.stdout


class _NoHerdr:
    """A bridge on a machine without herdr: nothing to type a briefing into."""

    def binary_present(self) -> bool:
        return False


def _ok(stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


def test_a_yes_run_issues_the_real_commands_in_order(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
):
    """With every hub call faked, the tour is the sequence a user would type."""
    from mycelium.config import MyceliumConfig

    monkeypatch.delenv("MYCELIUM_API_URL", raising=False)

    cfg_path = isolated_home / ".mycelium" / "config.toml"
    cfg_path.parent.mkdir(parents=True)
    cfg_path.write_text('[identity]\nname = "julia"\n')
    calls: list[list[str]] = []

    def fake_run(args: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:  # noqa: ARG001
        calls.append(args)
        return _ok()

    health = {"status": "ok", "version": "9.9", "auth": {"enabled": False}}
    verdict = {"converged": True, "assignments": {"date": "3 weeks"}, "text": "", "sender": "a"}
    with (
        patch.object(onboard, "probe_health", return_value=(health, "")),
        patch.object(onboard, "_run", side_effect=fake_run),
        patch.object(onboard, "_create_task", return_value=("work/plan", "urn:x:episode:r:t1")),
        patch.object(onboard, "_herdr_panes", return_value=(_NoHerdr(), [])),
        patch.object(onboard, "_wait_for_agents"),
        patch.object(onboard, "_tail_until_verdict", return_value=verdict),
        # The first read is the board before the summon; after it, the compiled row.
        patch.object(onboard, "_work_rows", side_effect=[set(), {"memory:work/notes"}]),
        patch.object(onboard, "_claimed", return_value=True),
        patch.object(onboard.time, "sleep"),
    ):
        result = runner.invoke(app, ["onboard", "--yes", "--hub", "https://hub.example/api"])

    assert result.exit_code == 0, result.stdout
    assert MyceliumConfig.load().server.api_url == "https://hub.example"
    heads = [c[:2] for c in calls]
    assert heads.index(["room", "create"]) < heads.index(["room", "use"])
    assert ["engine", "create"] in heads
    assert [c for c in calls if c[:2] == ["agent", "create"]] == [
        c for c in calls if c[:2] == ["agent", "create"] and "--adapter" in c
    ]
    assert len([c for c in calls if c[:2] == ["agent", "create"]]) == 2
    coordinate = next(c for c in calls if c[:2] == ["board", "coordinate"])
    assert coordinate[2] == "t1" and coordinate[3] == scenarios.ALIGNER_HANDLE
    follow_ups = [c for c in calls if c[:2] == ["board", "new"]]
    assert len(follow_ups) == 2
    assert all("--parent" in c and "work/plan" in c for c in follow_ups)
    # The briefings were printed for pasting (no clipboard in a test) and saved.
    assert "Paste this into coding agent 1" in result.stdout
    assert (isolated_home / ".mycelium" / "onboard" / "demo-release-plan" / "maya.md").exists()
    assert "Agreement" in result.stdout
    assert "https://hub.example/room/demo-release-plan" in result.stdout
