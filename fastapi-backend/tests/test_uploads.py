# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Uploads: files a room keeps, each an ``uploads/`` memory and a blob."""

import io

import pytest
from PIL import Image

from app.config import settings
from app.services import uploads


@pytest.fixture(autouse=True)
def _stub_embeddings(monkeypatch):
    """An upload's record is a memory write, which embeds; keep the model unloaded."""
    monkeypatch.setattr("app.services.embedding._STUB", True)


async def _make_room(client, name: str = "demo") -> None:
    await client.post("/api/rooms", json={"name": name})


def _png(color: str = "red", *, exif: bool = False) -> bytes:
    image = Image.new("RGB", (8, 8), color)
    out = io.BytesIO()
    if exif:
        tags = Image.Exif()
        tags[0x010F] = "SecretCam"  # Make
        image.save(out, format="JPEG", exif=tags.tobytes())
    else:
        image.save(out, format="PNG")
    return out.getvalue()


async def _upload(client, filename: str, data: bytes, *, room: str = "demo", who: str = "julia"):
    return await client.post(
        f"/api/rooms/{room}/uploads",
        files={"file": (filename, data, "application/octet-stream")},
        data={"created_by": who},
    )


@pytest.mark.asyncio
async def test_upload_lists_reads_and_serves_the_file(client):
    await _make_room(client)
    resp = await _upload(client, "Diagram.PNG", _png())
    assert resp.status_code == 201, resp.text
    up = resp.json()
    assert up["name"] == "Diagram.png"
    assert up["key"] == "uploads/Diagram.png"
    assert up["filename"] == "Diagram.PNG"
    assert up["kind"] == "image"
    assert up["content_type"] == "image/png"
    assert up["created_by"] == "julia"
    assert up["episode"]
    assert up["url"] == "/api/rooms/demo/uploads/Diagram.png/raw"

    listing = (await client.get("/api/rooms/demo/uploads")).json()
    assert listing["total"] == 1
    assert "png" in listing["accepted"]
    assert listing["max_bytes"] == settings.UPLOADS_MAX_BYTES

    raw = await client.get(up["url"])
    assert raw.status_code == 200
    assert raw.headers["content-type"] == "image/png"
    assert "sandbox" in raw.headers["content-security-policy"]
    assert raw.headers["x-content-type-options"] == "nosniff"
    assert raw.headers["content-disposition"].startswith("inline")
    Image.open(io.BytesIO(raw.content)).verify()

    saved = await client.get(up["url"], params={"download": "1"})
    assert saved.headers["content-disposition"] == "attachment; filename*=UTF-8''Diagram.PNG"


@pytest.mark.asyncio
async def test_an_upload_is_a_memory_whose_record_a_write_cannot_repoint(client):
    await _make_room(client)
    up = (await _upload(client, "notes.txt", b"ship on friday\n")).json()

    mem = await client.get("/api/rooms/demo/memory/uploads/notes.txt")
    assert mem.status_code == 200
    assert "ship on friday" in mem.json()["content_text"]
    assert "upload" not in (mem.json()["meta"] or {})

    # A memory write can edit the body but not the store-owned record.
    await client.post(
        "/api/rooms/demo/memory",
        json={
            "items": [
                {
                    "key": "uploads/notes.txt",
                    "value": "edited",
                    "created_by": "mallory",
                    "meta": {"upload": {"sha256": "0" * 64, "content_type": "text/html"}},
                }
            ]
        },
    )
    after = (await client.get("/api/rooms/demo/uploads/notes.txt")).json()
    assert after["sha256"] == up["sha256"]
    assert after["content_type"] == "text/plain; charset=utf-8"


@pytest.mark.asyncio
async def test_images_are_reencoded_without_their_metadata(client):
    await _make_room(client)
    original = _png(exif=True)
    assert b"SecretCam" in original
    up = (await _upload(client, "photo.jpg", original)).json()
    raw = (await client.get(up["url"])).content
    assert b"SecretCam" not in raw
    assert Image.open(io.BytesIO(raw)).format == "JPEG"


