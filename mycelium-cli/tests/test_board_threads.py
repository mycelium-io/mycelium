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

import httpx
import pytest
from typer.testing import CliRunner

from mycelium import cli_options
from mycelium.board.model import ItemSource, LiveItem
from mycelium.cli import app as cli_app
from mycelium.commands import board as board_cmd
from tests.conftest import install_stand_in_hub, memory_read
from tests.hub_answers import ok

if TYPE_CHECKING:
    from pathlib import Path

    from mycelium.config import MyceliumConfig

runner = CliRunner()

ROOM = "atlas"
THREAD = "urn:ioc:mycelium:episode:atlas:t3aa11bb"
SHORT = "t3aa11bb"
OTHER = "urn:ioc:mycelium:episode:atlas:c0ffee42"
OTHER_SHORT = "c0ffee42"


@pytest.fixture(autouse=True)
def _shared_options(monkeypatch: pytest.MonkeyPatch) -> None:
    """The room and handle the shared options resolve to, without a real config."""
    monkeypatch.setattr(cli_options, "resolve_room", lambda _c, flag=None: flag or ROOM)
    monkeypatch.setattr(cli_options, "resolve_handle", lambda _c, flag, **_k: flag or "julia")


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


def _hub(
    monkeypatch: pytest.MonkeyPatch,
    *,
    memories: list[dict],
    posts: list | None = None,
    keyed: dict[str, dict] | None = None,
    older: list[dict] | None = None,
):
    """Stand in for every hub read the board makes, plus the write it may do.

    ``memories`` are the room's recently changed ones, which the log reads
    (``memory?limit=50``); the board reads each of its namespaces whole, which
    adds ``older``, the tasks that haven't changed lately. ``keyed`` is the
    by-key memory read, which is how a chat verb reaches a memory the board
    never projects. A key absent from it 404s.
    """
    every = memories + (older or [])
    fake_config = SimpleNamespace(
        server=SimpleNamespace(api_url="http://localhost:8000"),
        get_active_room=lambda: ROOM,
        get_current_identity=lambda: "julia",
    )
    monkeypatch.setattr(board_cmd.MyceliumConfig, "load", classmethod(lambda _cls: fake_config))
    monkeypatch.setattr(board_cmd, "_resolve_room", lambda *_a, **_k: ROOM)

    base = f"/api/rooms/{ROOM}"
    reads = {
        f"{base}/episodes": {"episodes": []},
        f"{base}/status": (404, {"detail": "no status"}),
        f"{base}/agents": [],
        f"{base}/sessions/members": {"members": []},
        f"{base}/messages": {"messages": [], "total": 0},
        f"{base}/board": (404, {"detail": "no board"}),
    }

    def answer(request: httpx.Request):
        path, params = request.url.path, request.url.params
        if request.method == "POST":
            body = json.loads(request.content)
            if posts is not None:
                posts.append((path, body))
            if path == f"{base}/tasks":
                return 201, memory_read(
                    "work/ship-passkey-login", ROOM, value="Ship passkey login", episode=THREAD
                )
            return _assignment(body.get("key", ""), body.get("handle"))
        if path == f"{base}/memory":
            prefix = params.get("prefix")
            if prefix is None:
                return [_full(m) for m in memories]
            return [_full(m) for m in every if m["key"].startswith(prefix)]
        if path.startswith(f"{base}/memory/"):
            key = path[len(f"{base}/memory/") :]
            if key not in (keyed or {}):
                return 404, {"detail": "Memory not found"}
            return memory_read(key, ROOM, **(keyed or {})[key])
        return reads.get(path, {})

    install_stand_in_hub(monkeypatch).answer = answer


def _full(memory: dict) -> dict:
    """One of this file's memories, filled out to the hub's whole answer."""
    return memory_read(memory["key"], ROOM, **{k: v for k, v in memory.items() if k != "key"})


