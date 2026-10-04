# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Who is calling (``mycelium.caller``), and ``mycelium join`` / ``leave``.

The order of sources is the contract: a flag, then the environment, then this
folder's membership, then the machine. A membership has to change nothing for a
folder that never joined, and has to lose to anything a process was explicitly
told.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from mycelium import caller, identity
from mycelium.cli import app
from mycelium.client import auth_headers
from mycelium.config import MyceliumConfig

runner = CliRunner()

_ENV = (
    "MYCELIUM_AGENT_HANDLE",
    "MYCELIUM_ROOM_ID",
    "MYCELIUM_CHANNEL_ID",
    "MYCELIUM_API_URL",
    "MYCELIUM_AGENT_AUTH_TOKEN",
    "MYCELIUM_AGENT_AUTH_CLIENT_ID",
    "MYCELIUM_AGENT_AUTH_CLIENT_SECRET",
)


@pytest.fixture(autouse=True)
def _clean(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for name in _ENV:
        monkeypatch.delenv(name, raising=False)
    # No hub in these tests: "who does the hub say I am" answers nothing.
    monkeypatch.setattr(identity, "_hub_whoami", lambda _config: None)
    identity._WHOAMI_CACHE.clear()
    return isolated_home


def _join(folder: Path, **overrides: Any) -> caller.Membership:
    fields: dict[str, Any] = {
        "hub": "http://hub.test:8000",
        "room": "checkout",
        "handle": "builder",
        "token": None,
        "token_expires_at": None,
    }
    fields.update(overrides)
    return caller.save_membership(folder, **fields)


# ── a folder that never joined is unchanged ──────────────────────────────────


def test_without_a_membership_the_machine_answers(isolated_home: Path):
    config = MyceliumConfig.load()
    assert caller.find_membership() is None
    assert caller.hub(config).source == caller.MACHINE
    assert caller.room(config).source == caller.DEFAULT
    assert caller.config_overlay() == {}


# ── a membership answers for its folder and everything below it ─────────────


def test_a_membership_names_the_hub_room_and_handle(isolated_home: Path, monkeypatch):
    _join(isolated_home)
    work = isolated_home / "src" / "deep"
    work.mkdir(parents=True)
    monkeypatch.chdir(work)

    config = MyceliumConfig.load()
    assert config.server.api_url == "http://hub.test:8000"
    assert caller.room(config) == caller.Answer("checkout", caller.MEMBERSHIP)
    assert caller.handle(config) == caller.Answer("builder", caller.MEMBERSHIP)
    assert identity.resolve_actor(config) == "builder"


def test_the_environment_beats_a_membership(isolated_home: Path, monkeypatch):
    _join(isolated_home)
    monkeypatch.setenv("MYCELIUM_AGENT_HANDLE", "reviewer")
    monkeypatch.setenv("MYCELIUM_ROOM_ID", "other-room")
    monkeypatch.setenv("MYCELIUM_API_URL", "http://env.test:9000")

    config = MyceliumConfig.load()
    assert config.server.api_url == "http://env.test:9000"
    assert caller.handle(config).value == "reviewer"
    assert caller.room(config).value == "other-room"
    assert caller.hub(config).source == caller.ENVIRONMENT


def test_a_flag_beats_everything(isolated_home: Path, monkeypatch):
    _join(isolated_home)
    monkeypatch.setenv("MYCELIUM_AGENT_HANDLE", "reviewer")
    config = MyceliumConfig.load()
    assert identity.resolve_actor(config, "lead") == "lead"
    assert caller.room(config, "flagged").value == "flagged"


# ── the credential ───────────────────────────────────────────────────────────


def test_a_membership_token_is_used_for_its_own_member(isolated_home: Path):
    _join(isolated_home, token="tok-builder", token_expires_at="2999-01-01T00:00:00+00:00")
    config = MyceliumConfig.load()
    assert auth_headers(config) == {"Authorization": "Bearer tok-builder"}
    assert auth_headers(config, handle="builder") == {"Authorization": "Bearer tok-builder"}


def test_a_membership_token_is_not_lent_to_another_handle(isolated_home: Path):
    _join(isolated_home, token="tok-builder")
    config = MyceliumConfig.load()
    assert auth_headers(config, handle="someone-else") == {}


def test_an_expired_membership_token_is_not_sent(isolated_home: Path):
    _join(isolated_home, token="tok-old", token_expires_at="2000-01-01T00:00:00+00:00")
    assert auth_headers(MyceliumConfig.load()) == {}


# ── the saved file ───────────────────────────────────────────────────────────


def test_a_membership_is_private_and_ignored_by_git(isolated_home: Path):
    member = _join(isolated_home, token="secret")
    assert stat.S_IMODE(member.path.stat().st_mode) == 0o600
    ignore = (member.path.parent / ".gitignore").read_text().split()
    assert caller.MEMBERSHIP_FILE in ignore
    assert ".gitignore" in ignore


def test_explain_reports_where_each_answer_came_from_but_never_the_token(isolated_home: Path):
    _join(isolated_home, token="secret")
    rows = {q: (v, s) for q, v, s in caller.explain(MyceliumConfig.load())}
    assert rows["handle"] == ("builder", caller.MEMBERSHIP)
    assert rows["credential"] == ("a token", caller.MEMBERSHIP)
    assert "secret" not in json.dumps(rows)


# ── mycelium join / leave ────────────────────────────────────────────────────


class _Hub:
    """Stands in for ``POST /api/joins/redeem``."""

    def __init__(self, status: int = 200, body: dict | None = None) -> None:
        self.calls: list[tuple[str, dict, dict]] = []
        self.status = status
        self.body = body or {
            "room": "checkout",
            "handle": "builder",
            "token": None,
            "token_expires_at": None,
        }

    def post(self, url: str, *, json: dict, timeout: float, **kwargs: Any) -> httpx.Response:
        self.calls.append((url, json, kwargs))
        return httpx.Response(self.status, json=self.body, request=httpx.Request("POST", url))


@pytest.fixture
def hub(monkeypatch: pytest.MonkeyPatch) -> _Hub:
    fake = _Hub()
    monkeypatch.setattr("mycelium.commands.join.httpx.post", fake.post)
    return fake


def test_join_saves_the_membership_and_sends_no_credential(isolated_home: Path, hub: _Hub):
    result = runner.invoke(app, ["join", "abcd-efgh-jkmn", "--hub", "http://hub.test:8000/"])
    assert result.exit_code == 0, result.output
    url, body, extra = hub.calls[0]
    assert url == "http://hub.test:8000/api/joins/redeem"
    assert body == {"code": "abcd-efgh-jkmn"}
    assert "headers" not in extra
    member = caller.find_membership()
    assert member is not None
    assert (member.hub, member.room, member.handle) == (
        "http://hub.test:8000",
        "checkout",
        "builder",
    )


def test_join_refuses_a_folder_that_belongs_to_a_member_without_spending_the_code(
    isolated_home: Path, hub: _Hub
):
    _join(isolated_home, handle="reviewer")
    result = runner.invoke(app, ["join", "abcd-efgh-jkmn", "--hub", "http://hub.test:8000"])
    assert result.exit_code == 1
    assert hub.calls == []
    replaced = runner.invoke(
        app, ["join", "abcd-efgh-jkmn", "--hub", "http://hub.test:8000", "--replace"]
    )
    assert replaced.exit_code == 0, replaced.output
    member = caller.find_membership()
    assert member is not None
    assert member.handle == "builder"


def test_join_reports_a_refused_code(isolated_home: Path, monkeypatch: pytest.MonkeyPatch):
    fake = _Hub(status=400, body={"detail": "that join code isn't valid"})
    monkeypatch.setattr("mycelium.commands.join.httpx.post", fake.post)
    result = runner.invoke(app, ["join", "nope-nope-nope", "--hub", "http://hub.test:8000"])
    assert result.exit_code == 1
    assert "isn't valid" in result.output
    assert caller.find_membership() is None


def test_leave_forgets_the_membership(isolated_home: Path):
    _join(isolated_home)
    result = runner.invoke(app, ["leave"])
    assert result.exit_code == 0, result.output
    assert caller.find_membership() is None


# ── saving config next to a membership ───────────────────────────────────────


def _global_toml(home: Path) -> dict:
    import toml

    return toml.load(home / ".mycelium" / "config.toml")


def test_config_set_runner_host_is_saved(isolated_home: Path):
    """`config set runner.host omnigent` said it was set and wrote nothing."""
    result = runner.invoke(app, ["config", "set", "runner.host", "omnigent"])
    assert result.exit_code == 0, result.output
    assert _global_toml(isolated_home)["runner"]["host"] == "omnigent"
    assert MyceliumConfig.load().runner.host == "omnigent"


def test_beside_a_project_config_every_other_section_is_saved_globally(
    isolated_home: Path, monkeypatch
):
    """With a project .mycelium/config.toml, only its own sections go there;
    every other one, runner included, goes to the machine's config."""
    project = isolated_home / "proj"
    (project / ".mycelium").mkdir(parents=True)
    (project / ".mycelium" / "config.toml").write_text('[rooms]\nactive = "design"\n')
    monkeypatch.chdir(project)

    config = MyceliumConfig.load()
    config.runner.host = "omnigent"
    config.save()

    saved = set(_global_toml(isolated_home))
    assert "runner" in saved
    assert saved.isdisjoint(MyceliumConfig.PROJECT_ONLY_SECTIONS)
    assert MyceliumConfig.load().runner.host == "omnigent"


def test_saving_in_a_joined_folder_leaves_the_machines_hub_and_room_alone(
    isolated_home: Path, monkeypatch
):
    config = MyceliumConfig.load()
    config.server.api_url = "http://my-own-hub:8000"
    config.rooms.active = None
    config.save()

    work = isolated_home / "work"
    work.mkdir()
    _join(work, hub="http://someone-elses-hub:8000", room="their-room")
    monkeypatch.chdir(work)

    joined = MyceliumConfig.load()
    assert joined.server.api_url == "http://someone-elses-hub:8000"
    joined.runner.host = "omnigent"
    joined.save()

    saved = _global_toml(isolated_home)
    assert saved["server"]["api_url"] == "http://my-own-hub:8000"
    assert saved["runner"]["host"] == "omnigent"
    assert "active" not in saved.get("rooms", {})


def test_a_hub_you_set_in_a_joined_folder_is_still_saved(isolated_home: Path, monkeypatch):
    """Only what the membership put there is taken back out."""
    work = isolated_home / "work"
    work.mkdir()
    _join(work, hub="http://someone-elses-hub:8000")
    monkeypatch.chdir(work)
    config = MyceliumConfig.load()
    config.server.api_url = "http://chosen-on-purpose:8000"
    config.save()
    assert _global_toml(isolated_home)["server"]["api_url"] == "http://chosen-on-purpose:8000"


# ── a herdr pane names the agent the registry maps it to ────────────────────


def _map(room: str, handle: str, pane: str) -> None:
    from mycelium.integrations.herdr.bridge import HerdrPaneMapping, HerdrRegistry

    HerdrRegistry().set(HerdrPaneMapping(room=room, handle=handle, pane=pane, kind="claude"))


def _identity(home: Path, name: str, folder: Path | None = None) -> None:
    path = (folder or home) / ".mycelium" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'[identity]\nname = "{name}"\n')


