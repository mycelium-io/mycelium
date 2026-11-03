# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""An agent's session, read from its CLI's file and written where the app reads it.

The converter turns Claude Code's session lines into the rendered view's entries
(``mycelium-frontend/src/lib/agent-session.ts``), and the runner's follower
keeps one file per agent under ``~/.mycelium/runner/sessions`` for the desktop
app's ``agent_session``. Every line here is made up, in the checkout story.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from mycelium.integrations.agents import claude_session, of_kind
from mycelium.integrations.herdr.bridge import HerdrError, HerdrPaneMapping
from mycelium.runner.sessions import Follower

CWD = "/work/checkout"
T = "2026-11-03T10:00:{:02d}.000Z"


def _assistant(n: int, msg: str, block: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "type": "assistant",
        "uuid": f"a{n}",
        "timestamp": T.format(n),
        "cwd": CWD,
        "message": {"id": msg, "content": [block]},
        **extra,
    }


def _user(n: int, content: Any, **extra: Any) -> dict[str, Any]:
    return {
        "type": "user",
        "uuid": f"u{n}",
        "timestamp": T.format(n),
        "cwd": CWD,
        "message": {"content": content},
        **extra,
    }


def _result(
    n: int, call: str, text: str, detail: Any = None, *, error: bool = False
) -> dict[str, Any]:
    block: dict[str, Any] = {"type": "tool_result", "tool_use_id": call, "content": text}
    if error:
        block["is_error"] = True
    return _user(n, [block], toolUseResult=detail)


