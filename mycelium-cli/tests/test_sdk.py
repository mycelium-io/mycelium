# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``from mycelium import Room``: the library the CLI's verbs are built on.

A stand-in hub answers at httpx's transport, so these run each verb through
the same generated client the CLI uses. The last test is the contract: every
request the library sends is checked against the committed ``openapi.json``,
so a route the library uses that moves or renames a field fails here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import httpx
import pytest

from mycelium import Held, HubError, Room, Waiting
from mycelium.exceptions import MyceliumError
from tests.conftest import StandInHub, install_stand_in_hub, memory_read

OPENAPI = Path(__file__).resolve().parents[2] / "openapi.json"
THREAD = "urn:ioc:mycelium:episode:demo:t1"


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MYCELIUM_ROOM_ID", "demo")
    monkeypatch.setenv("MYCELIUM_AGENT_HANDLE", "scout")


def _answers(request: httpx.Request) -> Any:
    """What a hub answers each verb with, in the shapes ``openapi.json`` gives them."""
    path, method = request.url.path, request.method
    if method == "GET" and path.startswith("/api/rooms/demo/memory/"):
        return memory_read(path.rsplit("/memory/", 1)[1], episode=THREAD)
    if path == "/api/rooms/demo/await":
        return {
            "room": "demo",
            "handle": "scout",
            "prompt": "@scout ready?",
            "sender": "lead",
            "episode": THREAD,
            "topic": "urn:concept:mycelium:demo",
            "message_id": "m-0",
        }
    if path == "/api/rooms/demo/reply":
        return {"room": "demo", "handle": "scout", "id": "m-1"}
    if path == "/api/rooms/demo/tasks":
        return 201, memory_read("work/ship-it", episode=THREAD)
    if path.startswith("/api/rooms/demo/assignments/"):
        key = json.loads(request.content)["key"]
        return {"key": key, "assignment": "held", "waiting_on": [], "owner": "scout"}
    if path == "/api/rooms/demo/memory" and method == "POST":
        return 201, [memory_read(json.loads(request.content)["items"][0]["key"], version=2)]
    if path == "/api/rooms/demo/memory/search":
        return {"results": [{"memory": memory_read("context/goal"), "similarity": 0.9}], "total": 1}
    if path == "/api/rooms/demo/uploads":
        request.read()  # while the file it streams from is still open
        return 201, {"name": "notes.txt", "kind": "text", "size": 5}
    return 404, {"detail": "not found"}


@pytest.fixture
def hub(monkeypatch: pytest.MonkeyPatch) -> StandInHub:
    stand_in = install_stand_in_hub(monkeypatch)
    stand_in.answer = _answers
    return stand_in


def _body(request: httpx.Request) -> dict[str, Any]:
    return json.loads(request.content)


def test_a_room_works_out_where_and_who_as_the_cli_does(hub: StandInHub) -> None:
    room = Room()
    assert (room.name, room.handle) == ("demo", "scout")
    assert Room("other", handle="lead").handle == "lead"


def test_it_waits_and_responds_in_a_task_s_thread(hub: StandInHub) -> None:
    room = Room()
    turn = room.wait(timeout=5, task="work/ship-it")
    assert turn is not None
    assert turn.prompt == "@scout ready?"
    waited = hub.sent("GET", "/api/rooms/demo/await")[0]
    assert waited.url.params["episode"] == THREAD
    assert waited.url.params["handle"] == "scout"

    replied = room.respond("On it.", task="work/ship-it")
    assert replied.id == "m-1"
    assert _body(hub.sent("POST", "/api/rooms/demo/reply")[0]) == {
        "handle": "scout",
        "text": "On it.",
        "episode": THREAD,
    }


def test_a_reply_lands_where_the_question_was_asked(hub: StandInHub) -> None:
    room = Room()
    turn = room.wait(timeout=5)
    assert turn is not None
    room.respond("Friday.", reply_to=turn)
    assert _body(hub.sent("POST", "/api/rooms/demo/reply")[0])["episode"] == THREAD
    with pytest.raises(ValueError, match="not both"):
        room.respond("Friday.", task="work/ship-it", reply_to=turn)