def test_an_agent_herdr_restored_without_its_environment_is_still_itself(
    isolated_home: Path, monkeypatch
):
    """herdr restores a pane under the same id but without the env it was started with."""
    _identity(isolated_home, "operator")
    _map("checkout", "project-mgmt", "w1:p2")
    monkeypatch.setenv("HERDR_PANE_ID", "w1:p2")

    config = MyceliumConfig.load()
    assert caller.handle(config) == caller.Answer("project-mgmt", caller.PANE)
    assert caller.room(config) == caller.Answer("checkout", caller.PANE)
    assert identity.resolve_actor(config) == "project-mgmt"


def test_the_environment_beats_the_pane_and_the_pane_beats_a_membership(
    isolated_home: Path, monkeypatch
):
    """Several agents share one checkout, so the pane says more than the folder."""
    _join(isolated_home, handle="builder")
    _map("checkout", "coder", "w1:p3")
    monkeypatch.setenv("HERDR_PANE_ID", "w1:p3")
    config = MyceliumConfig.load()
    assert caller.handle(config) == caller.Answer("coder", caller.PANE)

    monkeypatch.setenv("MYCELIUM_AGENT_HANDLE", "coder2")
    assert caller.handle(config) == caller.Answer("coder2", caller.ENVIRONMENT)


