# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Uploads API: files a room keeps, a promoted view over ``uploads/`` memories.

An upload is a memory under ``uploads/`` plus the bytes it names (see
``app/services/uploads.py``). Adding one writes its record through the memory
upsert, so it is indexed, linked, threaded and announced like any memory.

POST   /rooms/{room}/uploads              add a file (multipart, one per request)
GET    /rooms/{room}/uploads              list the room's uploads
GET    /rooms/{room}/uploads/{name}       one upload's record
GET    /rooms/{room}/uploads/{name}/raw   its bytes (``?download=1`` to save)
DELETE /rooms/{room}/uploads/{name}       remove the record, and the bytes if unshared

A file goes back out sandboxed: its type comes from the service's table rather
than the record, ``nosniff`` stops a browser guessing otherwise, and the CSP
gives a file opened on its own no script, no requests and a unique origin.
"""

import asyncio
import logging
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse

from app.config import settings
from app.schemas import MemoryBatchCreate, MemoryCreate, UploadListResponse, UploadRead
from app.services import actor, links, search_index, uploads
from app.services.filesystem import (
    EPISODE_META,
    UPLOAD_META,
    delete_memory_file,
    get_room_dir,
    read_memory_file,
    recover_timestamps,
    room_exists,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rooms/{room_name}/uploads", tags=["uploads"])

# What every file response carries. The policy is the one GitHub serves raw
# files with: nothing loads, nothing runs, and the document gets an origin of
# its own, so even a file opened directly can't reach the app's session.
SANDBOX_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
    "X-Content-Type-Options": "nosniff",
    "Cross-Origin-Resource-Policy": "same-origin",
}

_CHUNK = 1024 * 1024


def _require_room(room_name: str) -> None:
    if not room_exists(room_name):
        raise HTTPException(status_code=404, detail="Room not found")


def _upload_read(room_name: str, key: str, meta: dict[str, Any]) -> UploadRead:
    info = meta[UPLOAD_META]
    name = uploads.name_from_key(key)
    filename = str(info.get("filename") or name)
    # The name's extension is the one the bytes were checked against, so the
    # type follows it, never the record's own `content_type`.
    served = uploads.type_for(name)
    created_at, _ = recover_timestamps(meta, get_room_dir(room_name) / f"{key}.md")
    return UploadRead(
        name=name,
        key=key,
        filename=filename,
        kind=served.kind if served else "text",
        content_type=served.content_type if served else "application/octet-stream",
        size=int(info.get("size") or 0),
        sha256=str(info.get("sha256") or ""),
        created_by=meta.get("created_by", "unknown"),
        created_at=created_at,
        episode=meta.get(EPISODE_META),
        url=f"/api/rooms/{quote(room_name)}/uploads/{quote(name)}/raw",
    )


def _find(room_name: str, name: str) -> tuple[str, dict[str, Any]]:
    """The record for ``name``, as ``(key, meta)``, or a 404."""
    key = uploads.key_for(name)
    found = read_memory_file(get_room_dir(room_name), key)
    if found is None or not isinstance(found[0].get(UPLOAD_META), dict):
        raise HTTPException(status_code=404, detail="Upload not found")
    return key, found[0]


async def _read_capped(file: UploadFile, limit: int) -> bytes:
    """The upload's bytes, refused with a 413 as soon as they pass ``limit``."""
    parts: list[bytes] = []
    total = 0
    while chunk := await file.read(_CHUNK):
        total += len(chunk)
        if total > limit:
            raise HTTPException(
                status_code=413,
                detail=f"{file.filename or 'This file'} is larger than {uploads.human_size(limit)}",
            )
        parts.append(chunk)
    return b"".join(parts)


