# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium desktop serve``: the supervisor under the desktop app.

Real child processes (tiny Python scripts), no hub: these hold the order a
hub's components start in, that a crash is restarted and a component that
keeps crashing is left failed, that a port something else answers on counts
as running, that a missing program says what to install, what client mode
runs, where programs are found, and that stopping stops the children.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from mycelium.desktop import supervisor as sv
from mycelium.desktop.supervisor import Component, LocateError, Locator, Supervisor

SLEEP = [sys.executable, "-c", "import time; time.sleep(60)"]
EXIT = [sys.executable, "-c", "raise SystemExit(3)"]


@pytest.fixture(autouse=True)
def _fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sv, "TICK_S", 0.02)
    monkeypatch.setattr(sv, "BACKOFF_S", (0.01, 0.01, 0.01))
    monkeypatch.setattr(sv, "MAX_RESTARTS", 3)


class Events:
    def __init__(self) -> None:
        self.all: list[dict[str, Any]] = []

    def __call__(self, event: dict[str, Any]) -> None:
        self.all.append(event)

    def statuses(self) -> list[dict[str, Any]]:
        return [e for e in self.all if e["type"] == "status"]

    def state(self, name: str) -> str:
        return self.statuses()[-1]["components"][name]["state"]


def hub(events: Events, components: list[Component], **kw: Any) -> Supervisor:
    kw.setdefault("look", list)
    sup = Supervisor(
        "hub", emit=events, env={}, start_runner=False, locator=Locator(None, None), **kw
    )
    sup.components = components
    return sup


