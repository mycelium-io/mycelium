# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""`mycelium agent add` brownfield onboarding: discovery, batch-adopt, the
non-interactive guard, and the create/add split."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from mycelium.integrations.openclaw import OpenClawIntegration

runner = CliRunner()


def test_discover_local_agents_parses_openclaw_json(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = tmp_path / ".openclaw"
    state.mkdir()
    (state / "openclaw.json").write_text(
        json.dumps(
            {
                "agents": {
                    "defaults": {"model": {"primary": "anthropic/sonnet"}},
                    "list": [
                        {"id": "zeta", "model": "anthropic/haiku", "workspace": "/w/z"},
                        # newer builds use the structured {primary: ...} form
                        {"id": "alpha", "model": {"primary": "anthropic/opus"}},
                        {"id": ""},  # junk — skipped
                        "not-a-dict",  # junk — skipped
                    ],
                }
            }
        )
    )
    monkeypatch.setattr(
        "mycelium.integrations.openclaw.dispatch._openclaw_state_dir",
        lambda _profile: state,
    )

    agents = OpenClawIntegration().discover_local_agents()
    ids = [a["id"] for a in agents]
    # sorted, implicit `main` always present, junk dropped
    assert ids == ["alpha", "main", "zeta"]
    by_id = {a["id"]: a for a in agents}
    assert by_id["alpha"]["model"] == "anthropic/opus"  # dict flattened
    assert by_id["zeta"]["workspace"] == "/w/z"


def test_discover_local_agents_missing_config_is_empty(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "mycelium.integrations.openclaw.dispatch._openclaw_state_dir",
        lambda _profile: tmp_path / "nope",
    )
    assert OpenClawIntegration().discover_local_agents() == []


def test_register_adopted_batch_restarts_gateway_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    impl = OpenClawIntegration()
    chan_calls: list[tuple[str, str]] = []
    restarts: list[int] = []

    monkeypatch.setattr(
        impl,
        "_register_channel",
        lambda *, room, agent_id, **_: chan_calls.append((room, agent_id)),
    )
    monkeypatch.setattr(impl, "restart_gateway", lambda: restarts.append(1))
    # These two shell out to the `openclaw` binary (absent in CI). The test is
    # about the batch->single-restart shape, not their side effects — stub them so
    # it runs without the binary (openclaw is a deferred adapter, bible D11/H6).
    monkeypatch.setattr(impl, "_allowlist_mycelium", lambda *a, **k: None)
    monkeypatch.setattr(impl, "_configure_exec_host_gateway", lambda *a, **k: None)

    impl.register_adopted_batch(["a", "b", "c"], room="demo", backend_url="http://hub:8000")

    # one channel write per agent, into the same room — and ONE restart total
    assert chan_calls == [("demo", "a"), ("demo", "b"), ("demo", "c")]
    assert restarts == [1]


def _write_oc(state, payload) -> None:
    state.mkdir(exist_ok=True)
    (state / "openclaw.json").write_text(json.dumps(payload))


def _patch_state(monkeypatch, state) -> None:
    monkeypatch.setattr(
        "mycelium.integrations.openclaw.dispatch._openclaw_state_dir",
        lambda _profile: state,
    )


def test_configure_exec_host_gateway_sets_host(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A wired-in agent must get tools.exec.host=gateway so the exec-approvals
    allowlist is consulted and mycelium runs on the host."""
    state = tmp_path / ".openclaw"
    _write_oc(state, {"agents": {"list": [{"id": "lawyer-a"}]}})
    _patch_state(monkeypatch, state)

    OpenClawIntegration()._configure_exec_host_gateway("lawyer-a")

    written = json.loads((state / "openclaw.json").read_text())
    entry = next(a for a in written["agents"]["list"] if a["id"] == "lawyer-a")
    assert entry["tools"]["exec"]["host"] == "gateway"


def test_configure_exec_host_gateway_is_idempotent(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-running must not clobber an already-correct config."""
    state = tmp_path / ".openclaw"
    _write_oc(
        state,
        {"agents": {"list": [{"id": "lawyer-a", "tools": {"exec": {"host": "gateway"}}}]}},
    )
    _patch_state(monkeypatch, state)

    OpenClawIntegration()._configure_exec_host_gateway("lawyer-a")

    written = json.loads((state / "openclaw.json").read_text())
    entry = next(a for a in written["agents"]["list"] if a["id"] == "lawyer-a")
    assert entry["tools"]["exec"]["host"] == "gateway"


def test_configure_exec_host_gateway_preserves_sibling_tool_config(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Setting exec.host must not drop other keys under tools/exec."""
    state = tmp_path / ".openclaw"
    _write_oc(
        state,
        {
            "agents": {
                "list": [
                    {"id": "lawyer-a", "tools": {"browser": {"on": True}, "exec": {"timeout": 30}}}
                ]
            }
        },
    )
    _patch_state(monkeypatch, state)

    OpenClawIntegration()._configure_exec_host_gateway("lawyer-a")

    entry = next(
        a
        for a in json.loads((state / "openclaw.json").read_text())["agents"]["list"]
        if a["id"] == "lawyer-a"
    )
    assert entry["tools"]["exec"] == {"timeout": 30, "host": "gateway"}
    assert entry["tools"]["browser"] == {"on": True}  # sibling tool untouched


def test_configure_exec_host_gateway_missing_agent_is_noop(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Implicit agents (e.g. `main`, not in agents.list) are skipped without
    raising and without rewriting the file."""
    state = tmp_path / ".openclaw"
    payload = {"agents": {"list": [{"id": "lawyer-a"}]}}
    _write_oc(state, payload)
    _patch_state(monkeypatch, state)

    OpenClawIntegration()._configure_exec_host_gateway("main")

    # untouched — no exec.host injected for an absent agent
    assert json.loads((state / "openclaw.json").read_text()) == payload


def test_configure_exec_host_gateway_tolerates_null_tools(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hand-edited `tools: null` must not crash the read-modify-write."""
    state = tmp_path / ".openclaw"
    _write_oc(state, {"agents": {"list": [{"id": "lawyer-a", "tools": None}]}})
    _patch_state(monkeypatch, state)

    OpenClawIntegration()._configure_exec_host_gateway("lawyer-a")  # must not raise

    entry = next(
        a
        for a in json.loads((state / "openclaw.json").read_text())["agents"]["list"]
        if a["id"] == "lawyer-a"
    )
    assert entry["tools"]["exec"]["host"] == "gateway"


def test_register_wires_exec_host_for_created_and_adopted(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """register() must configure exec.host=gateway for both created and adopted
    agents (paired with the allowlist), so they can exec mycelium on first tick."""
    from mycelium.integrations.base import AddOptions
    from mycelium.protocol import AgentManifest

    _patch_state(monkeypatch, tmp_path / ".openclaw")
    impl = OpenClawIntegration()
    configured: list[str] = []
    monkeypatch.setattr(impl, "_create_agent", lambda **_: None)
    monkeypatch.setattr(impl, "_register_channel", lambda **_: None)
    monkeypatch.setattr(impl, "_allowlist_mycelium", lambda _aid: None)
    monkeypatch.setattr(impl, "_configure_exec_host_gateway", lambda aid: configured.append(aid))
    monkeypatch.setattr(impl, "restart_gateway", lambda: None)

    cfg = type("C", (), {"server": type("S", (), {"api_url": "http://localhost:8000"})()})()
    opts = AddOptions(room="demo")

    for created, handle in ((True, "fresh"), (False, "legacy")):
        impl.register(
            manifest=AgentManifest(
                handle=handle,
                adapter="openclaw",
                openclaw_agent=handle,
                openclaw_created=created,
            ),
            config=cfg,  # ty: ignore[invalid-argument-type]
            opts=opts,
        )
    assert configured == ["fresh", "legacy"]


def test_agent_add_non_interactive_without_handle_errors() -> None:
    """CliRunner stdin/stdout aren't a TTY — bare `agent add` must refuse with
    guidance instead of hanging on a picker or silently doing nothing."""
    from mycelium.cli import app

    result = runner.invoke(app, ["agent", "add"])
    assert result.exit_code == 1
    assert "non-interactive" in result.output
    assert "mycelium agent create" in result.output  # points at greenfield


def test_agent_create_has_no_openclaw_agent_flag() -> None:
    """`create` is greenfield only — the adopt-only --openclaw-agent flag must
    live on `add`, not `create`."""
    import click
    import typer

    from mycelium.cli import app

    # Introspect the commands' params rather than the rendered --help text: Typer's
    # Rich help renders an empty options table under CI (non-TTY), so asserting on
    # the help string is width/environment-fragile. The params are the source of
    # truth for the create/add flag split regardless of rendering. (isinstance
    # guards narrow Command->Group so ty is happy and it's runtime-safe.)
    cli = typer.main.get_command(app)
    assert isinstance(cli, click.Group)
    agent = cli.commands["agent"]
    assert isinstance(agent, click.Group)
    create_opts = {o for p in agent.commands["create"].params for o in getattr(p, "opts", [])}
    add = agent.commands["add"]

    assert "--openclaw-agent" not in create_opts  # adopt-only flag isn't on greenfield create
    assert "--cwd" in create_opts
    handle = next((p for p in add.params if p.name == "handle"), None)
    assert handle is not None and not handle.required  # [HANDLE] optional on add (picker)


# ── _pick_room: fetch rooms → picker, with create-new ─────────────────────────


class _FakeRoom:
    def __init__(self, name: str) -> None:
        self._n = name

    def to_dict(self) -> dict:
        return {"name": self._n}


class _NullCM:
    def __enter__(self):
        return object()

    def __exit__(self, *_a):
        return False


class _Ask:
    def __init__(self, value):
        self._v = value

    def ask(self):
        return self._v


def _patch_rooms(monkeypatch, *, rooms, created: list):
    from mycelium.commands import agent as agent_mod

    monkeypatch.setattr(agent_mod, "_typed_client", lambda _c: _NullCM())
    monkeypatch.setattr(
        "mycelium_backend_client.api.rooms.list_rooms_api_rooms_get.sync",
        lambda **_kw: [_FakeRoom(r) for r in rooms],
    )
    monkeypatch.setattr(
        "mycelium_backend_client.api.rooms.create_room_api_rooms_post.sync",
        lambda *, client, body: created.append(body.name) or _FakeRoom(body.name),
    )


def test_pick_room_returns_existing_without_creating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import questionary

    from mycelium.commands.agent import _pick_room

    created: list[str] = []
    _patch_rooms(monkeypatch, rooms=["alpha", "beta"], created=created)
    monkeypatch.setattr(questionary, "select", lambda *a, **k: _Ask("beta"))

    cfg = type("C", (), {"rooms": type("R", (), {"active": "alpha"})()})()
    assert _pick_room(cfg) == "beta"  # ty: ignore[invalid-argument-type]
    assert created == []  # picked existing → no room created


def test_pick_room_creates_new_when_sentinel_chosen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import questionary

    from mycelium.commands.agent import _pick_room

    created: list[str] = []
    _patch_rooms(monkeypatch, rooms=["alpha"], created=created)
    # select returns the create-new sentinel; text supplies the name
    monkeypatch.setattr(questionary, "select", lambda *a, **k: _Ask("\x00new"))
    monkeypatch.setattr(questionary, "text", lambda *a, **k: _Ask("fresh-room"))

    cfg = type("C", (), {"rooms": type("R", (), {"active": None})()})()
    assert _pick_room(cfg) == "fresh-room"  # ty: ignore[invalid-argument-type]
    assert created == ["fresh-room"]  # backend room actually created


def test_pick_room_no_rooms_prompts_then_creates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import questionary

    from mycelium.commands.agent import _pick_room

    created: list[str] = []
    _patch_rooms(monkeypatch, rooms=[], created=created)
    monkeypatch.setattr(questionary, "text", lambda *a, **k: _Ask("only-room"))

    cfg = type("C", (), {"rooms": type("R", (), {"active": None})()})()
    assert _pick_room(cfg) == "only-room"  # ty: ignore[invalid-argument-type]
    assert created == ["only-room"]
