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
    assert "keeps exiting (last exit code 3)" in details[-1]


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


def test_client_mode_runs_herdr_and_the_runner_against_the_hub():
    events = Events()
    sup = Supervisor(
        "client", hub_url="https://hub.example.com/", emit=events, env={}, start_runner=False
    )
    status = sup.status()
    assert status["ui_url"] == status["api_url"] == "https://hub.example.com"
    assert {k: v["state"] for k, v in status["components"].items()} == {
        "herdr": "stopped",
        "slim": "disabled",
        "hub": "disabled",
        "ui": "disabled",
        "runner": "stopped",
    }
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


@pytest.mark.parametrize(("share", "sent"), [(True, "true"), (False, "false"), (None, None)])
def test_the_apps_answer_on_usage_stats_reaches_the_hub(share: bool | None, sent: str | None):
    sup = Supervisor("hub", emit=Events(), env={}, locator=Locator(None, None), share_usage=share)
    [hub_component] = [c for c in sup._components() if c.name == "hub"]
    assert hub_component.env["MYCELIUM_HUB_MODE"] == "desktop"
    assert hub_component.env.get("TELEMETRY_SEND_PRODUCT_ANALYTICS") == sent


def test_the_hubs_settings_come_from_config():
    from mycelium.config import MyceliumConfig

    config = MyceliumConfig()
    config.llm.model = "anthropic/claude-sonnet-4-6"
    env = sv.hub_env(config)
    assert env["LLM_MODEL"] == "anthropic/claude-sonnet-4-6"
    assert "LLM_API_KEY" not in env  # empty values are left to the hub's defaults