@pytest.mark.asyncio
async def test_the_same_file_twice_is_one_upload_and_a_new_file_gets_a_new_name(client):
    await _make_room(client)
    first = (await _upload(client, "plan.png", _png("red"))).json()
    again = (await _upload(client, "plan.png", _png("red"))).json()
    assert again["key"] == first["key"]
    other = (await _upload(client, "plan.png", _png("blue"))).json()
    assert other["name"] == "plan-2.png"
    assert (await client.get("/api/rooms/demo/uploads")).json()["total"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filename", "data", "status"),
    [
        ("tool.exe", b"MZ\x90\x00", 415),
        ("archive.zip", b"PK\x03\x04", 415),
        ("README", b"no extension", 415),
        ("fake.pdf", b"<html><script>alert(1)</script>", 415),
        ("fake.png", b"%PDF-1.7 not an image", 415),
        ("binary.txt", b"text\x00with a nul", 415),
        ("latin1.csv", "café".encode("latin-1"), 415),
        ("empty.txt", b"", 422),
    ],
)
async def test_files_the_app_cannot_preview_are_refused(client, filename, data, status):
    await _make_room(client)
    resp = await _upload(client, filename, data)
    assert resp.status_code == status, resp.text
    assert filename in resp.json()["detail"]
    assert (await client.get("/api/rooms/demo/uploads")).json()["total"] == 0


@pytest.mark.asyncio
async def test_a_file_over_the_cap_is_refused(client, monkeypatch):
    await _make_room(client)
    monkeypatch.setattr(settings, "UPLOADS_MAX_BYTES", 10)
    resp = await _upload(client, "long.txt", b"x" * 11)
    assert resp.status_code == 413


@pytest.mark.asyncio
async def test_html_is_kept_as_text_and_served_as_text(client):
    await _make_room(client)
    up = (await _upload(client, "page.html", b"<script>alert(1)</script>")).json()
    assert up["kind"] == "text"
    raw = await client.get(up["url"])
    assert raw.headers["content-type"] == "text/plain; charset=utf-8"


@pytest.mark.asyncio
async def test_markdown_uploads_keep_a_key_the_store_can_read_back(client):
    await _make_room(client)
    up = (await _upload(client, "Design Notes.md", b"# Notes\n")).json()
    assert up["key"] == "uploads/Design-Notes.markdown"
    assert up["filename"] == "Design Notes.md"
    assert (await client.get(f"/api/rooms/demo/uploads/{up['name']}")).status_code == 200
    assert (
        await client.get("/api/rooms/demo/memory/uploads/Design-Notes.markdown")
    ).status_code == 200


@pytest.mark.asyncio
async def test_media_is_checked_by_signature(client):
    await _make_room(client)
    pdf = await _upload(client, "spec.pdf", b"%PDF-1.7\n1 0 obj\n%%EOF\n")
    assert pdf.json()["kind"] == "pdf"
    mp4 = await _upload(client, "clip.mp4", b"\x00\x00\x00\x18ftypisom" + b"\x00" * 16)
    assert mp4.json()["kind"] == "video"
    wav = await _upload(client, "voice.wav", b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 16)
    assert wav.json()["kind"] == "audio"


@pytest.mark.asyncio
async def test_deleting_removes_the_bytes_once_nothing_names_them(client):
    await _make_room(client)
    up = (await _upload(client, "a.txt", b"same bytes")).json()
    twin = (await _upload(client, "b.txt", b"same bytes")).json()
    assert twin["sha256"] == up["sha256"]
    blob = uploads.blob_path("demo", up["sha256"])
    assert blob is not None
    assert blob.exists()

    assert (await client.delete("/api/rooms/demo/uploads/a.txt")).status_code == 204
    assert blob.exists()
    # The memory route frees it too.
    assert (await client.delete("/api/rooms/demo/memory/uploads/b.txt")).status_code == 204
    assert not blob.exists()
    assert (await client.get("/api/rooms/demo/uploads/a.txt")).status_code == 404


@pytest.mark.asyncio
async def test_upload_to_a_missing_room_is_404(client):
    resp = await _upload(client, "a.txt", b"hello", room="nowhere")
    assert resp.status_code == 404


def test_safe_name():
    assert uploads.safe_name("Rapport d'été.PDF") == "Rapport-d-ete.pdf"
    assert uploads.safe_name("../../etc/passwd") == "passwd"
    assert uploads.safe_name("C:\\Users\\me\\.bashrc") == "bashrc"
    assert uploads.safe_name("...") == "file"
