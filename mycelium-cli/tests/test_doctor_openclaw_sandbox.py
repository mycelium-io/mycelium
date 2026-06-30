# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""`mycelium doctor` agent-sandbox check.

A channel agent can only exec the mycelium CLI when its exec lands on the
gateway host — either because the sandbox is off, or because
``tools.exec.host = 'gateway'`` routes exec out of the sandbox container. The
check must accept *either* fix and only warn when both are absent.
"""

from __future__ import annotations

import json

import pytest

from mycelium.commands.doctor import _check_openclaw_agent_sandbox


def _setup(monkeypatch, tmp_path, agents_list) -> None:
    state = tmp_path / ".openclaw"
    state.mkdir()
    (state / "openclaw.json").write_text(
        json.dumps(
            {
                "channels": {"mycelium-room": {"agents": [a["id"] for a in agents_list]}},
                "agents": {"list": agents_list},
            }
        )
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("mycelium.commands.doctor._openclaw_adapter_registered", lambda: True)


def test_sandboxed_agent_without_either_fix_warns(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup(monkeypatch, tmp_path, [{"id": "lawyer-a", "sandbox": {"mode": "all"}}])
    result = _check_openclaw_agent_sandbox()
    assert result.status == "warning"
    assert any("lawyer-a" in d for d in result.details)


def test_exec_host_gateway_is_accepted(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Sandbox on, but exec routed to the gateway → the CLI works → green."""
    _setup(
        monkeypatch,
        tmp_path,
        [{"id": "lawyer-a", "sandbox": {"mode": "all"}, "tools": {"exec": {"host": "gateway"}}}],
    )
    assert _check_openclaw_agent_sandbox().status == "ok"


def test_sandbox_off_is_accepted(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup(monkeypatch, tmp_path, [{"id": "lawyer-a", "sandbox": {"mode": "off"}}])
    assert _check_openclaw_agent_sandbox().status == "ok"


def test_null_exec_tools_does_not_crash(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A hand-edited `exec: null` must be treated as 'no gateway routing', not
    raise — the agent is still sandboxed, so it warns."""
    _setup(
        monkeypatch,
        tmp_path,
        [{"id": "lawyer-a", "sandbox": {"mode": "all"}, "tools": {"exec": None}}],
    )
    result = _check_openclaw_agent_sandbox()
    assert result.status == "warning"
    assert any("lawyer-a" in d for d in result.details)
