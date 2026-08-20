# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium thread`` + the ``--thread`` scope on await/respond (#631).

Node-free: ``httpx`` is stubbed, so these exercise the CLI plumbing — that a
scope reaches the hub as a query/body param and nothing more. Threads add no
client state: ``--thread`` is one parameter on the same two stateless calls, and
its absence is the room-level behaviour the protocol always had.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mycelium.cli import app
from tests.conftest import FakeHTTPX, FakeResp

runner = CliRunner()

_THREAD = {
    "id": "3f9a1c2d-aaaa-bbbb-cccc-ddddeeeeffff",
    "kind": "chat",
    "title": "Cache TTL: what should it be?",
    "root_message_id": "3f9a1c2d-aaaa-bbbb-cccc-ddddeeeeffff",
    "last_message_id": "m-2",
    "episode": None,
    "participants": ["avery", "rowan"],
    "message_count": 3,
    "started_at": "2026-08-17T09:00:00+00:00",
    "last_message_at": "2026-08-17T09:04:00+00:00",
}


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MYCELIUM_ROOM_ID", "demo")


def test_thread_ls_lists_the_rooms_threads(fake_httpx: FakeHTTPX) -> None:
    fake_httpx.respond_with(lambda *_a: FakeResp({"threads": [_THREAD]}))

    result = runner.invoke(app, ["thread", "ls"])
    assert result.exit_code == 0
    assert "Cache TTL" in result.stdout
    assert "3f9a1c2d" in result.stdout

    method, path, _params = fake_httpx.calls[0]
    assert (method, path) == ("GET", "/api/rooms/demo/threads")


def test_thread_show_reads_one_conversation(fake_httpx: FakeHTTPX) -> None:
    fake_httpx.respond_with(
        lambda *_a: FakeResp(
            {
                **_THREAD,
                "messages": [
                    {
                        "sender_handle": "avery",
                        "content": "cache TTL?",
                        "created_at": "2026-08-17T09:00:00+00:00",
                    },
                    {
                        "sender_handle": "rowan",
                        "content": "60s",
                        "created_at": "2026-08-17T09:04:00+00:00",
                    },
                ],
            }
        )
    )

    result = runner.invoke(app, ["thread", "show", "3f9a"])
    assert result.exit_code == 0
    assert "avery" in result.stdout
    assert "60s" in result.stdout

    method, path, _params = fake_httpx.calls[0]
    assert (method, path) == ("GET", "/api/rooms/demo/threads/3f9a")


def test_thread_new_opens_one_and_prints_its_id(fake_httpx: FakeHTTPX) -> None:
    fake_httpx.respond_with(lambda *_a: FakeResp(_THREAD))

    result = runner.invoke(
        app, ["--json", "thread", "new", "Cache TTL: what should it be?", "--handle", "avery"]
    )
    assert result.exit_code == 0
    assert json.loads(result.stdout)["id"] == _THREAD["id"]

    method, path, body = fake_httpx.calls[0]
    assert (method, path) == ("POST", "/api/rooms/demo/threads")
    assert body == {"title": "Cache TTL: what should it be?", "sender_handle": "avery"}


def test_await_scopes_the_poll_to_a_thread(fake_httpx: FakeHTTPX) -> None:
    fake_httpx.respond_with(
        lambda *_a: FakeResp(
            {
                "room": "demo",
                "handle": "me",
                "prompt": "@me thoughts on the TTL?",
                "sender": "avery",
                "thread": _THREAD["id"],
                "message_id": "m-2",
            }
        )
    )

    result = runner.invoke(app, ["await", "--handle", "me", "--thread", "3f9a", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["thread"] == _THREAD["id"]

    _method, _path, params = fake_httpx.calls[0]
    assert params["thread"] == "3f9a"


def test_an_unscoped_await_asks_for_no_thread(fake_httpx: FakeHTTPX) -> None:
    """The default is unchanged: watch the whole room, route on the turn's thread."""
    fake_httpx.respond_with(
        lambda *_a: FakeResp({"room": "demo", "handle": "me", "prompt": "hi", "thread": None})
    )

    result = runner.invoke(app, ["await", "--handle", "me", "--json"])
    assert result.exit_code == 0
    _method, _path, params = fake_httpx.calls[0]
    assert "thread" not in params


def test_respond_carries_the_scope(fake_httpx: FakeHTTPX) -> None:
    fake_httpx.respond_with(lambda *_a: FakeResp({"room": "demo", "handle": "me"}))

    result = runner.invoke(app, ["respond", "60s", "--handle", "me", "--thread", "3f9a", "--json"])
    assert result.exit_code == 0

    method, path, body = fake_httpx.calls[0]
    assert (method, path) == ("POST", "/api/rooms/demo/reply")
    assert body == {"handle": "me", "text": "60s", "thread": "3f9a"}


def test_respond_can_answer_one_message(fake_httpx: FakeHTTPX) -> None:
    fake_httpx.respond_with(lambda *_a: FakeResp({"room": "demo", "handle": "me"}))

    result = runner.invoke(app, ["respond", "60s", "--handle", "me", "--reply-to", "m-1", "--json"])
    assert result.exit_code == 0
    _method, _path, body = fake_httpx.calls[0]
    assert body == {"handle": "me", "text": "60s", "reply_to": "m-1"}


def test_an_unscoped_respond_sends_what_it_always_did(fake_httpx: FakeHTTPX) -> None:
    fake_httpx.respond_with(lambda *_a: FakeResp({"room": "demo", "handle": "me"}))

    result = runner.invoke(app, ["respond", "60s", "--handle", "me", "--json"])
    assert result.exit_code == 0
    _method, _path, body = fake_httpx.calls[0]
    assert body == {"handle": "me", "text": "60s"}
