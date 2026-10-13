# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""A room's whole history, written to local files (``mycelium room export``).

The source is the hub's wire replay (``GET /rooms/{room}/messages/wire``): one
frame per transcript record, channel and task threads alike, including the
notices and pings that ``room messages`` leaves out. Each frame is written as one
flat JSON line a script can read without knowing the L9 envelope. The board is
read from the memory routes, one row per task.

An export directory keeps its own cursor, so running the same export again reads
back only to where the last run stopped and appends what is new.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol


class Response(Protocol):
    status_code: int

    def json(self) -> Any: ...

    def raise_for_status(self) -> Any: ...


class Hub(Protocol):
    """What an export reads with: an ``httpx.Client`` from ``hub_client``."""

    def get(self, url: str, *, params: dict[str, Any] | None = None) -> Response: ...


MESSAGES_FILE = "messages.jsonl"
BOARD_FILE = "board.json"
CURSOR_FILE = "cursor.json"

BOARD_PREFIXES = ("work/", "decisions/", "status/", "failed/")
PROSE_TYPES = frozenset({"message", "reply"})
WIRE_PAGE = 1000
MEMORY_PAGE = 1000

# The hub's rule (``contracts/mentions.json``, asserted in
# ``tests/test_mentions_contract.py``): a token at the start of the text or
# after whitespace, ``(`` or ``<``, and never inside code.
_MENTION = re.compile(r"(?:^|(?<=[\s(<]))@([!~]?)([A-Za-z0-9][\w-]*)")
_MENTION_MODES = {"!": "urgent", "~": "silent"}
_FENCE_OPEN = re.compile(r"^[ \t]*(`{3,}|~{3,})(.*)$")
_BLANK_LINE = re.compile(r"\n[ \t]*\n")
#: What code is replaced with before matching: no word character, no
#: whitespace, so it neither extends a handle nor starts one.
_CODE_MASK = "\x00"
_ROLE_KINDS = {"human": "person", "agent": "agent", "coordinator": "engine"}
_UNTHREADED = {None, "live", "knowledge"}


@dataclass
class ExportResult:
    room: str
    out: Path
    new: int
    total: int
    board_rows: int
    from_start: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "room": self.room,
            "out": str(self.out),
            "new": self.new,
            "total": self.total,
            "board_rows": self.board_rows,
            "from_start": self.from_start,
        }


class ExportError(Exception):
    """An export that can't go ahead, said in a sentence."""


# ── Reading the hub ─────────────────────────────────────────────────────────


def _stamp(frame: dict[str, Any]) -> datetime | None:
    raw = frame.get("created_at")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


def read_wire(
    client: Hub,
    room: str,
    *,
    after_id: str | None = None,
    after: datetime | None = None,
) -> list[dict[str, Any]]:
    """Frames newer than the cursor, oldest first.

    The wire replay pages backward from the newest frame, so this walks back
    until it reaches ``after_id`` (the last frame a previous run wrote) or a
    frame older than ``after``, whichever comes first, or the start of the room.
    ``before`` is strict, so each page asks for one microsecond past the oldest
    frame it has: frames sharing that stamp across the boundary come back again
    and are dropped by id rather than skipped. A page that is all one stamp
    already holds every frame at it the hub will page to, so the next one starts
    strictly before it.
    """
    frames: list[dict[str, Any]] = []
    seen: set[str] = set()
    before: datetime | None = None
    while True:
        params: dict[str, Any] = {"limit": WIRE_PAGE}
        if before:
            params["before"] = before.isoformat()
        resp = client.get(f"/api/rooms/{room}/messages/wire", params=params)
        resp.raise_for_status()
        page = resp.json()
        added = 0
        for frame in reversed(page):
            fid = frame.get("id")
            if fid in seen:
                continue
            stamp = _stamp(frame)
            if (after_id and fid == after_id) or (after and stamp and stamp < after):
                return list(reversed(frames))
            seen.add(fid)
            frames.append(frame)
            added += 1
        oldest = _stamp(page[0]) if page else None
        if len(page) < WIRE_PAGE or not added or oldest is None:
            return list(reversed(frames))
        one_stamp = _stamp(page[-1]) == oldest
        before = oldest if one_stamp else oldest + timedelta(microseconds=1)


