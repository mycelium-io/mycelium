# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A board row is a thread, and the verbs that talk in it (#838).

``board send`` / ``board messages`` / ``board coordinate`` are the room's own chat
verbs with a row id in front of them, and ``board new`` is the creation that
mints the thread in the first place. What these hold is the resolution — a
reader types what the board showed them and lands on the right conversation —
and its refusals, because a message that quietly went to the room instead of the
thread it was addressed to is worse than one that did not go.

Node-free: the hub reads are stubbed, so this exercises the CLI's own plumbing.
"""

from __future__ import annotations

import datetime
import json
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock, Mock
from uuid import uuid4

import pytest
from typer.testing import CliRunner

from mycelium.board.model import ItemSource, LiveItem
from mycelium.cli import app as cli_app
from mycelium.commands import board as board_cmd

if TYPE_CHECKING:
    from mycelium.config import MyceliumConfig

runner = CliRunner()

ROOM = "atlas"
THREAD = "urn:ioc:mycelium:episode:atlas:t3aa11bb"
SHORT = "t3aa11bb"


def _unit(key: str = "work/passkey-login", episode: str | None = THREAD) -> dict:
    """A ``work/`` memory as the hub hands it back, thread and all."""
    return {
        "key": key,
        "value": "Ship passkey login",
        "updated_by": "julia",
        "updated_at": "2026-08-24T10:00:00Z",
        "meta": {"kind": "action", "status": "open"},
        **({"episode": episode} if episode else {}),
    }


def _hub(monkeypatch: pytest.MonkeyPatch, *, memories: list[dict], posts: list | None = None):
    """Stand in for every hub read the board makes, plus the write it may do."""
    fake_config = SimpleNamespace(
        server=SimpleNamespace(api_url="http://localhost:8000"),
        get_active_room=lambda: ROOM,
        get_current_identity=lambda: "julia",
    )
    monkeypatch.setattr(board_cmd.MyceliumConfig, "load", classmethod(lambda _cls: fake_config))
    monkeypatch.setattr(board_cmd, "_resolve_room", lambda *_a, **_k: ROOM)

    class _Resp:
        def __init__(self, payload):
            self._payload = payload
            self.status_code = 200
            self.text = ""

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    routes = {
        f"/api/rooms/{ROOM}/episodes": {"episodes": []},
        f"/api/rooms/{ROOM}/memory?limit=50": memories,
        f"/api/rooms/{ROOM}/status": None,
        f"/api/rooms/{ROOM}/agents": [],
        f"/api/rooms/{ROOM}/sessions/members": {"members": []},
        f"/api/rooms/{ROOM}/messages?limit=300": {"messages": []},
    }

    class _Client:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def get(self, path, **_kw):
            return _Resp(routes.get(path, {}))

        def post(self, path, json=None, **_kw):  # noqa: A002 — httpx's own name
            if posts is not None:
                posts.append((path, json))
            return _Resp(
                {"key": "work/ship-passkey-login", "episode": THREAD, "value": "Ship passkey login"}
            )

    monkeypatch.setattr(board_cmd, "hub_client", lambda *_a, **_k: _Client())


def _chat(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Capture what the shared chat helper was asked to send / read."""
    sent: dict = {}

    def fake_post(_cfg, room_name, **kwargs):
        sent["post"] = {"room": room_name, **kwargs}

    def fake_read(_cfg, room_name, **kwargs):
        sent["read"] = {"room": room_name, **kwargs}

    monkeypatch.setattr(board_cmd.chat, "post", fake_post)
    monkeypatch.setattr(board_cmd.chat, "read", fake_read)
    return sent


