# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium herdr enroll``: an agent in a herdr pane joins a room as itself.

herdr is a scripted stand-in and the hub's manifest reads and writes are
replaced, so these check what enroll decides, not the transport.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

import pytest
import yaml
from typer.testing import CliRunner

from mycelium.cli import app
from mycelium.commands.agent import _manifest_from_yaml, _remote_memory_text
from mycelium.integrations.herdr import HerdrBridge, HerdrPaneMapping, HerdrRegistry
from tests.test_herdr_bridge import ScriptedRunner, _ok, _proc

#: The real hub read, kept before any fixture stubs it out.
REAL_READ = _remote_memory_text

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()

#: The line enroll ends on, for a room named "checkout".
NEXT = "Next: run `mycelium skill print`, then `mycelium board --room checkout`."

AGENT = {
    "pane_id": "w5:p3",
    "agent": "claude",
    "agent_status": "idle",
    "tab_id": "w5:t1",
    "workspace_id": "w5",
    "cwd": "/work/app",
}


@pytest.fixture
def herdr(monkeypatch: pytest.MonkeyPatch, isolated_home: Path) -> dict:
    """A herdr with one agent in pane w5:p3, under a tab named "Release notes"."""
    from mycelium.commands import herdr as herdr_cmd

    # ``hub`` is what the hub holds at ``agents/<handle>``: the manifest text.
    state: dict = {"hub": {}, "written": [], "by": [], "registry": HerdrRegistry()}
    bridge = HerdrBridge(
        runner=ScriptedRunner(
            {
                "agent list": _proc(_ok({"agents": [AGENT]})),
                "agent get": _proc(_ok({"agent": AGENT})),
                "tab list": _proc(_ok({"tabs": [{"tab_id": "w5:t1", "label": "Release notes"}]})),
            }
        ),
        registry=state["registry"],
    )
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/herdr")
    monkeypatch.setattr(herdr_cmd, "_bridge", lambda: bridge)
    monkeypatch.setattr(
        "mycelium.client.typed_client", lambda *_a, **_k: contextlib.nullcontext(None)
    )
    monkeypatch.setattr(
        "mycelium.commands.agent._remote_memory_text",
        lambda _client, _room, key: state["hub"].get(key.removeprefix("agents/")),
    )
    monkeypatch.setattr(
        "mycelium.commands.agent._load_manifest_remote",
        lambda _client, _room, handle: (
            _manifest_from_yaml(handle, state["hub"][handle], handle)
            if handle in state["hub"]
            else None
        ),
    )
    monkeypatch.setattr("mycelium.caller.person", lambda _config, **_kw: "julia")

    def write(_config, _room, manifest, created_by, **_kw) -> None:  # noqa: ANN001
        state["written"].append(manifest)
        state["by"].append(created_by)
        state["hub"][manifest.handle] = yaml.safe_dump(manifest.model_dump(exclude={"handle"}))

    monkeypatch.setattr("mycelium.commands.agent._write_manifest", write)
    monkeypatch.delenv("MYCELIUM_AGENT_HANDLE", raising=False)
    monkeypatch.setenv("HERDR_PANE_ID", "w5:p3")
    return state


def _member(state: dict, handle: str) -> None:
    """Put a readable manifest for ``handle`` on the stand-in hub."""
    state["hub"][handle] = "adapter: claude_code\ndescription: someone already here\n"


def _enroll(*args: str) -> Any:  # noqa: ANN401 - typer's Result, which ty can't resolve
    return runner.invoke(app, ["herdr", "enroll", *args, "--room", "checkout"])


def test_it_joins_under_the_tab_name_with_a_plain_mapping(herdr: dict) -> None:
    result = _enroll()
    assert result.exit_code == 0, result.output
    assert "Joined checkout as @release-notes" in result.output
    # It says the next step, in the words the app's introduction uses too.
    assert NEXT in result.output
    assert [m.handle for m in herdr["written"]] == ["release-notes"]
    # Owned and written by the machine's person, not "unknown" or the agent.
    assert herdr["written"][0].owner == "julia" and herdr["by"] == ["julia"]
    mapping = herdr["registry"].get("checkout", "release-notes")
    assert mapping is not None and mapping.pane == "w5:p3"
    # A plain mapping, so no sync pass retires it.
    assert not mapping.managed
    assert mapping.kind == "claude" and mapping.cwd == "/work/app"


def test_a_handle_given_is_used(herdr: dict) -> None:
    result = _enroll("@scribe")
    assert result.exit_code == 0, result.output
    assert herdr["registry"].get("checkout", "scribe") is not None


def test_a_description_and_owner_given_are_written(herdr: dict) -> None:
    result = _enroll("@scribe", "--description", "Writes the release notes", "--owner", "@sam")
    assert result.exit_code == 0, result.output
    (manifest,) = herdr["written"]
    assert (manifest.description, manifest.owner) == ("Writes the release notes", "sam")


