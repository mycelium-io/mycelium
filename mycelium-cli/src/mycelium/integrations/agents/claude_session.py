# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Claude Code's session file, read as the rendered view's entries.

Claude Code writes each session to ``~/.claude/projects/<folder>/<id>.jsonl``,
one line per event, and each sub-agent to ``<id>/subagents/agent-*.jsonl`` with
a ``.meta.json`` naming the tool call that started it. This turns those lines
into the entries the app draws (``mycelium-frontend/src/lib/agent-session.ts``),
which take the shapes of the Agent Client Protocol's ``session/update``. The
file is read on this machine and handed to the app on it; it never reaches the
hub.

What it keeps: prompts, replies, thinking, tool calls with their results, the
plan, and where the context was compacted. Everything else in the file (titles
aside) is bookkeeping and is left out. Text is cut short: the view shows the
first lines of a result, and the JSON a call was written as, never a whole file.

It also lists the sessions on this machine, for bringing one into a room
(:func:`list_sessions`). A title, the one thing listed in a session's own
words, is given only when asked for, to the app on this machine.
"""

from __future__ import annotations

import html
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

#: A file is read from its end, this much first, then twice as much each time
#: until it holds enough entries: the view shows the latest ones, a page at a time.
TAIL_BYTES = 4 * 1024 * 1024
#: How far back the live read and an earlier page may read, at most.
LIVE_MAX_BYTES = 32 * 1024 * 1024
PAGE_MAX_BYTES = 256 * 1024 * 1024
#: Entries read past what's sent, so the first one sent isn't one cut in half
#: where the read began (a reply missing its first blocks, a call its result).
MARGIN = 20
#: Entries sent at most, the latest ones; a page's by default; a sub-agent's at most.
MAX_ENTRIES = 300
PAGE_ENTRIES = 200
#: The span each file's live read last needed, by path.
_SPANS: dict[str, int] = {}
MAX_SUBAGENT_ENTRIES = 120
#: What listing the sessions reads of each file (its start and its end), how
#: many it lists, the newest, and how long a title it gives.
LIST_HEAD_BYTES = 64 * 1024
LIST_TAIL_BYTES = 256 * 1024
LIST_MAX = 500
TITLE_CHARS = 120
#: How much of a result or a raw value is kept.
RESULT_LINES = 40
RESULT_CHARS = 8000
RAW_CHARS = 4000

#: How a Mycelium wake begins, as the hub's digest writes it.
WAKE_START = "mycelium wake for @"

#: Claude Code's tools, as ACP's ``ToolKind``.
_KINDS = {
    "Bash": "execute",
    "BashOutput": "execute",
    "KillShell": "execute",
    "Read": "read",
    "Edit": "edit",
    "MultiEdit": "edit",
    "NotebookEdit": "edit",
    "Write": "edit",
    "Grep": "search",
    "Glob": "search",
    "ToolSearch": "search",
    "WebFetch": "fetch",
    "WebSearch": "fetch",
}
#: The tools whose argument is a file.
_FILE_TOOLS = frozenset({"Read", "Edit", "MultiEdit", "NotebookEdit", "Write"})
#: The tool whose calls are the plan rather than a step of their own.
_PLAN_TOOL = "TodoWrite"
_PLAN_STATUS = {"pending": "pending", "in_progress": "in_progress", "completed": "completed"}


def projects_dir() -> Path:
    """Where Claude Code keeps its projects' sessions."""
    root = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    return (Path(root).expanduser() if root else Path.home() / ".claude") / "projects"


def session_file(folder: str | None, session: str) -> Path | None:
    """The file of ``session``, begun in ``folder``; ``None`` when it isn't there.

    Claude Code names a project's folder by its path with every character that
    isn't a letter or a digit made ``-``. A session can outlive a move, so when
    it isn't there, every project is looked in for it.
    """
    if not _SESSION_ID.fullmatch(session or ""):
        return None
    projects = projects_dir()
    if folder:
        named = projects / re.sub(r"[^A-Za-z0-9]", "-", folder) / f"{session}.jsonl"
        if named.is_file():
            return named
    found = sorted(projects.glob(f"*/{session}.jsonl")) if projects.is_dir() else []
    return found[0] if found else None


