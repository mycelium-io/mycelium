# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The desktop app's Widgets: ``[statusline]`` in this computer's config file,
run here on each widget's interval. Real commands for the runs; a fake one,
and a fake clock, for the schedule."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from mycelium.config import MyceliumConfig, StatuslineConfig, StatusWidget
from mycelium.desktop import widgets as w
from mycelium.docker_utils import LOCAL_ONLY_FIELDS

posix = pytest.mark.skipif(sys.platform == "win32", reason="the commands are POSIX shell")


def test_a_widget_is_a_command_on_an_interval_or_fixed_text():
    run = StatusWidget(label="RAM free", command="echo 38%", every="30s", meter=True)
    assert (run.seconds(), run.timeout, run.icon) == (30.0, 10.0, "text")
    assert StatusWidget(label="hub", text="Mac mini").command is None
    assert StatusWidget(label="ci", command="x", every="2m").seconds() == 120.0
    for bad in (
        {"label": "both", "command": "x", "text": "y"},
        {"label": "neither"},
        {"label": "when", "command": "x", "every": "soon"},
        {"label": "icon", "command": "x", "icon": "rocket"},
        {"label": "slow", "command": "x", "timeout": 0},
    ):
        with pytest.raises(ValidationError):
            StatusWidget.model_validate(bad)


def test_a_widget_runs_at_most_every_five_seconds():
    """`0s` would run it on every tick of the supervisor, twice a second."""
    assert StatusWidget(label="x", command="x", every="5s").seconds() == 5.0
    for too_often in ("0s", "4s"):
        with pytest.raises(ValidationError, match="every must be at least 5s"):
            StatusWidget(label="x", command="x", every=too_often)


def test_the_section_is_read_from_config_toml_and_never_reaches_the_stack():
    config = MyceliumConfig.model_validate(
        {"statusline": {"widget": [{"label": "disk free", "command": "df -h /", "every": "5m"}]}}
    )
    assert [x.label for x in config.statusline.widget] == ["disk free"]
    assert StatuslineConfig().widget == []
    # Only the desktop app reads it, on this computer: never rendered into .env.
    assert "statusline.widget" in LOCAL_ONLY_FIELDS


@posix
def test_a_run_shows_the_first_line_printed():
    run = w.run_command("printf '\\n38%%\\nmore\\n'", 5)
    assert (run.ok, run.value, run.exit) == (True, "38%", 0)


@posix
def test_a_failing_command_says_how_it_exited_and_its_first_error_line():
    run = w.run_command("echo 'gh: please run gh auth login' >&2; exit 4", 5)
    assert (run.ok, run.exit, run.timed_out) == (False, 4, False)
    assert run.error == "gh: please run gh auth login"


@posix
def test_a_hung_command_is_stopped_with_what_it_started(tmp_path: Path):
    marker = tmp_path / "still-running"
    started = time.monotonic()
    run = w.run_command(f"sleep 0.6 && touch {marker} & sleep 30", 0.2)
    assert (run.ok, run.timed_out) == (False, True)
    assert time.monotonic() - started < 5
    # The whole group was stopped, so what it left in the background never finishes.
    time.sleep(1)
    assert not marker.exists()


def _config(path: Path, body: str) -> Path:
    path.write_text(body)
    return path


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _settle(widgets: w.Widgets) -> None:
    deadline = time.monotonic() + 5
    while widgets._running and time.monotonic() < deadline:
        time.sleep(0.01)


def test_each_widget_runs_on_its_own_interval_and_text_never_runs(tmp_path: Path):
    path = _config(
        tmp_path / "config.toml",
        '[[statusline.widget]]\nlabel = "fast"\ncommand = "a"\nevery = "30s"\n\n'
        '[[statusline.widget]]\nlabel = "slow"\ncommand = "b"\nevery = "5m"\n\n'
        '[[statusline.widget]]\nlabel = "hub"\ntext = "Mac mini"\n',
    )
    ran: list[str] = []
    clock = Clock()
    widgets = w.Widgets(
        path, run=lambda cmd, _t: ran.append(cmd) or w.Run(ok=True, value=cmd), clock=clock
    )

    assert widgets.tick()
    _settle(widgets)
    assert sorted(ran) == ["a", "b"]
    clock.now += 31
    widgets.tick()
    _settle(widgets)
    assert sorted(ran) == ["a", "a", "b"]  # only the 30s one is due again
    snap = widgets.snapshot()
    assert snap["type"] == "widgets"
    assert snap["config"] == str(path)
    assert [x["run"]["value"] if x["run"] else None for x in snap["widgets"]] == ["a", "b", None]
    assert snap["widgets"][2]["text"] == "Mac mini"


def test_an_edited_file_is_read_again_and_a_bad_one_runs_nothing(tmp_path: Path):
    path = _config(tmp_path / "config.toml", '[[statusline.widget]]\nlabel = "x"\ncommand = "a"\n')
    ran: list[str] = []
    widgets = w.Widgets(path, run=lambda cmd, _t: ran.append(cmd) or w.Run(ok=True), clock=Clock())
    widgets.tick()
    _settle(widgets)
    assert [x["label"] for x in widgets.snapshot()["widgets"]] == ["x"]

    _config(path, '[[statusline.widget]]\nlabel = "y"\ntext = "hello"\n')
    import os

    os.utime(path, (time.time() + 5, time.time() + 5))
    assert widgets.tick()
    assert [x["label"] for x in widgets.snapshot()["widgets"]] == ["y"]

    _config(path, '[[statusline.widget]]\nlabel = "z"\ncommand = "a"\ntext = "b"\n')
    os.utime(path, (time.time() + 10, time.time() + 10))
    ran.clear()
    widgets.tick()
    snap = widgets.snapshot()
    assert snap["widgets"] == []
    assert "isn't valid" in snap["error"]
    assert ran == []


def test_no_config_means_no_widgets_and_nothing_runs(tmp_path: Path):
    widgets = w.Widgets(tmp_path / "missing.toml", run=lambda *_: pytest.fail("ran"), clock=Clock())
    widgets.tick()
    assert widgets.snapshot()["widgets"] == []
    assert widgets.snapshot()["error"] is None
