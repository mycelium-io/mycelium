# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for ``mycelium memory`` (set / get / ls / search).

Node-free: ``get`` and ``ls`` read the local markdown under a temp home
(``isolated_home``); ``set`` and ``search`` go through the backend, whose API
``.sync`` is stubbed. No live stack.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from mycelium.commands import memory as memory_cmd
from mycelium.filesystem import get_room_dir, write_memory

runner = CliRunner()


@pytest.fixture(autouse=True)
def _home(isolated_home) -> None:
    """Every memory test reads/writes under the temp ``~/.mycelium``."""


def _seed(room: str, key: str, value: str) -> None:
    write_memory(get_room_dir(room), key, value, created_by="tester")


def _stub_create(monkeypatch: pytest.MonkeyPatch) -> list:
    """Stub the create-memories API, returning the batches it was handed."""
    import datetime
    import uuid

    from mycelium_backend_client.models import MemoryRead

    class _Client:
        def __enter__(self):
            return object()

        def __exit__(self, *_a):
            return False

    monkeypatch.setattr(memory_cmd, "_get_client", lambda: _Client())

    captured: list = []
    stamp = datetime.datetime(2026, 6, 1)  # noqa: DTZ001

    def _sync(*, room_name: str, client, body):  # noqa: ANN001, ARG001
        captured.append(body)
        item = body.items[0]
        return [
            MemoryRead(
                id=uuid.uuid4(),
                key=item.key,
                value=item.value,
                version=1,
                created_by=item.created_by,
                room_name=room_name,
                created_at=stamp,
                updated_at=stamp,
            )
        ]

    monkeypatch.setattr(
        "mycelium_backend_client.api.memory.create_memories_api_rooms_room_name_memory_post.sync",
        _sync,
    )
    return captured


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


def test_memory_get_prints_key_and_content() -> None:
    _seed("demo", "decisions/db", "we chose postgres")
    result = runner.invoke(memory_cmd.app, ["get", "decisions/db", "--room", "demo"])
    assert result.exit_code == 0, result.output
    assert "decisions/db" in result.output
    assert "we chose postgres" in result.output


def test_memory_get_missing_key_exits_nonzero() -> None:
    result = runner.invoke(memory_cmd.app, ["get", "nope", "--room", "demo"])
    assert result.exit_code == 1
    assert "Not found" in result.output


def test_memory_ls_lists_and_filters_by_prefix() -> None:
    _seed("demo", "decisions/db", "postgres")
    _seed("demo", "decisions/lang", "python")
    _seed("demo", "status/sprint", "green")

    listed = runner.invoke(memory_cmd.app, ["ls", "--room", "demo"])
    assert listed.exit_code == 0, listed.output
    assert "3 memories" in listed.output

    filtered = runner.invoke(memory_cmd.app, ["ls", "decisions/", "--room", "demo"])
    assert filtered.exit_code == 0, filtered.output
    assert "2 memories" in filtered.output
    assert "status/sprint" not in filtered.output


def test_memory_ls_empty_prints_hint() -> None:
    result = runner.invoke(memory_cmd.app, ["ls", "--room", "demo"])
    assert result.exit_code == 0, result.output
    assert "No memories found" in result.output


def test_memory_search_renders_backend_results(monkeypatch: pytest.MonkeyPatch) -> None:
    import datetime
    import uuid

    from mycelium_backend_client.models import (
        MemoryRead,
        MemorySearchResponse,
        MemorySearchResult,
    )

    monkeypatch.setattr(memory_cmd, "_get_active_room", lambda _room: "demo")

    stamp = datetime.datetime(2026, 6, 1)  # noqa: DTZ001

    class _Client:
        def __enter__(self):
            return object()

        def __exit__(self, *_a):
            return False

    monkeypatch.setattr(memory_cmd, "_get_client", lambda: _Client())

    mem = MemoryRead(
        id=uuid.uuid4(),
        key="decisions/db",
        value="postgres",
        content_text="we chose postgres for durability",
        version=1,
        created_by="tester",
        room_name="demo",
        created_at=stamp,
        updated_at=stamp,
    )
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

    monkeypatch.setattr(memory_cmd, "_get_active_room", lambda _room: "demo")

    class _Client:
        def __enter__(self):
            return object()

        def __exit__(self, *_a):
            return False

    monkeypatch.setattr(memory_cmd, "_get_client", lambda: _Client())
    monkeypatch.setattr(
        "mycelium_backend_client.api.memory."
        "search_memories_api_rooms_room_name_memory_search_post.sync",
        lambda **_kw: MemorySearchResponse(results=[], total=0),
    )

    result = runner.invoke(memory_cmd.app, ["search", "nothing", "--room", "demo"])
    assert result.exit_code == 0, result.output
    assert "No matching memories found" in result.output