_SESSION_ID = re.compile(r"[A-Za-z0-9-]{1,128}")


def list_sessions(*, titles: bool = False) -> list[dict[str, Any]]:
    """Every session on this machine, newest first, at most :data:`LIST_MAX`:
    ``id``, ``folder``, ``last_used`` and ``branch``, and with ``titles`` its
    ``title``, in its own words.

    Only each file's start (where it began) and end (its branch, and Claude
    Code's title for it) are read, so listing doesn't depend on how long the
    sessions are. A file with no prompt or reply in its start is left out.
    """
    projects = projects_dir()
    files: list[tuple[float, Path]] = []
    for path in projects.glob("*/*.jsonl") if projects.is_dir() else []:
        if not _SESSION_ID.fullmatch(path.stem):
            continue
        try:
            files.append((path.stat().st_mtime, path))
        except OSError:
            continue
    files.sort(reverse=True)
    out: list[dict[str, Any]] = []
    for mtime, path in files:
        if len(out) >= LIST_MAX:
            break
        try:
            found = _summary(path, mtime, titles=titles)
        except OSError:
            continue
        if found is not None:
            out.append(found)
    return out


def _summary(path: Path, mtime: float, *, titles: bool) -> dict[str, Any] | None:
    head = _head(path, LIST_HEAD_BYTES)
    folder = next((str(ln["cwd"]) for ln in head if isinstance(ln.get("cwd"), str)), None)
    if not folder or not any(ln.get("type") in ("user", "assistant") for ln in head):
        return None
    tail, _cut_off = _tail(path, LIST_TAIL_BYTES)
    branch = next(
        (str(ln["gitBranch"]) for ln in reversed([*head, *tail]) if ln.get("gitBranch")), None
    )
    found: dict[str, Any] = {
        "id": path.stem,
        "folder": folder,
        "last_used": datetime.fromtimestamp(mtime, UTC).isoformat(),
        "branch": branch,
    }
    if titles:
        found["title"] = _list_title(head, tail)
    return found


def _list_title(head: list[dict[str, Any]], tail: list[dict[str, Any]]) -> str | None:
    """Claude Code's latest title for the session, else what it was first asked."""
    named = [ln["aiTitle"] for ln in [*head, *tail] if isinstance(ln.get("aiTitle"), str)]
    text = named[-1] if named else None
    if not text:
        entries, _ = convert(head)
        text = next(
            (
                e["content"][0]["text"]
                for e in entries
                if e["sessionUpdate"] == "user_message" and e["_meta"].get("from") == "person"
            ),
            None,
        )
    line = next((ln.strip() for ln in (text or "").splitlines() if ln.strip()), "")
    if not line:
        return None
    return line if len(line) <= TITLE_CHARS else line[: TITLE_CHARS - 1].rstrip() + "…"


def _head(path: Path, span: int) -> list[dict[str, Any]]:
    """The file's first ``span`` bytes as parsed lines, less one cut at the end."""
    with path.open("rb") as f:
        raw = f.read(span)
    if len(raw) == span:
        raw = raw[: raw.rfind(b"\n") + 1]
    return _parse(raw)


def read(path: Path) -> dict[str, Any]:
    """The session in ``path`` as the rendered view's fields, less ``state``:
    its latest :data:`MAX_ENTRIES` entries, read back as far as that takes."""
    entries, earlier, title = _back(path, want=MAX_ENTRIES, max_bytes=LIVE_MAX_BYTES)
    return {
        "version": 1,
        "sessionId": path.stem,
        "title": title,
        "entries": entries or [],
        "earlier": earlier,
    }