def _assignment(key: str, handle: str | None) -> dict:
    """What the hub answers a claim, release or resolve with."""
    return {
        "key": key,
        "assignment": "held",
        "waiting_on": [],
        "owner": handle,
        "assignee": None,
        "claimed_at": None,
        "ttl_minutes": None,
        "freshness": None,
        "version": 2,
        "assignment_note": None,
        "assignment_note_by": None,
    }


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

    def test_a_key_the_room_does_not_have_at_all_is_refused(
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
        assert "this memory carries no thread yet" in result.output
        assert sent == {}


class TestBeyondTheBoard:
    """Everything can be discussed; only the board namespaces are worked (#872).

    A ``context/`` note carries a thread like any memory, but the board never
    projects one, so the chat verbs have to resolve it off the store rather than
    off the projection — and still refuse in the same terms when there is
    nothing to speak into.
    """

    def test_a_memory_the_board_does_not_project_resolves_to_its_thread(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _hub(monkeypatch, memories=[_unit()], keyed={"context/api-shape": {"episode": OTHER}})
        sent = _chat(monkeypatch)
        result = runner.invoke(board_cmd.app, ["send", "context/api-shape", "this is stale"])
        assert result.exit_code == 0, result.output
        assert sent["post"]["episode"] == OTHER
        assert sent["post"]["destination"] == f"{ROOM}/{OTHER_SHORT}"

    def test_reading_a_memory_s_thread_reads_that_thread_and_nothing_else(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _hub(monkeypatch, memories=[_unit()], keyed={"skills/review": {"episode": OTHER}})
        sent = _chat(monkeypatch)
        result = runner.invoke(board_cmd.app, ["messages", "skills/review"])
        assert result.exit_code == 0, result.output
        assert sent["read"]["episode"] == OTHER
        assert sent["read"]["label"] == f"{ROOM}/{OTHER_SHORT}"

    def test_a_memory_the_hub_wrote_for_itself_is_refused_not_sent_to_the_room(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _hub(monkeypatch, memories=[_unit()], keyed={"agents/sec": {}})
        sent = _chat(monkeypatch)
        result = runner.invoke(board_cmd.app, ["send", "agents/sec", "hello"])
        assert result.exit_code == 1
        assert "no thread" in result.output
        assert sent == {}

    def test_a_memory_that_is_not_there_says_neither_row_nor_memory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _hub(monkeypatch, memories=[_unit()])
        sent = _chat(monkeypatch)
        result = runner.invoke(board_cmd.app, ["send", "context/ghost", "hello"])
        assert result.exit_code == 1
        assert "no memory by that key" in result.output
        assert sent == {}

    def test_the_board_still_wins_when_a_key_is_both(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """One round trip, not two: a projected row already carries its thread."""
        _hub(monkeypatch, memories=[_unit()], keyed={"work/passkey-login": {"episode": OTHER}})
        sent = _chat(monkeypatch)
        result = runner.invoke(board_cmd.app, ["send", "work/passkey-login", "hello"])
        assert result.exit_code == 0, result.output
        assert sent["post"]["episode"] == THREAD


#: An open task that hasn't changed in a while, assigned and marked gone quiet:
#: the board's read of the room's most recent memories leaves it out.
QUIET_KEY = "work/add-a-rule-that-a-pr-touches-the-docs-only-when"
QUIET_THREAD = "urn:ioc:mycelium:episode:atlas:5bd40de8"
QUIET = {
    "key": QUIET_KEY,
    "value": {"text": "Add a rule that a PR touches the docs only when a reader has something new"},
    "updated_by": "runtime",
    "updated_at": "2026-08-20T20:37:39Z",
    "meta": {
        "kind": "action",
        "status": "open",
        "assignee": "reviewer",
        "hold_flagged_at": "2026-08-20T20:37:39Z",
    },
    "episode": QUIET_THREAD,
}


class TestATaskThatHasntChangedLately:
    """The board lists, and resolve, claim, release and block find, every live
    task, not just the ones among the room's most recently changed memories."""

    def _quiet_hub(self, monkeypatch: pytest.MonkeyPatch) -> list:
        posts: list = []
        _hub(monkeypatch, memories=[_unit()], posts=posts, older=[QUIET])
        return posts

    def test_the_board_lists_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._quiet_hub(monkeypatch)
        result = runner.invoke(board_cmd.app, ["--filter", "all"], env={"COLUMNS": "200"})
        assert result.exit_code == 0, result.output
        # Both tasks: the recent one and the quiet one, elided, held by reviewer.
        assert "Actions 2" in result.output
        assert "y-when  held @reviewer" in result.output

    @pytest.mark.parametrize("typed", [QUIET_KEY, f"memory:{QUIET_KEY}", "5bd40de8"])
    def test_resolve_finds_it_by_key_or_thread(
        self, monkeypatch: pytest.MonkeyPatch, typed: str
    ) -> None:
        posts = self._quiet_hub(monkeypatch)
        result = runner.invoke(board_cmd.app, ["resolve", typed])
        assert result.exit_code == 0, result.output
        assert "No row" not in result.output
        assert posts[-1][0] == f"/api/rooms/{ROOM}/assignments/resolve"
        assert posts[-1][1]["key"] == QUIET_KEY

    def test_release_and_block_find_it_too(self, monkeypatch: pytest.MonkeyPatch) -> None:
        posts = self._quiet_hub(monkeypatch)
        for args in (["release", QUIET_KEY], ["block", QUIET_KEY, "--on", "#1435"]):
            result = runner.invoke(board_cmd.app, args)
            assert "No row" not in result.output, args
        assert [p for p, _b in posts] == [
            f"/api/rooms/{ROOM}/assignments/release",
            f"/api/rooms/{ROOM}/fields",
        ]

    def test_claim_finds_it_and_says_it_is_assigned(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._quiet_hub(monkeypatch)
        result = runner.invoke(board_cmd.app, ["claim", QUIET_KEY])
        assert "No row" not in result.output

    def test_a_key_outside_the_board_or_not_there_is_still_no_row(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._quiet_hub(monkeypatch)
        for typed in ("work/never-filed", "context/notes", "deadbeef"):
            result = runner.invoke(board_cmd.app, ["resolve", typed])
            assert result.exit_code == 1, typed
            assert "No row" in result.output, typed


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
            "json_output": False,
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
            lambda *_a: SimpleNamespace(handle="conductor", adapter="engine", kind="conductor"),
        )
        monkeypatch.setattr("mycelium.client.typed_client", lambda _c: _null_cm())
        result = runner.invoke(
            board_cmd.app, ["coordinate", SHORT, "conductor", "concord @~api @~sec: storage"]
        )
        assert result.exit_code == 0, result.output
        post = sent["post"]
        assert post["content"] == "@conductor concord @~api @~sec: storage"
        assert post["episode"] == THREAD

    def test_coordinating_with_an_old_aligner_says_what_to_run_instead(
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
        assert result.exit_code == 1
        assert "The aligner was retired" in result.output
        assert "post" not in sent

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

    @pytest.mark.parametrize(
        "how",
        [
            ["The plan, in full."],
            ["--body", "The plan, in full."],
            ["-b", "The plan, in full."],
        ],
    )
    def test_new_files_the_task_with_its_body(
        self, monkeypatch: pytest.MonkeyPatch, how: list[str]
    ) -> None:
        posts: list = []
        _hub(monkeypatch, memories=[], posts=posts)
        result = runner.invoke(board_cmd.app, ["new", "Ship passkey login", *how])
        assert result.exit_code == 0, result.output
        _path, body = posts[0]
        assert body["title"] == "Ship passkey login"
        assert body["content"] == "The plan, in full."

    def test_new_reads_the_body_from_a_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        brief = tmp_path / "brief.md"
        brief.write_text("# Passkeys\n\n- keep passwords as a fallback\n")
        posts: list = []
        _hub(monkeypatch, memories=[], posts=posts)
        result = runner.invoke(board_cmd.app, ["new", "Ship passkey login", "--file", str(brief)])
        assert result.exit_code == 0, result.output
        assert posts[0][1]["content"] == "# Passkeys\n\n- keep passwords as a fallback\n"

    def test_new_with_no_body_sends_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        posts: list = []
        _hub(monkeypatch, memories=[], posts=posts)
        result = runner.invoke(board_cmd.app, ["new", "Ship passkey login"])
        assert result.exit_code == 0, result.output
        assert "content" not in posts[0][1]

    def test_new_refuses_a_body_given_twice(self, monkeypatch: pytest.MonkeyPatch) -> None:
        posts: list = []
        _hub(monkeypatch, memories=[], posts=posts)
        result = runner.invoke(board_cmd.app, ["new", "Ship it", "one", "--body", "two"])
        assert result.exit_code != 0
        assert posts == []

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
            from mycelium_backend_client.models import AwaitTurn

            captured.update(
                {"room": room_name, "handle": handle, "timeout": timeout, "episode": episode}
            )
            return AwaitTurn(
                room=room_name,
                handle=handle,
                prompt="@me?",
                sender="sec",
                episode=None,
                topic=None,
                message_id=None,
            )

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
        # The board reads still go to `_hub`'s answers; the reply is answered here.
        board_reads = httpx.HTTPTransport().handle_request

        def answer(request: httpx.Request):
            if request.url.path == f"/api/rooms/{ROOM}/reply":
                bodies.append(json.loads(request.content))
                return {"room": ROOM, "handle": "me", "message_id": "m1"}
            return board_reads(request)

        install_stand_in_hub(monkeypatch).answer = answer
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
        return ok(MessageListResponse(messages=_messages(THREAD), total=1))

    monkeypatch.setattr("mycelium.chat._typed_client", lambda _c: _null_cm())
    monkeypatch.setattr(
        "mycelium_backend_client.api.messages.list_messages_api_rooms_room_name_messages_get.sync_detailed",
        fake_sync,
    )
    monkeypatch.setattr("mycelium.commands.room._agent_owner_map", lambda _r: {})

    chat.read(_config(), ROOM, limit=10, episode=THREAD, label=f"{ROOM}/{SHORT}")
    assert captured["episode"] == THREAD
    assert captured["room_name"] == ROOM


def test_board_messages_json_after_the_command_prints_the_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mycelium_backend_client.models import MessageListResponse

    _hub(monkeypatch, memories=[_unit()])
    monkeypatch.setattr("mycelium.chat._typed_client", lambda _c: _null_cm())
    monkeypatch.setattr(
        "mycelium_backend_client.api.messages.list_messages_api_rooms_room_name_messages_get.sync_detailed",
        lambda **_k: ok(MessageListResponse(messages=_messages(THREAD), total=1)),
    )

    result = runner.invoke(board_cmd.app, ["messages", SHORT, "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert [m["content"] for m in payload["messages"]] == ["keychain, with a fallback"]


def test_board_log_json_after_the_command_prints_the_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _hub(monkeypatch, memories=[_unit()])

    result = runner.invoke(board_cmd.app, ["log", "--since", "30d", "--tz", "UTC", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["room"] == ROOM
    assert payload["timezone"] == "UTC"
    assert isinstance(payload["events"], list)
    assert set(payload["streak"]) == {"current", "longest"}


def test_a_thread_with_nothing_in_it_says_so_rather_than_no_messages(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    from mycelium import chat
    from mycelium_backend_client.models import MessageListResponse

    monkeypatch.setattr("mycelium.chat._typed_client", lambda _c: _null_cm())
    monkeypatch.setattr(
        "mycelium_backend_client.api.messages.list_messages_api_rooms_room_name_messages_get.sync_detailed",
        lambda **_k: ok(MessageListResponse(messages=[], total=0)),
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


def _replay(request: httpx.Request, history: list[dict]):
    """The hub's answers to the reads ``room watch`` opens with: who joined, then
    the room's recent messages, each filled out to a whole message record."""
    if request.url.path.endswith("/sessions"):
        return {"participants": [], "total": 0}
    messages = [
        {"id": str(uuid4()), "created_at": "2026-08-24T10:00:00+00:00", **m} for m in history
    ]
    return {"messages": messages, "total": len(messages)}


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

            def stream(self, _method, _path):
                return _Stream()

        monkeypatch.setattr(room_cmd, "hub_client", lambda *_a, **_k: _Client())
        install_stand_in_hub(monkeypatch).answer = lambda request: _replay(request, [])
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

            def stream(self, _method, _path):
                return _Stream()

        monkeypatch.setattr(room_cmd, "hub_client", lambda *_a, **_k: _Client())
        install_stand_in_hub(monkeypatch).answer = lambda request: _replay(request, history)
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
        "mycelium_backend_client.api.messages.list_messages_api_rooms_room_name_messages_get.sync_detailed",
        lambda **_k: ok(MessageListResponse(messages=_messages(THREAD), total=1)),
    )
    chat.read(_config(), ROOM, limit=10, episode=THREAD, json_output=True)
    assert json.loads(capsys.readouterr().out)["total"] == 1


TASK = ("work/passkey-login", "Passkey login")


def test_the_room_read_names_the_task_a_thread_message_came_from(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    from mycelium import chat
    from mycelium_backend_client.models import MessageListResponse

    monkeypatch.setattr("mycelium.chat._typed_client", lambda _c: _null_cm())
    monkeypatch.setattr(
        "mycelium_backend_client.api.messages.list_messages_api_rooms_room_name_messages_get.sync_detailed",
        lambda **_k: ok(MessageListResponse(messages=_messages(THREAD), total=1)),
    )
    monkeypatch.setattr("mycelium.chat.thread_tasks", lambda _c, _r: {THREAD: TASK})
    monkeypatch.setattr("mycelium.commands.room._agent_owner_map", lambda _r: {})

    chat.read(_config(), ROOM, limit=10)
    assert 'in "Passkey login"' in capsys.readouterr().out


def test_a_thread_no_row_carries_is_named_by_its_id(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    from mycelium import chat
    from mycelium_backend_client.models import MessageListResponse

    monkeypatch.setattr("mycelium.chat._typed_client", lambda _c: _null_cm())
    monkeypatch.setattr(
        "mycelium_backend_client.api.messages.list_messages_api_rooms_room_name_messages_get.sync_detailed",
        lambda **_k: ok(MessageListResponse(messages=_messages(THREAD), total=1)),
    )
    monkeypatch.setattr("mycelium.chat.thread_tasks", lambda _c, _r: {})
    monkeypatch.setattr("mycelium.commands.room._agent_owner_map", lambda _r: {})

    chat.read(_config(), ROOM, limit=10)
    assert f"in thread {SHORT}" in capsys.readouterr().out


def _notice_frame(subkind: str) -> dict:
    return {
        "l9": {
            "header": {"kind": "exchange", "message": {"episode": LIVE}},
            "payload": {
                "type": "notice",
                "data": {
                    "subkind": subkind,
                    "key": TASK[0],
                    "title": TASK[1],
                    "by": "sec",
                    "episode": THREAD,
                },
            },
        }
    }


class TestWatchAllFollowsEveryThread:
    """``room watch --all``: what the room's own view leaves to the thread."""

    @staticmethod
    def _watch(monkeypatch: pytest.MonkeyPatch, frames: list[dict], history: list[dict]) -> None:
        from mycelium.commands import room as room_cmd

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

            def stream(self, _method, _path):
                return _Stream()

        monkeypatch.setattr(room_cmd, "hub_client", lambda *_a, **_k: _Client())
        install_stand_in_hub(monkeypatch).answer = lambda request: _replay(request, history)
        monkeypatch.setattr(room_cmd, "_agent_owner_map", lambda _r: {})
        monkeypatch.setattr("mycelium.chat.thread_tasks", lambda _c, _r: {THREAD: TASK})
        room_cmd._watch_room(_config(), ROOM, 0, everything=True)

    def test_a_thread_s_message_is_printed_with_its_task(
        self, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        frames = [
            _bus_frame(_prose_frame(THREAD)),
            _bus_frame(_ping_frame(), sender="system"),
            _bus_frame(_prose_frame(LIVE, "standup in five")),
        ]
        self._watch(monkeypatch, frames, [])

        out = capsys.readouterr().out
        assert "Passkey login" in out
        assert "WebCrypto fallback" in out
        # The message draws itself, so the ping announcing it would be a repeat.
        assert "activity in" not in out
        assert "standup in five" in out

    def test_a_board_change_is_a_line(self, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        self._watch(monkeypatch, [_bus_frame(_notice_frame("claimed"), sender="system")], [])

        out = capsys.readouterr().out
        assert "sec" in out
        assert "took" in out
        assert "Passkey login" in out

    def test_the_replay_labels_a_thread_s_message_too(
        self, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        history = [
            {
                "message_type": "broadcast",
                "sender_handle": "sec",
                "content": "in the keychain",
                "episode": THREAD,
            },
        ]
        self._watch(monkeypatch, [], history)

        out = capsys.readouterr().out
        assert "in the keychain" in out
        assert "Passkey login" in out

    def test_agent_text_is_escaped_and_cut(self, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        long = "\n".join(["[red]not markup[/]", *[f"line {i}" for i in range(20)]])
        self._watch(monkeypatch, [_bus_frame(_prose_frame(THREAD, long))], [])

        out = capsys.readouterr().out
        assert "[red]not markup[/]" in out
        assert "line 19" not in out
        assert "board messages work/passkey-login" in out
