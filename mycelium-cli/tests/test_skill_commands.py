# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for ``mycelium skill`` (set / get / ls / rm).

Node-free and file-free: the skills store lives on the hub, so the API ``.sync``
functions are stubbed. Skills are global (not room-scoped).
"""

from __future__ import annotations

import datetime
from typing import Any

import pytest
from typer.testing import CliRunner

from mycelium.commands import skill as skill_cmd
from mycelium_backend_client.errors import UnexpectedStatus

runner = CliRunner()

STAMP = datetime.datetime(2026, 6, 1, 12, 30, tzinfo=datetime.UTC)


@pytest.fixture(autouse=True)
def _home(isolated_home) -> None:
    """Every skill test runs under the temp ``~/.mycelium``."""


class _Client:
    def __enter__(self):
        return object()

    def __exit__(self, *_a):
        return False


@pytest.fixture(autouse=True)
def _hub(monkeypatch: pytest.MonkeyPatch) -> None:
    """No command may open a real connection."""
    monkeypatch.setattr(skill_cmd, "_get_client", lambda: _Client())


def _skill_read(name: str, **overrides: Any):
    from mycelium_backend_client.models import SkillRead

    fields: dict[str, Any] = {
        "name": name,
        "description": "",
        "body": "",
        "created_by": "tester",
        "version": 1,
        "created_at": STAMP,
        "updated_at": STAMP,
    }
    fields.update(overrides)
    return SkillRead(**fields)


def test_skill_set(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list = []

    def _sync(*, client, body):
        captured.append(body)
        return _skill_read(body.name, version=1)

    monkeypatch.setattr(
        "mycelium_backend_client.api.skills.create_skill_api_skills_post.sync", _sync
    )
    result = runner.invoke(
        skill_cmd.app,
        ["set", "summarize-room", "Read decisions/ and brief.", "--desc", "A brief"],
    )
    assert result.exit_code == 0, result.output
    assert captured[0].name == "summarize-room"
    assert captured[0].body == "Read decisions/ and brief."
    assert captured[0].description == "A brief"
    assert "Skill set" in result.output


def test_skill_set_from_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list = []

    def _sync(*, client, body):
        captured.append(body)
        return _skill_read(body.name)

    monkeypatch.setattr(
        "mycelium_backend_client.api.skills.create_skill_api_skills_post.sync", _sync
    )
    result = runner.invoke(skill_cmd.app, ["set", "s", "--file", "-"], input="from stdin")
    assert result.exit_code == 0, result.output
    assert captured[0].body == "from stdin"


def test_skill_ls(monkeypatch: pytest.MonkeyPatch) -> None:
    from mycelium_backend_client.models import SkillListResponse

    def _sync(*, client):
        return SkillListResponse(
            skills=[_skill_read("alpha", description="the alpha skill")], total=1
        )

    monkeypatch.setattr("mycelium_backend_client.api.skills.list_skills_api_skills_get.sync", _sync)
    result = runner.invoke(skill_cmd.app, ["ls"])
    assert result.exit_code == 0, result.output
    assert "/alpha" in result.output
    assert "the alpha skill" in result.output


def test_skill_ls_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    from mycelium_backend_client.models import SkillListResponse

    monkeypatch.setattr(
        "mycelium_backend_client.api.skills.list_skills_api_skills_get.sync",
        lambda *, client: SkillListResponse(skills=[], total=0),
    )
    result = runner.invoke(skill_cmd.app, ["ls"])
    assert result.exit_code == 0
    assert "No skills found" in result.output


def test_skill_get(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "mycelium_backend_client.api.skills.get_skill_api_skills_name_get.sync",
        lambda *, name, client: _skill_read(name, body="the body", description="d"),
    )
    result = runner.invoke(skill_cmd.app, ["get", "alpha"])
    assert result.exit_code == 0, result.output
    assert "/alpha" in result.output
    assert "the body" in result.output


def test_skill_get_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def _sync(*, name, client):
        raise UnexpectedStatus(404, b"")

    monkeypatch.setattr(
        "mycelium_backend_client.api.skills.get_skill_api_skills_name_get.sync", _sync
    )
    result = runner.invoke(skill_cmd.app, ["get", "nope"])
    assert result.exit_code == 1
    assert "Not found" in result.output


def test_skill_rm(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Resp:
        status_code = 204

    monkeypatch.setattr(
        "mycelium_backend_client.api.skills.delete_skill_api_skills_name_delete.sync_detailed",
        lambda *, name, client: _Resp(),
    )
    result = runner.invoke(skill_cmd.app, ["rm", "alpha"])
    assert result.exit_code == 0, result.output
    assert "Skill removed" in result.output


def test_skill_rm_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Resp:
        status_code = 404

    monkeypatch.setattr(
        "mycelium_backend_client.api.skills.delete_skill_api_skills_name_delete.sync_detailed",
        lambda *, name, client: _Resp(),
    )
    result = runner.invoke(skill_cmd.app, ["rm", "nope"])
    assert result.exit_code == 1
    assert "Not found" in result.output
