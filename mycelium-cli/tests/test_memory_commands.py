# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for ``mycelium memory`` (set / get / ls / search).

Node-free and file-free: every command resolves against the hub, so the API
``.sync`` functions are stubbed. The temp home (``isolated_home``) deliberately
holds no ``rooms/`` files — that is the point of the thin client, and the reads
below still return the hub's memories.
"""

from __future__ import annotations

import datetime
import uuid
from http import HTTPStatus
from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from mycelium.commands import memory as memory_cmd
from mycelium_backend_client.errors import UnexpectedStatus
from mycelium_backend_client.types import Response

runner = CliRunner()

STAMP = datetime.datetime(2026, 6, 1, 12, 30, tzinfo=datetime.UTC)


@pytest.fixture(autouse=True)
def _home(isolated_home) -> None:
    """Every memory test runs under the temp ``~/.mycelium`` (no room files)."""


class _Client:
    def __enter__(self):
        return object()

    def __exit__(self, *_a):
        return False


@pytest.fixture(autouse=True)
def _hub(monkeypatch: pytest.MonkeyPatch) -> None:
    """No command may open a real connection."""
    monkeypatch.setattr(memory_cmd, "_get_client", lambda: _Client())


def _record(key: str, value: Any, **overrides: Any) -> dict[str, Any]:
    """A memory as the hub's list endpoint serializes it."""
    return {
        "key": key,
        "value": value,
        "created_by": "tester",
        "version": 1,
        "created_at": STAMP.isoformat(),
        "updated_at": STAMP.isoformat(),
        **overrides,
    }


def _memory_read(key: str, value: Any, **overrides: Any):
    from mycelium_backend_client.models import MemoryRead

    fields: dict[str, Any] = {
        "id": uuid.uuid4(),
        "room_name": "demo",
        "key": key,
        "value": value,
        "created_by": "tester",
        "version": 1,
        "created_at": STAMP,
        "updated_at": STAMP,
    }
    fields.update(overrides)
    return MemoryRead(**fields)


def _structured(**fields: Any):
    from mycelium_backend_client.models import MemoryReadValueType0

    return MemoryReadValueType0.from_dict(fields)


def _stub_get(monkeypatch: pytest.MonkeyPatch, result: Any) -> None:
    """Stub the get-memory API; an Exception instance is raised instead."""

    def _sync(**_kw: Any):
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(
        "mycelium_backend_client.api.memory.get_memory_api_rooms_room_name_memory_key_get.sync",
        _sync,
    )


def _stub_list(
    monkeypatch: pytest.MonkeyPatch, result: Any, pages: list[Any] | None = None
) -> list[dict[str, Any]]:
    """Stub the list-memories API; returns the kwargs it was called with.

    ``pages`` serves a paginated hub: each entry is one page, and every page but
    the last advertises a next cursor in its headers (where this list carries its
    pagination, its body being a bare list).
    """
    calls: list[dict[str, Any]] = []
    queued = list(pages) if pages is not None else None

    def _sync_detailed(**kwargs: Any):
        calls.append(kwargs)
        if isinstance(result, Exception):
            raise result
        if queued is None:
            return _response(result, more=False)
        page = queued.pop(0) if queued else []
        return _response(page, more=bool(queued), cursor=f"cursor-{len(calls)}")

    monkeypatch.setattr(
        "mycelium_backend_client.api.memory.list_memories_api_rooms_room_name_memory_get"
        ".sync_detailed",
        _sync_detailed,
    )
    return calls


def _response(parsed: Any, *, more: bool, cursor: str = "") -> Response:
    headers = {"x-has-more": "true" if more else "false"}
    if more:
        headers["x-next-cursor"] = cursor
    return Response(status_code=HTTPStatus.OK, content=b"", headers=headers, parsed=parsed)


def _stub_create(monkeypatch: pytest.MonkeyPatch) -> list:
    """Stub the create-memories API, returning the batches it was handed."""
    captured: list = []

    def _sync(*, room_name: str, client, body):  # noqa: ANN001, ARG001
        captured.append(body)
        item = body.items[0]
        return [_memory_read(item.key, item.value, room_name=room_name, created_by=item.created_by)]

    monkeypatch.setattr(
        "mycelium_backend_client.api.memory.create_memories_api_rooms_room_name_memory_post.sync",
        _sync,
    )
    return captured


# ── set ──────────────────────────────────────────────────────────────────────


