# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium user`` / ``whoami`` / ``iam`` read and write the hub's user store.

People span rooms, so the user store is global — but global still means the
hub's, not a per-machine `~/.mycelium/users/` replica. A spoke that kept its own
copy showed no users while the hub and the app showed several, and `iam` wrote a
record the hub never saw. These tests run under a temp home with no user files:
everything below is served by, or lands on, the stubbed hub.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from mycelium.cli import app as root_app
from mycelium.commands import user as user_cmd
from mycelium.protocol import UserManifest

runner = CliRunner()

USER_GET_SYNC = "mycelium_backend_client.api.users.get_user_api_users_handle_get.sync"
USER_LIST_SYNC = "mycelium_backend_client.api.users.list_users_api_users_get.sync"
USER_CREATE_SYNC = "mycelium_backend_client.api.users.create_user_api_users_post.sync"
ROOMS_LIST_SYNC = "mycelium_backend_client.api.rooms.list_rooms_api_rooms_get.sync"


@pytest.fixture(autouse=True)
def _home(isolated_home) -> None:  # noqa: ANN001
    """Every test here runs under the temp ``~/.mycelium`` — deliberately empty."""


# No client stub: ``typed_client`` only constructs a client, and every generated
# ``.sync`` a command reaches is scripted below, so nothing leaves the process.


def _user_read(handle: str, *, owns: list[dict[str, str]] | None = None, **fields: Any):  # noqa: ANN202
    from mycelium_backend_client.models import OwnedAgentRead, UserRead

    return UserRead(
        handle=handle,
        display_name=fields.get("display_name", ""),
        teams=fields.get("teams", []),
        notify=fields.get("notify"),
        owns=[OwnedAgentRead(**o) for o in owns or []],
    )


def _stub(monkeypatch: pytest.MonkeyPatch, target: str, outcome: Any) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def _sync(**kwargs: Any):
        calls.append(kwargs)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome(**kwargs) if callable(outcome) else outcome

    monkeypatch.setattr(target, _sync)
    return calls


def _not_found() -> Exception:
    from mycelium_backend_client.errors import UnexpectedStatus

    return UnexpectedStatus(404, b'{"detail":"User not found"}')


# ── reads ────────────────────────────────────────────────────────────────────


def test_user_ls_lists_what_the_hub_serves_with_no_local_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mycelium_backend_client.models import UserListResponse

    _stub(
        monkeypatch,
        USER_LIST_SYNC,
        UserListResponse(
            users=[_user_read("avery", display_name="Avery Quinn", teams=["core"])], total=1
        ),
    )

    result = runner.invoke(user_cmd.app, ["ls"])
    assert result.exit_code == 0, result.output
    assert "@avery" in result.output
    assert "No users registered" not in result.output


def test_user_ls_says_none_only_when_the_hub_serves_none(monkeypatch: pytest.MonkeyPatch) -> None:
    from mycelium_backend_client.models import UserListResponse

    _stub(monkeypatch, USER_LIST_SYNC, UserListResponse(users=[], total=0))

    result = runner.invoke(user_cmd.app, ["ls"])
    assert result.exit_code == 0, result.output
    assert "No users registered" in result.output


