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
from typing import TYPE_CHECKING, cast

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

    from mycelium.config import MyceliumConfig


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


def test_registry_managed_roundtrips(isolated_home: Path) -> None:
    reg = HerdrRegistry()
    reg.set(HerdrPaneMapping(room="r", handle="auto", pane="w2:pA", managed=True))
    reg.set(HerdrPaneMapping(room="r", handle="hand", pane="w2:pB"))  # default False
    auto = reg.get("r", "auto")
    hand = reg.get("r", "hand")
    assert auto is not None and auto.managed is True
    assert hand is not None and hand.managed is False
    assert {m.handle: m.managed for m in reg.all()} == {"auto": True, "hand": False}


def test_registry_workspace_bindings_roundtrip(isolated_home: Path) -> None:
    reg = HerdrRegistry()
    assert reg.bindings() == {}
    reg.bind("w2", "design")
    reg.bind("w3", "ops")
    reg.bind("w2", "design-v2")  # idempotent upsert (last write wins)
    assert reg.bindings() == {"w2": "design-v2", "w3": "ops"}
    assert reg.unbind("w3") is True
    assert reg.unbind("w9") is False
    assert reg.bindings() == {"w2": "design-v2"}


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


# ── invoke residence resolution (herdr-grounded) ────────────────────────────────


def test_herdr_presence_defers_when_autowake_off(isolated_home: Path) -> None:
    """`agent invoke` must not consult herdr unless `herdr.autowake` is on."""
    from mycelium.commands.agent import _herdr_presence
    from mycelium.config import MyceliumConfig

    config = MyceliumConfig()  # autowake defaults False
    assert config.herdr.autowake is False
    # None = "defer to the backend lease" — herdr never consulted.
    assert _herdr_presence(config, "design", "reviewer") is None