def _use(n: int, msg: str, call: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
    return _assistant(n, msg, {"type": "tool_use", "id": call, "name": name, "input": args})


SESSION = [
    {"type": "ai-title", "aiTitle": "Refund the double charges", "sessionId": "s1"},
    _user(
        1, "Refund the double charges from Friday.", origin={"kind": "human"}, promptSource="typed"
    ),
    _user(2, "<system-reminder>context</system-reminder>", isMeta=True),
    _assistant(3, "m1", {"type": "thinking", "thinking": "Find the charges first."}),
    _assistant(4, "m1", {"type": "text", "text": "Looking at the charges."}),
    _assistant(5, "m1", {"type": "text", "text": "Two are doubled."}),
    _use(
        6, "m2", "c1", "Bash", {"command": "grep -c refund log.txt", "description": "Count refunds"}
    ),
    _result(
        7,
        "c1",
        "",
        {"stdout": "\n".join(f"line {i}" for i in range(60)), "stderr": "", "interrupted": False},
    ),
    _use(
        8,
        "m3",
        "c2",
        "Edit",
        {"file_path": f"{CWD}/refunds.py", "old_string": "a", "new_string": "b"},
    ),
    _result(
        9,
        "c2",
        "ok",
        {
            "filePath": f"{CWD}/refunds.py",
            "oldString": "a",
            "newString": "b",
            "originalFile": "x" * 10_000,
        },
    ),
    _use(10, "m4", "c3", "Bash", {"command": "pytest"}),
    _result(
        11, "c3", "1 failed", {"stdout": "1 failed", "stderr": "", "interrupted": False}, error=True
    ),
    _use(12, "m5", "c4", "Read", {"file_path": f"{CWD}/README.md"}),
    _use(
        13, "m6", "plan", "TodoWrite", {"todos": [{"content": "Refund", "status": "in_progress"}]}
    ),
    {"type": "system", "subtype": "compact_boundary", "uuid": "k1", "timestamp": T.format(14)},
    _user(15, "Ship it after the iPhone test.", origin={"kind": "human"}, promptSource="queued"),
    _user(16, "mycelium wake for @builder in checkout\n…", origin={"kind": "human"}),
    _user(17, "a task finished", origin={"kind": "task-notification"}),
    _assistant(18, "m7", {"type": "text", "text": "from a side chain"}, isSidechain=True),
    _use(19, "m8", "c5", "Bash", {"command": "make deploy"}),
]


class TestClaudeConverter:
    def entries(self) -> tuple[list[dict[str, Any]], str | None]:
        return claude_session.convert(SESSION)

    def test_kinds_in_order_with_the_bookkeeping_left_out(self):
        entries, title = self.entries()
        assert title == "Refund the double charges"
        assert [e["sessionUpdate"] for e in entries] == [
            "user_message",
            "agent_thought",
            "agent_message",
            "tool_call",
            "tool_call",
            "tool_call",
            "tool_call",
            "plan",
            "compaction",
            "user_message",
            "user_message",
            "tool_call",
        ]

    def test_one_reply_written_as_several_lines_is_one_message(self):
        entries, _ = self.entries()
        reply = entries[2]
        assert [b["text"] for b in reply["content"]] == [
            "Looking at the charges.",
            "Two are doubled.",
        ]

    def test_a_tool_call_takes_its_result_status_and_short_title(self):
        entries, _ = self.entries()
        bash, edit, failed, read = entries[3:7]
        assert (bash["kind"], bash["title"], bash["status"]) == (
            "execute",
            "Count refunds",
            "completed",
        )
        out = bash["content"][0]["content"]["text"]
        assert out.startswith("line 0") and out.endswith("…") and "line 59" not in out
        assert (edit["kind"], edit["title"], edit["locations"]) == (
            "edit",
            "refunds.py",
            [{"path": f"{CWD}/refunds.py"}],
        )
        assert edit["content"] == [
            {"type": "diff", "path": f"{CWD}/refunds.py", "oldText": "a", "newText": "b"}
        ]
        assert "originalFile" not in edit["rawOutput"]
        assert failed["status"] == "failed"
        assert read["kind"] == "read" and "content" not in read

    def test_a_call_with_no_result_is_stopped_if_asked_after_else_running(self):
        entries, _ = self.entries()
        read, last = entries[6], entries[-1]
        assert (read["status"], read["_meta"]["interrupted"]) == ("failed", True)
        assert last["status"] == "in_progress"

    def test_prompts_say_who_typed_them(self):
        entries, _ = self.entries()
        prompts = [e for e in entries if e["sessionUpdate"] == "user_message"]
        assert [p["_meta"]["from"] for p in prompts] == ["person", "person", "wake"]
        assert prompts[1]["_meta"].get("queued") is True

    def test_the_plan_is_its_steps(self):
        entries, _ = self.entries()
        plan = next(e for e in entries if e["sessionUpdate"] == "plan")
        assert plan["entries"] == [
            {"content": "Refund", "priority": "medium", "status": "in_progress"}
        ]

    def test_a_sub_agent_s_work_comes_from_its_own_file(self, tmp_path: Path):
        folder = tmp_path / "subagents"
        folder.mkdir()
        (folder / "agent-x1.meta.json").write_text(
            json.dumps({"toolUseId": "c9", "description": "Find refunds"})
        )
        sub = [
            _user(1, "Find the refunds."),
            _assistant(2, "s1", {"type": "text", "text": "Found two."}),
        ]
        (folder / "agent-x1.jsonl").write_text("\n".join(json.dumps(line) for line in sub))
        entries, _ = claude_session.convert(
            [_use(1, "m1", "c9", "Agent", {"description": "Find refunds", "prompt": "…"})],
            subagents=folder,
        )
        sub_agent = entries[0]["_meta"]["subagent"]
        assert sub_agent["description"] == "Find refunds"
        assert [e["sessionUpdate"] for e in sub_agent["entries"]] == [
            "user_message",
            "agent_message",
        ]
        assert sub_agent["entries"][0]["_meta"]["from"] == "agent"


class TestFindingAndReading:
    @pytest.fixture
    def projects(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
        return tmp_path / "projects"

    def test_the_file_is_named_by_its_folder_or_found_anywhere(self, projects: Path):
        named = projects / "-work-checkout" / "abc-123.jsonl"
        named.parent.mkdir(parents=True)
        named.write_text("")
        assert claude_session.session_file(CWD, "abc-123") == named
        assert claude_session.session_file("/moved/away", "abc-123") == named
        assert claude_session.session_file(CWD, "nope") is None
        assert claude_session.session_file(CWD, "../escape") is None

    def test_a_long_file_is_read_from_its_end(
        self, projects: Path, monkeypatch: pytest.MonkeyPatch
    ):
        path = projects / "-work-checkout" / "s.jsonl"
        path.parent.mkdir(parents=True)
        lines = [
            _assistant(i % 60, f"m{i}", {"type": "text", "text": f"reply {i}"}) for i in range(400)
        ]
        path.write_text("\n".join(json.dumps(line) for line in lines) + '\n{"type": "assi')
        monkeypatch.setattr(claude_session, "TAIL_BYTES", 20_000)
        read = claude_session.read(path)
        assert read["earlier"] is True
        assert read["entries"][-1]["content"][0]["text"] == "reply 399"
        assert read["sessionId"] == "s"


# ── the runner writes each agent's session where the app reads it ────────────


class _Registry:
    def __init__(self, mappings: list[HerdrPaneMapping]) -> None:
        self.mappings = mappings

    def all(self) -> list[HerdrPaneMapping]:
        return list(self.mappings)


def _bridge(mappings: list[HerdrPaneMapping], live: list[dict[str, Any]] | None) -> Any:
    def list_agents() -> list[dict[str, Any]]:
        if live is None:
            raise HerdrError("herdr isn't running")
        return live

    return SimpleNamespace(registry=_Registry(mappings), list_agents=list_agents)


class TestFollower:
    @pytest.fixture
    def claude_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
        path = tmp_path / "claude" / "projects" / "-work-checkout" / "sess-1.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text("\n".join(json.dumps(line) for line in SESSION[:6]))
        return path

    def test_each_agent_gets_its_file_with_why_when_there_is_no_view(
        self, tmp_path: Path, claude_file: Path
    ):
        claude = of_kind("claude").herdr_kind or "claude"
        mappings = [
            HerdrPaneMapping(
                "checkout", "builder", "w1:p1", kind=claude, cwd=CWD, session="sess-1"
            ),
            HerdrPaneMapping("checkout", "design", "w1:p2", kind="kiro", cwd=CWD),
            HerdrPaneMapping("checkout", "lead", "w1:p3", kind=claude, cwd=CWD),
        ]
        live = [{"pane_id": "w1:p1", "agent_status": "blocked"}]
        base = tmp_path / "sessions"
        Follower(_bridge(mappings, live), base).tick()

        builder = base / "checkout" / "builder.json"
        session = json.loads(builder.read_text())
        assert (session["version"], session["state"], session["waitingOn"]) == (1, "waiting", None)
        assert session["title"] == "Refund the double charges"
        assert stat.S_IMODE(builder.stat().st_mode) == 0o600
        assert json.loads((base / "checkout" / "design.json").read_text()) == {
            "unavailable": "no_converter"
        }
        assert json.loads((base / "checkout" / "lead.json").read_text()) == {
            "unavailable": "no_session"
        }
        assert not [p for p in (base / "checkout").iterdir() if p.name.startswith(".")]

    def test_an_unchanged_session_isn_t_written_again_and_a_changed_one_is(
        self, tmp_path: Path, claude_file: Path
    ):
        claude = of_kind("claude").herdr_kind or "claude"
        mapping = HerdrPaneMapping(
            "checkout", "builder", "w1:p1", kind=claude, cwd=CWD, session="sess-1"
        )
        live = [{"pane_id": "w1:p1", "agent_status": "working"}]
        base = tmp_path / "sessions"
        follower = Follower(_bridge([mapping], live), base)
        follower.tick()
        target = base / "checkout" / "builder.json"
        target.write_text("{}")  # so a rewrite would show
        follower.tick()
        assert target.read_text() == "{}"
        with claude_file.open("a") as f:
            f.write("\n" + json.dumps(SESSION[6]))
        follower.tick()
        assert json.loads(target.read_text())["entries"][-1]["sessionUpdate"] == "tool_call"

    def test_herdr_down_reads_as_unknown_and_a_gone_agent_s_file_goes(
        self, tmp_path: Path, claude_file: Path
    ):
        claude = of_kind("claude").herdr_kind or "claude"
        mapping = HerdrPaneMapping(
            "checkout", "builder", "w1:p1", kind=claude, cwd=CWD, session="sess-1"
        )
        base = tmp_path / "sessions"
        bridge = _bridge([mapping], None)
        follower = Follower(bridge, base)
        follower.tick()
        target = base / "checkout" / "builder.json"
        assert json.loads(target.read_text())["state"] == "unknown"
        bridge.registry.mappings = []
        follower.tick()
        assert not target.exists()

    def test_a_name_that_can_t_be_a_file_here_is_skipped(self, tmp_path: Path):
        mappings = [HerdrPaneMapping("..", "builder", "w1:p1", kind="kiro")]
        base = tmp_path / "sessions"
        Follower(_bridge(mappings, []), base).tick()
        assert not base.exists() or not any(base.rglob("*.json"))
