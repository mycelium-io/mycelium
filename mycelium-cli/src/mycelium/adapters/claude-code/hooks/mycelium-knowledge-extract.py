#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
mycelium-knowledge-extract (Claude Code)

Claude Code hook: reads the current session transcript JSONL, extracts new
conversation turns since the last send, and POSTs them to mycelium-backend's
``/api/knowledge/ingest`` endpoint — which forwards to CFN's shared-memories
knowledge graph.

Mirrors the OpenClaw ``mycelium-knowledge-extract`` hook but parses Claude
Code's transcript JSONL shape. Delta state lives at
``~/.mycelium/extract-state/claude-code-<session-id>.json`` so only new turns
travel each fire. Falls back to a local log file if mycelium-backend is
unreachable or not configured.

Hook input (stdin JSON, from Claude Code):
  {
    "session_id":     "<uuid>",
    "transcript_path": "/abs/path/to/session.jsonl",
    "cwd":            "...",
    "hook_event_name": "Stop" | "SessionEnd" | "PreCompact" | ...
  }

Config (``~/.mycelium/config.toml``):
  [server]
  api_url      = "http://localhost:8000"
  workspace_id = "<uuid>"
  mas_id       = "<uuid>"

  [knowledge_ingest]
  enabled               = true
  max_tool_content_bytes = 4096
  skip_in_progress_turn = true

Env overrides (ephemeral; take precedence over config):
  MYCELIUM_API_URL
  MYCELIUM_WORKSPACE_ID
  MYCELIUM_MAS_ID
  MYCELIUM_AGENT_HANDLE
  MYCELIUM_INGEST_ENABLED
  MYCELIUM_INGEST_MAX_TOOL_CONTENT_BYTES

All errors are swallowed — this hook must not break the Stop chain.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ── Paths ─────────────────────────────────────────────────────────────────────

HOME = Path.home()
CONFIG_PATH = HOME / ".mycelium" / "config.toml"
STATE_DIR = HOME / ".mycelium" / "extract-state"
LOG_FILE = HOME / ".mycelium" / "logs" / "claude-code-knowledge-extract.log"


# ── Tiny TOML reader (stdlib-free-ish) ────────────────────────────────────────
#
# Python 3.11+ ships tomllib. We target that since pyproject.toml already
# requires Python >= 3.12 for the rest of the project, and the claude-code
# hook runs in the user's ambient Python. Falls back to a best-effort line
# parser if tomllib is missing (e.g. Python 3.10).


def _load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    try:
        import tomllib

        with CONFIG_PATH.open("rb") as f:
            return tomllib.load(f)
    except ImportError:
        return _fallback_toml_parse(CONFIG_PATH.read_text())
    except Exception:
        return {}


_SECTION_RE = re.compile(r"^\[([^\]]+)\]\s*$")
_KV_RE = re.compile(r"^([A-Za-z_][\w.]*)\s*=\s*(.+?)\s*$")


def _fallback_toml_parse(text: str) -> dict[str, Any]:
    """Best-effort TOML parser — string/bool/int values in flat sections only."""
    out: dict[str, Any] = {}
    section: dict[str, Any] = out
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        m = _SECTION_RE.match(line)
        if m:
            section = out.setdefault(m.group(1), {})
            continue
        m = _KV_RE.match(line)
        if not m:
            continue
        key, value = m.group(1), m.group(2).strip()
        if value.startswith('"') and value.endswith('"'):
            section[key] = value[1:-1]
        elif value.lower() in ("true", "false"):
            section[key] = value.lower() == "true"
        else:
            try:
                section[key] = int(value)
            except ValueError:
                section[key] = value
    return out


# ── Config resolution (env > config > defaults) ───────────────────────────────


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


