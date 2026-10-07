# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Uploads: files a room keeps, each one a memory promoted.

An upload is two things on the hub. The bytes are a blob named by their
SHA-256 at ``rooms/{room}/uploads/.blobs/<sha256>``, with no extension, so the
store's ``*.md`` scans never read one as a memory. The record is a memory at
``uploads/<name>``: who added it and when, a short description (or a text
file's own text, so search finds it), and the store-owned ``upload``
frontmatter that says which blob it is and what it is. Being a memory, an
upload links as ``[[uploads/<name>]]``, shows in the Memory list, has a thread
of its own, and is announced like any write.

Only files the app can preview are taken: images, PDFs, UTF-8 text, and common
audio and video. A file is accepted on its extension and its bytes agreeing,
never on the name or the browser's content type alone. Images are decoded and
re-encoded, which drops EXIF (location included) and anything that rode along
in the file; the rest is checked by signature and stored as sent.

What makes serving safe is mostly how a file goes back out (``routes/uploads``):
the content type comes from this module's table, never from frontmatter a
memory write could have edited, and every response is sandboxed and unsniffable.
"""

from __future__ import annotations

import hashlib
import io
import re
import secrets
import unicodedata
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from PIL import Image, ImageOps

from app.services.filesystem import (
    UPLOAD_META,
    _cleanup_empty_dirs,
    contained,
    get_room_dir,
    list_memory_files,
)

UPLOADS_PREFIX = "uploads/"
BLOBS_DIR = ".blobs"

Kind = Literal["image", "pdf", "text", "audio", "video"]

# Largest image accepted, in pixels. A small file can decode to an enormous
# bitmap; past this an image is refused rather than decoded.
MAX_IMAGE_PIXELS = 64_000_000

# How much of a text upload goes into its memory's body, for search and for an
# agent that reads it with `memory get`. The whole file is always kept.
TEXT_BODY_LIMIT = 64_000


class UploadRefused(ValueError):
    """A file the hub won't keep, with the reason to show the person."""

    def __init__(self, message: str, *, status: int = 415) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class FileType:
    kind: Kind
    content_type: str


_IMAGE = {
    "png": FileType("image", "image/png"),
    "jpg": FileType("image", "image/jpeg"),
    "jpeg": FileType("image", "image/jpeg"),
    "gif": FileType("image", "image/gif"),
    "webp": FileType("image", "image/webp"),
}
_MEDIA = {
    "pdf": FileType("pdf", "application/pdf"),
    "mp3": FileType("audio", "audio/mpeg"),
    "wav": FileType("audio", "audio/wav"),
    "ogg": FileType("audio", "audio/ogg"),
    "oga": FileType("audio", "audio/ogg"),
    "flac": FileType("audio", "audio/flac"),
    "m4a": FileType("audio", "audio/mp4"),
    "mp4": FileType("video", "video/mp4"),
    "m4v": FileType("video", "video/mp4"),
    "mov": FileType("video", "video/quicktime"),
    "webm": FileType("video", "video/webm"),
}
# Text is served as text/plain whatever it holds, so an .html or .svg file is
# shown as its source and never rendered as a page.
_TEXT_EXTENSIONS = frozenset(
    [
        "txt",
        "md",
        "markdown",
        "csv",
        "tsv",
        "json",
        "jsonl",
        "yaml",
        "yml",
        "toml",
        "ini",
        "cfg",
        "conf",
        "log",
        "env",
        "py",
        "ts",
        "tsx",
        "js",
        "jsx",
        "mjs",
        "cjs",
        "go",
        "rs",
        "java",
        "kt",
        "swift",
        "c",
        "h",
        "cc",
        "cpp",
        "hpp",
        "cs",
        "rb",
        "php",
        "sh",
        "bash",
        "zsh",
        "fish",
        "sql",
        "css",
        "scss",
        "html",
        "htm",
        "xml",
        "svg",
        "graphql",
        "proto",
        "tf",
        "lua",
        "r",
        "diff",
        "patch",
    ]
)
TEXT_TYPE = FileType("text", "text/plain; charset=utf-8")

TYPES: dict[str, FileType] = {
    **_IMAGE,
    **_MEDIA,
    **dict.fromkeys(_TEXT_EXTENSIONS, TEXT_TYPE),
}

# Pillow's format name for each image extension, to check the bytes decode as
# what the name says.
_PIL_FORMAT = {"png": "PNG", "jpg": "JPEG", "jpeg": "JPEG", "gif": "GIF", "webp": "WEBP"}


def extension_of(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def type_for(filename: str) -> FileType | None:
    """The type a file with this name is served as, or ``None`` if it isn't taken."""
    return TYPES.get(extension_of(filename))


def accepted_extensions() -> list[str]:
    return sorted(TYPES)


# ── Checking and cleaning ────────────────────────────────────────────────────


def _is_iso_media(head: bytes) -> bool:
    # MP4, M4A, MOV: an ISO base media file opens with a box whose type is `ftyp`.
    return head[4:8] == b"ftyp"


def _signature_matches(ext: str, head: bytes) -> bool:
    match ext:
        case "pdf":
            return b"%PDF-" in head[:1024]
        case "mp3":
            return head.startswith(b"ID3") or (
                len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0
            )
        case "wav":
            return head[:4] == b"RIFF" and head[8:12] == b"WAVE"
        case "ogg" | "oga":
            return head.startswith(b"OggS")
        case "flac":
            return head.startswith(b"fLaC")
        case "m4a" | "mp4" | "m4v" | "mov":
            return _is_iso_media(head)
        case "webm":
            return head.startswith(b"\x1a\x45\xdf\xa3")
        case _:
            return False


def _clean_image(data: bytes, ext: str) -> bytes:
    """Decode and re-encode an image, keeping its pixels and dropping the rest."""
    expected = _PIL_FORMAT[ext]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as probe:
                if probe.format != expected:
                    msg = f"this file isn't a {ext.upper()} image"
                    raise UploadRefused(msg)
                if probe.width * probe.height > MAX_IMAGE_PIXELS:
                    msg = "this image is too large to preview"
                    raise UploadRefused(msg, status=413)
                probe.verify()
            image = Image.open(io.BytesIO(data))
            image.load()
    except UploadRefused:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        msg = "this image is too large to preview"
        raise UploadRefused(msg, status=413) from exc
    except Exception as exc:
        msg = f"this file isn't a readable {ext.upper()} image"
        raise UploadRefused(msg) from exc

    out = io.BytesIO()
    with image:
        icc = image.info.get("icc_profile")
        animated = getattr(image, "n_frames", 1) > 1 and expected in {"GIF", "WEBP"}
        if animated:
            image.save(
                out,
                format=expected,
                save_all=True,
                loop=image.info.get("loop", 0),
                duration=image.info.get("duration", 100),
            )
        else:
            # Apply the camera's rotation before the EXIF that carried it is dropped.
            upright = ImageOps.exif_transpose(image)
            if expected == "JPEG" and upright.mode not in {"RGB", "L", "CMYK"}:
                upright = upright.convert("RGB")
            options: dict[str, Any] = {"icc_profile": icc} if icc else {}
            if expected == "JPEG":
                options["quality"] = 92
            upright.save(out, format=expected, **options)
    return out.getvalue()


def _check_text(data: bytes) -> str:
    if b"\x00" in data:
        msg = "this file has binary content, not text"
        raise UploadRefused(msg)
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        msg = "this text file isn't UTF-8"
        raise UploadRefused(msg) from exc


@dataclass(frozen=True)
class Cleaned:
    data: bytes
    type: FileType
    text: str | None = None


def clean(filename: str, data: bytes) -> Cleaned:
    """The bytes to keep for ``filename``, or :class:`UploadRefused` saying why not."""
    ext = extension_of(filename)
    file_type = TYPES.get(ext)
    if file_type is None:
        shown = f".{ext} files" if ext else "files without an extension"
        msg = f"{shown} can't be previewed, so they can't be uploaded"
        raise UploadRefused(msg)
    if not data:
        msg = "this file is empty"
        raise UploadRefused(msg, status=422)
    if file_type.kind == "image":
        return Cleaned(_clean_image(data, ext), file_type)
    if file_type.kind == "text":
        return Cleaned(data, file_type, _check_text(data))
    if not _signature_matches(ext, data[:1024]):
        msg = f"this file's contents don't match .{ext}"
        raise UploadRefused(msg)
    return Cleaned(data, file_type)


# ── Names ────────────────────────────────────────────────────────────────────

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_name(filename: str) -> str:
    """A filename reduced to what a memory key and a URL segment can carry.

    ``Rapport d'été.PDF`` becomes ``Rapport-d-ete.pdf``: accents folded, runs of
    anything else turned into one dash, the extension lowercased, no leading
    dots. The original name is kept on the record for download.
    """
    base = Path(filename.replace("\\", "/")).name
    ascii_name = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode().lstrip(".")
    stem, dot, ext = ascii_name.rpartition(".")
    if not dot:
        stem, ext = ascii_name, ""
    stem = _UNSAFE.sub("-", stem).strip("-.") or "file"
    name = f"{stem[:96]}.{ext.lower()}" if ext else stem[:96]
    return _UNSAFE.sub("-", name)


def key_for(name: str) -> str:
    """The memory key an upload named ``name`` is kept under.

    The store reads a key ending in ``.md`` as the file itself rather than a key
    to append ``.md`` to, so a Markdown upload's key spells it ``.markdown``.
    """
    if name.endswith(".md"):
        name = name[: -len(".md")] + ".markdown"
    return f"{UPLOADS_PREFIX}{name}"


def name_from_key(key: str) -> str:
    return key[len(UPLOADS_PREFIX) :] if key.startswith(UPLOADS_PREFIX) else key


def _with_suffix(name: str, n: int) -> str:
    stem, dot, ext = name.rpartition(".")
    return f"{stem}-{n}.{ext}" if dot else f"{name}-{n}"


# ── Storage ──────────────────────────────────────────────────────────────────


def blobs_dir(room_name: str) -> Path:
    return get_room_dir(room_name) / UPLOADS_PREFIX.rstrip("/") / BLOBS_DIR


def blob_path(room_name: str, sha256: str) -> Path | None:
    """Where a blob lives, or ``None`` for a hash that isn't one."""
    if not re.fullmatch(r"[0-9a-f]{64}", sha256 or ""):
        return None
    return contained(blobs_dir(room_name), sha256)


def store_blob(room_name: str, data: bytes) -> str:
    """Write ``data`` under its hash (once) and return the hash."""
    sha = hashlib.sha256(data).hexdigest()
    path = blob_path(room_name, sha)
    assert path is not None
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{sha}.{secrets.token_hex(4)}.part")
        tmp.write_bytes(data)
        tmp.replace(path)
    return sha


def list_uploads(room_name: str) -> list[tuple[str, dict[str, Any], str]]:
    """Every upload in the room as ``(key, meta, body)``, newest first."""
    entries = list_memory_files(get_room_dir(room_name), prefix=UPLOADS_PREFIX)
    return [
        (key, meta, body) for key, meta, body in entries if isinstance(meta.get(UPLOAD_META), dict)
    ]


def choose_key(room_name: str, name: str, sha256: str) -> tuple[str, bool]:
    """The key for a new upload, and whether that key already holds these bytes.

    The same bytes under the same name are the same upload, so adding a file
    twice links to one record. A different file with a taken name gets a
    numbered one (``plan-2.pdf``), so a link already sent in chat keeps showing
    the file it was sent with.
    """
    taken = {
        key: meta.get(UPLOAD_META, {})
        for key, meta, _ in list_memory_files(get_room_dir(room_name), prefix=UPLOADS_PREFIX)
    }
    candidate, n = name, 1
    while (key := key_for(candidate)) in taken:
        if taken[key].get("sha256") == sha256:
            return key, True
        n += 1
        candidate = _with_suffix(name, n)
    return key, False


def describe(filename: str, file_type: FileType, size: int, text: str | None) -> str:
    """The memory body for an upload: a text file's own text, else a line about it."""
    if text is not None:
        if len(text) > TEXT_BODY_LIMIT:
            return text[:TEXT_BODY_LIMIT] + "\n\n[The rest of this file is in the upload.]"
        return text
    return f"{file_type.kind.capitalize()} file `{filename}`, {human_size(size)}."


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("bytes", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{int(value)} {unit}" if unit == "bytes" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} bytes"


def forget_blob(room_name: str, sha256: str | None) -> None:
    """Remove a blob once no upload in the room points at it."""
    if not sha256:
        return
    if any(meta[UPLOAD_META].get("sha256") == sha256 for _, meta, _ in list_uploads(room_name)):
        return
    path = blob_path(room_name, sha256)
    if path is not None and path.exists():
        path.unlink()
        _cleanup_empty_dirs(path.parent, get_room_dir(room_name))