def test_it_files_claims_and_resolves_a_task(hub: StandInHub) -> None:
    room = Room()
    task = room.board.new("Ship it", body="Today.", assign="@lead")
    assert task.key == "work/ship-it"
    assert _body(hub.sent("POST", "/api/rooms/demo/tasks")[0]) == {
        "title": "Ship it",
        "handle": "scout",
        "content": "Today.",
        "assignee": "lead",
    }
    assert room.board.claim(task.key).owner == "scout"
    assert room.board.resolve(task.key).key == "work/ship-it"
    assert _body(hub.sent("POST", "/api/rooms/demo/assignments/resolve")[0]) == {
        "key": "work/ship-it",
        "handle": "scout",
    }


def test_a_claim_says_who_holds_it_or_what_it_waits_on(hub: StandInHub) -> None:
    room = Room()
    hub.answer = lambda _r: (409, {"detail": {"owner": "lead"}})
    with pytest.raises(Held) as held:
        room.board.claim("work/ship-it")
    assert (held.value.key, held.value.owner, held.value.status_code) == (
        "work/ship-it",
        "lead",
        409,
    )

    hub.answer = lambda _r: (409, {"detail": {"waiting_on": ["work/design"]}})
    with pytest.raises(Waiting) as waiting:
        room.board.claim("work/ship-it")
    assert waiting.value.waiting_on == ["work/design"]


def test_it_reads_writes_and_searches_memory(hub: StandInHub) -> None:
    room = Room()
    saved = room.memory.set(
        "notes/launch", "Friday", tags=["launch"], kind="finding", derived_from=["context/goal"]
    )
    assert saved.version == 2
    item = _body(hub.sent("POST", "/api/rooms/demo/memory")[0])["items"][0]
    assert (item["key"], item["value"], item["created_by"], item["tags"]) == (
        "notes/launch",
        "Friday",
        "scout",
        ["launch"],
    )
    assert item["meta"] == {"kind": "finding", "derived-from": ["context/goal"]}

    assert room.memory.get("context/goal").key == "context/goal"
    found = room.memory.search("when do we launch", limit=3)
    assert [r.memory.key for r in found] == ["context/goal"]
    searched = _body(hub.sent("POST", "/api/rooms/demo/memory/search")[0])
    assert (searched["query"], searched["limit"]) == ("when do we launch", 3)


def test_it_refuses_a_key_before_asking_the_hub(hub: StandInHub) -> None:
    with pytest.raises(ValueError, match="can't have folders"):
        Room().memory.set("work/a/b", "x")
    assert hub.requests == []


