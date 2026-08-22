# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium agent``/``engine`` reads resolve against the hub, not local files.

A spoke keeps no local ``.mycelium/`` replica, so anything that answered from
``get_room_dir()`` reported "No agents registered" for a room that demonstrably
has agents — a confident empty answer rather than an error (#787). These tests
run under a temp home with **no** room files on purpose: every listing below is
served by the stubbed hub, and the unreachable-hub cases assert the command says
so instead of printing the empty branch.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

import httpx
import pytest
import yaml
from typer.testing import CliRunner

from mycelium.commands import agent as agent_cmd
from mycelium.commands import engine as engine_cmd
from mycelium.commands import user as user_cmd
from mycelium.protocol import AgentManifest

runner = CliRunner()

STAMP = datetime.datetime(2026, 6, 1, 12, 30, tzinfo=datetime.UTC)

MEMORY_LIST_SYNC = (
    "mycelium_backend_client.api.memory.list_memories_api_rooms_room_name_memory_get.sync"
)
MEMORY_GET_SYNC = (
    "mycelium_backend_client.api.memory.get_memory_api_rooms_room_name_memory_key_get.sync"
)
ROOMS_LIST_SYNC = "mycelium_backend_client.api.rooms.list_rooms_api_rooms_get.sync"
MESSAGE_SEND_SYNC = (
    "mycelium_backend_client.api.messages.send_message_api_rooms_room_name_messages_post.sync"
)


@pytest.fixture(autouse=True)
def _home(isolated_home) -> None:  # noqa: ANN001
    """Every test here runs under the temp ``~/.mycelium`` — deliberately empty."""


@pytest.fixture(autouse=True)
def _hub(backend) -> None:  # noqa: ANN001
    """Neutralize the typed-client plumbing in each module under test.

    ``MyceliumConfig`` is one class object shared by every command module, so
    patching it through ``agent_cmd`` covers the ``user`` roll-up too.
    """
    for module in (agent_cmd, engine_cmd):
        backend(module, room="demo", active_room="demo")


def _manifest_yaml(handle: str, **fields: Any) -> str:
    manifest = AgentManifest(handle=handle, cwd="/tmp", **fields)
    return yaml.safe_dump(manifest.model_dump(exclude={"handle"}), sort_keys=False)


def _record(key: str, body: str) -> dict[str, Any]:
    """A memory as the hub's (untyped) list endpoint serializes it."""
    return {
        "key": key,
        "value": body,
        "content_text": body,
        "created_by": "tester",
        "version": 1,
        "created_at": STAMP.isoformat(),
        "updated_at": STAMP.isoformat(),
    }


def _memory_read(key: str, body: str):  # noqa: ANN202
    from mycelium_backend_client.models import MemoryRead

    return MemoryRead(
        id=uuid.uuid4(),
        room_name="demo",
        key=key,
        value=body,
        content_text=body,
        created_by="tester",
        version=1,
        created_at=STAMP,
        updated_at=STAMP,
    )


def _stub(monkeypatch: pytest.MonkeyPatch, target: str, outcome: Any) -> list[dict[str, Any]]:
    """Script one generated ``.sync``; returns the list of calls it received."""
    calls: list[dict[str, Any]] = []

    def _sync(**kwargs: Any):
        calls.append(kwargs)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome(**kwargs) if callable(outcome) else outcome

    monkeypatch.setattr(target, _sync)
    return calls


# ── agent ls ─────────────────────────────────────────────────────────────────


def test_agent_ls_lists_what_the_hub_serves_with_no_local_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The #787 regression: an agent the hub knows about shows up on a spoke."""
    calls = _stub(
        monkeypatch,
        MEMORY_LIST_SYNC,
        [
            _record(
                "agents/echo",
                _manifest_yaml(
                    "echo",
                    adapter="a2a",
                    a2a_card="https://echo.example/",
                    description="hello",
                ),
            ),
            _record("agents/scribe", _manifest_yaml("scribe", owner="avery", team="core")),
        ],
    )

    result = runner.invoke(agent_cmd.app, ["ls", "--room", "demo"])
    assert result.exit_code == 0, result.output
    assert "@echo" in result.output
    assert "@scribe" in result.output
    assert "No agents registered" not in result.output
    assert calls[0]["prefix"] == "agents/"
    assert calls[0]["room_name"] == "demo"


def test_agent_ls_skips_notes_and_log_children(monkeypatch: pytest.MonkeyPatch) -> None:
    """``agents/<handle>/…`` entries are the agent's brain, not more agents."""
    _stub(
        monkeypatch,
        MEMORY_LIST_SYNC,
        [
            _record("agents/echo", _manifest_yaml("echo")),
            _record("agents/echo/notes", "remember: be brief"),
            _record("agents/echo/log/2026-06-01", "invoked"),
        ],
    )

    assert [m.handle for m in agent_cmd._room_manifests("demo")] == ["echo"]


def test_agent_ls_says_none_only_when_the_hub_serves_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub(monkeypatch, MEMORY_LIST_SYNC, [])

    result = runner.invoke(agent_cmd.app, ["ls", "--room", "demo"])
    assert result.exit_code == 0, result.output
    assert "No agents registered" in result.output


def test_agent_ls_reports_an_unreachable_hub_rather_than_zero_agents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty answer must mean "no agents", never "couldn't look"."""
    _stub(monkeypatch, MEMORY_LIST_SYNC, httpx.ConnectError("connection refused"))

    result = runner.invoke(agent_cmd.app, ["ls", "--room", "demo"])
    assert result.exit_code == 1
    assert "No agents registered" not in result.output
    assert "Failed to connect" in result.output


def test_agent_ls_filters_by_owner_over_hub_manifests(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(
        monkeypatch,
        MEMORY_LIST_SYNC,
        [
            _record("agents/a1", _manifest_yaml("a1", owner="avery")),
            _record("agents/a2", _manifest_yaml("a2", owner="sam")),
        ],
    )

    result = runner.invoke(agent_cmd.app, ["ls", "--room", "demo", "--owner", "@Avery"])
    assert result.exit_code == 0, result.output
    assert "@a1" in result.output
    assert "@a2" not in result.output


def test_agent_ls_warns_on_a_corrupt_hub_manifest_and_lists_the_rest(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A manifest that won't parse is logged, never silently dropped as missing."""
    _stub(
        monkeypatch,
        MEMORY_LIST_SYNC,
        [
            _record("agents/broken", "adapter: not-a-real-adapter\ncwd: /tmp\n"),
            _record("agents/echo", _manifest_yaml("echo")),
        ],
    )

    with caplog.at_level("WARNING", logger="mycelium.commands.agent"):
        result = runner.invoke(agent_cmd.app, ["ls", "--room", "demo"])
    assert result.exit_code == 0, result.output
    assert "@echo" in result.output
    assert any("agents/broken" in r.message for r in caplog.records)


# ── agent show / invoke ──────────────────────────────────────────────────────


def test_agent_show_resolves_manifest_and_notes_from_the_hub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bodies = {
        "agents/echo": _manifest_yaml("echo", description="the echoing one"),
        "agents/echo/notes": "remember: be brief",
    }
    _stub(
        monkeypatch,
        MEMORY_GET_SYNC,
        lambda **kw: _memory_read(kw["key"], bodies[kw["key"]]) if kw["key"] in bodies else None,
    )

    result = runner.invoke(agent_cmd.app, ["show", "echo", "--room", "demo"])
    assert result.exit_code == 0, result.output
    assert "the echoing one" in result.output
    assert "remember: be brief" in result.output


def test_agent_show_reports_a_missing_agent_the_hub_doesnt_have(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub(monkeypatch, MEMORY_GET_SYNC, None)

    result = runner.invoke(agent_cmd.app, ["show", "ghost", "--room", "demo"])
    assert result.exit_code == 1
    assert "no agent named 'ghost'" in result.output


def test_agent_invoke_resolves_the_handle_from_the_hub(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, MEMORY_GET_SYNC, _memory_read("agents/echo", _manifest_yaml("echo")))
    sends = _stub(monkeypatch, MESSAGE_SEND_SYNC, None)
    monkeypatch.setattr(agent_cmd, "_is_resident", lambda *_a, **_k: False)

    result = runner.invoke(
        agent_cmd.app, ["invoke", "echo", "ping", "--room", "demo", "--as", "tester"]
    )
    assert result.exit_code == 0, result.output
    assert sends[0]["body"].content == "@echo ping"


# ── engine ls ────────────────────────────────────────────────────────────────


def test_engine_ls_lists_engines_the_hub_serves(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(
        monkeypatch,
        MEMORY_LIST_SYNC,
        [
            _record("agents/aligner", _manifest_yaml("aligner", adapter="engine", kind="aligner")),
            _record("agents/echo", _manifest_yaml("echo")),
        ],
    )

    result = runner.invoke(engine_cmd.app, ["ls", "--room", "demo"])
    assert result.exit_code == 0, result.output
    assert "@aligner" in result.output
    assert "@echo" not in result.output


# ── owned-agent roll-up ──────────────────────────────────────────────────────


def _room(name: str):  # noqa: ANN202
    from mycelium_backend_client.models import RoomRead

    return RoomRead(id=abs(hash(name)) % 10_000, name=name, created_at=STAMP, is_public=False)


def test_load_owned_agents_spans_every_room_on_the_hub(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, ROOMS_LIST_SYNC, [_room("alpha"), _room("beta")])
    per_room = {
        "alpha": [_record("agents/a1", _manifest_yaml("a1", owner="avery"))],
        "beta": [
            _record("agents/a2", _manifest_yaml("a2", owner="avery")),
            _record("agents/a3", _manifest_yaml("a3", owner="sam")),
        ],
    }
    _stub(monkeypatch, MEMORY_LIST_SYNC, lambda **kw: per_room[kw["room_name"]])

    owned = agent_cmd.load_owned_agents(owner="@Avery")
    assert sorted(m.handle for _room_name, m in owned) == ["a1", "a2"]
    assert sorted(r for r, _m in owned) == ["alpha", "beta"]


def test_owned_roll_up_distinguishes_unreachable_hub_from_owning_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub(monkeypatch, ROOMS_LIST_SYNC, httpx.ConnectError("connection refused"))
    assert user_cmd._owned_agents("avery") is None

    _stub(monkeypatch, ROOMS_LIST_SYNC, [])
    assert user_cmd._owned_agents("avery") == []
