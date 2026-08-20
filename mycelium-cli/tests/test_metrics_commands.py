# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for ``mycelium metrics`` helpers.

Node-free: ``metrics status`` aggregates docker/prometheus/collector state (its
own integration surface), so these pin the pure, deterministic helpers — the
add-pricing spec parser, the MAS-id formatter, and the collector-PID reader — that
back the command without a live stack.
"""

from __future__ import annotations

import pytest

from mycelium.commands import metrics as metrics_cmd


def test_parse_add_spec_pattern_and_key() -> None:
    assert metrics_cmd._parse_add_spec("gpt-4o:openai/gpt-4o") == {
        "pattern": "gpt-4o",
        "provider": "",
        "litellm_key": "openai/gpt-4o",
    }


def test_parse_add_spec_bare_key_doubles_as_pattern() -> None:
    assert metrics_cmd._parse_add_spec("claude-sonnet-4-6") == {
        "pattern": "claude-sonnet-4-6",
        "provider": "",
        "litellm_key": "claude-sonnet-4-6",
    }


def test_format_mas_shortens_by_default_and_full_on_detail() -> None:
    mas = "0123456789abcdef0123456789abcdef"
    assert metrics_cmd._format_mas(mas) == "01234567"  # narrow column
    assert metrics_cmd._format_mas(mas, detail=True) == mas
    assert metrics_cmd._format_mas("") == ""


def test_read_collector_pid_returns_running_pid(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    import os

    pid_file = tmp_path / "collector.pid"
    pid_file.write_text(str(os.getpid()))
    monkeypatch.setattr(metrics_cmd, "_collector_pid_file", lambda: pid_file)
    assert metrics_cmd._read_collector_pid() == os.getpid()


def test_read_collector_pid_none_when_missing(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(metrics_cmd, "_collector_pid_file", lambda: tmp_path / "absent.pid")
    assert metrics_cmd._read_collector_pid() is None


def test_read_collector_pid_prunes_dead_pid(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    pid_file = tmp_path / "collector.pid"
    pid_file.write_text("999999999")
    monkeypatch.setattr(metrics_cmd, "_collector_pid_file", lambda: pid_file)
    assert metrics_cmd._read_collector_pid() is None
    assert not pid_file.exists()
