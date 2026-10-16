# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Uploads: files a room keeps, each an ``uploads/`` memory and a blob."""

import io
from datetime import UTC, datetime, timedelta

import pytest
from PIL import Image

from app.config import settings
from app.services import message_format, persister, tasks, uploads
from app.services.message_models import Kind
from app.services.message_slim import serialize_content


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


def _say(room: str, message_id: str, *, sender: str, text: str, at, episode: str | None = None):
    """A message in the room's history, as a reply that rode the channel."""
    env = message_format.build_envelope(
        kind=Kind.exchange,
        episode=episode or message_format.live_episode_urn(room),
        sender=sender,
        recipients=[message_format.SYSTEM_ACTOR_ID],
        topic=f"urn:concept:mycelium:{room}",
        message_id=message_id,
        payload_type="reply",
    )
    record = persister.record_from(
        env, serialize_content(env, extra={"content": text}), now=at.isoformat()
    )
    persister.append_transcript(room, record)


@pytest.mark.asyncio
async def test_an_upload_says_which_message_it_was_posted_with(client, monkeypatch):
    monkeypatch.setattr("app.routes.memory.embed_text", lambda _text: [0.0])
    await _make_room(client)
    for name in ("shot.png", "notes.txt", "loose.txt", "quoted.txt"):
        await _upload(client, name, _png() if name.endswith(".png") else name.encode())
    row = await tasks.create_task("demo", "Fix the settings page", created_by="julia")
    thread = tasks.episode_of("demo", row.key)
    assert thread
    first = datetime.now(UTC) - timedelta(minutes=10)
    _say("demo", "m1", sender="julia", text="the bug\n\n[[uploads/shot.png]]", at=first)
    # Linked again later, in a task: the first message still counts.
    _say(
        "demo",
        "m2",
        sender="builder",
        text="same here [[uploads/shot.png]] and [[uploads/notes.txt]]",
        at=first + timedelta(minutes=1),
        episode=thread,
    )
    # A link written inside code is about the syntax, not an attachment.
    _say("demo", "m3", sender="julia", text="write `[[uploads/quoted.txt]]`", at=first)

    listing = (await client.get("/api/rooms/demo/uploads")).json()["uploads"]
    by_name = {u["name"]: u for u in listing}
    said = (await client.get("/api/rooms/demo/messages")).json()["messages"]
    ids = {m["content"]: m["id"] for m in said}

    shot = by_name["shot.png"]["posted_in"]
    assert shot["sender"] == "julia"
    assert shot["message_id"] == ids["the bug\n\n[[uploads/shot.png]]"]
    assert shot["episode"] is None
    assert shot["task"] is None

    notes = by_name["notes.txt"]["posted_in"]
    assert notes["sender"] == "builder"
    assert notes["episode"] == thread
    assert (notes["task"], notes["task_title"]) == (row.key, "Fix the settings page")

    assert by_name["loose.txt"]["posted_in"] is None
    assert by_name["quoted.txt"]["posted_in"] is None
    single = (await client.get("/api/rooms/demo/uploads/notes.txt")).json()
    assert single["posted_in"]["task"] == row.key


@pytest.mark.asyncio
async def test_the_uploaders_own_message_wins_over_a_teammate_linking_it_first(client):
    """An agent uploads with the CLI; a teammate links it before the agent does."""
    await _make_room(client)
    await _upload(client, "report.txt", b"the report", who="worker")
    first = datetime.now(UTC) - timedelta(minutes=10)
    _say("demo", "t1", sender="julia", text="look [[uploads/report.txt]]", at=first)
    _say(
        "demo",
        "t2",
        sender="worker",
        text="done: [[uploads/report.txt]]",
        at=first + timedelta(minutes=2),
    )
    up = (await client.get("/api/rooms/demo/uploads/report.txt")).json()
    assert up["created_by"] == "worker"
    assert up["posted_in"]["sender"] == "worker"
    listed = (await client.get("/api/rooms/demo/uploads")).json()["uploads"][0]
    assert listed["posted_in"]["sender"] == "worker"


@pytest.mark.asyncio
async def test_an_image_has_a_small_thumbnail_and_other_files_none(client):
    await _make_room(client)
    big = io.BytesIO()
    Image.new("RGB", (1600, 900), "teal").save(big, format="PNG")
    up = (await _upload(client, "wide.png", big.getvalue())).json()
    text = (await _upload(client, "a.txt", b"hello")).json()
    assert text["thumb_url"] is None
    assert up["thumb_url"].startswith("/api/rooms/demo/uploads/wide.png/thumb?v=")

    resp = await client.get(up["thumb_url"])
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/webp"
    assert "immutable" in resp.headers["cache-control"]
    with Image.open(io.BytesIO(resp.content)) as thumb:
        assert thumb.size == (uploads.THUMB_PX, 225)

    # Made once and kept, then gone with the file.
    path = uploads.thumb_path("demo", up["sha256"])
    assert path is not None
    assert path.is_file()
    assert (await client.get("/api/rooms/demo/uploads/a.txt/thumb")).status_code == 404
    assert (await client.delete("/api/rooms/demo/uploads/wide.png")).status_code == 204
    assert not path.exists()


def test_linked_keys_reads_links_like_the_app_does():
    text = (
        "see [[uploads/a.png]], [[uploads/b.pdf|the plan]] and [[uploads/a.png]]\n"
        "```\n[[uploads/c.txt]]\n```\n![[uploads/d.png]]"
    )
    assert uploads.linked_keys(text) == ["uploads/a.png", "uploads/b.pdf"]


def test_safe_name():
    assert uploads.safe_name("Rapport d'été.PDF") == "Rapport-d-ete.pdf"
    assert uploads.safe_name("../../etc/passwd") == "passwd"
    assert uploads.safe_name("C:\\Users\\me\\.bashrc") == "bashrc"
    assert uploads.safe_name("...") == "file"
