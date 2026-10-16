# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

from __future__ import annotations

from pathlib import Path

import pytest

from mycelium import old_daemon

_PLIST = """<plist><dict>
<key>Label</key><string>io.mycelium.cc-daemon</string>
<key>ProgramArguments</key><array>
<string>/x/.venv/bin/python3</string><string>-m</string><string>mycelium.daemon</string>
</array></dict></plist>
"""


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    ran: list[list[str]] = []
    monkeypatch.setattr(old_daemon, "_run", ran.append)
    monkeypatch.setattr(old_daemon.shutil, "which", lambda name: f"/bin/{name}")
    return ran


def test_removes_the_old_launchd_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, calls: list[list[str]]
) -> None:
    monkeypatch.setattr(old_daemon.sys, "platform", "darwin")
    agents = tmp_path / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    (agents / "io.mycelium.cc-daemon.plist").write_text(_PLIST)

    assert old_daemon.remove_old_daemon(tmp_path) == ["io.mycelium.cc-daemon"]
    assert not (agents / "io.mycelium.cc-daemon.plist").exists()
    assert calls and calls[0][:2] == ["launchctl", "bootout"]
    # Nothing left to do the second time.
    assert old_daemon.remove_old_daemon(tmp_path) == []


def test_leaves_a_job_under_that_name_that_runs_something_else(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, calls: list[list[str]]
) -> None:
    monkeypatch.setattr(old_daemon.sys, "platform", "darwin")
    agents = tmp_path / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    mine = agents / "io.mycelium.daemon.plist"
    mine.write_text("<plist><string>/usr/local/bin/my-own-thing</string></plist>")

    assert old_daemon.remove_old_daemon(tmp_path) == []
    assert mine.exists() and calls == []


def test_removes_the_old_systemd_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, calls: list[list[str]]
) -> None:
    monkeypatch.setattr(old_daemon.sys, "platform", "linux")
    units = tmp_path / ".config" / "systemd" / "user"
    units.mkdir(parents=True)
    (units / "mycelium-daemon.service").write_text(
        "[Service]\nExecStart=/x/python -m mycelium.daemon\n"
    )

    assert old_daemon.remove_old_daemon(tmp_path) == ["mycelium-daemon.service"]
    assert not (units / "mycelium-daemon.service").exists()
    assert ["systemctl", "--user", "disable", "--now", "mycelium-daemon.service"] in calls
