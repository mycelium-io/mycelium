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
from tests.conftest import install_stand_in_hub

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


# ── the desktop app in client mode names the hub ────────────────────────────

APP_HUB = "https://hub.example.com"


def _app(home: Path, mode: str = "client", hub_url: str | None = APP_HUB + "/") -> None:
    folder = home / ".mycelium"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "desktop.json").write_text(json.dumps({"mode": mode, "hubUrl": hub_url}))


def _config_toml(home: Path, api_url: str) -> None:
    (home / ".mycelium" / "config.toml").write_text(f'[server]\napi_url = "{api_url}"\n')


def test_a_fresh_home_in_client_mode_uses_the_app_s_hub(isolated_home: Path):
    """Only the app's setting, as a first run in client mode leaves it."""
    _app(isolated_home)
    config = MyceliumConfig.load()
    assert config.server.api_url == APP_HUB
    assert caller.hub(config) == caller.Answer(APP_HUB, caller.DESKTOP)
    assert ("hub", APP_HUB, caller.DESKTOP) in caller.explain(config)


def test_whoami_sources_says_the_hub_came_from_the_app(isolated_home: Path):
    _app(isolated_home)
    result = runner.invoke(app, ["whoami", "--sources"])
    assert result.exit_code == 0, result.output
    assert APP_HUB in result.output
    assert "desktop app" in result.output


def test_a_hub_this_machine_set_wins_over_the_app(isolated_home: Path):
    _app(isolated_home)
    _config_toml(isolated_home, "https://other.example.com")
    config = MyceliumConfig.load()
    assert caller.hub(config) == caller.Answer("https://other.example.com", caller.MACHINE)


def test_a_saved_default_hub_is_no_hub_of_its_own(isolated_home: Path):
    """A whole-config save writes the default too; it doesn't hide the app's hub."""
    _app(isolated_home)
    _config_toml(isolated_home, caller.DEFAULT_HUB)
    assert MyceliumConfig.load().server.api_url == APP_HUB


def test_the_environment_wins_over_the_app(isolated_home: Path, monkeypatch):
    _app(isolated_home)
    monkeypatch.setenv("MYCELIUM_API_URL", "http://env.test:9000")
    config = MyceliumConfig.load()
    assert caller.hub(config) == caller.Answer("http://env.test:9000", caller.ENVIRONMENT)


@pytest.mark.parametrize(("mode", "hub_url"), [("hub", None), ("client", None), ("client", "")])
def test_an_app_running_its_own_hub_or_naming_none_changes_nothing(
    isolated_home: Path, mode: str, hub_url: str | None
):
    _app(isolated_home, mode=mode, hub_url=hub_url)
    config = MyceliumConfig.load()
    assert config.server.api_url == caller.DEFAULT_HUB
    assert caller.hub(config).source == caller.MACHINE


def test_login_asks_the_app_s_hub_what_it_trusts(isolated_home: Path, monkeypatch):
    from mycelium.commands import login

    _app(isolated_home)
    asked: list[str] = []

    def answer(request: httpx.Request):
        asked.append(str(request.url))
        return 503, {"detail": "starting"}

    install_stand_in_hub(monkeypatch).answer = answer
    login._hub_issuers(MyceliumConfig.load())
    assert asked
    assert asked[0].startswith(APP_HUB + "/health")


def test_saving_the_config_never_copies_the_app_s_hub(isolated_home: Path):
    """Read, never written: leave client mode and the CLI follows the app."""
    _app(isolated_home)
    config = MyceliumConfig.load()
    config.save()
    saved = (isolated_home / ".mycelium" / "config.toml").read_text()
    assert APP_HUB not in saved
    _app(isolated_home, mode="hub", hub_url=None)
    assert MyceliumConfig.load().server.api_url == caller.DEFAULT_HUB


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
        self.calls: list[tuple[str, dict, httpx.Headers]] = []
        self.status = status
        self.body = body or {
            "room": "checkout",
            "handle": "builder",
            "token": None,
            "token_expires_at": None,
        }

    def answer(self, request: httpx.Request) -> tuple[int, dict]:
        self.calls.append((str(request.url), json.loads(request.content), request.headers))
        return self.status, self.body

    def install(self, monkeypatch: pytest.MonkeyPatch) -> _Hub:
        install_stand_in_hub(monkeypatch).answer = self.answer
        return self


@pytest.fixture
def hub(monkeypatch: pytest.MonkeyPatch) -> _Hub:
    return _Hub().install(monkeypatch)