@router.post("", response_model=UploadRead, status_code=201)
async def create_upload(
    room_name: str,
    request: Request,
    file: Annotated[UploadFile, File(description="The file to add")],
    created_by: Annotated[str, Form(description="Handle adding the file")],
) -> UploadRead:
    """Add a file to the room. Refused (415) unless the app can preview it."""
    # Break routes.memory ↔ routes.uploads cycle, as routes.skills does.
    from app.routes.memory import upsert_memories

    _require_room(room_name)
    author = actor.bind_delegated_actor(request, room_name, created_by, field="created_by")
    filename = (file.filename or "").strip() or "file"
    data = await _read_capped(file, settings.UPLOADS_MAX_BYTES)
    try:
        cleaned = await asyncio.to_thread(uploads.clean, filename, data)
    except uploads.UploadRefused as refused:
        raise HTTPException(
            status_code=refused.status, detail=f"{filename}: {refused}"
        ) from refused

    sha = await asyncio.to_thread(uploads.store_blob, room_name, cleaned.data)
    # Picking a free name and writing it are one step per room, so two files
    # with the same name added at once get two records rather than one
    # overwriting the other.
    async with _naming_lock(room_name):
        key, existing = uploads.choose_key(room_name, uploads.safe_name(filename), sha)
        if existing:
            return _find_read(room_name, key)
        body = uploads.describe(filename, cleaned.type, len(cleaned.data), cleaned.text)
        item = MemoryCreate(
            key=key,
            value={"text": body},
            content_text=f"{filename}\n\n{body}",
            created_by=author,
        )
        system = {
            UPLOAD_META: {
                "filename": filename,
                "sha256": sha,
                "size": len(cleaned.data),
                "kind": cleaned.type.kind,
                "content_type": cleaned.type.content_type,
            }
        }
        await upsert_memories(room_name, MemoryBatchCreate(items=[item]), system=system)
    return _find_read(room_name, key)


_naming_locks: dict[str, asyncio.Lock] = {}


def _naming_lock(room_name: str) -> asyncio.Lock:
    return _naming_locks.setdefault(room_name, asyncio.Lock())


def _find_read(room_name: str, key: str) -> UploadRead:
    found = read_memory_file(get_room_dir(room_name), key)
    assert found is not None
    return _upload_read(room_name, key, found[0])


@router.get("", response_model=UploadListResponse)
async def list_room_uploads(room_name: str) -> UploadListResponse:
    """The room's uploads, newest first, with what this hub accepts."""
    _require_room(room_name)
    items = [_upload_read(room_name, key, meta) for key, meta, _ in uploads.list_uploads(room_name)]
    return UploadListResponse(
        uploads=items,
        total=len(items),
        accepted=uploads.accepted_extensions(),
        max_bytes=settings.UPLOADS_MAX_BYTES,
    )


@router.get("/{name}", response_model=UploadRead)
async def get_upload(room_name: str, name: str) -> UploadRead:
    """One upload's record."""
    _require_room(room_name)
    key, meta = _find(room_name, name)
    return _upload_read(room_name, key, meta)


@router.get("/{name}/raw", response_class=FileResponse)
async def get_upload_bytes(
    room_name: str,
    name: str,
    download: Annotated[bool, Query(description="Save it rather than show it")] = False,
) -> FileResponse:
    """The file itself, sandboxed. Supports ranges, so audio and video can seek."""
    _require_room(room_name)
    key, meta = _find(room_name, name)
    read = _upload_read(room_name, key, meta)
    path = uploads.blob_path(room_name, read.sha256)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="This upload's file is missing on the hub")
    unknown = read.content_type == "application/octet-stream"
    disposition = "attachment" if download or unknown else "inline"
    return FileResponse(
        path,
        media_type=read.content_type,
        headers={
            **SANDBOX_HEADERS,
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(read.filename)}",
            "Cache-Control": "private, max-age=300",
            "ETag": f'"{read.sha256}"',
        },
    )


@router.delete("/{name}", status_code=204)
async def delete_upload(room_name: str, name: str) -> None:
    """Remove an upload's record, and its bytes once nothing else names them."""
    _require_room(room_name)
    key, meta = _find(room_name, name)
    room_dir = get_room_dir(room_name)
    delete_memory_file(room_dir, key)
    search_index.remove(room_name, key)
    links.remove(room_name, key)
    uploads.forget_blob(room_name, meta[UPLOAD_META].get("sha256"))