def test_user_ls_reports_an_unreachable_hub_rather_than_zero_users(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub(monkeypatch, USER_LIST_SYNC, httpx.ConnectError("connection refused"))

    result = runner.invoke(user_cmd.app, ["ls"])
    assert result.exit_code == 1
    assert "No users registered" not in result.output


def test_load_user_normalizes_the_handle_it_asks_the_hub_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _stub(monkeypatch, USER_GET_SYNC, _user_read("avery", display_name="Avery"))

    loaded = user_cmd.load_user("@Avery")
    assert loaded is not None
    assert loaded.display_name == "Avery"
    assert calls[0]["handle"] == "avery"


def test_load_user_returns_none_for_a_handle_the_hub_doesnt_have(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub(monkeypatch, USER_GET_SYNC, _not_found())
    assert user_cmd.load_user("ghost") is None


def test_load_user_propagates_an_unreachable_hub(monkeypatch: pytest.MonkeyPatch) -> None:
    """404 is "no such user"; a dead hub is not — it must not read as absent."""
    _stub(monkeypatch, USER_GET_SYNC, httpx.ConnectError("connection refused"))
    with pytest.raises(httpx.ConnectError):
        user_cmd.load_user("avery")


def test_user_show_renders_the_hubs_own_owned_agent_roll_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _stub(
        monkeypatch,
        USER_GET_SYNC,
        _user_read(
            "avery",
            display_name="Avery Quinn",
            teams=["core"],
            owns=[{"room": "alpha", "handle": "a1", "adapter": "claude_code"}],
        ),
    )

    result = runner.invoke(user_cmd.app, ["show", "avery"])
    assert result.exit_code == 0, result.output
    assert "owns 1 agent(s)" in result.output
    assert "@a1" in result.output
    assert "alpha" in result.output
    # One request: the roll-up rides along with the record.
    assert len(calls) == 1


# ── writes ───────────────────────────────────────────────────────────────────


def test_user_create_posts_the_record_to_the_hub(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _stub(monkeypatch, USER_CREATE_SYNC, _user_read("avery"))

    result = runner.invoke(
        user_cmd.app,
        ["create", "avery", "--name", "Avery Quinn", "--team", "core", "--as", "julia"],
    )
    assert result.exit_code == 0, result.output
    body = calls[0]["body"]
    assert body.handle == "avery"
    assert body.display_name == "Avery Quinn"
    assert body.teams == ["core"]
    assert body.created_by == "julia"


def test_write_user_sends_no_local_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """The CLI is a client of the store, not a second writer of it."""
    from mycelium.filesystem import get_mycelium_dir

    _stub(monkeypatch, USER_CREATE_SYNC, _user_read("avery"))
    user_cmd._write_user(UserManifest(handle="avery"), created_by="tester")
    assert not (get_mycelium_dir() / "users").exists()


# ── whoami / iam ─────────────────────────────────────────────────────────────


def test_whoami_rolls_up_from_the_hub_record(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(
        monkeypatch,
        USER_GET_SYNC,
        _user_read(
            "avery",
            display_name="Avery Quinn",
            owns=[{"room": "alpha", "handle": "a1", "adapter": "claude_code"}],
        ),
    )

    result = runner.invoke(root_app, ["whoami"])
    assert result.exit_code == 0, result.output
    assert "owns 1 agent(s)" in result.output
    assert "Not registered" not in result.output


def test_whoami_rolls_up_an_unregistered_principal_from_room_manifests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A principal can own agents before it has a user record."""
    from mycelium.commands import agent as agent_cmd

    _stub(monkeypatch, USER_GET_SYNC, _not_found())
    monkeypatch.setattr(
        agent_cmd,
        "load_owned_agents",
        lambda **_kw: [("alpha", agent_cmd.AgentManifest(handle="a1", cwd="/tmp", owner="avery"))],
    )

    result = runner.invoke(root_app, ["whoami"])
    assert result.exit_code == 0, result.output
    assert "Not registered" in result.output
    assert "@a1" in result.output


def test_whoami_still_answers_with_the_hub_down(monkeypatch: pytest.MonkeyPatch) -> None:
    """Who you are on this machine is local knowledge; the roll-up isn't."""
    _stub(monkeypatch, USER_GET_SYNC, httpx.ConnectError("connection refused"))

    result = runner.invoke(root_app, ["whoami"])
    assert result.exit_code == 0, result.output
    assert "acting as" in result.output
    assert "Can't reach the hub" in result.output
    # Never the confident "you have no record" line when we couldn't look.
    assert "Not registered" not in result.output


def test_whoami_json_marks_an_unreachable_hub_rather_than_reporting_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub(monkeypatch, USER_GET_SYNC, httpx.ConnectError("connection refused"))

    result = runner.invoke(root_app, ["--json", "whoami"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["hub_reachable"] is False
    assert payload["registered"] is None
    assert payload["owns"] is None


def test_iam_sets_the_local_identity_even_when_registration_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hub outage must not leave you unable to say who you are on this machine."""
    from mycelium.config import MyceliumConfig

    _stub(monkeypatch, USER_GET_SYNC, httpx.ConnectError("connection refused"))
    _stub(monkeypatch, USER_CREATE_SYNC, httpx.ConnectError("connection refused"))

    result = runner.invoke(root_app, ["iam", "avery"])
    assert result.exit_code == 0, result.output
    assert MyceliumConfig.load().identity.name == "avery"
    assert "Not registered on the hub" in result.output