def read_board(client: Hub, room: str) -> list[dict[str, Any]]:
    """Every row in the board's namespaces, with its status, holder and thread."""
    rows = []
    for prefix in BOARD_PREFIXES:
        offset = 0
        while True:
            resp = client.get(
                f"/api/rooms/{room}/memory",
                params={"prefix": prefix, "limit": MEMORY_PAGE, "offset": offset},
            )
            resp.raise_for_status()
            page = resp.json()
            for mem in page:
                text = mem.get("content_text") or ""
                rows.append(
                    {
                        "key": mem["key"],
                        "title": text.split("\n", 1)[0],
                        "body": text,
                        "thread": short_id(mem.get("episode")),
                        "meta": mem.get("meta") or {},
                        "created_by": mem.get("created_by"),
                        "updated_by": mem.get("updated_by"),
                        "version": mem.get("version"),
                        "created_at": mem.get("created_at"),
                        "updated_at": mem.get("updated_at"),
                    }
                )
            if len(page) < MEMORY_PAGE:
                break
            offset += MEMORY_PAGE
    return rows


def read_roster(client: Hub, room: str) -> dict[str, str]:
    """Handle → ``person`` or ``agent``, from the hub's users and the room's members.

    Engines are not listed here; a sender that isn't is placed by the role its
    envelope gives it.
    """
    kinds: dict[str, str] = {"system": "system"}
    resp = client.get(f"/api/rooms/{room}/agents")
    if resp.status_code == 200:  # noqa: PLR2004
        for agent in resp.json():
            if agent.get("handle"):
                kinds[agent["handle"]] = "agent"
    resp = client.get("/api/users")
    if resp.status_code == 200:  # noqa: PLR2004
        body = resp.json()
        for user in body.get("users", []) if isinstance(body, dict) else body:
            if user.get("handle"):
                kinds[user["handle"]] = "person"
    return kinds


# ── One frame → one line ────────────────────────────────────────────────────


def short_id(urn: str | None) -> str | None:
    """``urn:ioc:mycelium:episode:<room>:<id>`` → ``<id>``."""
    return urn.rsplit(":", 1)[-1] if urn else None


def _notice_text(data: dict[str, Any]) -> str:
    sub = data.get("subkind")
    title = data.get("title") or data.get("key") or ""
    if sub == "upstream":
        parts = [f"[upstream] {data.get('label') or ''} {data.get('change') or ''}".rstrip()]
        return f"{parts[0]}: {title} {data.get('url') or ''}".strip()
    by = f" by @{data['by']}" if data.get("by") else ""
    for_ = f" for @{data['for']}" if data.get("for") else ""
    return f"[{sub}] {title}{by}{for_}"


def _mask(text: str) -> str:
    return "".join("\n" if c == "\n" else _CODE_MASK for c in text)


def _blank_fences(text: str) -> str:
    out: list[str] = []
    fence: str | None = None
    for line in text.split("\n"):
        if fence is not None:
            if re.fullmatch(rf"[ \t]*{re.escape(fence[0])}{{{len(fence)},}}[ \t]*", line):
                fence = None
            out.append(_mask(line))
            continue
        opened = _FENCE_OPEN.match(line)
        if opened and not (opened.group(1)[0] == "`" and "`" in opened.group(2)):
            fence = opened.group(1)
            out.append(_mask(line))
            continue
        out.append(line)
    return "\n".join(out)


def _backtick_run(text: str, start: int) -> int:
    end = start
    while end < len(text) and text[end] == "`":
        end += 1
    return end


