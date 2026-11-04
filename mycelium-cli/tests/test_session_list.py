# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The earlier agent sessions on a machine, listed to bring one into a room.

Claude Code's are listed from its session files; the runner's scan carries
where and when each was, and only the app on the machine gets its title. Every
line here is made up, in the checkout story.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from mycelium.integrations.agents import claude_session
from mycelium.runner.frameworks import Found, with_sessions


def _line(kind: str, n: int, cwd: str, **extra: Any) -> dict[str, Any]:
    return {
        "type": kind,
        "uuid": f"{kind[0]}{n}",
        "timestamp": f"2026-11-03T10:00:{n:02d}.000Z",
        "cwd": cwd,
        **extra,
    }


def _write(projects: Path, cwd: str, session: str, lines: list[dict[str, Any]], mtime: int) -> Path:
    path = projects / cwd.replace("/", "-") / f"{session}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    os.utime(path, (mtime, mtime))
    return path


@pytest.fixture
def projects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    return tmp_path / "claude" / "projects"


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    folder = tmp_path / "code" / "checkout"
    folder.mkdir(parents=True)
    return folder


def _sessions(projects: Path, checkout: Path) -> None:
    cwd = str(checkout)
    prompt = {"content": "Fix the double charge on a network timeout."}
    _write(
        projects,
        cwd,
        "older-1",
        [
            _line("user", 1, cwd, message=prompt, gitBranch="main"),
            _line("assistant", 2, cwd, message={"id": "m1", "content": []}, gitBranch="fix/charge"),
        ],
        mtime=1_000,
    )
    _write(
        projects,
        cwd,
        "newer-2",
        [
            _line("user", 1, cwd, message={"content": "Write tests for the refund webhook."}),
            {"type": "ai-title", "aiTitle": "Refund webhook tests", "sessionId": "newer-2"},
            {"type": "ai-title", "aiTitle": "Test the refund webhook", "sessionId": "newer-2"},
        ],
        mtime=2_000,
    )
    # Nothing was said in it, so there's nothing to bring back.
    _write(projects, cwd, "empty-3", [{"type": "summary", "summary": "x"}], mtime=3_000)
    _write(projects, cwd, "not_an_id", [_line("user", 1, cwd, message=prompt)], mtime=4_000)
    sub = projects / cwd.replace("/", "-") / "newer-2" / "subagents" / "agent-a1.jsonl"
    sub.parent.mkdir(parents=True)
    sub.write_text(json.dumps(_line("user", 1, cwd, message=prompt)) + "\n")


class TestListing:
    def test_newest_first_with_where_and_when_and_no_words(self, projects: Path, checkout: Path):
        _sessions(projects, checkout)
        listed = claude_session.list_sessions()
        assert [s["id"] for s in listed] == ["newer-2", "older-1"]
        older = listed[1]
        assert older["folder"] == str(checkout)
        assert older["branch"] == "fix/charge"
        assert older["last_used"].startswith("1970-01-01T00:16:40")
        assert all("title" not in s for s in listed)

    def test_titles_are_the_cli_s_latest_else_the_first_prompt(
        self, projects: Path, checkout: Path
    ):
        _sessions(projects, checkout)
        titles = {s["id"]: s["title"] for s in claude_session.list_sessions(titles=True)}
        assert titles == {
            "newer-2": "Test the refund webhook",
            "older-1": "Fix the double charge on a network timeout.",
        }

    def test_a_long_first_prompt_is_cut_to_its_first_line(self, projects: Path, checkout: Path):
        cwd = str(checkout)
        long = "Review " + "the tax line on large orders " * 10 + "\nand more"
        _write(projects, cwd, "s1", [_line("user", 1, cwd, message={"content": long})], 1)
        (found,) = claude_session.list_sessions(titles=True)
        assert len(found["title"]) == claude_session.TITLE_CHARS
        assert found["title"].endswith("…")
        assert "and more" not in found["title"]

    def test_no_projects_folder_is_no_sessions(self, projects: Path):
        assert claude_session.list_sessions() == []


def _found(framework: str) -> Found:
    return Found(framework, framework, framework, None, None, True, True, None)


class TestTheScan:
    def test_sessions_here_that_could_be_resumed_with_where_and_when_only(
        self, projects: Path, checkout: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        _sessions(projects, checkout)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        _write(projects, str(elsewhere), "outside-4", [_line("user", 1, str(elsewhere))], 5_000)
        gone = str(tmp_path / "code" / "deleted")
        _write(projects, gone, "gone-5", [_line("user", 1, gone)], 6_000)
        real = claude_session.list_sessions

        def with_titles(*, titles: bool = False) -> list[dict[str, Any]]:
            return real(titles=True)  # so the scan has to drop them itself

        monkeypatch.setattr(claude_session, "list_sessions", with_titles)
        claude, gemini = with_sessions(
            [_found("claude"), _found("gemini")],
            roots=[(tmp_path / "code").resolve()],
            busy={"newer-2"},
            members={"older-1": {"room": "checkout", "handle": "builder"}},
        )
        assert gemini.sessions is None
        assert claude.sessions is not None
        assert claude.sessions == [
            {
                "id": "older-1",
                "folder": str(checkout),
                "last_used": claude.sessions[0]["last_used"],
                "branch": "fix/charge",
                "member": {"room": "checkout", "handle": "builder"},
            }
        ]
        assert "title" not in json.dumps(claude.wire())

    def test_a_cli_the_host_can_t_start_and_isn_t_here_lists_none(self, projects: Path):
        absent = Found("claude", "claude", "claude", None, None, False, False, None)
        (found,) = with_sessions([absent], roots=[], busy=set())
        assert found.sessions is None


def test_the_local_command_lists_titles(projects: Path, checkout: Path):
    from mycelium.cli import app

    _sessions(projects, checkout)
    result = CliRunner().invoke(app, ["machine", "sessions", "--json"])
    assert result.exit_code == 0, result.output
    listed = json.loads(result.output)
    assert [(s["framework"], s["id"], s["title"]) for s in listed] == [
        ("claude", "newer-2", "Test the refund webhook"),
        ("claude", "older-1", "Fix the double charge on a network timeout."),
    ]


def test_the_follower_keeps_which_member_each_session_was(tmp_path: Path):
    from types import SimpleNamespace

    from mycelium.integrations.herdr.bridge import HerdrPaneMapping
    from mycelium.runner.sessions import MEMBERS_FILE, Follower, read_members

    mappings = [
        HerdrPaneMapping("checkout", "builder", "w1:p1", kind="kiro", session="sess-1"),
        HerdrPaneMapping("checkout", "design", "w1:p2", kind="kiro"),
    ]
    registry = SimpleNamespace(all=lambda: list(mappings))
    bridge = SimpleNamespace(registry=registry, list_agents=list)
    base = tmp_path / "runner" / "sessions"
    Follower(bridge, base).tick()  # ty: ignore[invalid-argument-type]
    record = tmp_path / "runner" / MEMBERS_FILE
    assert read_members(record) == {"sess-1": {"room": "checkout", "handle": "builder"}}
    assert oct(record.stat().st_mode & 0o777) == "0o600"
    mappings.clear()  # the member was removed; the record stays
    Follower(bridge, base).tick()  # ty: ignore[invalid-argument-type]
    assert read_members(record) == {"sess-1": {"room": "checkout", "handle": "builder"}}
