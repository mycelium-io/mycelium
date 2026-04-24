#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
mycelium-knowledge-extract (Claude Code)

Claude Code hook: reads the current session transcript JSONL, extracts the
most recent *completed conversation turn* (one user prompt → all assistant
thinking / tool calls / response until the next user prompt), and POSTs it
to mycelium-backend's ``/api/knowledge/ingest`` endpoint — which forwards
to CFN's shared-memories knowledge graph.

Design: last-turn-only, no delta state. Each fire ships exactly one turn —
the most recent complete one. If a Stop event doesn't fire (crash, kill),
that turn is lost; we accept that because this is an observability /
knowledge-graph-enrichment hook, not an at-least-once delivery system.
Keeping each fire bounded (~1 turn, a few KB) is the whole point.

**Opt-in by default, behind two gates.** Silently no-ops unless ALL of:

  1. ``[knowledge_ingest] enabled = true`` — global kill switch across
     every adapter (also honored by openclaw).
  2. ``[adapters.claude-code] knowledge_extract = true`` — per-adapter
     switch so Claude Code can be on while openclaw is off (or vice versa).

Spoke nodes only send ``room_name`` — the backend resolves ``workspace_id``
and ``mas_id`` from the room's DB record or its own settings (see #139).

CFN ingest costs real tokens per record, so we don't turn this on for
people automatically. Both gates default to off/unset.

Hook input (stdin JSON, from Claude Code):
  {
    "session_id":     "<uuid>",
    "transcript_path": "/abs/path/to/session.jsonl",
    "cwd":            "...",
    "hook_event_name": "Stop" | "SessionEnd" | "PreCompact" | ...
  }

Config (``~/.mycelium/config.toml``):
  [server]
  api_url = "http://localhost:8000"

  [rooms]
  active = "my-room"   # optional — routes ingest to per-room MAS

  [knowledge_ingest]
  enabled                = false     # global — must be explicitly true
  max_tool_content_bytes = 4096      # per tool_call input/result
  max_text_bytes         = 8192      # per thinking/response block

  [adapters.claude-code]
  knowledge_extract = false          # per-adapter — must be explicitly true

Env overrides (ephemeral; take precedence over config):
  MYCELIUM_API_URL
  MYCELIUM_ACTIVE_ROOM
  MYCELIUM_AGENT_HANDLE
  MYCELIUM_INGEST_ENABLED
  MYCELIUM_INGEST_MAX_TOOL_CONTENT_BYTES
  MYCELIUM_INGEST_MAX_TEXT_BYTES

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
    """Resolve target API and identity for ingest.

    Spoke nodes only send room_name — the backend resolves workspace_id and
    mas_id from the room's DB record or its own settings (#139).
    """
    server = config.get("server", {}) or {}
    identity = config.get("identity", {}) or {}
    rooms = config.get("rooms", {}) or {}
    return {
        "api_url": os.environ.get("MYCELIUM_API_URL")
        or server.get("api_url")
        or "http://localhost:8000",
        "room_name": os.environ.get("MYCELIUM_ACTIVE_ROOM") or rooms.get("active"),
        "agent_handle": os.environ.get("MYCELIUM_AGENT_HANDLE")
        or identity.get("name")
        or "claude-code",
    }