def test_nothing_is_written_when_it_doesnt_know_who_you_are(
    hub: StandInHub, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("MYCELIUM_AGENT_HANDLE")
    notes = tmp_path / "notes.txt"
    notes.write_text("hello")
    room = Room()
    assert room.handle is None
    writes = [
        lambda: room.respond("hi"),
        lambda: room.wait(timeout=1),
        lambda: room.board.new("Ship it"),
        lambda: room.board.claim("work/ship-it"),
        lambda: room.board.resolve("work/ship-it"),
        lambda: room.memory.set("context/goal", "Friday"),
        lambda: room.files.upload(notes),
    ]
    for write in writes:
        with pytest.raises(MyceliumError, match="Say who you're acting as"):
            write()
    assert [r for r in hub.requests if r.method != "GET"] == []


def test_a_refusal_is_a_hub_error_with_what_the_hub_said(hub: StandInHub) -> None:
    hub.answer = lambda _r: (404, {"detail": "No memory 'context/none'"})
    with pytest.raises(HubError) as refused:
        Room().memory.get("context/none")
    assert refused.value.status_code == 404
    assert b"context/none" in refused.value.content


def test_it_uploads_a_file(hub: StandInHub, tmp_path: Path) -> None:
    notes = tmp_path / "notes.txt"
    notes.write_text("hello")
    assert Room().files.upload(notes)["name"] == "notes.txt"
    sent = hub.sent("POST", "/api/rooms/demo/uploads")[0].content
    assert b'name="created_by"' in sent
    assert b"hello" in sent


# ── the contract: every request it sends is one openapi.json describes ────────


def _route(spec: dict[str, Any], method: str, path: str) -> dict[str, Any]:
    """The operation ``openapi.json`` gives ``method`` on ``path``, or a failure.

    A memory key has slashes, so a parameter may span them. Of the routes that
    match, the one with the most fixed text wins, so ``memory/search`` is never
    taken for a key and ``rooms/{room_name}`` never for ``rooms/demo/await``.
    """
    matching = [
        (len(re.sub(r"\{[^/]+\}", "", template)), operations[method.lower()])
        for template, operations in spec["paths"].items()
        if method.lower() in operations
        and re.match("^" + re.sub(r"\{[^/]+\}", ".+", template) + "$", path)
    ]
    if not matching:
        pytest.fail(f"openapi.json has no {method} {path}")
    return max(matching, key=lambda m: m[0])[1]


def _schema(spec: dict[str, Any], ref: dict[str, Any]) -> dict[str, Any]:
    while "$ref" in ref:
        ref = spec["components"]["schemas"][ref["$ref"].rsplit("/", 1)[1]]
    return ref


def test_every_request_it_sends_is_one_the_hub_describes(hub: StandInHub, tmp_path: Path) -> None:
    notes = tmp_path / "notes.txt"
    notes.write_text("hello")
    room = Room()
    room.wait(timeout=5, task="work/ship-it")
    room.respond("On it.", task="work/ship-it")
    room.board.new("Ship it", body="Today.", assign="lead", parent="work/launch")
    room.board.claim("work/ship-it", ttl=30, force=True)
    room.board.resolve("work/ship-it")
    room.memory.set("context/goal", "Friday", tags=["launch"], meta={"expandable": True})
    room.memory.get("context/goal")
    room.memory.search("launch")
    room.files.upload(notes)

    spec = json.loads(OPENAPI.read_text())
    checked = set()
    for request in hub.requests:
        operation = _route(spec, request.method, request.url.path)
        declared = {p["name"] for p in operation.get("parameters", []) if p["in"] == "query"}
        assert set(request.url.params) <= declared, (request.url, declared)
        content = operation.get("requestBody", {}).get("content", {})
        if "application/json" in content:
            schema = _schema(spec, content["application/json"]["schema"])
            sent = json.loads(request.content)
            items = sent["items"] if "items" in sent and "items" in schema["properties"] else []
            assert set(sent) <= set(schema["properties"]), (request.url.path, sent)
            assert set(schema.get("required", [])) <= set(sent), (request.url.path, sent)
            item_schema = schema["properties"].get("items", {}).get("items")
            for item in items:
                fields = _schema(spec, item_schema)["properties"]
                assert set(item) <= set(fields) | {"meta"}, item
        checked.add((request.method, request.url.path))
    # Every verb above reached the hub, so none of them went unchecked.
    assert checked == {
        ("GET", "/api/rooms/demo/memory/work/ship-it"),
        ("GET", "/api/rooms/demo/await"),
        ("POST", "/api/rooms/demo/reply"),
        ("POST", "/api/rooms/demo/tasks"),
        ("POST", "/api/rooms/demo/assignments/claim"),
        ("POST", "/api/rooms/demo/assignments/resolve"),
        ("POST", "/api/rooms/demo/memory"),
        ("GET", "/api/rooms/demo/memory/context/goal"),
        ("POST", "/api/rooms/demo/memory/search"),
        ("POST", "/api/rooms/demo/uploads"),
    }