def blank_code(text: str) -> str:
    """``text`` with its fenced blocks and code spans masked, same length.

    The CLI's copy of the hub's ``persister.blank_code``: a code span closes on
    the next backtick run of its own length within its paragraph, a run with no
    such close is literal backticks, and a fence runs to its close or the end.
    """
    text = _blank_fences(text)
    out: list[str] = []
    i = 0
    while i < len(text):
        if text[i] != "`":
            out.append(text[i])
            i += 1
            continue
        run_end = _backtick_run(text, i)
        run = run_end - i
        close = -1
        k = run_end
        while k < len(text):
            if text[k] != "`":
                k += 1
                continue
            k_end = _backtick_run(text, k)
            if k_end - k == run:
                close = k
                break
            k = k_end
        if close == -1 or _BLANK_LINE.search(text, run_end, close):
            out.append(text[i:run_end])
            i = run_end
            continue
        out.append(_mask(text[i : close + run]))
        i = close + run
    return "".join(out)


def mentions(text: str) -> list[dict[str, str]]:
    """Every ``@handle`` in prose, with how it was said: plain, silent ``@~`` or urgent ``@!``.

    A handle inside code is quoted, not mentioned, so it isn't listed.
    """
    return [
        {"handle": handle, "mode": _MENTION_MODES.get(mode, "plain")}
        for mode, handle in _MENTION.findall(blank_code(text))
    ]


def record(frame: dict[str, Any], kinds: dict[str, str], task_of: dict[str, str]) -> dict[str, Any]:
    """A wire frame as one flat line: who, where, what kind, and the text."""
    raw = frame.get("content") or "{}"
    try:
        parsed: Any = json.loads(raw)
    except json.JSONDecodeError:
        parsed = raw
    content: dict[str, Any] = parsed if isinstance(parsed, dict) else {"content": str(parsed)}
    l9: dict[str, Any] = content.get("l9") or {}
    header = l9.get("header") or {}
    message = header.get("message") or {}
    payload = l9.get("payload") or {}
    data = dict(payload.get("data") or {})
    ptype = payload.get("type") or str(frame.get("message_type", "")).removeprefix("l9_")
    sender = frame.get("sender_handle") or ""
    actors = (header.get("participants") or {}).get("actors") or []
    role = next((a.get("role") for a in actors if a.get("id") == sender), None)
    kind = kinds.get(sender) or _ROLE_KINDS.get(role or "", "unknown")

    refers_to = None
    if ptype == "notice":
        text = _notice_text(data)
        refers_to = short_id(data.get("episode"))
    elif ptype == "ping":
        text = f"[ping] @{data.get('sender')} wrote in {short_id(data.get('episode'))}"
        refers_to = short_id(data.get("episode"))
    else:
        text = content.get("content") or ""
        if ptype == "extraction":
            data.pop("content", None)

    thread = short_id(message.get("episode") or frame.get("episode"))
    threaded = thread not in _UNTHREADED
    return {
        "id": frame.get("id"),
        "at": frame.get("created_at"),
        "sender": sender,
        "sender_kind": kind,
        "type": ptype,
        "notice": data.get("subkind") if ptype == "notice" else None,
        "channel": "thread" if threaded else (thread or "live"),
        "thread": thread if threaded else None,
        "task": task_of.get(thread) if threaded else None,
        "refers_to_thread": refers_to,
        "refers_to_task": task_of.get(refers_to) if refers_to else None,
        "parents": message.get("parents") or [],
        "mentions": mentions(text) if ptype in PROSE_TYPES else [],
        "text": text,
        "data": data,
    }


# ── Redaction ───────────────────────────────────────────────────────────────

