# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for the herdr bridge — registry, CLI parsing, and wake logic.

The ``herdr`` CLI is mocked via an injectable ``runner`` (a scripted
``CompletedProcess`` per command), so these exercise the parsing + fail-soft wake
orchestration without a live herdr server. The live end-to-end lives in the
claude_code-style e2e smoke, not here.
"""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING

import pytest

from mycelium.integrations.herdr import (
    HerdrBridge,
    HerdrError,
    HerdrPaneMapping,
    HerdrRegistry,
    HerdrUnavailableError,
    build_wake_prompt,
)

if TYPE_CHECKING:
    from pathlib import Path


def _proc(stdout: str = "", stderr: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["herdr"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _ok(result: dict) -> str:
    return json.dumps({"id": "cli:test", "result": result})


class ScriptedRunner:
    """A herdr CLI stand-in: maps the leading args of a call to a response.

    ``key`` is the space-joined first two args (e.g. ``"agent list"``); the value
    is either a ``CompletedProcess`` or a callable ``(args) -> CompletedProcess``.
    Records every call for assertions.
    """

    def __init__(self, responses: dict) -> None:
        self._responses = responses
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> subprocess.CompletedProcess:
        self.calls.append(args)
        key = " ".join(args[:2])
        resp = self._responses.get(key)
        if resp is None:
            return _proc(stderr=_ok({}), returncode=2)
        return resp(args) if callable(resp) else resp


# ── registry ──────────────────────────────────────────────────────────────────


def test_registry_roundtrip(isolated_home: Path) -> None:
    reg = HerdrRegistry()
    reg.set(HerdrPaneMapping(room="design", handle="reviewer", pane="w2:pV", kind="claude"))
    got = reg.get("design", "reviewer")
    assert got is not None
    assert got.pane == "w2:pV"
    assert got.kind == "claude"
    # Handle is stored without a leading @, and lookups tolerate one.
    assert reg.get("design", "@reviewer") == got


def test_registry_scopes_by_room(isolated_home: Path) -> None:
    reg = HerdrRegistry()
    reg.set(HerdrPaneMapping(room="design", handle="bot", pane="w1:pA"))
    reg.set(HerdrPaneMapping(room="ops", handle="bot", pane="w2:pB"))
    design = reg.get("design", "bot")
    ops = reg.get("ops", "bot")
    assert design is not None and design.pane == "w1:pA"
    assert ops is not None and ops.pane == "w2:pB"
    assert {m.pane for m in reg.all()} == {"w1:pA", "w2:pB"}


def test_registry_remove(isolated_home: Path) -> None:
    reg = HerdrRegistry()
    reg.set(HerdrPaneMapping(room="design", handle="bot", pane="w1:pA"))
    assert reg.remove("design", "bot") is True
    assert reg.get("design", "bot") is None
    assert reg.remove("design", "bot") is False


def test_registry_corrupt_file_reads_empty(isolated_home: Path) -> None:
    reg = HerdrRegistry()
    reg.path.parent.mkdir(parents=True, exist_ok=True)
    reg.path.write_text("}{ not json")
    assert reg.all() == []
    assert reg.get("design", "bot") is None


# ── availability ────────────────────────────────────────────────────────────────


def test_available_false_when_binary_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _: None)
    bridge = HerdrBridge(runner=ScriptedRunner({}))
    assert bridge.binary_present() is False
    assert bridge.available() is False


def test_available_true_when_agent_list_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/herdr")
    runner = ScriptedRunner({"agent list": _proc(_ok({"agents": []}))})
    assert HerdrBridge(runner=runner).available() is True


def test_available_false_when_server_down(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/herdr")
    runner = ScriptedRunner({"agent list": _proc(stderr="connection refused", returncode=1)})
    assert HerdrBridge(runner=runner).available() is False


# ── parsing ─────────────────────────────────────────────────────────────────────


def test_list_agents_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/herdr")
    agents = [{"pane_id": "w2:pV", "agent": "claude", "agent_status": "idle"}]
    runner = ScriptedRunner({"agent list": _proc(_ok({"agents": agents}))})
    assert HerdrBridge(runner=runner).list_agents() == agents


def test_get_agent_none_when_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/herdr")
    runner = ScriptedRunner({"agent get": _proc(_ok({"agent": {}}))})
    assert HerdrBridge(runner=runner).get_agent("w2:pV") is None


def test_server_error_raises_herdr_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/herdr")
    err = json.dumps({"error": {"message": "no such pane"}})
    runner = ScriptedRunner({"agent get": _proc(stderr=err, returncode=1)})
    with pytest.raises(HerdrError, match="no such pane"):
        HerdrBridge(runner=runner)._run_json(["agent", "get", "w9:pZ"])


def test_missing_binary_raises_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _: None)
    with pytest.raises(HerdrUnavailableError):
        HerdrBridge(runner=ScriptedRunner({}))._run_json(["agent", "list"])


# ── wake orchestration ──────────────────────────────────────────────────────────


def _bridge_with(
    monkeypatch: pytest.MonkeyPatch, responses: dict
) -> tuple[HerdrBridge, ScriptedRunner]:
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/herdr")
    runner = ScriptedRunner(responses)
    return HerdrBridge(runner=runner), runner


def test_wake_happy_path(monkeypatch: pytest.MonkeyPatch, isolated_home: Path) -> None:
    bridge, runner = _bridge_with(
        monkeypatch,
        {
            "agent get": _proc(_ok({"agent": {"pane_id": "w2:pV", "agent_status": "idle"}})),
            "agent prompt": _proc(_ok({"agent_status": "idle"})),
        },
    )
    mapping = HerdrPaneMapping(room="design", handle="reviewer", pane="w2:pV")
    result = bridge.wake(mapping, "wake up", timeout_ms=5000)
    assert result.ok is True
    assert result.pane == "w2:pV"
    # The prompt was actually submitted with --wait to the mapped pane.
    prompt_calls = [c for c in runner.calls if c[:2] == ["agent", "prompt"]]
    assert prompt_calls and prompt_calls[0][2] == "w2:pV" and "--wait" in prompt_calls[0]


def test_wake_holds_when_agent_busy(monkeypatch: pytest.MonkeyPatch, isolated_home: Path) -> None:
    bridge, runner = _bridge_with(
        monkeypatch,
        {"agent get": _proc(_ok({"agent": {"pane_id": "w2:pV", "agent_status": "working"}}))},
    )
    result = bridge.wake(
        HerdrPaneMapping(room="design", handle="reviewer", pane="w2:pV"), "wake", timeout_ms=5000
    )
    assert result.ok is False
    assert "working" in result.detail
    # Never prompts a busy agent — the message stays on the cursor.
    assert not [c for c in runner.calls if c[:2] == ["agent", "prompt"]]


def test_wake_fails_soft_on_stale_mapping(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    bridge, _ = _bridge_with(monkeypatch, {"agent get": _proc(_ok({"agent": {}}))})
    result = bridge.wake(
        HerdrPaneMapping(room="design", handle="reviewer", pane="w2:pV"), "wake", timeout_ms=5000
    )
    assert result.ok is False
    assert "stale" in result.detail.lower()


def test_wake_fails_soft_when_prompt_stalls(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    err = json.dumps({"error": {"message": "agent_prompt_stalled"}})
    bridge, _ = _bridge_with(
        monkeypatch,
        {
            "agent get": _proc(_ok({"agent": {"pane_id": "w2:pV", "agent_status": "idle"}})),
            "agent prompt": _proc(stderr=err, returncode=1),
        },
    )
    result = bridge.wake(
        HerdrPaneMapping(room="design", handle="reviewer", pane="w2:pV"), "wake", timeout_ms=5000
    )
    assert result.ok is False
    assert "stalled" in result.detail


# ── wake prompt ─────────────────────────────────────────────────────────────────


def test_build_wake_prompt_mentions_room_handle_and_cycle() -> None:
    p = build_wake_prompt("design", "@reviewer")
    assert "design" in p
    assert "reviewer" in p and "@@" not in p  # leading @ normalized
    assert "mycelium await" in p and "mycelium respond" in p


# ── invoke auto-wake gate ───────────────────────────────────────────────────────


def test_invoke_autowake_gated_off_by_default(isolated_home: Path) -> None:
    """`agent invoke` must not touch herdr unless `herdr.autowake` is on."""
    from mycelium.commands.agent import _try_herdr_wake
    from mycelium.config import MyceliumConfig

    config = MyceliumConfig()  # autowake defaults False
    assert config.herdr.autowake is False
    assert _try_herdr_wake(config, "design", "reviewer") is False


def test_invoke_autowake_on_but_unmapped_returns_false(isolated_home: Path) -> None:
    """Feature on, but no pane mapped → fall back to the cursor (False)."""
    from mycelium.commands.agent import _try_herdr_wake
    from mycelium.config import MyceliumConfig

    config = MyceliumConfig()
    config.herdr.autowake = True
    assert _try_herdr_wake(config, "design", "reviewer") is False