def _resolve_ingest_config(config: dict[str, Any]) -> dict[str, Any]:
    # Opt-in by default. CFN ingest costs real tokens, so the hook must be
    # explicitly enabled — either via config.toml or MYCELIUM_INGEST_ENABLED=1.
    ki = config.get("knowledge_ingest", {}) or {}
    enabled = ki.get("enabled", False)
    if "MYCELIUM_INGEST_ENABLED" in os.environ:
        enabled = _env_bool("MYCELIUM_INGEST_ENABLED", False)

    max_tool_bytes = ki.get("max_tool_content_bytes", 4096)
    env_tool = os.environ.get("MYCELIUM_INGEST_MAX_TOOL_CONTENT_BYTES")
    if env_tool is not None:
        try:
            max_tool_bytes = int(env_tool)
        except ValueError:
            pass

    max_text_bytes = ki.get("max_text_bytes", 8192)
    env_text = os.environ.get("MYCELIUM_INGEST_MAX_TEXT_BYTES")
    if env_text is not None:
        try:
            max_text_bytes = int(env_text)
        except ValueError:
            pass

    return {
        "enabled": bool(enabled),
        "max_tool_content_bytes": int(max_tool_bytes),
        "max_text_bytes": int(max_text_bytes),
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


# ── Payload / POST ────────────────────────────────────────────────────────────


def _build_payload(
    session_id: str,
    transcript_path: str,
    cwd: str | None,
    agent_handle: str,
    turns: list[dict[str, Any]],
    stats_total_entries: int,
    max_tool_bytes: int,
    max_text_bytes: int,
) -> dict[str, Any]:
    truncated_bytes = 0

    def _track(before: Any, after: Any) -> None:
        nonlocal truncated_bytes
        before_size = len(
            (before if isinstance(before, str) else json.dumps(before, default=str)).encode("utf-8")
        )
        after_size = len(
            (after if isinstance(after, str) else json.dumps(after, default=str)).encode("utf-8")
        )
        if after_size < before_size:
            truncated_bytes += before_size - after_size

    def _cap(value: Any, max_bytes: int) -> Any:
        if max_bytes <= 0:
            return value
        result = _truncate(value, max_bytes)
        _track(value, result)
        return result

    payload_turns = []
    tool_call_count = 0
    thinking_turn_count = 0
    for t in turns:
        thinking = _cap(t.get("thinking"), max_text_bytes) if t.get("thinking") else None
        if thinking:
            thinking_turn_count += 1
        tool_calls = []
        for tc in t["tool_calls"]:
            tool_call_count += 1
            tool_calls.append(
                {
                    "id": tc["id"],
                    "name": tc["name"],
                    "input": _cap(tc["input"], max_tool_bytes),
                    "result": _cap(tc["result"], max_tool_bytes),
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
                "user_message": _cap(t["user_message"], max_text_bytes),
                "thinking": thinking,
                "tool_calls": tool_calls,
                "response": _cap(t["response"], max_text_bytes) if t["response"] else None,
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
    agent_handle: str,
    payload: dict[str, Any],
    *,
    room_name: str | None = None,
) -> bool:
    """POST knowledge to the backend ingest endpoint.

    Spoke nodes only send room_name — the backend resolves workspace_id and
    mas_id from the room's DB record or its own settings (#139).
    """
    body: dict[str, Any] = {
        "agent_id": agent_handle,
        "records": [payload],
    }
    if room_name:
        body["room_name"] = room_name
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

    config = _load_config()
    ingest_cfg = _resolve_ingest_config(config)
    if not ingest_cfg["enabled"]:
        # Global kill switch is off. Silent.
        return 0

    # Per-adapter gate: requires [adapters.claude-code].knowledge_extract = true.
    # Two independent gates so openclaw and claude-code can be toggled
    # separately without flipping the global switch.
    adapter_cfg = (config.get("adapters") or {}).get("claude-code") or {}
    if not adapter_cfg.get("knowledge_extract", False):
        return 0

    target = _resolve_target(config)

    if not transcript_path:
        return 0
    entries = _read_transcript(Path(transcript_path))
    if not entries:
        return 0

    all_turns = _extract_turns(entries)
    if not all_turns:
        return 0

    # Ship only the most recent complete turn. One user prompt → all assistant
    # thinking / tool calls / response until the next user prompt. Bounded by
    # design: a single turn is typically a few KB, well under the circuit
    # breaker. If this Stop doesn't fire (crash), the turn is lost — accepted
    # tradeoff for an observability hook, not an at-least-once delivery system.
    payload = _build_payload(
        session_id=session_id,
        transcript_path=transcript_path,
        cwd=cwd,
        agent_handle=target["agent_handle"],
        turns=all_turns[-1:],
        stats_total_entries=len(entries),
        max_tool_bytes=ingest_cfg["max_tool_content_bytes"],
        max_text_bytes=ingest_cfg["max_text_bytes"],
    )

    ok = _post_ingest(
        api_url=target["api_url"],
        agent_handle=target["agent_handle"],
        payload=payload,
        room_name=target.get("room_name"),
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