def test_a_pane_the_registry_does_not_map_says_nothing(isolated_home: Path, monkeypatch):
    _identity(isolated_home, "operator")
    _map("checkout", "coder", "w1:p3")
    monkeypatch.setenv("HERDR_PANE_ID", "w9:p1")
    config = MyceliumConfig.load()
    assert caller.pane_agent() is None
    assert caller.handle(config) == caller.Answer("operator", caller.MACHINE)


def test_a_pane_mapped_to_two_agents_guesses_neither_and_says_so(
    isolated_home: Path, monkeypatch, capsys
):
    _identity(isolated_home, "operator")
    _map("checkout", "coder", "w1:p3")
    _map("checkout", "designer", "w1:p3")
    monkeypatch.setenv("HERDR_PANE_ID", "w1:p3")
    caller._WARNED.clear()

    config = MyceliumConfig.load()
    assert caller.handle(config) == caller.Answer("operator", caller.MACHINE)
    assert caller.room(config) == caller.Answer("checkout", caller.PANE)
    err = capsys.readouterr().err
    assert "@coder, @designer" in err
    assert "--as" in err


# ── a folder config never quietly names someone else ────────────────────────


def test_an_opaque_id_in_identity_name_names_nobody(isolated_home: Path):
    _identity(isolated_home, "9907770b-3781-49ad-a242-fce7c28e5008")
    config = MyceliumConfig.load()
    assert caller.handle(config) == caller.Answer(None, caller.DEFAULT)
    assert identity.resolve_actor(config) == identity.LEGACY_ACTOR_SENTINEL