def test_herdr_presence_defers_when_unmapped(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    """Feature on, but no pane mapped → defer to the lease (None), never wake."""
    from mycelium.commands import agent as agent_cmd
    from mycelium.config import MyceliumConfig

    # herdr reachable + agent list empty, but nothing is mapped for this handle.
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/herdr")
    monkeypatch.setattr(
        agent_cmd,
        "_is_resident",
        lambda *_: False,  # keep the fallback off the network
    )
    monkeypatch.setattr(
        "mycelium.integrations.herdr.HerdrBridge._default_runner",
        lambda self, args: _proc(_ok({"agents": []})),
    )
    config = MyceliumConfig()
    config.herdr.autowake = True
    assert agent_cmd._herdr_presence(config, "design", "reviewer") is None


def test_herdr_presence_wakes_idle_over_stale_lease(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    """The Finding-2 fix: a mapped, idle herdr pane is woken even when the backend
    lease would (falsely) report the handle as resident."""
    from mycelium.commands import agent as agent_cmd
    from mycelium.config import MyceliumConfig
    from mycelium.integrations.herdr import HerdrBridge, HerdrPaneMapping

    HerdrBridge().registry.set(
        HerdrPaneMapping(room="design", handle="reviewer", pane="w2:pV", kind="claude")
    )

    def runner(self: object, args: list[str]) -> subprocess.CompletedProcess:
        if args[:2] == ["agent", "list"]:
            return _proc(_ok({"agents": [{"pane_id": "w2:pV", "agent_status": "idle"}]}))
        if args[:2] == ["agent", "get"]:
            return _proc(_ok({"agent": {"pane_id": "w2:pV", "agent_status": "idle"}}))
        if args[:2] == ["agent", "prompt"]:
            return _proc(_ok({"agent_status": "idle"}))
        return _proc(returncode=2)

    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/herdr")
    monkeypatch.setattr("mycelium.integrations.herdr.HerdrBridge._default_runner", runner)
    # Stale lease: the backend would call this handle resident — herdr must win.
    monkeypatch.setattr(agent_cmd, "_is_resident", lambda *_: True)

    config = MyceliumConfig()
    config.herdr.autowake = True
    state, _ = agent_cmd._resolve_presence(config, "design", "reviewer")
    assert state == "woke"


def test_resolve_presence_reports_stale_mapping(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    """Mapped but the herdr pane is empty → 'stale', not a phantom 'resident'."""
    from mycelium.commands import agent as agent_cmd
    from mycelium.config import MyceliumConfig
    from mycelium.integrations.herdr import HerdrBridge, HerdrPaneMapping

    HerdrBridge().registry.set(HerdrPaneMapping(room="design", handle="reviewer", pane="w2:pV"))

    def runner(self: object, args: list[str]) -> subprocess.CompletedProcess:
        if args[:2] == ["agent", "list"]:
            return _proc(_ok({"agents": []}))
        if args[:2] == ["agent", "get"]:
            return _proc(_ok({"agent": {}}))  # no live agent at the pane
        return _proc(returncode=2)

    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/herdr")
    monkeypatch.setattr("mycelium.integrations.herdr.HerdrBridge._default_runner", runner)
    monkeypatch.setattr(agent_cmd, "_is_resident", lambda *_: True)

    config = MyceliumConfig()
    config.herdr.autowake = True
    state, detail = agent_cmd._resolve_presence(config, "design", "reviewer")
    assert state == "stale"
    assert detail and "stale" in detail.lower()


# ── ls reconciliation verdict ───────────────────────────────────────────────────


def test_reconcile_note_stale_lease() -> None:
    """Backend holds a lease but the herdr pane is dead → the Finding-2 flag."""
    from mycelium.commands.herdr import _reconcile_note

    text, colour = _reconcile_note("lease", None)
    assert "stale" in text.lower()
    assert colour == "red"


def test_reconcile_note_in_sync() -> None:
    from mycelium.commands.herdr import _reconcile_note

    text, _ = _reconcile_note("slim", "idle")
    assert "sync" in text.lower()


def test_reconcile_note_herdr_only() -> None:
    """A live herdr agent the backend never joined."""
    from mycelium.commands.herdr import _reconcile_note

    text, colour = _reconcile_note(None, "working")
    assert "herdr-only" in text.lower()
    assert colour == "yellow"


def test_reconcile_note_both_absent() -> None:
    from mycelium.commands.herdr import _reconcile_note

    text, _ = _reconcile_note(None, None)
    assert text == "-"


# ── sync handle derivation ────────────────────────────────────────────────────

_HANDLE_RE = __import__("re").compile(r"^[a-z0-9][a-z0-9._-]*$")  # AgentManifest.handle rule


def test_sanitize_handle_coerces_tab_label() -> None:
    from mycelium.commands.herdr import _sanitize_handle

    # A real tab label with spaces/emoji/punctuation → a valid handle.
    h = _sanitize_handle("✳ Review pull requests excluding PR 494", "")
    assert _HANDLE_RE.match(h)
    assert h.startswith("review-pull-requests") and len(h) <= 32  # emoji dropped, capped
    # Prefix namespacing still yields a valid handle.
    assert _sanitize_handle("pr review", "agent-") == "agent-pr-review"
    # Nothing usable → empty (caller falls back to the pane).
    assert _sanitize_handle("✳✳✳", "") == ""


def test_derive_handle_prefers_tab_then_falls_back_to_pane() -> None:
    from mycelium.commands.herdr import _derive_handle

    taken: set[str] = set()
    # Tab name wins.
    h1 = _derive_handle(
        tab_label="pr review", pane_id="w2:pQ", prefix="", name_from="tab", taken=taken
    )
    assert h1 == "pr-review"
    # Empty/unusable label → pane fallback (namespaced so it isn't a bare "pr").
    h2 = _derive_handle(tab_label="", pane_id="w2:pR", prefix="", name_from="tab", taken=taken)
    assert h2 == "agent-pr"
    # name_from='pane' ignores the label entirely.
    h3 = _derive_handle(
        tab_label="pr review", pane_id="w2:pS", prefix="", name_from="pane", taken=taken
    )
    assert h3 == "ps"


def test_derive_handle_disambiguates_duplicate_tab_names() -> None:
    from mycelium.commands.herdr import _derive_handle

    taken: set[str] = set()
    first = _derive_handle(
        tab_label="build", pane_id="w2:pA", prefix="", name_from="tab", taken=taken
    )
    taken.add(first)
    second = _derive_handle(
        tab_label="build", pane_id="w2:pB", prefix="", name_from="tab", taken=taken
    )
    assert first == "build"
    assert second == "build-pb"  # collision → pane suffix appended
    assert _HANDLE_RE.match(second)


# ── sync membership reconcile ─────────────────────────────────────────────────


def test_reconcile_workspace_enrolls_new_and_retires_closed(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    """The lifecycle mirror: a live workspace agent that isn't a member gets
    enrolled; a sync-managed member whose pane closed is retired; a hand-mapped
    (unmanaged) member is left alone even if its pane is gone."""
    from mycelium.commands import herdr as herdr_cmd

    reg = HerdrRegistry()
    reg.set(HerdrPaneMapping(room="r", handle="old", pane="w2:pDEAD", kind="claude", managed=True))
    reg.set(HerdrPaneMapping(room="r", handle="manual", pane="w2:pGONE"))  # unmanaged

    written: list[str] = []
    deleted: list[str] = []

    class _FakeManifest:
        def __init__(self, handle: str) -> None:
            self.handle = handle
            self.memory_key = f"agents/{handle}"

    class _FakeImpl:
        def build_manifest(self, *, handle: str, **_: object) -> _FakeManifest:
            return _FakeManifest(handle)

    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/herdr")
    monkeypatch.setattr("mycelium.integrations.get_integration", lambda *_a, **_k: _FakeImpl())
    monkeypatch.setattr(
        "mycelium.commands.agent._write_manifest",
        lambda config, room, manifest, created_by: written.append(manifest.handle),
    )
    # Retire path loads then deletes the manifest; enroll of a new pane never loads.
    monkeypatch.setattr(
        "mycelium.commands.agent._load_manifest", lambda room, handle: _FakeManifest(handle)
    )
    monkeypatch.setattr(
        "mycelium.commands.agent._delete_manifest",
        lambda config, room, manifest: deleted.append(manifest.handle),
    )

    agents = [
        {
            "pane_id": "w2:pNEW",
            "agent_status": "idle",
            "tab_id": "w2:tNEW",
            "workspace_id": "w2",
            "agent": "claude",
            "cwd": "/x",
        }
    ]
    tabs = [{"tab_id": "w2:tNEW", "label": "fresh agent"}]
    bridge = HerdrBridge(
        runner=ScriptedRunner(
            {"agent list": _proc(_ok({"agents": agents})), "tab list": _proc(_ok({"tabs": tabs}))}
        )
    )

    class _Cfg:
        def get_current_identity(self) -> str:
            return "tester"

    enrolled, retired = herdr_cmd._reconcile_workspace(
        cast("MyceliumConfig", _Cfg()), bridge, "w2", "r", name_from="tab", prefix="", kind=None
    )

    assert enrolled == ["fresh-agent"]
    assert written == ["fresh-agent"]
    assert retired == ["old"] and deleted == ["old"]
    # New member is managed; the dead managed one is gone; the hand-mapped one stays.
    fresh = bridge.registry.get("r", "fresh-agent")
    assert fresh is not None and fresh.managed is True
    assert bridge.registry.get("r", "old") is None
    assert bridge.registry.get("r", "manual") is not None


# ── sync presence collection ────────────────────────────────────────────────────


def test_collect_presence_maps_live_panes_per_room(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    from mycelium.commands.herdr import _collect_presence

    reg = HerdrRegistry()
    reg.set(HerdrPaneMapping(room="design", handle="reviewer", pane="w2:pV"))
    reg.set(HerdrPaneMapping(room="design", handle="docs", pane="w2:pT"))
    reg.set(HerdrPaneMapping(room="ops", handle="ci", pane="w3:pA"))
    reg.set(HerdrPaneMapping(room="ops", handle="ghost", pane="w9:pZ"))  # dead pane

    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/herdr")
    agents = [
        {"pane_id": "w2:pV", "agent_status": "idle", "terminal_title_stripped": "Review PR 12"},
        {"pane_id": "w2:pT", "agent_status": "working"},  # no title → None
        {"pane_id": "w3:pA", "agent_status": "blocked", "terminal_title_stripped": "Fix CI"},
        # w9:pZ absent → 'ghost' omitted so its backend entry lapses.
    ]
    bridge = HerdrBridge(runner=ScriptedRunner({"agent list": _proc(_ok({"agents": agents}))}))

    # Each handle carries status + terminal title (the current task) for the roster.
    view = _collect_presence(bridge, room_filter=None)
    assert view == {
        "design": {
            "reviewer": {"status": "idle", "title": "Review PR 12"},
            "docs": {"status": "working", "title": None},
        },
        "ops": {"ci": {"status": "blocked", "title": "Fix CI"}},
    }
    # Room filter scopes the push.
    assert _collect_presence(bridge, room_filter="ops") == {
        "ops": {"ci": {"status": "blocked", "title": "Fix CI"}}
    }