_REDACTIONS = [
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "<EMAIL>"),
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}"), "<TOKEN>"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"), "<TOKEN>"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), "<TOKEN>"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "<TOKEN>"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"), "<TOKEN>"),
    (
        re.compile(
            r"(?i)\b((?:api[_-]?key|token|secret|password|passwd)\s*[:=]\s*)['\"]?[^\s'\"`,;]{8,}"
        ),
        r"\1<TOKEN>",
    ),
    (re.compile(r"/Users/[^/\s`'\"]+"), "/Users/<USER>"),
    (re.compile(r"/home/[^/\s`'\"]+"), "/home/<USER>"),
]
_URL = re.compile(r"\bhttps?://[^\s)>\]`'\"]+")
_KEPT_HOSTS = ("github.com", "githubusercontent.com", "localhost", "127.0.0.1")


def _url(match: re.Match[str]) -> str:
    host = urllib.parse.urlsplit(match.group(0)).hostname or ""
    if any(host == kept or host.endswith("." + kept) for kept in _KEPT_HOSTS):
        return match.group(0)
    return "<URL>"


def redact_text(text: str) -> str:
    """Emails, tokens, non-GitHub URLs and home-folder names, replaced with placeholders."""
    text = _URL.sub(_url, text)
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


def redact(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    return value


# ── The export ──────────────────────────────────────────────────────────────


def _read_cursor(out: Path, room: str, *, redacted: bool) -> dict[str, Any] | None:
    path = out / CURSOR_FILE
    if not path.exists():
        return None
    cursor = json.loads(path.read_text(encoding="utf-8"))
    if cursor.get("room") != room:
        msg = f"{out} holds an export of {cursor.get('room')!r}, not {room!r}. Pick another --out."
        raise ExportError(msg)
    if bool(cursor.get("redacted")) != redacted:
        said = "redacted" if cursor.get("redacted") else "not redacted"
        msg = f"{out} holds an export that is {said}. Use the same --redact, or another --out."
        raise ExportError(msg)
    return cursor


def export_room(
    client: Hub,
    room: str,
    out: Path,
    *,
    since: datetime | None = None,
    redacted: bool = False,
) -> ExportResult:
    """Write ``room``'s history into ``out``, appending only what is new since its cursor."""
    out.mkdir(parents=True, exist_ok=True)
    cursor = _read_cursor(out, room, redacted=redacted)
    messages_path = out / MESSAGES_FILE
    from_start = cursor is None or not messages_path.exists()

    kinds = read_roster(client, room)
    rows = read_board(client, room)
    task_of = {row["thread"]: row["key"] for row in rows if row["thread"]}
    previous = {} if from_start else (cursor or {})
    if from_start:
        frames = read_wire(client, room, after=since)
    else:
        # The stamp as well as the id: if the last frame written is ever gone from
        # the hub, the walk still stops where the last run did.
        frames = read_wire(
            client,
            room,
            after_id=previous.get("last_id"),
            after=_stamp({"created_at": previous.get("last_at")}),
        )

    lines = [record(frame, kinds, task_of) for frame in frames]
    if redacted:
        lines = redact(lines)
        rows = redact(rows)
    with messages_path.open("w" if from_start else "a", encoding="utf-8") as fh:
        for line in lines:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    (out / BOARD_FILE).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    total = int(previous.get("total", 0)) + len(lines)
    last = frames[-1] if frames else {}
    new_cursor = {
        "room": room,
        "redacted": redacted,
        "last_id": last.get("id", previous.get("last_id")),
        "last_at": last.get("created_at", previous.get("last_at")),
        "total": total,
        "since": since.isoformat() if since and from_start else previous.get("since"),
    }
    (out / CURSOR_FILE).write_text(json.dumps(new_cursor, indent=2), encoding="utf-8")
    return ExportResult(room, out, len(lines), total, len(rows), from_start)


def default_out(room: str) -> Path:
    """``~/mycelium-exports/<room>``: outside whatever folder the command runs in,
    since that is usually a repository and a transcript must not land in a commit."""
    return Path.home() / "mycelium-exports" / room


def in_git_work_tree(path: Path) -> bool:
    """Whether ``path`` (or the folder it would be made in) is inside a git checkout."""
    path = path.expanduser().resolve()
    return any((parent / ".git").exists() for parent in (path, *path.parents))
