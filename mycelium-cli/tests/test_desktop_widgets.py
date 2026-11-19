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
    assert (run.seconds(), run.timeout, run.icon, run.meter) == (30.0, 10.0, None, True)
    assert StatusWidget(label="hub", text="Mac mini").command is None
    assert StatusWidget(label="ci", command="x", every="2m").seconds() == 120.0
    for bad in (
        {"label": "both", "command": "x", "text": "y"},
        {"label": "neither"},
        {"label": "when", "command": "x", "every": "soon"},
        {"label": "slow", "command": "x", "timeout": 0},
    ):
        with pytest.raises(ValidationError):
            StatusWidget.model_validate(bad)


def test_a_widget_sets_its_look_and_a_bad_field_is_only_noted():
    good = StatusWidget(
        label="RAM",
        command="x",
        icon="memory-stick",
        color="accent",
        state="warn",
        meter=38,
        tooltip="Swap is *2.1G*",
    )
    assert (good.icon, good.color, good.state, good.meter) == (
        "memory-stick",
        "accent",
        "warn",
        38.0,
    )
    assert good.notes == []
    assert StatusWidget(label="mood", text="fine", icon="🚀").icon == "🚀"

    bad = StatusWidget(
        label="RAM",
        command="x",
        icon="Memory Stick",
        color="#ff0000",
        state="great",
        meter=140,
        tooltip="kept",
    )
    # The widget stands, with the fields that were right.
    assert (bad.icon, bad.color, bad.state, bad.meter, bad.tooltip) == (
        None,
        None,
        None,
        None,
        "kept",
    )
    assert [n.split(" ", 1)[0] for n in bad.notes] == ["icon", "color", "state", "meter"]
    assert "one of accent, green, yellow, red, muted" in bad.notes[1]


def test_a_tooltip_keeps_a_few_lines():
    long = "\n".join(f"line {i}" for i in range(20))
    assert (StatusWidget(label="x", text="y", tooltip=long).tooltip or "").count("\n") == 7


def test_a_run_that_prints_json_sets_its_fields_for_that_run():
    run = w.read_output(
        '{"text": "**38%** free\\nsecond", "icon": "memory-stick", "color": "yellow",'
        ' "state": "warn", "meter": 38, "tooltip": "Swap is *2.1G*"}\n'
    )
    assert (run.ok, run.value) == (True, "**38%** free")
    assert run.fields == {
        "icon": "memory-stick",
        "color": "yellow",
        "state": "warn",
        "meter": 38.0,
        "tooltip": "Swap is *2.1G*",
    }
    assert run.notes == []


def test_a_bad_field_in_a_runs_json_is_noted_and_the_rest_shows():
    run = w.read_output('{"text": "up", "color": "#0f0", "meter": "38", "colour": "red"}')
    assert (run.value, run.fields) == ("up", {})
    assert len(run.notes) == 3
    assert "colour isn't a widget field" in run.notes[2]


def test_output_that_isnt_one_json_object_is_plain_text():
    assert w.read_output("[1, 2]\n").value == "[1, 2]"
    assert w.read_output("38%\n").fields == {}
    # A raw newline inside a JSON string is the easy way to get it wrong: shown as
    # it printed, and Settings says why it wasn't read.
    broken = w.read_output('{"text": "up",\n"tooltip": "two\nlines"}\n')
    assert (broken.ok, broken.value, broken.fields) == (True, '{"text": "up",', {})
    assert "starts like JSON but isn't" in broken.notes[0]


def test_a_widget_runs_at_most_every_five_seconds():
    """`0s` would run it on every tick of the supervisor, twice a second."""
    assert StatusWidget(label="x", command="x", every="5s").seconds() == 5.0
    for too_often in ("0s", "4s"):
        with pytest.raises(ValidationError, match="every must be at least 5s"):
            StatusWidget(label="x", command="x", every=too_often)


def test_the_section_is_kept_in_config_toml_and_never_reaches_the_stack():
    row = {"label": "disk free", "command": "df -h /", "every": "5m"}
    config = MyceliumConfig.model_validate({"statusline": {"widget": [row]}})
    assert config.statusline.widget == [row]
    assert StatuslineConfig().widget == []
    # Only the desktop app reads it, on this computer: never rendered into .env.
    assert "statusline.widget" in LOCAL_ONLY_FIELDS