def test_a_taken_handle_is_refused(herdr: dict) -> None:
    _member(herdr, "scribe")
    result = _enroll("scribe")
    assert result.exit_code == 1
    assert "already a member" in result.output
    assert herdr["written"] == []


def test_a_derived_handle_steps_around_a_member(herdr: dict) -> None:
    _member(herdr, "release-notes")
    result = _enroll()
    assert result.exit_code == 0, result.output
    assert [m.handle for m in herdr["written"]] == ["release-notes-p3"]


def test_running_it_again_changes_nothing(herdr: dict) -> None:
    herdr["registry"].set(HerdrPaneMapping(room="checkout", handle="scribe", pane="w5:p3"))
    _member(herdr, "scribe")
    result = _enroll()
    assert result.exit_code == 0, result.output
    assert "Already a member" in result.output and "@scribe" in result.output
    assert NEXT in result.output
    assert herdr["written"] == []


def test_running_it_again_leaves_a_manifest_it_cant_read_alone(herdr: dict) -> None:
    # Someone edited the manifest and left it as YAML that doesn't parse (an
    # unquoted colon in the description): it's still theirs, not a missing one.
    herdr["registry"].set(HerdrPaneMapping(room="checkout", handle="scribe", pane="w5:p3"))
    herdr["hub"]["scribe"] = "description: Combat designer. Owns how fights play: weapons\n"
    result = _enroll()
    assert result.exit_code == 0, result.output
    assert herdr["written"] == []


def test_running_it_again_with_a_description_updates_just_that(herdr: dict) -> None:
    herdr["registry"].set(HerdrPaneMapping(room="checkout", handle="scribe", pane="w5:p3"))
    herdr["hub"]["scribe"] = "adapter: claude_code\ndescription: old\nowner: sam\n"
    result = _enroll("--description", "Writes the release notes")
    assert result.exit_code == 0, result.output
    assert "Updated @scribe's description" in result.output
    (manifest,) = herdr["written"]
    assert (manifest.description, manifest.owner) == ("Writes the release notes", "sam")


@pytest.fixture
def first_time(herdr: dict, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The real manifest lookup, against a hub that has no agents yet.

    The hub answers a missing ``agents/<handle>`` with a 404 its OpenAPI spec
    doesn't declare, so the generated client raises on it. The fixture above
    stubs the lookup out, which is how enroll shipped unable to enroll anyone.
    """
    import httpx

    from mycelium_backend_client import Client

    asked: list[str] = []

    def hub(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.path)
        return httpx.Response(404, json={"detail": "No memory in room 'checkout'"})

    monkeypatch.setattr(
        "mycelium.client.typed_client",
        lambda *_a, **_k: Client(
            base_url="http://hub",
            raise_on_unexpected_status=True,
            httpx_args={"transport": httpx.MockTransport(hub)},
        ),
    )
    monkeypatch.setattr("mycelium.commands.agent._remote_memory_text", REAL_READ)
    return asked


def test_a_first_time_agent_is_enrolled_under_its_tab_name(
    herdr: dict, first_time: list[str]
) -> None:
    result = _enroll()
    assert result.exit_code == 0, result.output
    assert "Memory not found" not in result.output
    assert first_time == ["/api/rooms/checkout/memory/agents/release-notes"]
    assert [m.handle for m in herdr["written"]] == ["release-notes"]
    assert herdr["registry"].get("checkout", "release-notes") is not None


def test_a_first_time_agent_is_enrolled_under_a_handle_given(
    herdr: dict, first_time: list[str]
) -> None:
    result = _enroll("@scribe")
    assert result.exit_code == 0, result.output
    assert [m.handle for m in herdr["written"]] == ["scribe"]
    assert herdr["registry"].get("checkout", "scribe") is not None


def test_a_missing_memory_is_none_and_a_hub_error_still_raises() -> None:
    import httpx

    from mycelium.commands.agent import _remote_memory_text
    from mycelium_backend_client import Client
    from mycelium_backend_client.errors import UnexpectedStatus

    def client(status: int) -> Client:
        return Client(
            base_url="http://hub",
            raise_on_unexpected_status=True,
            httpx_args={
                "transport": httpx.MockTransport(
                    lambda _r: httpx.Response(status, json={"detail": "Memory not found"})
                )
            },
        )

    assert _remote_memory_text(client(404), "checkout", "agents/scribe") is None
    # "Couldn't look" must never read as "not there".
    with pytest.raises(UnexpectedStatus):
        _remote_memory_text(client(500), "checkout", "agents/scribe")


def test_outside_a_herdr_pane_it_says_so(herdr: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HERDR_PANE_ID")
    result = _enroll()
    assert result.exit_code == 1
    assert "Not in a herdr pane" in result.output
    assert herdr["written"] == []