def test_saving_in_a_folder_does_not_copy_the_machines_identity_into_it(
    isolated_home: Path, monkeypatch
):
    """A folder config that names someone shadows ~/.mycelium for every folder below it."""
    import toml

    _identity(isolated_home, "operator")
    project = isolated_home / "proj"
    (project / ".mycelium").mkdir(parents=True)
    (project / ".mycelium" / "config.toml").write_text('[rooms]\nactive = "design"\n')
    monkeypatch.chdir(project)

    config = MyceliumConfig.load()
    config.set_active_room("checkout")
    config.init_project(room_name="checkout")

    folder = toml.load(project / ".mycelium" / "config.toml")
    assert "identity" not in folder
    assert folder["rooms"]["active"] == "checkout"
    assert _global_toml(isolated_home)["identity"]["name"] == "operator"


def test_an_identity_a_folder_set_itself_stays_the_folders(isolated_home: Path, monkeypatch):
    import toml

    _identity(isolated_home, "operator")
    project = isolated_home / "proj"
    _identity(isolated_home, "folder-bot", folder=project)
    monkeypatch.chdir(project)

    config = MyceliumConfig.load()
    assert config.identity.name == "folder-bot"
    assert config.identity_name_path() == project / ".mycelium" / "config.toml"
    config.runner.host = "omnigent"
    config.save()

    assert toml.load(project / ".mycelium" / "config.toml")["identity"] == {"name": "folder-bot"}
    assert _global_toml(isolated_home)["identity"]["name"] == "operator"


def test_whoami_sources_names_the_file_identity_came_from(isolated_home: Path, monkeypatch):
    project = isolated_home / "proj"
    _identity(isolated_home, "9907770b-3781-49ad-a242-fce7c28e5008", folder=project)
    monkeypatch.chdir(project)
    result = runner.invoke(app, ["whoami", "--sources"])
    assert result.exit_code == 0, result.output
    out = "".join(result.output.split())
    assert f"identity.name:{project / '.mycelium' / 'config.toml'}" in out
    assert "notahandle" in out