def run_until(sup: Supervisor, done, timeout: float = 10.0) -> None:
    thread = threading.Thread(target=sup.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + timeout
    reached = False
    while time.monotonic() < deadline and not (reached := done()):
        time.sleep(0.02)
    sup.stop()
    thread.join(timeout=10)
    assert reached, "condition not reached"


def comp(name: str, argv: list[str], ready=lambda: True, **kw: Any) -> Component:
    return Component(name=name, argv=lambda: (argv, None), ready=ready, **kw)


def test_each_component_waits_for_the_one_before_it():
    events = Events()
    gate = threading.Event()
    first = comp("slim", SLEEP, ready=gate.is_set)
    second = comp("hub", SLEEP)
    sup = hub(events, [first, second])

    def check() -> bool:
        if first.state == "starting" and not gate.is_set():
            assert second.proc is None  # not started while the first is not up
            gate.set()
        return second.state == "running"

    run_until(sup, check)
    order = [
        (s["components"]["slim"]["state"], s["components"]["hub"]["state"])
        for s in events.statuses()
    ]
    assert ("starting", "stopped") in order
    assert order.index(("running", "stopped")) < order.index(("running", "starting"))


def test_a_crash_is_restarted_and_one_that_keeps_crashing_is_left_failed():
    events = Events()
    crashing = comp("slim", EXIT, ready=lambda: False)
    run_until(hub(events, [crashing]), lambda: crashing.state == "failed")
    details = [s["components"]["slim"]["detail"] or "" for s in events.statuses()]
    assert any("starting again" in d for d in details)
    assert "keeps exiting (last time it exited with code 3)" in details[-1]
    # Each exit is in the log as a line of its own, before it's started again.
    said = [e["line"] for e in events.all if e["type"] == "log" and e.get("component") == "slim"]
    assert "slim exited with code 3" in said


def test_a_program_killed_by_a_signal_says_which():
    assert sv.how_it_exited(-9) == "was stopped by SIGKILL"
    assert sv.how_it_exited(-15) == "was stopped by SIGTERM"
    assert sv.how_it_exited(1) == "exited with code 1"
    assert sv.how_it_exited(-999) == "was stopped by signal 999"


def test_a_crash_says_what_the_program_said():
    # A UI missing a dependency exits at once; the reason is in its output,
    # and the status carries it where the app shows it.
    events = Events()
    noisy = comp(
        "ui",
        [
            sys.executable,
            "-c",
            "print('booting'); print(\"Error: Cannot find module 'next'\"); raise SystemExit(1)",
        ],
        ready=lambda: False,
    )
    run_until(hub(events, [noisy]), lambda: noisy.state == "failed")
    assert "Cannot find module 'next'" in (noisy.detail or "")


def test_something_already_on_the_port_counts_as_running():
    events = Events()
    outside = comp("hub", EXIT, external=lambda: True)
    run_until(hub(events, [outside]), lambda: outside.state == "running")
    assert outside.proc is None
    assert "not started by the app" in (outside.detail or "")


def _eval_stack() -> Any:
    from mycelium.hubs import Hub

    return Hub(
        source="docker",
        port=sv.HUB_PORT,
        version="3.0.12",
        image="mycelium-backend:dev",
        project="mycelium-concord-eval",
        data_path="/Users/julia/.mycelium-concord-eval",
        answering=True,
    )


def test_a_hub_the_app_did_not_start_is_used_and_reported_never_stopped():
    # Whose it is, its version and its data folder go in the status for the
    # app to show; nothing waits on the person, and the other hub keeps running.
    events = Events()
    outside = comp("hub", EXIT, external=lambda: True)
    sup = hub(events, [outside], look=lambda: [_eval_stack()])
    run_until(sup, lambda: outside.state == "running")
    other = events.statuses()[-1]["existing_hub"]
    assert other["project"] == "mycelium-concord-eval"
    assert other["data_path"] == "/Users/julia/.mycelium-concord-eval"
    assert other["same_store"] is False
    assert "question" not in events.statuses()[-1]
    assert outside.detail == f"another hub on port {sv.HUB_PORT}"
    assert any(e["type"] == "warning" and "development build" in e["message"] for e in events.all)


def _alive(pid: int) -> bool:
    import os

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _program(tmp_path: Path, name: str) -> list[str]:
    """A stand-in program at its own path, so its command line names it."""
    script = tmp_path / name
    script.write_text("import time\ntime.sleep(60)\n")
    return [sys.executable, str(script)]


@pytest.mark.skipif(sys.platform == "win32", reason="process groups are POSIX")
def test_a_pid_that_leads_no_group_is_still_stopped(tmp_path: Path):
    """A program started without a session of its own: its group is this one's,
    so signalling a group named by its pid finds none, and it is signalled alone."""
    import subprocess

    other = subprocess.Popen(_program(tmp_path, "no-session.py"))
    try:
        sv.stop_pid(other.pid, grace_s=2)
        assert other.wait(timeout=5) is not None
    finally:
        other.kill()


def test_what_an_earlier_run_left_running_is_stopped_and_started_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The app updated itself in place: its supervisor went, its hub didn't.
    The next supervisor stops that hub, as the app's own, and starts a new one."""
    started = tmp_path / "started.json"
    events = Events()
    old = comp("hub", SLEEP)
    before = hub(events, [old], started_path=started)
    # Gone without stopping anything, as an update leaves it.
    monkeypatch.setattr(before, "_shutdown", lambda: None)
    run_until(before, lambda: old.state == "running")
    assert old.proc is not None
    leftover, left = old.proc, old.proc.pid
    assert json.loads(started.read_text())["hub"]["pid"] == left
    assert leftover.poll() is None

    events = Events()
    new = comp("hub", SLEEP)
    run_until(hub(events, [new], started_path=started), lambda: new.state == "running")
    # Stopped (and reaped here, since this test started it).
    assert leftover.wait(timeout=5) is not None
    assert any(f"pid {left}" in str(e.get("line")) for e in events.all)


def test_a_pid_now_running_something_else_is_never_stopped(tmp_path: Path):
    import subprocess

    other = subprocess.Popen(_program(tmp_path, "someone-elses.py"))
    try:
        started = tmp_path / "started.json"
        # Written down for a program that isn't what that pid runs now.
        started.write_text(json.dumps({"hub": {"pid": other.pid, "program": "/gone/mycelium-hub"}}))
        events = Events()
        new = comp("hub", SLEEP)
        run_until(hub(events, [new], started_path=started), lambda: new.state == "running")
        assert other.poll() is None
    finally:
        other.kill()
        other.wait()


def test_a_hub_running_the_apps_own_program_is_stopped_not_adopted(tmp_path: Path):
    """From a version that wrote nothing down: the hub on the port runs the app's
    own hub program, so it's the app's, from before the update."""
    import subprocess

    from mycelium.hubs import Hub

    argv = _program(tmp_path, "mycelium-hub")
    old = subprocess.Popen(argv, start_new_session=True)
    try:
        there = Hub(
            source="process", port=sv.HUB_PORT, version="3.0.58", pid=old.pid, answering=True
        )

        class _App(Locator):
            def app_hub(self) -> Path | None:
                return Path(argv[1])

        events = Events()
        new = comp("hub", SLEEP, external=lambda: old.poll() is None)
        sup = hub(
            events,
            [new],
            look=lambda: [there] if old.poll() is None else [],
            started_path=tmp_path / "started.json",
        )
        sup.locator = _App(None, None)
        run_until(sup, lambda: new.state == "running" and new.proc is not None)
        assert old.wait(timeout=5) is not None
        assert sup.adopted_hub is None
        assert any("version 3.0.58" in str(e.get("line")) for e in events.all)
    finally:
        if old.poll() is None:
            old.kill()


def test_the_app_starts_no_second_runner_beside_one_from_a_terminal(isolated_home: Path):
    import os

    from mycelium.runner.daemon import runner_dir

    (runner_dir() / "runner.pid").write_text(f"{os.getppid()}\n")  # another process, alive
    events = Events()
    sup = Supervisor("client", hub_url="https://hub.example.com", emit=events, env={})
    sup._start_runner()
    assert sup.runner is None
    assert sup.runner_state == "stopped"
    assert str(os.getppid()) in (sup.runner_detail or "")


def test_the_runner_trusts_only_a_hub_the_app_started():
    # A hub the app started listens on 127.0.0.1 alone, so a launch from it
    # needs no question. One that was already there (Docker publishes to the
    # network) or a hub elsewhere could be reached by anyone.
    events = Events()
    started = comp("hub", SLEEP)
    sup = hub(events, [started])
    run_until(sup, lambda: started.state == "running" and sup._own_hub())

    outside = comp("hub", EXIT, external=lambda: True)
    sup = hub(events, [outside])
    run_until(sup, lambda: outside.state == "running")
    assert not sup._own_hub()

    client = Supervisor("client", hub_url="https://hub.example.com", emit=events, env={})
    assert not client._own_hub()


def test_a_runner_the_hub_refuses_shows_as_a_sign_in_not_as_connecting():
    from types import SimpleNamespace

    sup = Supervisor("client", hub_url="https://hub.example.com", emit=Events(), env={})
    sup.runner = SimpleNamespace(connected=False, signed_out=True, herdr=True)  # type: ignore[assignment]
    sup._tick_runner()
    assert sup.runner_state == "failed"
    assert "isn't signed in to https://hub.example.com" in (sup.runner_detail or "")
    assert "`mycelium login`" in (sup.runner_detail or "")
    # Signing in clears it on the next heartbeat.
    sup.runner = SimpleNamespace(connected=True, signed_out=False, herdr=True)  # type: ignore[assignment]
    sup._tick_runner()
    assert (sup.runner_state, sup.runner_detail) == ("running", None)


def test_a_missing_program_says_what_to_install():
    def missing() -> tuple[list[str], Path | None]:
        raise LocateError("slimctl isn't installed")

    events = Events()
    absent = Component(name="slim", argv=missing, ready=lambda: True)
    run_until(hub(events, [absent]), lambda: absent.state == "failed")
    assert {
        "type": "error",
        "component": "slim",
        "message": "slimctl isn't installed",
    } in events.all


def test_stopping_stops_the_children():
    events = Events()
    running = comp("slim", SLEEP)
    sup = hub(events, [running])
    run_until(sup, lambda: running.state == "running")
    assert running.proc is None  # terminated and let go
    assert events.state("slim") == "stopped"


def test_client_mode_runs_herdr_the_ui_and_the_runner_against_the_hub():
    events = Events()
    sup = Supervisor(
        "client",
        hub_url="https://hub.example.com/",
        emit=events,
        env={},
        start_runner=False,
        ui_token="launch-token",
    )
    status = sup.status()
    # The window shows this machine's own UI, which talks to the hub; never
    # the hub's own pages.
    assert status["api_url"] == "https://hub.example.com"
    assert status["ui_url"] == "http://127.0.0.1:3717"
    assert {k: v["state"] for k, v in status["components"].items()} == {
        "herdr": "stopped",
        "slim": "disabled",
        "hub": "disabled",
        "ui": "stopped",
        "runner": "stopped",
    }
    ui = next(c for c in sup.components if c.name == "ui")
    assert ui.env["MYCELIUM_INTERNAL_API_URL"] == "https://hub.example.com"
    # It signs in with the CLI's client, and gets this launch's token on its
    # stdin, as in hub mode: what keeps the sign-in to the hub in its memory
    # and away from every other page on the machine.
    assert ui.env["MYCELIUM_OIDC_CLIENT_ID"] == "mycelium-cli"
    assert ui.env["MYCELIUM_UI_TOKEN_STDIN"] == "1"
    assert ui.stdin == "launch-token"
    # A UI already on the port is talking to some other hub, so it isn't used.
    assert ui.external is None
    with pytest.raises(ValueError, match="needs the hub's URL"):
        Supervisor("client", emit=events, env={})


def test_herdr_is_left_running_when_mycelium_stops():
    # Agents live in herdr's panes; quitting Mycelium must not end them.
    events = Events()
    herdr = comp("herdr", SLEEP, outlives=True)
    sup = hub(events, [herdr])
    run_until(sup, lambda: herdr.state == "running")
    assert herdr.proc is not None
    assert herdr.proc.poll() is None
    herdr.proc.kill()


def test_programs_are_found_in_the_bundle_before_the_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    macos = tmp_path / "Mycelium.app" / "Contents" / "MacOS"
    resources = macos.parent / "Resources"
    macos.mkdir(parents=True)
    (resources / "ui" / ".next" / "static").mkdir(parents=True)
    (resources / "ui" / "server.js").write_text("")
    for name in ("slimctl", "node"):
        (macos / name).write_text("")
    (resources / "hub").mkdir()
    (resources / "hub" / "mycelium-hub").write_text("")
    (resources / "models").mkdir()
    monkeypatch.delenv("MYCELIUM_SLIMCTL", raising=False)
    monkeypatch.delenv("MYCELIUM_HUB_CMD", raising=False)
    monkeypatch.delenv("MYCELIUM_UI_DIR", raising=False)
    monkeypatch.delenv("MYCELIUM_NODE", raising=False)
    loc = Locator(bundle=macos, repo=None)

    assert loc.slim()[:3] == [str(macos / "slimctl"), "slim", "start"]
    assert loc.hub()[0][0] == str(resources / "hub" / "mycelium-hub")
    assert loc.ui() == ([str(macos / "node"), "server.js"], resources / "ui")
    assert loc.models() == resources / "models"
    assert Locator(bundle=None, repo=None).models() == Path.home() / ".mycelium" / "models"

    monkeypatch.setenv("MYCELIUM_HUB_CMD", "my-hub --port 9")
    assert loc.hub() == (["my-hub", "--port", "9"], None)


@pytest.mark.parametrize(
    ("windows", "programs", "resources"),
    [
        # An AppImage: programs in usr/bin, resources in usr/lib/Mycelium.
        (False, ("usr", "bin"), ("usr", "lib", "Mycelium")),
        # Windows: everything in the install folder, programs named .exe.
        (True, ("Mycelium",), ("Mycelium",)),
    ],
)
def test_programs_are_found_in_each_platforms_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    windows: bool,  # noqa: FBT001
    programs: tuple[str, ...],
    resources: tuple[str, ...],
):
    monkeypatch.setattr(sv, "WINDOWS", windows)
    for var in ("MYCELIUM_SLIMCTL", "MYCELIUM_HUB_CMD", "MYCELIUM_UI_DIR", "MYCELIUM_NODE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("ALIGNER_PI_BINARY", raising=False)
    exe = ".exe" if windows else ""
    bin_dir, res = tmp_path.joinpath(*programs), tmp_path.joinpath(*resources)
    bin_dir.mkdir(parents=True, exist_ok=True)
    for name in ("slimctl", "node", "herdr"):
        (bin_dir / f"{name}{exe}").write_text("")
    (res / "hub").mkdir(parents=True)
    (res / "hub" / f"mycelium-hub{exe}").write_text("")
    (res / "ui" / ".next" / "static").mkdir(parents=True)
    (res / "ui" / "server.js").write_text("")
    # On Windows the hub runs Pi's entry point on node; a batch launcher would
    # mangle every prompt on its way through cmd.exe.
    pi = res / sv.PI_ENTRY if windows else res / "pi" / "pi"
    pi.parent.mkdir(parents=True)
    pi.write_text("")
    (res / "models").mkdir()
    loc = Locator(bundle=bin_dir, repo=None)

    assert loc.slim()[0] == str(bin_dir / f"slimctl{exe}")
    assert loc.herdr() == [str(bin_dir / f"herdr{exe}"), "server"]
    assert loc.hub()[0][0] == str(res / "hub" / f"mycelium-hub{exe}")
    assert loc.ui() == ([str(bin_dir / f"node{exe}"), "server.js"], res / "ui")
    assert loc.pi() == str(pi)
    assert loc.models() == res / "models"


@pytest.mark.parametrize(
    ("cli", "programs"),
    [
        # The app's mycelium is a directory build among its resources (#1269).
        (
            "/Applications/Mycelium.app/Contents/Resources/cli",
            "/Applications/Mycelium.app/Contents/MacOS",
        ),
        ("/tmp/.mount_Myc/usr/lib/Mycelium/cli", "/tmp/.mount_Myc/usr/bin"),
        ("C:/Users/me/AppData/Local/Mycelium/cli", "C:/Users/me/AppData/Local/Mycelium"),
        # A standalone binary, or an app from before, is its own programs folder.
        ("/usr/local/bin", "/usr/local/bin"),
        (
            "/Applications/Mycelium.app/Contents/MacOS",
            "/Applications/Mycelium.app/Contents/MacOS",
        ),
    ],
)
def test_the_apps_programs_are_found_from_its_cli_folder(cli: str, programs: str):
    assert sv.programs_dir(Path(cli)) == Path(programs)


def test_a_ui_build_without_its_static_files_is_not_used(tmp_path: Path):
    # `next build` puts the static files beside the standalone server; a
    # server without them renders every page blank.
    (tmp_path / "server.js").write_text("")
    assert not sv.runnable_ui(tmp_path)
    (tmp_path / ".next" / "static").mkdir(parents=True)
    assert sv.runnable_ui(tmp_path)


def test_without_a_bundle_or_checkout_the_hub_says_so(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MYCELIUM_HUB_CMD", raising=False)
    monkeypatch.delenv("MYCELIUM_SLIMCTL", raising=False)
    monkeypatch.setattr(sv.shutil, "which", lambda _name: None)
    loc = Locator(bundle=None, repo=None)
    with pytest.raises(LocateError, match="doesn't include the hub"):
        loc.hub()
    with pytest.raises(LocateError, match="slimctl isn't installed"):
        loc.slim()


def test_the_repo_checkout_is_found_from_this_code():
    root = sv.repo_root()
    assert root is not None
    assert (root / "fastapi-backend" / "app" / "main.py").exists()


def test_the_launch_token_reaches_the_ui_server_on_its_stdin_never_an_environment():
    """Any program running as this user can read another's environment (`ps
    eww`, /proc), so the token goes to the UI server alone, on its stdin."""
    sup = Supervisor("hub", emit=Events(), env={}, locator=Locator(None, None), ui_token="t0k")
    components = sup._components()
    [ui] = [c for c in components if c.name == "ui"]
    assert ui.stdin == "t0k"
    assert ui.env.get("MYCELIUM_UI_TOKEN_STDIN") == "1"
    for c in components:
        assert "t0k" not in c.env.values(), c.name
        if c.name != "ui":
            assert c.stdin is None, c.name


def test_a_program_the_ui_server_starts_reads_nothing_from_its_stdin():
    """The token is written once and the pipe closed: what the UI server reads
    is gone from it, so a program it starts later inherits an empty stdin."""
    grandchild = "import sys; print('child read', repr(sys.stdin.read()))"
    script = (
        "import subprocess, sys; sys.stdin.readline(); "
        f"subprocess.run([sys.executable, '-c', {grandchild!r}])"
    )
    ui = Component(name="ui", argv=lambda: ([sys.executable, "-c", script], None),
                   ready=lambda: False, stdin="t0k")  # fmt: skip
    sup = hub(Events(), [ui])
    sup._spawn(ui)
    assert ui.proc is not None
    ui.proc.wait(timeout=10)
    assert ui.reader is not None
    ui.reader.join(timeout=5)
    assert list(ui.tail) == ["child read ''"]


def test_the_ui_is_never_one_the_app_didnt_start():
    sup = Supervisor("hub", emit=Events(), env={}, locator=Locator(None, None), ui_token="t0k")
    [ui] = [c for c in sup._components() if c.name == "ui"]
    assert ui.external is None


def test_a_taken_ui_port_is_said_and_the_ui_goes_on_another(monkeypatch: pytest.MonkeyPatch):
    import socket

    with socket.socket() as taken:
        taken.bind((sv.HOST, 0))
        taken.listen(1)
        port = taken.getsockname()[1]
        monkeypatch.setattr(sv, "UI_PORT", port)
        sup = Supervisor("hub", emit=Events(), env={}, locator=Locator(None, None), ui_token="t")
        [ui] = [c for c in sup._components() if c.name == "ui"]
        assert ui.prepare is not None
        ui.prepare()
        assert sup.ui_port != port
        assert ui.env["PORT"] == str(sup.ui_port)
        assert sup.ui_url == f"http://{sv.HOST}:{sup.ui_port}"
        assert f"another program is using port {port}" in (ui.running_detail or "")
    ui.prepare()  # free again: back on its own port
    assert (sup.ui_port, ui.running_detail) == (port, None)


def test_the_ui_counts_as_up_only_once_it_proves_it_holds_the_token(
    monkeypatch: pytest.MonkeyPatch,
):
    """Whatever answers on the port must answer a fresh nonce with the HMAC
    only this launch's token makes; a program that took the port can't."""
    import httpx

    from tests.conftest import install_stand_in_hub

    token = "a" * 64
    # The same vector as the UI server's test (`ui-guard.test.ts`).
    assert sv.ui_proof("0" * 32, token) == (
        "e09458aaecee116ce381f943381097f89f5e436f943082fc27346c2457188ff9"
    )

    on_the_port = install_stand_in_hub(monkeypatch)
    for answer, proves in ((lambda n: "ok", False), (lambda n: sv.ui_proof(n, token), True)):
        on_the_port.answer = lambda request, answer=answer: httpx.Response(
            200, text=answer(request.url.params.get("nonce", ""))
        )
        assert sv.proves_token(f"http://{sv.HOST}:3000", token) is proves


@pytest.mark.parametrize(("share", "sent"), [(True, "true"), (False, "false"), (None, None)])
def test_the_apps_answer_on_usage_stats_reaches_the_hub(share: bool | None, sent: str | None):
    sup = Supervisor("hub", emit=Events(), env={}, locator=Locator(None, None), share_usage=share)
    [hub_component] = [c for c in sup._components() if c.name == "hub"]
    assert hub_component.env["MYCELIUM_HUB_MODE"] == "desktop"
    assert hub_component.env.get("TELEMETRY_SEND_PRODUCT_ANALYTICS") == sent


@pytest.mark.parametrize(("voice", "sent"), [(True, "true"), (False, "false"), (None, None)])
def test_the_apps_voice_switch_reaches_the_hub(voice: bool | None, sent: str | None):
    sup = Supervisor("hub", emit=Events(), env={}, locator=Locator(None, None), voice=voice)
    [hub_component] = [c for c in sup._components() if c.name == "hub"]
    assert hub_component.env.get("VOICE_ENABLED") == sent


def test_voice_is_off_in_config_unless_turned_on():
    from mycelium.config import MyceliumConfig

    assert sv.hub_env(MyceliumConfig())["VOICE_ENABLED"] == "false"
    config = MyceliumConfig()
    config.voice.enabled = True
    assert sv.hub_env(config)["VOICE_ENABLED"] == "true"


def test_the_speech_model_is_fast_unless_chosen():
    from mycelium.config import MyceliumConfig

    assert sv.hub_env(MyceliumConfig())["VOICE_MODEL"] == "fast"
    config = MyceliumConfig()
    config.voice.model = "accurate"
    assert sv.hub_env(config)["VOICE_MODEL"] == "accurate"


@pytest.mark.parametrize("model", ["accurate", "fast", None])
def test_the_apps_speech_model_reaches_the_hub(model: str | None):
    sup = Supervisor(
        "hub", emit=Events(), env={}, locator=Locator(None, None), voice=True, voice_model=model
    )
    [hub_component] = [c for c in sup._components() if c.name == "hub"]
    assert hub_component.env.get("VOICE_MODEL") == model


def test_the_hubs_settings_come_from_config():
    from mycelium.config import MyceliumConfig

    config = MyceliumConfig()
    config.llm.model = "anthropic/claude-sonnet-4-6"
    env = sv.hub_env(config)
    assert env["LLM_MODEL"] == "anthropic/claude-sonnet-4-6"
    assert "LLM_API_KEY" not in env  # empty values are left to the hub's defaults


def test_the_hub_is_told_which_cli_saves_its_settings():
    sup = Supervisor("hub", emit=Events(), env={}, locator=Locator(None, None))
    [hub_component] = [c for c in sup._components() if c.name == "hub"]
    assert json.loads(hub_component.env["MYCELIUM_CONFIG_CLI"]) == sv.own_cli()
    assert sv.own_cli()[0] == sys.executable


def test_a_hub_that_asks_to_restart_is_started_again_at_once_with_config_read_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # The hub's Hub page saved a setting: the hub leaves the marker and exits
    # cleanly. Its second run stays up.
    marker = tmp_path / sv.HUB_RESTART_MARKER
    once = tmp_path / "ran-once"
    script = (
        "import pathlib, time\n"
        f"once = pathlib.Path({str(once)!r})\n"
        "if not once.exists():\n"
        "    once.write_text('1')\n"
        f"    pathlib.Path({str(marker)!r}).write_text('restart')\n"
        "    raise SystemExit(0)\n"
        "time.sleep(60)\n"
    )
    events = Events()
    restarting = comp("hub", [sys.executable, "-c", script])
    sup = hub(events, [restarting])
    sup.env = {"MYCELIUM_DATA_DIR": str(tmp_path)}
    sup._env_from_config = True
    monkeypatch.setattr(
        sv,
        "hub_env",
        lambda _config: {"MYCELIUM_DATA_DIR": str(tmp_path), "LLM_MODEL": "new/model"},
    )

    def restarted() -> bool:
        # The first run is up too before it exits, so wait for the restart
        # itself, then for the second run.
        details = [s["components"]["hub"]["detail"] or "" for s in events.statuses()]
        asked = any("restarting to apply new settings" in d for d in details)
        return asked and restarting.state == "running" and restarting.proc is not None

    run_until(sup, restarted)
    assert restarting.restarts == 0  # not counted as a crash
    assert not marker.exists()
    assert restarting.env["LLM_MODEL"] == "new/model"


def test_a_hub_that_exits_without_the_marker_is_a_crash(tmp_path: Path):
    events = Events()
    crashing = comp("hub", EXIT, ready=lambda: False)
    sup = hub(events, [crashing])
    sup.env = {"MYCELIUM_DATA_DIR": str(tmp_path)}
    run_until(sup, lambda: crashing.state == "failed")
    details = [s["components"]["hub"]["detail"] or "" for s in events.statuses()]
    assert not any("restarting to apply" in d for d in details)