def test_a_bad_widget_stops_only_the_widgets_never_the_cli(tmp_path: Path, monkeypatch):
    """A typo in a status readout must not stop `await`, `respond` or the runner."""
    home = tmp_path / "home"
    (home / ".mycelium").mkdir(parents=True)
    path = home / ".mycelium" / "config.toml"
    path.write_text('[[statusline.widget]]\nlabel = "busy"\ncommand = "a"\nevery = "4s"\n')
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)

    config = MyceliumConfig.load()
    assert config.statusline.widget == [{"label": "busy", "command": "a", "every": "4s"}]

    widgets = w.Widgets(path, run=lambda *_: pytest.fail("ran"), clock=Clock())
    widgets.tick()
    snap = widgets.snapshot()
    assert snap["widgets"] == []
    assert "every must be at least 5s" in snap["error"]


@pytest.mark.parametrize("body", ['statusline = "x"\n', '[statusline]\nwidget = "x"\n'])
def test_a_section_of_the_wrong_shape_stops_only_the_widgets(
    tmp_path: Path, monkeypatch, body: str
):
    home = tmp_path / "home"
    (home / ".mycelium").mkdir(parents=True)
    path = home / ".mycelium" / "config.toml"
    path.write_text(body)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)

    assert MyceliumConfig.load().statusline.widget == "x"
    widgets = w.Widgets(path, run=lambda *_: pytest.fail("ran"), clock=Clock())
    widgets.tick()
    assert widgets.snapshot()["widgets"] == []
    assert "isn't valid" in widgets.snapshot()["error"]


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
        path, run=lambda cmd, _t, _env: ran.append(cmd) or w.Run(ok=True, value=cmd), clock=clock
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
    widgets = w.Widgets(
        path, run=lambda cmd, _t, _env: ran.append(cmd) or w.Run(ok=True), clock=Clock()
    )
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


def test_a_widget_can_be_kept_running_instead_of_run_on_an_interval():
    kept = StatusWidget(label="box", command="ssh -N box", every="always")
    assert kept.always()
    assert not StatusWidget(label="ci", command="x", every="5m").always()
    for bad in ("Always", "always 5s", "forever"):
        with pytest.raises(ValidationError):
            StatusWidget(label="x", command="x", every=bad)


@posix
def test_every_command_is_given_the_hub_s_port(tmp_path: Path):
    path = _config(
        tmp_path / "config.toml",
        '[[statusline.widget]]\nlabel = "port"\ncommand = "echo $MYCELIUM_HUB_PORT"\n',
    )
    widgets = w.Widgets(path, clock=Clock())
    widgets.hub_port = 3718
    widgets.tick()
    _settle(widgets)
    assert widgets.snapshot()["widgets"][0]["run"]["value"] == "3718"


KEEP = '[[statusline.widget]]\nlabel = "box"\ncommand = "{}"\nevery = "always"\n'


