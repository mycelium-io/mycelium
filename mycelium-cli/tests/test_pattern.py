# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium pattern``: a thin caller of the hub's ``/api/patterns``.

The hub owns what a scenario is and what loading one writes, so these hold only
what the command asks of it and how it reports the answer: a pattern in the
hub's own pack is loaded by name; a pack of your own (a folder, or a git URL
cloned with your credentials) is read here and sent in the request, unchecked,
because the hub checks it; the options it passes; and what it says when the hub
refuses. The hub is an ``httpx.MockTransport`` and git a recorder.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx
import pytest
import yaml
from typer.testing import CliRunner

from mycelium.cli import app
from mycelium.commands import pattern

if TYPE_CHECKING:
    from pathlib import Path

SCENARIO: dict[str, Any] = {
    "pattern": "adversarial-review-agents",
    "title": "Adversarial review",
    "summary": "A proposer defends against a critic.",
    "room": {"title": "Vendor deal"},
    "members": [
        {"handle": "proposer", "kind": "persona", "notes": "You propose."},
        {"handle": "critic", "kind": "persona", "notes": "You criticise."},
    ],
    "task": {"title": "Sign the deal?"},
    "summon": {"flow": "adversarial-review", "members": ["proposer", "critic"], "ask": "Sign?"},
    "flow_file": "protocol.yaml",
}
FLOW = "roles: [proposer, critic]\nsteps:\n  - {id: done, end: resolved}\n"

LOADED = {
    "room": "adversarial-review-agents",
    "title": "Vendor deal",
    "members": ["conductor", "proposer", "critic"],
    "memories": ["context/pattern", "protocols/adversarial-review"],
    "summon": "@conductor adversarial-review @proposer @critic: Sign?",
    "key": "work/sign-the-deal",
    "episode": "urn:t1",
    "ran": False,
    "dry_run": False,
}


class Hub:
    """A hub stand-in: it records each call and answers with what it is given."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self.status = 201
        self.body: Any = LOADED
        self.detail: str | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        content = json.loads(request.content) if request.content else None
        self.calls.append((request.method, request.url.path, content))
        if self.detail is not None:
            return httpx.Response(self.status, json={"detail": self.detail})
        return httpx.Response(self.status, json=self.body)

    def client(self) -> httpx.Client:
        return httpx.Client(base_url="http://hub", transport=httpx.MockTransport(self))


@pytest.fixture
def hub(monkeypatch) -> Hub:
    stand_in = Hub()
    monkeypatch.setattr(pattern, "hub_client", lambda *_a, **_k: stand_in.client())
    return stand_in


def write_pack(root: Path, scenario: dict[str, Any] | None = None, flow: str | None = FLOW) -> Path:
    data = dict(scenario or SCENARIO)
    folder = root / "scenarios" / data["pattern"]
    folder.mkdir(parents=True)
    (folder / "scenario.yaml").write_text(yaml.safe_dump(data))
    if flow is not None:
        (folder / "protocol.yaml").write_text(flow)
    return root


def run(*args: str):
    return CliRunner().invoke(app, ["pattern", *args, "--as", "julia"])


def said(result) -> str:
    """What the command printed, with Rich's line wrapping undone."""
    return " ".join(result.output.split())


# ── a pack of your own ───────────────────────────────────────────────────────


def test_a_pack_is_read_with_its_flow(tmp_path: Path) -> None:
    pack = pattern.fetch_pack(str(write_pack(tmp_path)))
    assert pack.names() == ["adversarial-review-agents"]
    data, flow = pack.read("adversarial-review-agents")
    assert data["summon"]["flow"] == "adversarial-review"
    assert flow == FLOW


def test_an_unknown_scenario_names_the_known_ones(tmp_path: Path) -> None:
    pack = pattern.fetch_pack(str(write_pack(tmp_path)))
    with pytest.raises(pattern.PatternError, match="Known: adversarial-review-agents"):
        pack.read("nope")


def test_a_source_that_is_neither_a_folder_nor_a_url_is_refused(tmp_path: Path) -> None:
    with pytest.raises(pattern.PatternError, match="not a folder or a git URL"):
        pattern.fetch_pack(str(tmp_path / "missing"))


def test_a_flow_file_outside_the_scenario_folder_is_never_read(tmp_path: Path) -> None:
    (tmp_path / "secret.yaml").write_text("do not send me")
    scenario = {**SCENARIO, "flow_file": "../../../secret.yaml"}
    pack = pattern.Pack(root=write_pack(tmp_path / "p", scenario, flow=None), source="x")
    with pytest.raises(pattern.PatternError, match="not a file in the folder"):
        pack.read("adversarial-review-agents")


