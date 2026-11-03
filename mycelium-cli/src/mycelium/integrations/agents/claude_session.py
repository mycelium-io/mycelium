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
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

#: The oldest part of a long file is skipped: the view shows the latest entries.
TAIL_BYTES = 4 * 1024 * 1024
#: Entries sent at most, the latest ones; a sub-agent's at most.
MAX_ENTRIES = 300
MAX_SUBAGENT_ENTRIES = 120
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
    if not re.fullmatch(r"[A-Za-z0-9-]{1,128}", session or ""):
        return None
    projects = projects_dir()
    if folder:
        named = projects / re.sub(r"[^A-Za-z0-9]", "-", folder) / f"{session}.jsonl"
        if named.is_file():
            return named
    found = sorted(projects.glob(f"*/{session}.jsonl")) if projects.is_dir() else []
    return found[0] if found else None


def read(path: Path) -> dict[str, Any]:
    """The session in ``path`` as the rendered view's fields, less ``state``."""
    lines, cut = _tail(path)
    entries, title = convert(lines, subagents=path.with_suffix("") / "subagents")
    earlier = cut or len(entries) > MAX_ENTRIES
    return {
        "version": 1,
        "sessionId": path.stem,
        "title": title,
        "entries": entries[-MAX_ENTRIES:],
        "earlier": earlier,
    }


def _tail(path: Path) -> tuple[list[dict[str, Any]], bool]:
    """The file's last :data:`TAIL_BYTES` as parsed lines, and whether any was left out."""
    size = path.stat().st_size
    with path.open("rb") as f:
        if size > TAIL_BYTES:
            f.seek(size - TAIL_BYTES)
            f.readline()  # the rest of a line cut in half
        raw = f.read()
    lines = []
    for line in raw.splitlines():
        try:
            parsed = json.loads(line)
        except ValueError:
            continue  # a line still being written
        if isinstance(parsed, dict):
            lines.append(parsed)
    return lines, size > TAIL_BYTES


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


def _prompt(line: dict[str, Any], text: str, entries: list[dict[str, Any]]) -> None:
    """A prompt someone or something typed; what the CLI adds on its own is left out."""
    said = line.get("origin")
    origin: dict[str, Any] = said if isinstance(said, dict) else {}
    if line.get("isMeta") or origin.get("kind") not in (None, "human") or not text.strip():
        return
    meta = _meta(line, str(line.get("uuid") or line.get("promptId") or len(entries)))
    meta["from"] = "wake" if text.lstrip().startswith(WAKE_START) else "person"
    if line.get("promptSource") == "queued":
        meta["queued"] = True
    entries.append({"sessionUpdate": "user_message", "content": [_text(text)], "_meta": meta})


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