def test_join_saves_the_membership_and_sends_no_credential(isolated_home: Path, hub: _Hub):
    result = runner.invoke(app, ["join", "abcd-efgh-jkmn", "--hub", "http://hub.test:8000/"])
    assert result.exit_code == 0, result.output
    url, body, headers = hub.calls[0]
    assert url == "http://hub.test:8000/api/joins/redeem"
    assert body == {"code": "abcd-efgh-jkmn"}
    assert "authorization" not in headers
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
    _Hub(status=400, body={"detail": "that join code isn't valid"}).install(monkeypatch)
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


# ── a pane's agent finds the token the runner keeps for it ──────────────────


def _jwt(exp: float) -> str:
    import base64

    def seg(data: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    return f"{seg({'alg': 'ES256'})}.{seg({'sub': 'coder', 'exp': exp})}.sig"


def _keep(room: str, handle: str, token: str) -> None:
    from mycelium.agent_credentials import member_token_path

    path = member_token_path(room, handle)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token)


def test_an_agent_started_before_panes_got_a_token_file_finds_its_token(
    isolated_home: Path, monkeypatch
):
    """No token variable in its environment: the pane's agent says which file."""
    import time

    token = _jwt(time.time() + 3600)
    _keep("checkout", "coder", token)
    _map("checkout", "coder", "w1:p2")
    monkeypatch.setenv("HERDR_PANE_ID", "w1:p2")

    answer = caller.credential(MyceliumConfig.load())
    assert answer == caller.Answer(token, caller.PANE)
    assert auth_headers(MyceliumConfig.load()) == {"Authorization": f"Bearer {token}"}


def test_a_pane_the_runner_started_finds_its_token_by_its_environment(
    isolated_home: Path, monkeypatch
):
    import time

    token = _jwt(time.time() + 3600)
    _keep("checkout", "coder", token)
    monkeypatch.setenv("MYCELIUM_AGENT_PANE", "1")
    monkeypatch.setenv("MYCELIUM_AGENT_HANDLE", "coder")
    monkeypatch.setenv("MYCELIUM_ROOM_ID", "checkout")

    assert caller.credential(MyceliumConfig.load()) == caller.Answer(token, caller.PANE)


def test_an_expired_kept_token_is_not_sent(isolated_home: Path, monkeypatch):
    _keep("checkout", "coder", _jwt(1000.0))
    _map("checkout", "coder", "w1:p2")
    monkeypatch.setenv("HERDR_PANE_ID", "w1:p2")

    assert caller.credential(MyceliumConfig.load()).value is None


def test_another_agents_pane_in_a_joined_folder_never_carries_the_membership_token(
    isolated_home: Path, monkeypatch
):
    """The folder joined as @agora-coding; @builder works in it with no kept token yet."""
    _join(isolated_home, handle="agora-coding", token="tok-agora")
    _map("checkout", "builder", "w1:p2")
    monkeypatch.setenv("HERDR_PANE_ID", "w1:p2")

    config = MyceliumConfig.load()
    assert caller.handle(config) == caller.Answer("builder", caller.PANE)
    assert caller.credential(config).value is None
    assert auth_headers(config) == {}


def test_the_joined_agents_own_pane_still_carries_its_membership_token(
    isolated_home: Path, monkeypatch
):
    _join(isolated_home, handle="agora-coding", token="tok-agora")
    _map("checkout", "agora-coding", "w1:p2")
    monkeypatch.setenv("HERDR_PANE_ID", "w1:p2")

    assert caller.credential(MyceliumConfig.load()) == caller.Answer("tok-agora", caller.MEMBERSHIP)


def test_a_pane_mapped_to_two_agents_never_falls_to_the_folders_membership(
    isolated_home: Path, monkeypatch
):
    _identity(isolated_home, "operator")
    _join(isolated_home, handle="agora-coding", token="tok-agora")
    _map("checkout", "coder", "w1:p3")
    _map("checkout", "designer", "w1:p3")
    monkeypatch.setenv("HERDR_PANE_ID", "w1:p3")
    caller._WARNED.clear()

    config = MyceliumConfig.load()
    assert caller.handle(config) == caller.Answer("operator", caller.MACHINE)
    assert caller.credential(config).value is None


def test_a_persons_terminal_never_reads_an_agents_kept_token(isolated_home: Path, monkeypatch):
    import time

    _keep("checkout", "coder", _jwt(time.time() + 3600))
    monkeypatch.setenv("MYCELIUM_AGENT_HANDLE", "coder")
    monkeypatch.setenv("MYCELIUM_ROOM_ID", "checkout")

    assert caller.credential(MyceliumConfig.load()).value is None


# ── a folder config never quietly names someone else ────────────────────────


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
    _identity(isolated_home, "someone-else", folder=project)
    monkeypatch.chdir(project)
    result = runner.invoke(app, ["whoami", "--sources"])
    assert result.exit_code == 0, result.output
    out = "".join(result.output.split())
    assert f"identity.name:{project / '.mycelium' / 'config.toml'}" in out