class TestResolution:
    """A reader types what the board showed them, and lands on the right thread."""

    @pytest.mark.parametrize("typed", ["work/passkey-login", "memory:work/passkey-login", SHORT])
    def test_a_row_resolves_to_its_thread_however_its_id_was_typed(
        self, monkeypatch: pytest.MonkeyPatch, typed: str
    ) -> None:
        _hub(monkeypatch, memories=[_unit()])
        sent = _chat(monkeypatch)
        result = runner.invoke(board_cmd.app, ["send", typed, "starting on the schema"])
        assert result.exit_code == 0, result.output
        assert sent["post"]["episode"] == THREAD

    def test_a_row_the_board_does_not_have_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _hub(monkeypatch, memories=[_unit()])
        sent = _chat(monkeypatch)
        result = runner.invoke(board_cmd.app, ["send", "work/nothing", "hello"])
        assert result.exit_code == 1
        assert "No row" in result.output
        assert sent == {}

    def test_a_row_with_no_thread_is_refused_in_its_own_terms(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Never posted to the room instead: a message that went somewhere the
        sender did not name is the failure this refusal exists to prevent."""
        _hub(monkeypatch, memories=[_unit(key="decisions/db", episode=None)])
        sent = _chat(monkeypatch)
        result = runner.invoke(board_cmd.app, ["send", "decisions/db", "hello"])
        assert result.exit_code == 1
        assert "no thread" in result.output
        assert "another namespace" in result.output
        assert sent == {}


class TestChatVerbs:
    def test_send_posts_into_the_thread_and_says_which(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _hub(monkeypatch, memories=[_unit()])
        sent = _chat(monkeypatch)
        result = runner.invoke(board_cmd.app, ["send", SHORT, "@sec token storage?"])
        assert result.exit_code == 0, result.output
        post = sent["post"]
        assert post == {
            "room": ROOM,
            "sender_handle": "julia",
            "content": "@sec token storage?",
            "episode": THREAD,
            "destination": f"{ROOM}/{SHORT}",
        }

    def test_messages_reads_only_that_thread(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _hub(monkeypatch, memories=[_unit()])
        sent = _chat(monkeypatch)
        result = runner.invoke(board_cmd.app, ["messages", SHORT, "--limit", "5"])
        assert result.exit_code == 0, result.output
        read = sent["read"]
        assert read["episode"] == THREAD
        assert read["limit"] == 5
        assert read["label"] == f"{ROOM}/{SHORT}"

    def test_coordinate_addresses_the_engine_inside_the_row_s_thread(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _hub(monkeypatch, memories=[_unit()])
        sent = _chat(monkeypatch)
        monkeypatch.setattr(
            "mycelium.commands.agent._load_manifest_remote",
            lambda *_a: SimpleNamespace(handle="aligner", adapter="engine", kind="aligner"),
        )
        monkeypatch.setattr("mycelium.client.typed_client", lambda _c: _null_cm())
        result = runner.invoke(
            board_cmd.app, ["coordinate", SHORT, "aligner", "converge on storage"]
        )
        assert result.exit_code == 0, result.output
        post = sent["post"]
        assert post["content"] == "@aligner converge on storage"
        assert post["episode"] == THREAD

    def test_coordinating_with_a_plain_agent_is_refused_with_the_verb_that_does_work(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _hub(monkeypatch, memories=[_unit()])
        sent = _chat(monkeypatch)
        monkeypatch.setattr(
            "mycelium.commands.agent._load_manifest_remote",
            lambda *_a: SimpleNamespace(handle="sec", adapter="claude_code", kind=None),
        )
        monkeypatch.setattr("mycelium.client.typed_client", lambda _c: _null_cm())
        result = runner.invoke(board_cmd.app, ["coordinate", SHORT, "sec", "mediate"])
        assert result.exit_code == 1
        assert "board send" in result.output
        assert sent == {}


class TestCreation:
    def test_new_asks_the_hub_for_a_unit_and_reports_its_thread(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        posts: list = []
        _hub(monkeypatch, memories=[], posts=posts)
        result = runner.invoke(board_cmd.app, ["new", "Ship passkey login", "--assign", "@sec"])
        assert result.exit_code == 0, result.output
        path, body = posts[0]
        assert path == f"/api/rooms/{ROOM}/tasks"
        assert body == {"title": "Ship passkey login", "handle": "julia", "assignee": "sec"}
        assert SHORT in result.output

    def test_a_parent_is_resolved_against_the_board_before_it_is_sent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        posts: list = []
        _hub(monkeypatch, memories=[_unit()], posts=posts)
        result = runner.invoke(board_cmd.app, ["new", "Pick token storage", "--parent", SHORT])
        assert result.exit_code == 0, result.output
        _path, body = posts[0]
        assert body["parent"] == "work/passkey-login"

    def test_a_parent_the_board_does_not_have_never_reaches_the_hub(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        posts: list = []
        _hub(monkeypatch, memories=[_unit()], posts=posts)
        result = runner.invoke(board_cmd.app, ["new", "Pick storage", "--parent", "work/ghost"])
        assert result.exit_code == 1
        assert posts == []

    def test_a_row_with_no_frontmatter_cannot_be_a_parent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A ``part-of`` edge points at a memory; a projected row is not one."""
        posts: list = []
        _hub(monkeypatch, memories=[], posts=posts)
        monkeypatch.setattr(
            board_cmd,
            "_row",
            lambda *_a: LiveItem(
                id="agent:sec", title="@sec", source=ItemSource("agent", "claude_code")
            ),
        )
        result = runner.invoke(board_cmd.app, ["new", "Pick storage", "--parent", "@sec"])
        assert result.exit_code == 1
        assert "can't be a parent" in result.output
        assert posts == []


def _config():
    """A config the helper only reads a base URL off; the wire call is stubbed."""
    return cast("MyceliumConfig", SimpleNamespace(server=SimpleNamespace(api_url="http://hub")))


def _null_cm():
    cm = MagicMock()
    cm.__enter__.return_value = Mock(name="client")
    cm.__exit__.return_value = None
    return cm


class TestUnitScopedParticipation:
    """``await --task`` / ``respond --task``: the resident loop, narrowed to a row."""

    def test_await_scopes_the_long_poll_to_the_row_s_thread(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        from mycelium.commands import participate as participate_cmd

        monkeypatch.setenv("HOME", str(tmp_path))
        _hub(monkeypatch, memories=[_unit()])
        monkeypatch.setattr(participate_cmd, "_resolve_room", lambda *_a, **_k: ROOM)
        captured: dict = {}

        def fake_await(_cfg, room_name, handle, timeout, episode=None):
            captured.update(
                {"room": room_name, "handle": handle, "timeout": timeout, "episode": episode}
            )
            return {"room": room_name, "handle": handle, "prompt": "@me?", "sender": "sec"}

        monkeypatch.setattr(participate_cmd, "_await_once", fake_await)
        result = runner.invoke(cli_app, ["await", "--handle", "me", "--task", SHORT, "--json"])
        assert result.exit_code == 0, result.output
        assert captured["episode"] == THREAD

    def test_respond_names_the_thread_it_is_redirecting_into(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        from mycelium.commands import participate as participate_cmd

        monkeypatch.setenv("HOME", str(tmp_path))
        _hub(monkeypatch, memories=[_unit()])
        monkeypatch.setattr(participate_cmd, "_resolve_room", lambda *_a, **_k: ROOM)
        bodies: list = []

        class _Client:
            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def post(self, _path, json=None, **_kw):  # noqa: A002 — httpx's own name
                bodies.append(json)
                return SimpleNamespace(
                    raise_for_status=lambda: None, json=lambda: {"message_id": "m1"}
                )

        monkeypatch.setattr(participate_cmd, "hub_client", lambda *_a, **_k: _Client())
        result = runner.invoke(
            cli_app, ["respond", "ok, claiming it", "--handle", "me", "--task", SHORT]
        )
        assert result.exit_code == 0, result.output
        assert bodies[0]["episode"] == THREAD

    def test_a_unit_that_does_not_resolve_never_starts_the_poll(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        from mycelium.commands import participate as participate_cmd

        monkeypatch.setenv("HOME", str(tmp_path))
        _hub(monkeypatch, memories=[_unit()])
        monkeypatch.setattr(participate_cmd, "_resolve_room", lambda *_a, **_k: ROOM)
        polled: list = []
        monkeypatch.setattr(
            participate_cmd,
            "_await_once",
            lambda *_a, **_k: polled.append(1),
        )
        result = runner.invoke(
            cli_app, ["await", "--handle", "me", "--task", "work/ghost", "--loop"]
        )
        assert result.exit_code == 1
        assert polled == []


def _messages(episode: str) -> list:
    from mycelium_backend_client.models import MessageRead

    stamp = datetime.datetime(2026, 8, 24, 10, 0, 0)  # noqa: DTZ001 — fixed for assertions
    return [
        MessageRead(
            id=uuid4(),
            sender_handle="sec",
            message_type="broadcast",
            content="keychain, with a fallback",
            created_at=stamp,
            episode=episode,
        )
    ]


def test_the_thread_read_is_the_room_read_with_one_argument(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No second implementation: ``board messages`` and ``room messages`` are the
    same call, so they cannot drift on attribution, edit marks or wrapping."""
    from mycelium import chat
    from mycelium_backend_client.models import MessageListResponse

    captured: dict = {}

    def fake_sync(**kwargs):
        captured.update(kwargs)
        return MessageListResponse(messages=_messages(THREAD), total=1)

    monkeypatch.setattr("mycelium.chat._typed_client", lambda _c: _null_cm())
    monkeypatch.setattr(
        "mycelium_backend_client.api.messages.list_messages_api_rooms_room_name_messages_get.sync",
        fake_sync,
    )
    monkeypatch.setattr("mycelium.commands.room._agent_owner_map", lambda _r: {})

    chat.read(_config(), ROOM, limit=10, episode=THREAD, label=f"{ROOM}/{SHORT}")
    assert captured["episode"] == THREAD
    assert captured["room_name"] == ROOM


def test_a_thread_with_nothing_in_it_says_so_rather_than_no_messages(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    from mycelium import chat
    from mycelium_backend_client.models import MessageListResponse

    monkeypatch.setattr("mycelium.chat._typed_client", lambda _c: _null_cm())
    monkeypatch.setattr(
        "mycelium_backend_client.api.messages.list_messages_api_rooms_room_name_messages_get.sync",
        lambda **_k: MessageListResponse(messages=[], total=0),
    )
    chat.read(
        _config(),
        ROOM,
        limit=10,
        episode=THREAD,
        label=f"{ROOM}/{SHORT}",
        empty_note="nothing said in this thread yet",
    )
    assert "nothing said in this thread yet" in capsys.readouterr().out


LIVE = f"urn:ioc:mycelium:episode:{ROOM}:live"


def _ping_frame() -> dict:
    """The frame the hub raises into the room when a thread moves."""
    return {
        "l9": {
            "header": {"kind": "exchange", "message": {"episode": LIVE}},
            "payload": {
                "type": "ping",
                "data": {"episode": THREAD, "sender": "sec", "message": "m1"},
            },
        }
    }


def _bus_frame(content: dict, sender: str = "sec") -> dict:
    """The SSE frame the hub pushes: an envelope carried as a JSON string."""
    return {
        "message_type": "l9_exchange",
        "sender_handle": sender,
        "content": json.dumps(content),
        "episode": content["l9"]["header"]["message"]["episode"],
    }


def _prose_frame(episode: str, text: str = "keychain, with a WebCrypto fallback") -> dict:
    """The message itself, as the live stream carries it."""
    return {
        "content": text,
        "l9": {
            "header": {"kind": "exchange", "message": {"episode": episode, "parents": []}},
            "payload": {"type": "message"},
        },
    }


def test_a_ping_draws_the_thread_that_moved_and_not_what_was_said() -> None:
    """The room's whole account of a thread write: which task, and who."""
    from mycelium.commands.room import chat_line

    line = chat_line("l9_exchange", {}, _ping_frame(), "system", "12:00:00", "")
    assert line is not None
    assert SHORT in line
    assert "@sec" in line
    assert "keychain" not in line


class TestTheRoomShowsThePingAndNotTheProse:
    """The property the whole epic rests on, asserted where a reader would see it.

    A thread write reaches the room twice — the message itself, and the ping
    announcing it — so drawing the ping is only half the job. Printing both is
    the argument *plus* a line saying an argument happened, which is worse than
    either alone, and a test that only checks the ping in isolation stays green
    through exactly that.
    """

    def test_the_prose_of_a_thread_write_is_dropped_from_the_tail(self) -> None:
        from mycelium.commands.room import in_a_thread

        assert in_a_thread(ROOM, "l9_exchange", {}, _prose_frame(THREAD)) is True

    def test_the_ping_announcing_it_is_not(self) -> None:
        """It rides the room's own episode, which is what makes it the room's line."""
        from mycelium.commands.room import in_a_thread

        assert in_a_thread(ROOM, "l9_exchange", {}, _ping_frame()) is False

    def test_a_message_to_the_room_still_draws_in_full(self) -> None:
        from mycelium.commands.room import in_a_thread

        assert in_a_thread(ROOM, "l9_exchange", {}, _prose_frame(LIVE)) is False

    def test_a_replayed_row_is_judged_by_the_same_rule(self) -> None:
        """History arrives as a folded row carrying the episode as a plain field,
        so a filter that only read the envelope would let the replay through."""
        from mycelium.commands.room import in_a_thread

        row = {"content": "keychain", "episode": THREAD}
        assert in_a_thread(ROOM, "broadcast", row, {}) is True
        assert in_a_thread(ROOM, "broadcast", {"content": "hi", "episode": LIVE}, {}) is False

    def test_a_message_from_before_threading_is_the_room_s(self) -> None:
        from mycelium.commands.room import in_a_thread

        assert in_a_thread(ROOM, "broadcast", {"content": "hi"}, {}) is False

    def test_the_tail_itself_prints_the_ping_and_not_the_message(
        self, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        """Driven through the watch loop rather than its predicate: the rule is
        only worth anything if the thing that renders actually asks it."""
        from mycelium.commands import room as room_cmd

        requested: list[dict] = []
        frames = [
            _bus_frame(_prose_frame(THREAD)),
            _bus_frame(_ping_frame(), sender="system"),
            _bus_frame(_prose_frame(LIVE, "standup in five")),
        ]

        class _Stream:
            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            @staticmethod
            def iter_lines():
                for frame in frames:
                    yield f"data: {json.dumps(frame)}"

        class _Client:
            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def get(self, path, params=None, **_kw):
                requested.append({"path": path, "params": params or {}})
                body = {"sessions": []} if path.endswith("/sessions") else {"messages": []}
                return SimpleNamespace(status_code=200, json=lambda: body)

            def stream(self, _method, _path):
                return _Stream()

        monkeypatch.setattr(room_cmd, "hub_client", lambda *_a, **_k: _Client())
        monkeypatch.setattr(room_cmd, "_agent_owner_map", lambda _r: {})
        room_cmd._watch_room(_config(), ROOM, 0)

        out = capsys.readouterr().out
        assert "activity in" in out
        assert SHORT in out
        assert "WebCrypto fallback" not in out, "a thread's prose reached the room's tail"
        # The room's own messages are untouched — this drops threads, not chat.
        assert "standup in five" in out
        assert out.count("activity in") == 1

    def test_the_replay_drops_a_thread_s_prose_too(
        self, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        """The tail opens with history, so a filter that only covered the live
        stream would still show the argument — just a moment earlier.

        Filtered here rather than by asking the hub for ``?episode=<live>``:
        that read is exact only for rows written since threading, and would
        drop every message from before it — history a reader would never know
        was missing.
        """
        from mycelium.commands import room as room_cmd

        history = [
            {
                "message_type": "broadcast",
                "sender_handle": "sec",
                "content": "in the keychain",
                "episode": THREAD,
            },
            {
                "message_type": "broadcast",
                "sender_handle": "julia",
                "content": "standup in five",
                "episode": LIVE,
            },
            {"message_type": "broadcast", "sender_handle": "julia", "content": "from before"},
        ]

        class _Stream:
            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            @staticmethod
            def iter_lines():
                return iter(())

        class _Client:
            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def get(self, path, params=None, **_kw):  # noqa: ARG002
                body = {"sessions": []} if path.endswith("/sessions") else {"messages": history}
                return SimpleNamespace(status_code=200, json=lambda: body)

            def stream(self, _method, _path):
                return _Stream()

        monkeypatch.setattr(room_cmd, "hub_client", lambda *_a, **_k: _Client())
        monkeypatch.setattr(room_cmd, "_agent_owner_map", lambda _r: {})
        room_cmd._watch_room(_config(), ROOM, 0)

        out = capsys.readouterr().out
        assert "in the keychain" not in out
        assert "standup in five" in out
        # Written before threading existed, so it carries no episode at all.
        assert "from before" in out


def test_a_json_dump_of_the_thread_is_still_json(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    from mycelium import chat
    from mycelium_backend_client.models import MessageListResponse

    monkeypatch.setattr("mycelium.chat._typed_client", lambda _c: _null_cm())
    monkeypatch.setattr(
        "mycelium_backend_client.api.messages.list_messages_api_rooms_room_name_messages_get.sync",
        lambda **_k: MessageListResponse(messages=_messages(THREAD), total=1),
    )
    chat.read(_config(), ROOM, limit=10, episode=THREAD, json_output=True)
    assert json.loads(capsys.readouterr().out)["total"] == 1
