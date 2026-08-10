# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium await`` / ``mycelium respond`` — the daemon-free participant path.

Node-free: the SLIM core is stubbed so these exercise the CLI plumbing —
room resolution, the awaited-message hand-off file that lets ``respond`` thread
onto what ``await`` surfaced, and the ``--json`` agent contract.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mycelium.cli import app
from mycelium.commands import participate
from mycelium.slim import l9

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MYCELIUM_ROOM_ID", "demo")
    monkeypatch.setattr(participate, "get_mycelium_dir", lambda: tmp_path)


def _addressed() -> dict:
    return l9.build_reply_content(
        sender="mediator",
        recipients=["me"],
        episode="urn:ioc:mycelium:episode:demo:live",
        parents=[],
        topic="urn:concept:mycelium:demo",
        text="@me what is your position?",
        message_id="tick-1",
        payload_type="tick",
    )


def test_await_prints_and_persists_addressed_message(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_await(config, room, handle, *, timeout_s=None):
        assert room == "demo" and handle == "me"
        return _addressed()

    monkeypatch.setattr(participate, "await_addressed", _fake_await)

    result = runner.invoke(app, ["await", "--handle", "me", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["message_id"] == "tick-1"
    assert payload["prompt"] == "@me what is your position?"
    assert payload["sender"] == "mediator"

    # The surfaced message is saved so a following `respond` can thread onto it.
    saved = participate._load_awaited("demo", "me")
    assert saved is not None and l9.message_id_of(saved) == "tick-1"


def test_await_timeout_exits_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_await(config, room, handle, *, timeout_s=None):
        return None

    monkeypatch.setattr(participate, "await_addressed", _fake_await)
    result = runner.invoke(app, ["await", "--handle", "me", "--timeout", "1", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["message"] is None


def test_respond_threads_onto_awaited(monkeypatch: pytest.MonkeyPatch) -> None:
    # Seed the awaited message as if `await` had just surfaced it.
    participate._save_awaited("demo", "me", _addressed())

    published: list[dict] = []

    async def _fake_publish(config, room, handle, content, **_kw):
        published.append(content)

    monkeypatch.setattr(participate, "publish_reply", _fake_publish)

    result = runner.invoke(
        app,
        ["respond", "I can move to 30%. [[mycelium: stance=accept]]", "--handle", "me", "--json"],
    )
    assert result.exit_code == 0
    assert len(published) == 1
    reply = published[0]
    # Threaded onto the awaited tick, in its episode, as an exchange by @me.
    assert l9.sender_of(reply) == "me"
    assert reply["l9"]["header"]["message"]["parents"] == ["tick-1"]
    assert l9.episode_of(reply) == "urn:ioc:mycelium:episode:demo:live"
    # Position marker lifted onto the payload, stripped from prose.
    assert l9.human_text_of(reply) == "I can move to 30%."
    assert l9.payload_data_of(reply)["action"] == "accept"


def test_respond_without_prior_await_is_standalone(monkeypatch: pytest.MonkeyPatch) -> None:
    published: list[dict] = []

    async def _fake_publish(config, room, handle, content, **_kw):
        published.append(content)

    monkeypatch.setattr(participate, "publish_reply", _fake_publish)

    result = runner.invoke(app, ["respond", "opening position", "--handle", "me"])
    assert result.exit_code == 0
    reply = published[0]
    # No awaited context → a valid standalone exchange in the room's live episode.
    assert reply["l9"]["header"]["message"]["parents"] == []
    assert l9.episode_of(reply) == "urn:ioc:mycelium:episode:demo:live"