def read_page(path: Path, before: str, limit: int = PAGE_ENTRIES) -> dict[str, Any] | None:
    """The ``limit`` entries just before the entry ``before``, oldest first, and
    whether there are more; ``None`` when that entry isn't in the session.

    The ids are the ones :func:`read` gives, so a page joins the live view.
    """
    entries, earlier, _title = _back(path, want=limit, max_bytes=PAGE_MAX_BYTES, before=before)
    if entries is None:
        return None
    return {"entries": entries, "earlier": earlier}


def _back(
    path: Path, *, want: int, max_bytes: int, before: str | None = None
) -> tuple[list[dict[str, Any]] | None, bool, str | None]:
    """The last ``want`` entries (before the entry ``before``, when given),
    whether there are earlier ones, and the session's title.

    The file is read from its end, more each time, until it holds ``want``
    entries and :data:`MARGIN` more, it's read whole, or ``max_bytes`` is
    reached. ``None`` for the entries when ``before`` isn't found.
    """
    subagents = path.with_suffix("") / "subagents"
    # The live read starts from the span it needed last time: a session whose
    # results are large needs more than the first read every time it changes.
    remembered = _SPANS.get(str(path), TAIL_BYTES) if before is None else TAIL_BYTES
    size, span = path.stat().st_size, min(remembered, max_bytes)
    while True:
        lines, cut = _tail(path, span)
        entries, title = convert(lines, subagents=subagents)
        if before is not None:
            at = next((i for i, e in enumerate(entries) if e["_meta"]["id"] == before), None)
            found = entries[:at] if at is not None else None
        else:
            found = entries
        enough = found is not None and len(found) >= want + MARGIN
        if not cut or enough or span >= max_bytes or span >= size:
            break
        span = min(span * 2, max_bytes)
    if before is None:
        _SPANS[str(path)] = span
    if found is None:
        return None, False, title
    return found[-want:], cut or len(found) > want, title


def _tail(path: Path, span: int = TAIL_BYTES) -> tuple[list[dict[str, Any]], bool]:
    """The file's last ``span`` bytes as parsed lines, and whether any was left out."""
    size = path.stat().st_size
    with path.open("rb") as f:
        if size > span:
            f.seek(size - span)
            f.readline()  # the rest of a line cut in half
        raw = f.read()
    return _parse(raw), size > span


def _parse(raw: bytes) -> list[dict[str, Any]]:
    lines = []
    for line in raw.splitlines():
        try:
            parsed = json.loads(line)
        except ValueError:
            continue  # a line still being written
        if isinstance(parsed, dict):
            lines.append(parsed)
    return lines


def convert(
    lines: list[dict[str, Any]], *, subagents: Path | None = None
) -> tuple[list[dict[str, Any]], str | None]:
    """Claude Code's lines as entries, oldest first, and the session's title."""
    entries: list[dict[str, Any]] = []
    calls: dict[str, dict[str, Any]] = {}
    said: dict[str, dict[str, Any]] = {}
    title: str | None = None
    agents = _subagent_files(subagents)

    for line in lines:
        kind = line.get("type")
        if kind == "ai-title" and isinstance(line.get("aiTitle"), str):
            title = line["aiTitle"]
        elif kind == "system" and line.get("subtype") == "compact_boundary":
            entries.append(
                {"sessionUpdate": "compaction", "_meta": _meta(line, f"compact-{line.get('uuid')}")}
            )
        elif kind == "assistant" and not line.get("isSidechain"):
            _assistant(line, entries, calls, said, agents)
        elif kind == "user" and not line.get("isSidechain"):
            _user(line, entries, calls)

    # A call with no result is running if nothing was asked after it, else it was stopped.
    asked_after = False
    for entry in reversed(entries):
        if entry["sessionUpdate"] == "user_message":
            asked_after = True
        elif entry["sessionUpdate"] == "tool_call" and entry["status"] == "pending":
            if asked_after:
                entry["status"] = "failed"
                entry["_meta"]["interrupted"] = True
            else:
                entry["status"] = "in_progress"
    return entries, title


def _meta(line: dict[str, Any], entry_id: str) -> dict[str, Any]:
    return {"id": entry_id, "at": str(line.get("timestamp") or "")}


