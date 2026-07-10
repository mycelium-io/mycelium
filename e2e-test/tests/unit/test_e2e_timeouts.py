"""Unit tests for E2E timeout helpers."""

from __future__ import annotations

import os

from jobs._common import get_agent_idle_wait


def test_get_agent_idle_wait_from_env(monkeypatch):
    monkeypatch.setenv("MYCELIUM_E2E_AGENT_IDLE_WAIT", "42")
    assert get_agent_idle_wait() == 42


def test_get_agent_idle_wait_from_datafile(monkeypatch):
    monkeypatch.delenv("MYCELIUM_E2E_AGENT_IDLE_WAIT", raising=False)
    path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "..",
        "data",
        "scenarios_datafile.yaml",
    )
    assert get_agent_idle_wait(os.path.abspath(path)) == 20