def _until(check, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not check():
        assert time.monotonic() < deadline, "never happened"
        time.sleep(0.02)


def _run_of(widgets: w.Widgets) -> dict:
    return widgets.snapshot()["widgets"][0]["run"]


def _alive(pid: int) -> bool:
    import os

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A child that exited but isn't reaped yet counts as gone.
    import subprocess

    state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    return bool(state.stdout.strip()) and not state.stdout.strip().startswith("Z")


@posix
def test_a_command_kept_running_shows_its_last_line_and_starts_again_after_a_wait(
    tmp_path: Path,
):
    # The command holds at its first line until the test has seen it, so how
    # fast the machine runs doesn't decide which line the test finds.
    go = tmp_path / "go"
    path = _config(
        tmp_path / "config.toml",
        KEEP.format(
            f"echo starting; echo 'Warning: slow' >&2; "
            f"while [ ! -e '{go}' ]; do sleep 0.02; done; "
            "echo 'connection refused' >&2; exit 3"
        ),
    )
    clock = Clock()
    widgets = w.Widgets(path, clock=clock)
    try:
        assert widgets.tick()
        # What it says on stderr while it runs is its last line too.
        _until(lambda: _run_of(widgets)["value"] == "Warning: slow")
        assert _run_of(widgets)["running"] is True

        # It exits: the row says how and why, and it waits a second to start again.
        go.touch()
        _until(lambda: widgets._kept[0].proc.poll() is not None)
        widgets.tick()
        run = _run_of(widgets)
        assert (run["running"], run["ok"], run["exit"], run["error"]) == (
            False,
            False,
            3,
            "connection refused",
        )
        clock.now += 0.5
        widgets.tick()
        assert not widgets._kept
        clock.now += 0.6
        widgets.tick()
        assert _run_of(widgets)["running"] is True

        # Exiting quickly again doubles the wait.
        _until(lambda: widgets._kept[0].proc.poll() is not None)
        widgets.tick()
        assert widgets._restart_at[0] - clock.now == pytest.approx(2.0)
    finally:
        widgets.stop()


@posix
def test_one_that_ran_steadily_waits_only_the_first_wait():
    widgets = w.Widgets(Path("/nonexistent/config.toml"), clock=Clock())
    widgets._wait[0] = 32.0
    widgets._stopped(0, 1000.0, ran_for=w.STEADY_S)
    assert widgets._wait[0] == w.RESTART_FIRST_S
    for _ in range(10):
        widgets._stopped(0, 1000.0, ran_for=1)
    assert widgets._wait[0] == w.RESTART_MOST_S


@posix
def test_a_command_kept_running_is_started_again_when_the_hub_moves(tmp_path: Path):
    path = _config(tmp_path / "config.toml", KEEP.format("echo $MYCELIUM_HUB_PORT; sleep 30"))
    widgets = w.Widgets(path, clock=Clock())
    try:
        widgets.hub_port = 3718
        widgets.tick()
        _until(lambda: _run_of(widgets)["value"] == "3718")
        first = widgets._kept[0].proc.pid

        widgets.hub_port = 51206
        widgets.tick()
        _until(lambda: _run_of(widgets)["value"] == "51206")
        assert widgets._kept[0].proc.pid != first
        assert not _alive(first)
    finally:
        widgets.stop()


@posix
def test_stopping_the_app_stops_it_with_what_it_started(tmp_path: Path):
    child = tmp_path / "child.pid"
    path = _config(tmp_path / "config.toml", KEEP.format(f"sleep 30 & echo $! > {child}; wait"))
    widgets = w.Widgets(path, clock=Clock())
    widgets.tick()
    _until(child.exists)
    _until(lambda: child.read_text().strip() != "")
    pid, sleeper = widgets._kept[0].proc.pid, int(child.read_text())
    widgets.stop()
    assert not _alive(pid)
    assert not _alive(sleeper)
    assert not widgets.kept_path.exists()


@posix
def test_a_changed_widget_stops_its_old_command(tmp_path: Path):
    import os

    path = _config(tmp_path / "config.toml", KEEP.format("sleep 30"))
    widgets = w.Widgets(path, clock=Clock())
    try:
        widgets.tick()
        old = widgets._kept[0].proc.pid
        _config(path, KEEP.format("sleep 31"))
        os.utime(path, (time.time() + 5, time.time() + 5))
        widgets.tick()
        assert not _alive(old)
        assert widgets._kept[0].proc.pid != old
    finally:
        widgets.stop()


@posix
def test_what_an_app_that_was_killed_kept_running_is_stopped_by_the_next(tmp_path: Path):
    import subprocess

    # `exec`, since only some shells become the command on their own.
    path = _config(tmp_path / "config.toml", KEEP.format("exec sleep 30"))
    clock = Clock()
    first = w.Widgets(path, clock=clock)
    first.tick()
    left = first._kept[0].proc.pid
    # The clock here is fake: wait for the shell to become the command for real.
    from mycelium.desktop.supervisor import command_of

    _until(lambda: command_of(left) == "sleep 30")
    clock.now += w.SEEN_AFTER_S
    first.tick()  # its command line is written down
    assert first.kept_path.exists()

    # Another program on a pid written down, with a different command line, is left alone.
    other = subprocess.Popen(["sleep", "29"])
    entries = __import__("json").loads(first.kept_path.read_text())["kept"]
    entries.append({"pid": other.pid, "command": "sleep 30"})
    first.kept_path.write_text(__import__("json").dumps({"kept": entries}))
    try:
        # The app ends without stopping it: the next run stops it before starting its own.
        second = w.Widgets(path, clock=Clock())
        second.tick()
        _until(lambda: not _alive(left))
        assert _alive(other.pid)
        assert second._kept[0].proc.pid != left
        second.stop()
    finally:
        other.kill()
        first._kept[0].proc.wait(5)


def test_no_config_means_no_widgets_and_nothing_runs(tmp_path: Path):
    widgets = w.Widgets(tmp_path / "missing.toml", run=lambda *_: pytest.fail("ran"), clock=Clock())
    widgets.tick()
    assert widgets.snapshot()["widgets"] == []
    assert widgets.snapshot()["error"] is None