def _text(text: str) -> dict[str, str]:
    return {"type": "text", "text": text}


def _assistant(
    line: dict[str, Any],
    entries: list[dict[str, Any]],
    calls: dict[str, dict[str, Any]],
    said: dict[str, dict[str, Any]],
    agents: dict[str, Path],
) -> None:
    message = line.get("message") or {}
    message_id = str(message.get("id") or line.get("uuid") or "")
    for block in message.get("content") or []:
        if not isinstance(block, dict):
            continue
        part = block.get("type")
        if part in ("text", "thinking"):
            text = block.get("text") if part == "text" else block.get("thinking")
            if not isinstance(text, str) or not text.strip():
                continue
            update = "agent_message" if part == "text" else "agent_thought"
            # One reply is written as one line per block, sharing the message's id.
            key = f"{update}-{message_id}"
            if key in said:
                said[key]["content"].append(_text(text))
            else:
                said[key] = {
                    "sessionUpdate": update,
                    "content": [_text(text)],
                    "_meta": _meta(line, key),
                }
                entries.append(said[key])
        elif part == "tool_use":
            call = _call(line, block, agents)
            if call is None:
                continue
            # A plan is the agent's steps, not a call that gets a result.
            if call["sessionUpdate"] == "tool_call":
                calls[call["toolCallId"]] = call
            entries.append(call)


def _call(
    line: dict[str, Any], block: dict[str, Any], agents: dict[str, Path]
) -> dict[str, Any] | None:
    name = str(block.get("name") or "")
    given = block.get("input")
    args: dict[str, Any] = given if isinstance(given, dict) else {}
    call_id = str(block.get("id") or "")
    if name == _PLAN_TOOL:
        return _plan(line, args, call_id)
    cwd = str(line.get("cwd") or "")
    call: dict[str, Any] = {
        "sessionUpdate": "tool_call",
        "toolCallId": call_id,
        "title": _title(name, args, cwd),
        "name": name,
        "kind": _KINDS.get(name, "other"),
        "status": "pending",
        "rawInput": _cut_raw(args),
        "_meta": _meta(line, call_id),
    }
    path = args.get("file_path") or args.get("notebook_path")
    if name in _FILE_TOOLS and isinstance(path, str):
        call["locations"] = [{"path": path}]
    if name in ("Agent", "Task") and call_id in agents:
        sub_lines, _ = _tail(agents[call_id])
        sub_entries, _title_ = convert(sub_lines)
        for entry in sub_entries:
            if entry["sessionUpdate"] == "user_message":
                entry["_meta"]["from"] = "agent"
        call["_meta"]["subagent"] = {
            "description": str(args.get("description") or ""),
            "entries": sub_entries[-MAX_SUBAGENT_ENTRIES:],
        }
    return call


def _plan(line: dict[str, Any], args: dict[str, Any], call_id: str) -> dict[str, Any] | None:
    todos = args.get("todos")
    if not isinstance(todos, list):
        return None
    steps = [
        {
            "content": str(t.get("content") or ""),
            "priority": "medium",
            "status": _PLAN_STATUS.get(str(t.get("status")), "pending"),
        }
        for t in todos
        if isinstance(t, dict)
    ]
    return {"sessionUpdate": "plan", "entries": steps, "_meta": _meta(line, f"plan-{call_id}")}


