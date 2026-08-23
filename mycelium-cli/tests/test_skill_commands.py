# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for ``mycelium skill`` (set / get / ls / rm).

Node-free and file-free: skills live on the hub (the room's skills/ namespace),
so the API ``.sync`` functions are stubbed. Room-scoped, like memory.
"""

from __future__ import annotations

import datetime
from typing import Any

import pytest
from mycelium_backend_client.errors import UnexpectedStatus
from typer.testing import CliRunner

from mycelium.commands import skill as skill_cmd

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

    def _sync(*, room_name, client, body):
        captured.append((room_name, body))
        return _skill_read(body.name, version=1)

    monkeypatch.setattr(
        "mycelium_backend_client.api.skills.create_skill_api_rooms_room_name_skills_post.sync",
        _sync,
    )
    result = runner.invoke(
        skill_cmd.app,
        [
            "set",
            "summarize-room",
            "Read decisions/ and brief.",
            "--desc",
            "A brief",
            "--room",
            "demo",
        ],
    )
    assert result.exit_code == 0, result.output
    room_name, body = captured[0]
    assert room_name == "demo"
    assert body.name == "summarize-room"
    assert body.body == "Read decisions/ and brief."
    assert body.description == "A brief"
    assert "Skill set" in result.output


def test_skill_set_from_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list = []

    def _sync(*, room_name, client, body):
        captured.append(body)
        return _skill_read(body.name)

    monkeypatch.setattr(
        "mycelium_backend_client.api.skills.create_skill_api_rooms_room_name_skills_post.sync",
        _sync,
    )
    result = runner.invoke(
        skill_cmd.app, ["set", "s", "--file", "-", "--room", "demo"], input="from stdin"
    )
    assert result.exit_code == 0, result.output
    assert captured[0].body == "from stdin"


def test_skill_ls(monkeypatch: pytest.MonkeyPatch) -> None:
    from mycelium_backend_client.models import SkillListResponse

    def _sync(*, room_name, client):
        return SkillListResponse(
            skills=[_skill_read("alpha", description="the alpha skill")], total=1
        )

    monkeypatch.setattr(
        "mycelium_backend_client.api.skills.list_skills_api_rooms_room_name_skills_get.sync", _sync
    )
    result = runner.invoke(skill_cmd.app, ["ls", "--room", "demo"])
    assert result.exit_code == 0, result.output
    assert "/alpha" in result.output
    assert "the alpha skill" in result.output


def test_skill_ls_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    from mycelium_backend_client.models import SkillListResponse

    monkeypatch.setattr(
        "mycelium_backend_client.api.skills.list_skills_api_rooms_room_name_skills_get.sync",
        lambda *, room_name, client: SkillListResponse(skills=[], total=0),
    )
    result = runner.invoke(skill_cmd.app, ["ls", "--room", "demo"])
    assert result.exit_code == 0
    assert "No skills found" in result.output


def test_skill_get(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "mycelium_backend_client.api.skills.get_skill_api_rooms_room_name_skills_name_get.sync",
        lambda *, room_name, name, client: _skill_read(name, body="the body", description="d"),
    )
    result = runner.invoke(skill_cmd.app, ["get", "alpha", "--room", "demo"])
    assert result.exit_code == 0, result.output
    assert "/alpha" in result.output
    assert "the body" in result.output


def test_skill_get_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def _sync(*, room_name, name, client):
        raise UnexpectedStatus(404, b"")

    monkeypatch.setattr(
        "mycelium_backend_client.api.skills.get_skill_api_rooms_room_name_skills_name_get.sync",
        _sync,
    )
    result = runner.invoke(skill_cmd.app, ["get", "nope", "--room", "demo"])
    assert result.exit_code == 1
    assert "Not found" in result.output


def test_skill_set_403_surfaces_backend_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 403 from the hub must show the backend's ``detail`` message, not just the code."""
    import json

    detail_msg = (
        "handle 'cli-user' is not the authenticated principal '@julvalen@cisco.com' "
        "and has granted it no access"
    )

    def _sync(*, room_name, client, body):
        raise UnexpectedStatus(403, json.dumps({"detail": detail_msg}).encode())

    monkeypatch.setattr(
        "mycelium_backend_client.api.skills.create_skill_api_rooms_room_name_skills_post.sync",
        _sync,
    )
    result = runner.invoke(skill_cmd.app, ["set", "alpha", "do something", "--room", "demo"])
    assert result.exit_code == 1
    assert "HTTP 403" in result.output
    assert "cli-user" in result.output
    assert "julvalen@cisco.com" in result.output


def test_skill_rm(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Resp:
        status_code = 204

    monkeypatch.setattr(
        "mycelium_backend_client.api.skills.delete_skill_api_rooms_room_name_skills_name_delete.sync_detailed",
        lambda *, room_name, name, client: _Resp(),
    )
    result = runner.invoke(skill_cmd.app, ["rm", "alpha", "--room", "demo"])
    assert result.exit_code == 0, result.output
    assert "Skill removed" in result.output


def test_skill_rm_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Resp:
        status_code = 404

    monkeypatch.setattr(
        "mycelium_backend_client.api.skills.delete_skill_api_rooms_room_name_skills_name_delete.sync_detailed",
        lambda *, room_name, name, client: _Resp(),
    )
    result = runner.invoke(skill_cmd.app, ["rm", "nope", "--room", "demo"])
    assert result.exit_code == 1
    assert "Not found" in result.output
