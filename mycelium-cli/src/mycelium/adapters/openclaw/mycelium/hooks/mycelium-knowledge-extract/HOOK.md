---
name: mycelium-knowledge-extract
description: "Extracts structured conversation data (thinking, tool calls, tool results, token usage, cost) from session JSONL and forwards it to mycelium-backend, which relays to CFN's shared-memories knowledge graph."
metadata:
  openclaw:
    emoji: "🔍"
    events:
      - message:sent
      - agent:bootstrap
---

# Conversation Extractor

Reads the session JSONL on each configured openclaw event and emits a structured payload of new conversation turns (since the last send) — thinking chains, tool calls, tool results, token usage, cost per turn. Forwards the payload to `POST /api/knowledge/ingest`, which applies user-configurable gates and then relays to CFN's shared-memories endpoint.

Observability: every forward attempt (ok, deduped, refused, disabled, error) shows up in `mycelium cfn log` and `mycelium cfn stats`.

## Configuration

All knobs live under `[knowledge_ingest]` in `~/.mycelium/config.toml`. Read via `mycelium config get knowledge_ingest.<key>`, set via `mycelium config set knowledge_ingest.<key> <value>`. Each is also overridable at the process level via the matching `MYCELIUM_INGEST_*` env var for ephemeral changes (no config edit, no restart needed to change the env var itself).

| Key | Default | Where it's read | Effect |
|---|---|---|---|
| `enabled` | `true` | hook + backend | Master kill switch. `false` stops the hook on entry (zero I/O, zero POSTs) and makes the backend short-circuit with a `disabled` event. |
| `events` | `["command:new", "agent:bootstrap"]` | hook | Which openclaw events fire the hook. Drop `agent:bootstrap` if you still see restart amplification after the optimistic-write fix. |
| `max_tool_content_bytes` | `4096` | hook | Truncation threshold for each `tc.input` and `tc.result` in the payload. `0` disables truncation. Truncated bytes are counted in `stats.truncatedBytes`. |
| `skip_in_progress_turn` | `true` | hook | Skip the last un-finalized turn so tool-result late arrivals don't trigger re-sends. Final session turn sends when the next turn arrives or the session closes. |
| `max_input_tokens` | `50000` | backend | Circuit breaker. Refused with HTTP 413 if estimated input tokens exceed this. `0` disables. |
| `dedupe_ttl_seconds` | `300` | backend | Content-hash dedupe window. Identical payloads within this many seconds return the cached response_id without re-hitting CFN. `0` disables. |

Quickest panic button: `MYCELIUM_INGEST_ENABLED=0` in the shell (or `mycelium config set knowledge_ingest.enabled false` for persistence, followed by `mycelium config apply --restart` to propagate to the backend container).

## Correctness guarantees

- **Diff baseline is optimistic.** The per-session `lastSentIndex` advances *before* the POST, so concurrent hook fires compute their diff against the correct state. Trade-off is at-least-once on POST failure; the backend content-hash dedupe absorbs any duplicates.
- **Per-session in-process mutex.** A module-level `Set` keyed on `${agentId}:${sessionId}` prevents a pending POST from being re-entered by the next fire. Restart clears the mutex, but the backend dedupe catches any replays.
- **Tool content is capped per tool call.** `tc.input` / `tc.result` longer than `max_tool_content_bytes` UTF-8 bytes are truncated with a `…[truncated N bytes]` marker. CFN's extractor pulls concepts, not verbatim text, so extraction quality is unaffected.

## Fallback

If mycelium-backend is unreachable, the payload is appended to `~/.openclaw/mycelium-knowledge-extract.log` as a JSON line. This is a best-effort archive, not a retry queue.