def test_memory_set_file_value_round_trips(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured = _stub_create(monkeypatch)
    spec = tmp_path / "spec.md"
    spec.write_text('# Spec\n\nLine "two" with quotes & newlines.\n', encoding="utf-8")

    result = runner.invoke(
        memory_cmd.app, ["set", "reference/spec", "--file", str(spec), "--room", "demo"]
    )
    assert result.exit_code == 0, result.output
    assert captured[0].items[0].value == spec.read_text(encoding="utf-8")


def test_memory_set_file_dash_reads_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _stub_create(monkeypatch)

    result = runner.invoke(
        memory_cmd.app,
        ["set", "context/notes", "-f", "-", "--room", "demo"],
        input="piped body\n",
    )
    assert result.exit_code == 0, result.output
    # context/ is a structured category, so the piped text lands in the value's text field
    assert captured[0].items[0].value["text"] == "piped body\n"


def test_memory_set_rejects_both_value_and_file(tmp_path: Path) -> None:
    spec = tmp_path / "spec.md"
    spec.write_text("body", encoding="utf-8")

    result = runner.invoke(
        memory_cmd.app, ["set", "reference/spec", "inline", "--file", str(spec), "--room", "demo"]
    )
    assert result.exit_code == 1
    assert "not both" in result.output


def test_memory_set_rejects_neither_value_nor_file() -> None:
    result = runner.invoke(memory_cmd.app, ["set", "reference/spec", "--room", "demo"])
    assert result.exit_code == 1
    assert "--file" in result.output


def test_memory_set_missing_file_errors(tmp_path: Path) -> None:
    result = runner.invoke(
        memory_cmd.app,
        ["set", "reference/spec", "--file", str(tmp_path / "nope.md"), "--room", "demo"],
    )
    assert result.exit_code == 1
    assert "cannot read" in result.output


# ── get ──────────────────────────────────────────────────────────────────────


def test_memory_get_reads_from_hub_without_local_files(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_get(monkeypatch, _memory_read("decisions/db", "we chose postgres"))

    result = runner.invoke(memory_cmd.app, ["get", "decisions/db", "--room", "demo"])
    assert result.exit_code == 0, result.output
    assert "decisions/db" in result.output
    assert "we chose postgres" in result.output


def test_memory_get_renders_structured_value(monkeypatch: pytest.MonkeyPatch) -> None:
    value = _structured(text="deploy is green", logged_at=STAMP.isoformat(), category="status")
    _stub_get(monkeypatch, _memory_read("status/deploy", value))

    result = runner.invoke(memory_cmd.app, ["get", "status/deploy", "--room", "demo"])
    assert result.exit_code == 0, result.output
    assert "deploy is green" in result.output


def test_memory_get_renders_textless_structured_value_as_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_get(monkeypatch, _memory_read("context/config", _structured(retries=3)))

    result = runner.invoke(memory_cmd.app, ["get", "context/config", "--room", "demo"])
    assert result.exit_code == 0, result.output
    assert "retries" in result.output


def test_memory_get_raw_renders_markdown_form(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_get(
        monkeypatch,
        _memory_read("decisions/db", "we chose postgres", tags=["infra"], updated_by="other"),
    )

    result = runner.invoke(memory_cmd.app, ["get", "decisions/db", "--raw", "--room", "demo"])
    assert result.exit_code == 0, result.output
    assert result.output.startswith("---")
    assert "key: decisions/db" in result.output
    assert "created_by: tester" in result.output
    assert "we chose postgres" in result.output


def test_memory_get_missing_key_exits_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_get(monkeypatch, UnexpectedStatus(404, b'{"detail":"Memory not found"}'))

    result = runner.invoke(memory_cmd.app, ["get", "nope", "--room", "demo"])
    assert result.exit_code == 1
    assert "Not found" in result.output


def test_memory_get_unreachable_hub_reports_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_get(monkeypatch, httpx.ConnectError("connection refused"))

    result = runner.invoke(memory_cmd.app, ["get", "decisions/db", "--room", "demo"])
    assert result.exit_code == 1
    assert "can't reach the hub at" in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_memory_get_hub_error_status_reports_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_get(monkeypatch, UnexpectedStatus(500, b"boom"))

    result = runner.invoke(memory_cmd.app, ["get", "decisions/db", "--room", "demo"])
    assert result.exit_code == 1
    assert "HTTP 500" in result.output


# ── ls ───────────────────────────────────────────────────────────────────────


def test_memory_ls_lists_from_hub_without_local_files(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_list(
        monkeypatch,
        [_record("decisions/db", "postgres"), _record("decisions/lang", "python")],
    )

    result = runner.invoke(memory_cmd.app, ["ls", "--room", "demo"])
    assert result.exit_code == 0, result.output
    assert "2 memories" in result.output
    assert "decisions/db" in result.output
    assert "postgres" in result.output


def test_memory_ls_forwards_prefix_and_limit_to_hub(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _stub_list(monkeypatch, [_record("decisions/db", "postgres")])

    result = runner.invoke(memory_cmd.app, ["ls", "decisions/", "--room", "demo", "-n", "5"])
    assert result.exit_code == 0, result.output
    assert calls[0]["prefix"] == "decisions/"
    assert calls[0]["limit"] == 5
    assert calls[0]["room_name"] == "demo"


def test_memory_ls_renders_structured_values(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_list(
        monkeypatch,
        [_record("status/sprint", {"text": "green", "logged_at": "x", "category": "status"})],
    )

    result = runner.invoke(memory_cmd.app, ["ls", "--room", "demo"])
    assert result.exit_code == 0, result.output
    assert "green" in result.output


def test_memory_ls_empty_prints_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_list(monkeypatch, [])

    result = runner.invoke(memory_cmd.app, ["ls", "--room", "demo"])
    assert result.exit_code == 0, result.output
    assert "No memories found" in result.output


def test_memory_ls_unknown_room_reports_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_list(monkeypatch, UnexpectedStatus(404, b'{"detail":"Room not found"}'))

    result = runner.invoke(memory_cmd.app, ["ls", "--room", "ghost"])
    assert result.exit_code == 1
    assert "ghost" in result.output


def test_memory_ls_unreachable_hub_reports_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_list(monkeypatch, httpx.ConnectError("connection refused"))

    result = runner.invoke(memory_cmd.app, ["ls", "--room", "demo"])
    assert result.exit_code == 1
    assert "can't reach the hub at" in result.output


def test_memory_category_view_reads_from_hub(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _stub_list(monkeypatch, [_record("decisions/db", "postgres")])

    result = runner.invoke(memory_cmd.app, ["decisions", "--room", "demo"])
    assert result.exit_code == 0, result.output
    assert calls[0]["prefix"] == "decisions/"
    # the category prefix is stripped in the table
    assert "postgres" in result.output


# ── search ───────────────────────────────────────────────────────────────────


def test_memory_search_renders_backend_results(monkeypatch: pytest.MonkeyPatch) -> None:
    from mycelium_backend_client.models import MemorySearchResponse, MemorySearchResult

    mem = _memory_read("decisions/db", "postgres", content_text="we chose postgres for durability")
    resp = MemorySearchResponse(results=[MemorySearchResult(memory=mem, similarity=0.91)], total=1)
    monkeypatch.setattr(
        "mycelium_backend_client.api.memory."
        "search_memories_api_rooms_room_name_memory_search_post.sync",
        lambda **_kw: resp,
    )

    result = runner.invoke(memory_cmd.app, ["search", "database choice", "--room", "demo"])
    assert result.exit_code == 0, result.output
    assert "decisions/db" in result.output
    assert "0.910" in result.output
    assert "we chose postgres" in result.output


def test_memory_search_no_results(monkeypatch: pytest.MonkeyPatch) -> None:
    from mycelium_backend_client.models import MemorySearchResponse

    monkeypatch.setattr(
        "mycelium_backend_client.api.memory."
        "search_memories_api_rooms_room_name_memory_search_post.sync",
        lambda **_kw: MemorySearchResponse(results=[], total=0),
    )

    result = runner.invoke(memory_cmd.app, ["search", "nothing", "--room", "demo"])
    assert result.exit_code == 0, result.output
    assert "No matching memories found" in result.output


def test_memory_ls_walks_every_page_with_all(monkeypatch: pytest.MonkeyPatch) -> None:
    """Past the first page a room's memories used to be unreachable (issue #654)."""
    calls = _stub_list(
        monkeypatch,
        None,
        pages=[
            [_record("decisions/db", "postgres")],
            [_record("decisions/lang", "python")],
            [_record("decisions/ui", "next")],
        ],
    )

    result = runner.invoke(memory_cmd.app, ["ls", "--room", "demo", "-n", "1", "--all"])

    assert result.exit_code == 0, result.output
    assert "decisions/db" in result.output
    assert "decisions/lang" in result.output
    assert "decisions/ui" in result.output
    assert [c["cursor"] for c in calls][1:] == ["cursor-1", "cursor-2"]


def test_memory_ls_reads_one_page_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _stub_list(
        monkeypatch,
        None,
        pages=[[_record("decisions/db", "postgres")], [_record("decisions/lang", "python")]],
    )

    result = runner.invoke(memory_cmd.app, ["ls", "--room", "demo", "-n", "1"])

    assert result.exit_code == 0, result.output
    assert "decisions/lang" not in result.output
    assert len(calls) == 1