def test_a_url_is_cloned_once_then_brought_up_to_date(tmp_path: Path, monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_git(args: list[str], _source: str) -> None:
        calls.append(args)

    monkeypatch.setattr(pattern, "cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(pattern, "_git", fake_git)

    url = "https://example.test/org/patterns"
    first = pattern.fetch_pack(url)
    (first.root / ".git").mkdir(parents=True)  # what a real clone leaves
    second = pattern.fetch_pack(url)

    assert calls[0][:3] == ["clone", "--depth", "1"]
    assert [c[2] for c in calls[1:]] == ["fetch", "reset"]
    assert second.root == first.root
    assert first.root.parent == tmp_path / "cache"


# ── use ──────────────────────────────────────────────────────────────────────


def test_a_pattern_in_the_hubs_pack_is_loaded_by_name(hub: Hub) -> None:
    result = run("use", "adversarial-review-agents", "--room", "deal")
    assert result.exit_code == 0, result.output
    method, path, body = hub.calls[0]
    assert (method, path) == ("POST", "/api/patterns/adversarial-review-agents/load")
    assert body == {
        "room": "deal",
        "private": False,
        "run": False,
        "dry_run": False,
        "created_by": "julia",
    }
    assert "paused" in result.output
    # One line, so it can be pasted as it is.
    assert (
        'mycelium board coordinate work/sign-the-deal conductor "adversarial-review @proposer '
        '@critic: Sign?" --room adversarial-review-agents'
    ) in result.output


def test_a_pack_of_your_own_is_sent_in_the_request_unchecked(tmp_path: Path, hub: Hub) -> None:
    # Nothing is checked here: the hub does that, and says what is wrong.
    scenario = {**SCENARIO, "members": "nonsense"}
    pack = write_pack(tmp_path, scenario)
    result = run("use", "adversarial-review-agents", "--from", str(pack), "--run", "--private")
    assert result.exit_code == 0, result.output
    method, path, body = hub.calls[0]
    assert (method, path) == ("POST", "/api/patterns/load")
    assert body["scenario"]["members"] == "nonsense"
    assert body["flow"] == FLOW
    assert body["run"] is True
    assert body["private"] is True


def test_run_says_it_started(hub: Hub) -> None:
    hub.body = {**LOADED, "ran": True}
    result = run("use", "adversarial-review-agents", "--run")
    assert "Started" in result.output
    assert "paused" not in result.output


def test_a_dry_run_asks_the_hub_to_write_nothing(hub: Hub) -> None:
    hub.body = {**LOADED, "dry_run": True, "key": None, "episode": None}
    result = run("use", "adversarial-review-agents", "--dry-run")
    assert result.exit_code == 0, result.output
    assert hub.calls[0][2]["dry_run"] is True
    assert "Would create" in result.output
    assert "paused" not in result.output


def test_a_scenario_with_no_flow_says_the_room_is_ready(hub: Hub) -> None:
    hub.body = {**LOADED, "summon": None}
    result = run("use", "adversarial-review-agents")
    assert "No flow to run" in result.output


def test_the_hubs_reason_for_refusing_is_shown(hub: Hub) -> None:
    hub.status, hub.detail = 422, "role 'critic' is bound to 'judge', a aligner"
    result = run("use", "adversarial-review-agents")
    assert result.exit_code == 1
    assert "could not load adversarial-review-agents" in said(result)
    assert "bound to 'judge'" in said(result)


def test_a_hub_that_takes_no_pack_of_yours_says_so(tmp_path: Path, hub: Hub) -> None:
    hub.status, hub.detail = 403, "This hub loads only the patterns in its own pack"
    result = run("use", "adversarial-review-agents", "--from", str(write_pack(tmp_path)))
    assert result.exit_code == 1
    assert "only the patterns in its own pack" in said(result)


def test_json_prints_what_the_hub_answered(hub: Hub) -> None:
    # Long values must not be wrapped: the output has to stay parseable.
    hub.body = {**LOADED, "summon": "@conductor gated " + "@member " * 40 + ": a long ask"}
    result = CliRunner().invoke(
        app, ["--json", "pattern", "use", "adversarial-review-agents", "--as", "julia"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["key"] == "work/sign-the-deal"
    assert json.loads(result.output)["summon"] == hub.body["summon"]


# ── ls ───────────────────────────────────────────────────────────────────────


def test_ls_lists_the_hubs_patterns(hub: Hub) -> None:
    hub.status = 200
    hub.body = {
        "patterns": [
            {
                "pattern": "approval-gate-agent",
                "summary": "An agent proposes, a person decides.",
                "flow": "gated",
                "members": [{"handle": "ops"}, {"handle": "you"}],
            }
        ],
        "skipped": {"broken": "needs notes"},
    }
    result = CliRunner().invoke(app, ["pattern", "ls"])
    assert result.exit_code == 0, result.output
    assert hub.calls[0][:2] == ("GET", "/api/patterns")
    assert "approval-gate-agent" in result.output
    assert "gated" in result.output
    assert "skipped broken" in result.output


def test_ls_from_a_pack_of_your_own_never_calls_the_hub(tmp_path: Path, hub: Hub) -> None:
    result = CliRunner().invoke(app, ["pattern", "ls", "--from", str(write_pack(tmp_path))])
    assert result.exit_code == 0, result.output
    assert "adversarial-review-agents" in said(result)
    assert hub.calls == []