def _resolve_target(config: dict[str, Any]) -> dict[str, Any]:
    server = config.get("server", {}) or {}
    identity = config.get("identity", {}) or {}
    return {
        "api_url": os.environ.get("MYCELIUM_API_URL")
        or server.get("api_url")
        or "http://localhost:8000",
        "workspace_id": os.environ.get("MYCELIUM_WORKSPACE_ID") or server.get("workspace_id"),
        "mas_id": os.environ.get("MYCELIUM_MAS_ID") or server.get("mas_id"),
        "agent_handle": os.environ.get("MYCELIUM_AGENT_HANDLE")
        or identity.get("name")
        or "claude-code",
    }


def _resolve_ingest_config(config: dict[str, Any]) -> dict[str, Any]:
    ki = config.get("knowledge_ingest", {}) or {}
    enabled = ki.get("enabled", True)
    if "MYCELIUM_INGEST_ENABLED" in os.environ:
        enabled = _env_bool("MYCELIUM_INGEST_ENABLED", True)

    max_bytes = ki.get("max_tool_content_bytes", 4096)
    env_max = os.environ.get("MYCELIUM_INGEST_MAX_TOOL_CONTENT_BYTES")
    if env_max is not None:
        try:
            max_bytes = int(env_max)
        except ValueError:
            pass

    skip_in_progress = ki.get("skip_in_progress_turn", True)

    return {
        "enabled": bool(enabled),
        "max_tool_content_bytes": int(max_bytes),
        "skip_in_progress_turn": bool(skip_in_progress),
    }


# ── Transcript parsing ────────────────────────────────────────────────────────


