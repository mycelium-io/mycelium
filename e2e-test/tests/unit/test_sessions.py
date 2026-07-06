"""Unit tests for :mod:`libs.sessions`.

All host_exec calls and consensus polling are stubbed so the tests run
offline in <100ms.
"""

from __future__ import annotations

import json
import json
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from libs import sessions
from libs.host_exec import HostExecError

# ── shared helpers ──────────────────────────────────────────────────


def _device():
    return SimpleNamespace(custom={"transport": "local"}, name="hub")


def _ok(stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr=stderr)


def _fail(stderr: str = "boom", stdout: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=1, stdout=stdout, stderr=stderr)


# ── create_room / delete_room ───────────────────────────────────────


def test_create_room_passes_room_name():
    with patch("libs.host_exec.execute", return_value=_ok()) as exec_mock:
        sessions.create_room(_device(), "r-alpha")
    argv = exec_mock.call_args.args[1]
    assert argv == ["mycelium", "room", "create", "r-alpha"]


def test_create_room_tolerates_already_exists():
    out = _fail(stdout="Error: Room r-alpha already exists\n", stderr="")
    with patch("libs.host_exec.execute", return_value=out):
        sessions.create_room(_device(), "r-alpha")  # no raise


def test_create_room_raises_on_unknown_failure():
    with patch("libs.host_exec.execute", return_value=_fail("backend 503")):
        with pytest.raises(sessions.SessionError, match="create_room"):
            sessions.create_room(_device(), "r-x")


def test_delete_room_never_raises_even_on_dispatch_error():
    with patch("libs.host_exec.execute", side_effect=HostExecError("ssh down")):
        sessions.delete_room(_device(), "r-x")  # no raise


# ── session_create / session_join ───────────────────────────────────


def test_session_create_argv():
    stdout = json.dumps({"session_room": "r-x:session:abc123"})
    with patch("libs.host_exec.execute", return_value=_ok(stdout=stdout)) as exec_mock:
        room = sessions.session_create(_device(), "r-x")
    assert room == "r-x:session:abc123"
    assert exec_mock.call_args.args[1] == [
        "mycelium",
        "--json",
        "session",
        "create",
        "--room",
        "r-x",
    ]


def test_session_join_rejects_empty_position():
    with pytest.raises(sessions.SessionError, match="non-empty"):
        sessions.session_join(_device(), "r-x", "alpha", "")


def test_session_join_argv_includes_handle_room_and_message():
    with patch("libs.host_exec.execute", return_value=_ok()) as exec_mock:
        sessions.session_join(_device(), "r-x", "alpha", "REST forever")
    argv = exec_mock.call_args.args[1]
    assert argv[:3] == ["mycelium", "session", "join"]
    assert argv[argv.index("--room") + 1] == "r-x"
    assert argv[argv.index("--handle") + 1] == "alpha"
    assert argv[argv.index("--message") + 1] == "REST forever"


def test_session_join_raises_on_cli_failure():
    with patch("libs.host_exec.execute", return_value=_fail("rooms: not found")):
        with pytest.raises(sessions.SessionError, match="session_join"):
            sessions.session_join(_device(), "r-bad", "alpha", "anything")


# ── memory_set / memory_search ──────────────────────────────────────


def test_memory_set_argv():
    with patch("libs.host_exec.execute", return_value=_ok()) as exec_mock:
        sessions.memory_set(_device(), "r-x", "alpha", "decisions/api", '{"x":1}')
    argv = exec_mock.call_args.args[1]
    assert argv[:3] == ["mycelium", "memory", "set"]
    assert argv[-2:] == ["decisions/api", '{"x":1}']


def test_memory_search_returns_stdout():
    with patch("libs.host_exec.execute", return_value=_ok(stdout="hit: api-style")):
        out = sessions.memory_search(_device(), "r-x", "what was decided")
    assert "api-style" in out


# ── poll_consensus ──────────────────────────────────────────────────


def test_poll_consensus_parses_full_envelope():
    result = {
        "coordination_state": "complete",
        "completion_source": "coordination_consensus",
        "consensus": {
            "plan": "go with REST",
            "plan_file": "plan/tasks.md",
            "broken": False,
            "assignments": {"alpha": "REST"},
        },
    }
    with patch("libs.coordination_flow.poll_for_consensus", return_value=result):
        outcome = sessions.poll_consensus(
            "http://backend:8000",
            "r-x",
            timeout_seconds=1,
            poll_interval=0,
        )
    assert outcome.reached is True
    assert outcome.plan_file == "plan/tasks.md"
    assert outcome.assignments == {"alpha": "REST"}
    assert outcome.broken is False


def test_poll_consensus_handles_broken_envelope():
    result = {
        "coordination_state": "failed",
        "completion_source": "coordination_consensus",
        "consensus": {"plan": "Negotiation ended: timeout", "broken": True},
    }
    with patch("libs.coordination_flow.poll_for_consensus", return_value=result):
        outcome = sessions.poll_consensus(
            "http://backend:8000",
            "r-x",
            timeout_seconds=1,
            poll_interval=0,
        )
    assert outcome.state == "consensus"
    assert outcome.broken is True
    assert outcome.reached is False


def test_poll_consensus_returns_timeout_state():
    with patch("libs.coordination_flow.poll_for_consensus", return_value=None):
        outcome = sessions.poll_consensus(
            "http://backend:8000",
            "r-x",
            timeout_seconds=0,
            poll_interval=0,
        )
    assert outcome.state == "timeout"
    assert outcome.broken is True
    assert outcome.plan_file is None


def test_consensus_outcome_from_poll_tolerates_invalid_content_json():
    result = {
        "coordination_state": "complete",
        "completion_source": "coordination_consensus",
        "consensus": {"plan": "this is not json", "broken": False},
    }
    outcome = sessions.consensus_outcome_from_poll(result)
    assert outcome.state == "consensus"
    assert outcome.plan == "this is not json"


# ── read_plan_tasks ─────────────────────────────────────────────────


def test_read_plan_tasks_returns_body():
    with patch(
        "libs.host_exec.execute",
        return_value=_ok(stdout="# Plan\n- [ ] thing\n"),
    ):
        body = sessions.read_plan_tasks(_device(), "r-x")
    assert "- [ ] thing" in body


def test_read_plan_tasks_raises_when_missing():
    with patch("libs.host_exec.execute", return_value=_fail("not found")):
        with pytest.raises(sessions.SessionError, match="read_plan_tasks"):
            sessions.read_plan_tasks(_device(), "r-x")
