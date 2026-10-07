# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for ``mycelium file`` (upload / download / ls / show / rm).

Node-free and file-free on the hub side: the JSON routes' ``.sync`` functions
are stubbed and the raw client (multipart upload, streamed download) runs over
an ``httpx.MockTransport``.
"""

from __future__ import annotations

import datetime
import json
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from mycelium.commands import file as file_cmd
from mycelium_backend_client.errors import UnexpectedStatus

runner = CliRunner()

STAMP = datetime.datetime(2026, 10, 7, 9, 15, tzinfo=datetime.UTC)


@pytest.fixture(autouse=True)
def _home(isolated_home) -> None:
    """Every file test runs under the temp ``~/.mycelium``."""


class _Client:
    def __enter__(self):
        return object()

    def __exit__(self, *_a):
        return False


@pytest.fixture(autouse=True)
def _hub(monkeypatch: pytest.MonkeyPatch) -> None:
    """No command may open a real connection."""
    monkeypatch.setattr(file_cmd, "_get_client", lambda: _Client())


def _record(name: str = "spec.pdf", **overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "name": name,
        "key": f"uploads/{name}",
        "filename": name,
        "kind": "pdf",
        "content_type": "application/pdf",
        "size": 2048,
        "sha256": "a" * 64,
        "created_by": "julia",
        "created_at": STAMP.isoformat(),
        "url": f"/api/rooms/demo/uploads/{name}/raw",
    }
    fields.update(overrides)
    return fields


def _upload_read(name: str = "spec.pdf", **overrides: Any):
    from mycelium_backend_client.models import UploadRead

    return UploadRead.from_dict(_record(name, **overrides))


def _raw(monkeypatch: pytest.MonkeyPatch, handler) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def _wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    def _factory(_handle: str | None = None) -> httpx.Client:
        return httpx.Client(base_url="http://hub", transport=httpx.MockTransport(_wrapped))

    monkeypatch.setattr(file_cmd, "_raw_client", _factory)
    return seen


@pytest.mark.parametrize(
    "ref",
    [
        "spec.pdf",
        "uploads/spec.pdf",
        "[[uploads/spec.pdf]]",
        " ![[uploads/spec.pdf]] ",
        "myc://uploads/spec.pdf",
    ],
)
def test_upload_name_reads_every_way_a_file_is_written(ref: str) -> None:
    assert file_cmd.upload_name(ref) == "spec.pdf"


def test_upload_prints_the_link_and_continues_past_a_refusal(monkeypatch, tmp_path) -> None:
    good = tmp_path / "spec.pdf"
    good.write_bytes(b"%PDF-1.7")
    bad = tmp_path / "tool.exe"
    bad.write_bytes(b"MZ")

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read()
        if b'filename="tool.exe"' in body:
            return httpx.Response(415, json={"detail": "tool.exe: .exe files can't be previewed"})
        assert b'name="created_by"' in body
        assert b"julia" in body
        return httpx.Response(201, json=_record("spec.pdf"))

    seen = _raw(monkeypatch, handler)
    result = runner.invoke(
        file_cmd.app, ["upload", str(bad), str(good), "-r", "demo", "--as", "julia"]
    )
    assert result.exit_code == 1, result.output
    assert "[[uploads/spec.pdf]]" in result.output
    assert ".exe files can't be previewed" in result.output
    assert [r.url.path for r in seen] == ["/api/rooms/demo/uploads"] * 2


def test_upload_json_lists_what_was_added(monkeypatch, tmp_path) -> None:
    path = tmp_path / "spec.pdf"
    path.write_bytes(b"%PDF-1.7")
    _raw(monkeypatch, lambda _r: httpx.Response(201, json=_record("spec.pdf")))
    result = runner.invoke(file_cmd.app, ["upload", str(path), "-r", "demo", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)[0]["key"] == "uploads/spec.pdf"


def test_upload_a_missing_path_fails_without_calling_the_hub(monkeypatch, tmp_path) -> None:
    seen = _raw(monkeypatch, lambda _r: httpx.Response(201, json=_record()))
    result = runner.invoke(file_cmd.app, ["upload", str(tmp_path / "nope.pdf"), "-r", "demo"])
    assert result.exit_code == 1
    assert "Not a file" in result.output
    assert seen == []


def _stub_get(monkeypatch, record=None) -> None:
    def _sync(*, room_name, name, client):
        if record is None:
            raise UnexpectedStatus(404, b'{"detail": "Upload not found"}')
        return record

    monkeypatch.setattr(
        "mycelium_backend_client.api.uploads.get_upload_api_rooms_room_name_uploads_name_get.sync",
        _sync,
    )


def test_download_saves_to_the_files_own_name(monkeypatch, tmp_path) -> None:
    _stub_get(monkeypatch, _upload_read("spec.pdf"))
    seen = _raw(monkeypatch, lambda _r: httpx.Response(200, content=b"%PDF-1.7 bytes"))
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(file_cmd.app, ["download", "[[uploads/spec.pdf]]", "-r", "demo"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "spec.pdf").read_bytes() == b"%PDF-1.7 bytes"
    assert seen[0].url.path == "/api/rooms/demo/uploads/spec.pdf/raw"
    assert seen[0].url.params["download"] == "1"


def test_download_will_not_replace_a_file_without_force(monkeypatch, tmp_path) -> None:
    _stub_get(monkeypatch, _upload_read("spec.pdf"))
    _raw(monkeypatch, lambda _r: httpx.Response(200, content=b"new"))
    target = tmp_path / "out.pdf"
    target.write_bytes(b"old")
    result = runner.invoke(file_cmd.app, ["download", "spec.pdf", "-r", "demo", "-o", str(target)])
    assert result.exit_code == 1
    assert target.read_bytes() == b"old"
    forced = runner.invoke(
        file_cmd.app, ["download", "spec.pdf", "-r", "demo", "-o", str(target), "--force"]
    )
    assert forced.exit_code == 0, forced.output
    assert target.read_bytes() == b"new"


def test_download_to_stdout(monkeypatch) -> None:
    _stub_get(monkeypatch, _upload_read("notes.txt", kind="text"))
    _raw(monkeypatch, lambda _r: httpx.Response(200, content=b"ship on friday\n"))
    result = runner.invoke(file_cmd.app, ["download", "notes.txt", "-r", "demo", "-o", "-"])
    assert result.exit_code == 0, result.output
    assert "ship on friday" in result.output


def test_download_of_a_missing_file_says_so(monkeypatch) -> None:
    _stub_get(monkeypatch, None)
    result = runner.invoke(file_cmd.app, ["download", "gone.pdf", "-r", "demo"])
    assert result.exit_code == 1
    assert "Not found" in result.output


def test_ls_and_its_json(monkeypatch) -> None:
    from mycelium_backend_client.models import UploadListResponse

    resp = UploadListResponse.from_dict(
        {"uploads": [_record("spec.pdf"), _record("diagram.png", kind="image")], "total": 2}
    )
    monkeypatch.setattr(
        "mycelium_backend_client.api.uploads.list_room_uploads_api_rooms_room_name_uploads_get.sync",
        lambda *, room_name, client: resp,
    )
    result = runner.invoke(file_cmd.app, ["ls", "-r", "demo"])
    assert result.exit_code == 0, result.output
    assert "spec.pdf" in result.output
    assert "2.0 KB" in result.output
    limited = runner.invoke(file_cmd.app, ["ls", "-r", "demo", "--json", "-n", "1"])
    assert [u["name"] for u in json.loads(limited.output)] == ["spec.pdf"]


def test_show_prints_the_link(monkeypatch) -> None:
    _stub_get(monkeypatch, _upload_read("spec.pdf"))
    result = runner.invoke(file_cmd.app, ["show", "uploads/spec.pdf", "-r", "demo"])
    assert result.exit_code == 0, result.output
    assert "[[uploads/spec.pdf]]" in result.output


def test_rm_asks_unless_yes(monkeypatch) -> None:
    calls: list[str] = []

    class _Resp:
        status_code = 204

    def _sync_detailed(*, room_name, name, client):
        calls.append(name)
        return _Resp()

    monkeypatch.setattr(
        "mycelium_backend_client.api.uploads.delete_upload_api_rooms_room_name_uploads_name_delete.sync_detailed",
        _sync_detailed,
    )
    declined = runner.invoke(file_cmd.app, ["rm", "spec.pdf", "-r", "demo"], input="n\n")
    assert declined.exit_code == 0
    assert calls == []
    done = runner.invoke(file_cmd.app, ["rm", "[[uploads/spec.pdf]]", "-r", "demo", "--yes"])
    assert done.exit_code == 0, done.output
    assert calls == ["spec.pdf"]