def _title(name: str, args: dict[str, Any], cwd: str) -> str:
    """A call's arguments in a few words: the command, the path, the query."""

    def here(path: str) -> str:
        return path[len(cwd) + 1 :] if cwd and path.startswith(cwd + "/") else path

    if name == "Bash":
        said = args.get("description") or str(args.get("command") or "").strip().splitlines()[:1]
        return said if isinstance(said, str) else (said[0] if said else name)
    path = args.get("file_path") or args.get("notebook_path") or args.get("path")
    if isinstance(path, str) and path:
        return here(path)
    for key in ("pattern", "query", "url", "description", "prompt"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().splitlines()[0][:200]
    return name


def _user(
    line: dict[str, Any], entries: list[dict[str, Any]], calls: dict[str, dict[str, Any]]
) -> None:
    content = (line.get("message") or {}).get("content")
    if isinstance(content, list):
        texts = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_result":
                call = calls.get(str(block.get("tool_use_id") or ""))
                if call is not None:
                    _result(call, block, line)
            elif block.get("type") == "text" and isinstance(block.get("text"), str):
                texts.append(block["text"])
        if texts:
            _prompt(line, "\n\n".join(texts), entries)
    elif isinstance(content, str):
        _prompt(line, content, entries)


#: A paste, as the terminal wraps one; herdr pastes each wake.
_PASTED = re.compile(r"\A\s*<pasted_content\b[^>]*>\s*(.*?)\s*</pasted_content\b[^>]*>\s*\Z", re.S)
#: Claude Code's own line when someone stops a turn; the call it stopped says so.
_INTERRUPTED = re.compile(r"\A\s*\[Request interrupted by user[^\]]*\]\s*\Z")
#: How Claude Code writes a ``!`` command the person ran, and its output.
_BASH_INPUT = re.compile(r"<bash-input>(.*?)</bash-input>", re.S)
_BASH_OUT = re.compile(r"<bash-(stdout|stderr)>(.*?)</bash-\1>", re.S)
#: How it writes a slash command, and the output of one it runs itself.
_COMMAND_NAME = re.compile(r"<command-name>(.*?)</command-name>", re.S)
_COMMAND_ARGS = re.compile(r"<command-args>(.*?)</command-args>", re.S)
_COMMAND_OUT = re.compile(r"\A\s*<local-command-std(?:out|err)>", re.S)


def _prompt(line: dict[str, Any], text: str, entries: list[dict[str, Any]]) -> None:
    """A prompt someone or something typed; what the CLI adds on its own is left out."""
    said = line.get("origin")
    origin: dict[str, Any] = said if isinstance(said, dict) else {}
    if line.get("isMeta") or origin.get("kind") not in (None, "human") or not text.strip():
        return
    if _INTERRUPTED.match(text):
        # Not a prompt of its own, but what it stopped was stopped.
        for entry in entries:
            if entry["sessionUpdate"] == "tool_call" and entry["status"] == "pending":
                entry["status"] = "failed"
                entry["_meta"]["interrupted"] = True
        return
    if _COMMAND_OUT.match(text):
        return
    meta = _meta(line, str(line.get("uuid") or line.get("promptId") or len(entries)))
    if (ran := _BASH_INPUT.search(text)) or _BASH_OUT.search(text):
        _person_command(line, text, ran, meta, entries)
        return
    if named := _COMMAND_NAME.search(text):
        name = named.group(1).strip()
        args = _COMMAND_ARGS.search(text)
        text = " ".join(
            p for p in (("/" + name.lstrip("/")), (args.group(1).strip() if args else "")) if p
        )
    elif pasted := _PASTED.match(text):
        text = pasted.group(1)
    meta["from"] = "wake" if text.lstrip().startswith(WAKE_START) else "person"
    if line.get("promptSource") == "queued":
        meta["queued"] = True
    entries.append({"sessionUpdate": "user_message", "content": [_text(text)], "_meta": meta})


def _person_command(
    line: dict[str, Any],
    text: str,
    ran: re.Match[str] | None,
    meta: dict[str, Any],
    entries: list[dict[str, Any]],
) -> None:
    """A ``!`` command the person ran in the terminal, as a call they made.

    Claude Code writes the command on one line and its output on the next, so
    output with no command of its own goes to the latest such call.
    """
    if ran is not None:
        command = html.unescape(ran.group(1)).strip()
        meta["from"] = "person"
        entries.append(
            {
                "sessionUpdate": "tool_call",
                "toolCallId": meta["id"],
                "title": command.splitlines()[0] if command else "!",
                "name": "bash",
                "kind": "execute",
                # Settled by its output, or by what's asked after it, like any call.
                "status": "pending",
                "rawInput": _cut_raw({"command": command}),
                "_meta": meta,
            }
        )
    output = {kind: html.unescape(body) for kind, body in _BASH_OUT.findall(text)}
    if not output:
        return
    call = next(
        (
            e
            for e in reversed(entries)
            if e["sessionUpdate"] == "tool_call" and e["_meta"].get("from") == "person"
        ),
        None,
    )
    if call is None:
        return
    shown = "\n".join(part for part in (output.get("stdout", ""), output.get("stderr", "")) if part)
    call["status"] = "completed"
    call["_meta"]["endedAt"] = str(line.get("timestamp") or "") or None
    if shown.strip():
        call["content"] = [{"type": "content", "content": _text(_cut(shown))}]
    call["rawOutput"] = _cut_raw(output)


def _result(call: dict[str, Any], block: dict[str, Any], line: dict[str, Any]) -> None:
    detail = line.get("toolUseResult")
    interrupted = isinstance(detail, dict) and bool(detail.get("interrupted"))
    call["status"] = "failed" if block.get("is_error") or interrupted else "completed"
    call["_meta"]["endedAt"] = str(line.get("timestamp") or "") or None
    if interrupted:
        call["_meta"]["interrupted"] = True
    content: list[dict[str, Any]] = []
    if isinstance(detail, dict) and isinstance(detail.get("filePath"), str):
        new = detail.get("newString") if "newString" in detail else detail.get("content")
        if isinstance(new, str):
            old = detail.get("oldString") if "oldString" in detail else detail.get("originalFile")
            content.append(
                {
                    "type": "diff",
                    "path": detail["filePath"],
                    "oldText": _cut(old) if isinstance(old, str) else None,
                    "newText": _cut(new),
                }
            )
    if not content and call["kind"] != "read":
        text = _result_text(block, detail)
        if text:
            content.append({"type": "content", "content": _text(_cut(text))})
    if content:
        call["content"] = content
    raw = (
        {k: v for k, v in detail.items() if k != "originalFile"}
        if isinstance(detail, dict)
        else block.get("content")
    )
    call["rawOutput"] = _cut_raw(raw)


def _result_text(block: dict[str, Any], detail: Any) -> str:
    if isinstance(detail, dict) and ("stdout" in detail or "stderr" in detail):
        out = str(detail.get("stdout") or "")
        err = str(detail.get("stderr") or "")
        return "\n".join(part for part in (out, err) if part)
    said = block.get("content")
    if isinstance(said, str):
        return said
    if isinstance(said, list):
        return "\n".join(str(p.get("text") or "") for p in said if isinstance(p, dict))
    return ""


def _cut(text: str) -> str:
    """The first lines of ``text``, as the view shows a result."""
    lines = text.splitlines()
    kept = "\n".join(lines[:RESULT_LINES])[:RESULT_CHARS]
    return kept + ("\n…" if len(lines) > RESULT_LINES or len(kept) < len(text) else "")


def _cut_raw(value: Any) -> Any:
    """``value`` with every long string cut, for the JSON view of a call."""
    if isinstance(value, str):
        return value if len(value) <= RAW_CHARS else value[:RAW_CHARS] + "…"
    if isinstance(value, dict):
        return {k: _cut_raw(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_cut_raw(v) for v in value[:200]]
    return value


def _subagent_files(folder: Path | None) -> dict[str, Path]:
    """Each sub-agent's file, by the tool call that started it (its ``.meta.json``)."""
    found: dict[str, Path] = {}
    if folder is None or not folder.is_dir():
        return found
    for meta in folder.glob("agent-*.meta.json"):
        try:
            said = json.loads(meta.read_text())
        except (OSError, ValueError):
            continue
        tool = said.get("toolUseId") if isinstance(said, dict) else None
        log = meta.with_name(meta.name.removesuffix(".meta.json") + ".jsonl")
        if isinstance(tool, str) and log.is_file():
            found[tool] = log
    return found