def _read_transcript(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    entries.append(json.loads(raw))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return entries


def _extract_text_from_content(content: Any) -> str:
    """Flatten a Claude message content block into plain text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks = []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text" and isinstance(block.get("text"), str):
                chunks.append(block["text"])
        return "".join(chunks)
    return ""


def _truncate(value: Any, max_bytes: int) -> Any:
    """Truncate long strings / large JSON blobs to keep CFN input tokens sane."""
    if max_bytes <= 0 or value is None:
        return value
    if isinstance(value, str):
        encoded = value.encode("utf-8")
        if len(encoded) <= max_bytes:
            return value
        head = encoded[:max_bytes].decode("utf-8", errors="ignore")
        return f"{head}...[truncated {len(encoded) - max_bytes} bytes]"
    if isinstance(value, (dict, list)):
        serialized = json.dumps(value, default=str)
        if len(serialized.encode("utf-8")) <= max_bytes:
            return value
        head = serialized[:max_bytes]
        return f"{head}...[truncated {len(serialized) - max_bytes} bytes of JSON]"
    return value


def _extract_turns(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Walk the Claude Code transcript and emit one turn per user→assistant pair.

    Each turn captures: user message, assistant thinking, tool calls (with
    their matched tool_result), and the final assistant response text.
    """
    turns: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    pending_tool_calls: dict[str, dict[str, Any]] = {}

    for entry in entries:
        etype = entry.get("type")
        msg = entry.get("message") or {}
        role = msg.get("role") if isinstance(msg, dict) else None
        content = msg.get("content") if isinstance(msg, dict) else None

        # A new user turn starts a fresh turn bucket (but we merge tool_result
        # user entries into the prior assistant turn rather than starting a new
        # one — tool results aren't fresh user input).
        if etype == "user" and role == "user":
            if _is_tool_result_user(content):
                _apply_tool_results(current, content)
                continue
            if current is not None:
                turns.append(_finalize_turn(current))
            current = {
                "index": len(turns),
                "timestamp": entry.get("timestamp"),
                "user_message": _extract_text_from_content(content),
                "thinking": [],
                "tool_calls": [],
                "response": "",
                "model": None,
                "stop_reason": None,
                "usage": None,
            }
            pending_tool_calls = {}
            continue

        if etype == "assistant" and role == "assistant" and current is not None:
            if isinstance(msg.get("model"), str):
                current["model"] = msg["model"]
            if isinstance(msg.get("stop_reason"), str):
                current["stop_reason"] = msg["stop_reason"]
            usage = msg.get("usage") or entry.get("usage")
            if isinstance(usage, dict):
                current["usage"] = _merge_usage(current["usage"], usage)

            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    btype = block.get("type")
                    if btype == "thinking" and isinstance(block.get("thinking"), str):
                        current["thinking"].append(block["thinking"])
                    elif btype == "text" and isinstance(block.get("text"), str):
                        current["response"] += block["text"]
                    elif btype == "tool_use":
                        tc = {
                            "id": block.get("id"),
                            "name": block.get("name") or "unknown",
                            "input": block.get("input") or {},
                            "result": None,
                            "is_error": None,
                        }
                        current["tool_calls"].append(tc)
                        if tc["id"]:
                            pending_tool_calls[tc["id"]] = tc
            continue

    if current is not None:
        turns.append(_finalize_turn(current))
    return turns


def _is_tool_result_user(content: Any) -> bool:
    """A 'user' entry whose content is a list of tool_result blocks only."""
    if not isinstance(content, list) or not content:
        return False
    return all(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)


def _apply_tool_results(current: dict[str, Any] | None, content: Any) -> None:
    """Match tool_result blocks to their pending tool_use in the current turn."""
    if current is None or not isinstance(content, list):
        return
    by_id = {tc["id"]: tc for tc in current["tool_calls"] if tc.get("id")}
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_result":
            continue
        tc_id = block.get("tool_use_id")
        tc = by_id.get(tc_id)
        if tc is None:
            continue
        tc["result"] = _extract_text_from_content(block.get("content"))
        tc["is_error"] = bool(block.get("is_error", False))


def _merge_usage(acc: dict[str, Any] | None, usage: dict[str, Any]) -> dict[str, Any]:
    base = dict(acc or {})
    for key in (
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
    ):
        base[key] = (base.get(key, 0) or 0) + (usage.get(key, 0) or 0)
    return base


def _finalize_turn(turn: dict[str, Any]) -> dict[str, Any]:
    return {
        **turn,
        "thinking": "\n\n".join(turn["thinking"]) if turn["thinking"] else None,
    }


# ── Delta state ───────────────────────────────────────────────────────────────


def _state_path(session_id: str) -> Path:
    return STATE_DIR / f"claude-code-{session_id}.json"


def _read_last_index(session_id: str) -> int:
    try:
        data = json.loads(_state_path(session_id).read_text())
        return int(data.get("last_sent_index", -1))
    except (OSError, ValueError, TypeError):
        return -1


def _write_last_index(session_id: str, index: int) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        _state_path(session_id).write_text(
            json.dumps({"last_sent_index": index, "updated_at": _now_iso()})
        )
    except OSError:
        pass


# ── Payload / POST ────────────────────────────────────────────────────────────


def _build_payload(
    session_id: str,
    transcript_path: str,
    cwd: str | None,
    agent_handle: str,
    turns: list[dict[str, Any]],
    stats_total_entries: int,
    max_tool_bytes: int,
) -> dict[str, Any]:
    truncated_bytes = 0

    def _truncate_and_track(value: Any) -> Any:
        nonlocal truncated_bytes
        if max_tool_bytes <= 0:
            return value
        before_size = len(
            (value if isinstance(value, str) else json.dumps(value, default=str)).encode("utf-8")
        )
        result = _truncate(value, max_tool_bytes)
        after_size = len(
            (result if isinstance(result, str) else json.dumps(result, default=str)).encode("utf-8")
        )
        if after_size < before_size:
            truncated_bytes += before_size - after_size
        return result

    payload_turns = []
    tool_call_count = 0
    thinking_turn_count = 0
    for t in turns:
        thinking = t.get("thinking")
        if thinking:
            thinking_turn_count += 1
        tool_calls = []
        for tc in t["tool_calls"]:
            tool_call_count += 1
            tool_calls.append(
                {
                    "id": tc["id"],
                    "name": tc["name"],
                    "input": _truncate_and_track(tc["input"]),
                    "result": _truncate_and_track(tc["result"]),
                    "is_error": tc["is_error"],
                }
            )
        payload_turns.append(
            {
                "index": t["index"],
                "timestamp": t["timestamp"],
                "model": t["model"],
                "stop_reason": t["stop_reason"],
                "usage": t["usage"],
                "user_message": t["user_message"],
                "thinking": thinking,
                "tool_calls": tool_calls,
                "response": t["response"] or None,
            }
        )

    stats: dict[str, Any] = {
        "total_entries": stats_total_entries,
        "turns": len(turns),
        "tool_call_count": tool_call_count,
        "thinking_turn_count": thinking_turn_count,
    }
    if truncated_bytes > 0:
        stats["truncated_bytes"] = truncated_bytes

    return {
        "schema": "claude-code-conversation-v1",
        "extracted_at": _now_iso(),
        "session": {
            "session_id": session_id,
            "transcript_path": transcript_path,
            "cwd": cwd,
            "agent_handle": agent_handle,
            "channel": "claude-code",
        },
        "stats": stats,
        "turns": payload_turns,
    }


def _post_ingest(
    api_url: str,
    workspace_id: str,
    mas_id: str,
    agent_handle: str,
    payload: dict[str, Any],
) -> bool:
    body = {
        "workspace_id": workspace_id,
        "mas_id": mas_id,
        "agent_id": agent_handle,
        "records": [payload],
    }
    url = api_url.rstrip("/") + "/api/knowledge/ingest"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    token = os.environ.get("MYCELIUM_API_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (trusted local URL)
            return 200 <= resp.status < 300
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        return False
    except Exception:
        return False


def _append_log(data: dict[str, Any]) -> None:
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(data, default=str) + "\n")
    except OSError:
        pass


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> int:
    try:
        hook_input_raw = sys.stdin.read()
    except Exception:
        return 0
    if not hook_input_raw.strip():
        return 0

    try:
        hook_input = json.loads(hook_input_raw)
    except json.JSONDecodeError:
        return 0

    session_id = hook_input.get("session_id") or "unknown"
    transcript_path = hook_input.get("transcript_path") or ""
    cwd = hook_input.get("cwd")
    hook_event = hook_input.get("hook_event_name", "Stop")

    config = _load_config()
    ingest_cfg = _resolve_ingest_config(config)
    if not ingest_cfg["enabled"]:
        return 0

    target = _resolve_target(config)
    if not target["workspace_id"] or not target["mas_id"]:
        # No CFN binding configured — nothing to ingest. Silent.
        return 0

    if not transcript_path:
        return 0
    entries = _read_transcript(Path(transcript_path))
    if not entries:
        return 0

    all_turns = _extract_turns(entries)
    if not all_turns:
        return 0

    # Skip an in-progress turn on non-terminal events (catch-up / pre-compact)
    # where the final turn may still be mid-flight. On Stop / SessionEnd the
    # most recent turn has just finalized — sending it is the whole point.
    skip_last = ingest_cfg["skip_in_progress_turn"] and hook_event not in (
        "Stop",
        "SessionEnd",
    )
    eligible = all_turns[:-1] if skip_last and len(all_turns) >= 1 else all_turns

    last_sent = _read_last_index(session_id)
    new_turns = [t for t in eligible if t["index"] > last_sent]
    if not new_turns:
        return 0

    payload = _build_payload(
        session_id=session_id,
        transcript_path=transcript_path,
        cwd=cwd,
        agent_handle=target["agent_handle"],
        turns=new_turns,
        stats_total_entries=len(entries),
        max_tool_bytes=ingest_cfg["max_tool_content_bytes"],
    )

    # Optimistic write: advance baseline before the POST so any concurrent
    # fire computes its delta from the right index. Backend content-hash
    # dedupe absorbs replays on retry.
    next_last = new_turns[-1]["index"]
    _write_last_index(session_id, next_last)

    ok = _post_ingest(
        api_url=target["api_url"],
        workspace_id=target["workspace_id"],
        mas_id=target["mas_id"],
        agent_handle=target["agent_handle"],
        payload=payload,
    )
    if not ok:
        _append_log({"event": "ingest_failed", "payload": payload})

    return 0


if __name__ == "__main__":
    # Never propagate an exception — Claude Code hooks that exit non-zero
    # can surface as user-visible errors. Swallow everything.
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
