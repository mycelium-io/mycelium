# Status: Cognition Engine Adapter + Demo Hardening
_2026-03-17_

## What shipped in this batch

### 1. Demo hardening (Part 1 + Part 2 both working)

**Part 1 — async memory flow**
- 7 agent memory writes working end-to-end (pgvector bytea bug fixed)
- `memory ls`, `memory search` (semantic vector), `catchup` with LLM synthesis all confirmed

**Part 2 — sync negotiation flow**
- `room create friday-demo --mode sync` → two agents join → CE fires → NegMAS SAO → consensus
- `broken: false`, `timedout: false`, round 1 agreement confirmed
- Key learning: agents must call `await` within 60s of CE firing (reply_timeout); fixed by running await immediately after join

### 2. Embedding stack replaced

- Removed `fastembed` (failed on Cisco VPN SSL due to HF network calls at startup)
- Replaced with `sentence-transformers==2.7.0` + `all-MiniLM-L6-v2` (already in local HF cache)
- Model loaded eagerly at import time from snapshot path (`~/.cache/huggingface/hub/.../snapshots/`)
- `TRANSFORMERS_OFFLINE=1` + `HF_HUB_OFFLINE=1` set in `main.py` before any imports
- `embed_text` called via `asyncio.to_thread` to keep event loop unblocked
- `transformers<4.40` pinned to avoid `find_adapter_config_file` network check

### 3. pgvector NULL/bytea fix

`app/models.py`: `Vector` subclass with `bind_expression` that wraps `None` with `CAST(NULL AS vector)`.
asyncpg cannot infer the type for `None` on a `UserDefinedType` and emits `$N::BYTEA`.
No binary codec registration — that conflicted with SQLAlchemy's text `bind_processor`.

### 4. Cognition Engine adapter (`app/routes/cognition_engine.py`)

New file implementing the `ioc-cfn-svc` → Mycelium surface:

| Endpoint | Status | Notes |
|----------|--------|-------|
| `POST /api/knowledge-mgmt/extraction` | ✅ Implemented | Calls `IngestionService` private methods; LLM extraction → AgensGraph |
| `POST /api/knowledge-mgmt/reasoning/evidence` | ✅ Implemented | Cypher MATCH on MAS graph; graceful fallback if graph missing |
| `POST /api/semantic-negotiation` | ✅ Stub | NegMAS wire-up TODO |

Router registered in `main.py`. `ioc-cfn-svc` added to `compose.yml` under `cfn` profile with `COGNITION_ENGINE_SVC_URL=http://mycelium-backend:8000`.

### 5. CLI flag standardization

All commands now use `--room / -r` (was `--channel / -c` in `room join`, `room await`, all `message` subcommands).
Env var renamed `MYCELIUM_CHANNEL_ID` → `MYCELIUM_ROOM_ID` (old name kept as backward-compat fallback in `_resolve_room`).
Updated: `room.py`, `message.py`, `adapter.py`, SKILL.md, OPENHIVE_INSTRUCTIONS.md, `handler.js`, `index.ts`.

---

## Known gaps / follow-up

### Cognition engine evidence schema drift
`ioc-cfn-cognitive-agents2` evidence response records have `{"id", "type", "content"}` structure.
Our impl returns `{"content": {...}}` — may break `ioc-cfn-svc` parser if it's strict.
Not yet tested end-to-end with `ioc-cfn-svc` running.

### Extraction couples to IngestionService internals
`cognition_engine.py` calls `svc._build_compact_payload`, `svc._llm_extract_concepts`, `svc._llm_extract_relationships`, `svc._generate_id` — all private.
If `IngestionService` internals change, this will silently break.
Acceptable for now; can be decoupled when `IngestionService` API stabilizes.

### `ioc-cfn-svc` not yet tested in compose
The service block is in compose.yml but end-to-end verification (cfn-svc health → extraction → evidence curl tests from the plan) has not been run.

### Negotiation endpoint path mismatch
`ioc-cfn-cognitive-agents2` exposes `POST /api/v1/negotiate/initiate` (SSTP envelope).
Our stub is at `POST /api/semantic-negotiation` — this is what `ioc-cfn-svc` calls, so it's correct for the current integration surface. Full NegMAS SSTP wire-up is a separate workstream.

---

## Files changed (this batch)

```
fastapi-backend/app/models.py                          # Vector.bind_expression NULL fix
fastapi-backend/app/database.py                        # removed pgvector codec registration
fastapi-backend/app/main.py                            # TRANSFORMERS_OFFLINE, cognition_engine router
fastapi-backend/app/config.py                          # EMBEDDING_MODEL → sentence-transformers
fastapi-backend/app/services/embedding.py              # rewritten: sentence-transformers, eager load
fastapi-backend/app/routes/memory.py                   # asyncio.to_thread for embed_text
fastapi-backend/app/routes/cognition_engine.py         # NEW: 3 endpoints for ioc-cfn-svc
fastapi-backend/pyproject.toml                         # fastembed removed, sentence-transformers added
fastapi-backend/uv.lock                                # updated
mycelium-cli/src/mycelium/commands/room.py             # --channel/-c → --room/-r, MYCELIUM_ROOM_ID
mycelium-cli/src/mycelium/commands/message.py          # --channel/-c → --room/-r
mycelium-cli/src/mycelium/commands/adapter.py          # MYCELIUM_CHANNEL_ID → MYCELIUM_ROOM_ID
mycelium-cli/src/mycelium/adapters/openclaw/...        # SKILL.md, handler.js, index.ts, OPENHIVE_INSTRUCTIONS.md
mycelium-cli/src/mycelium/docker/compose.yml           # ioc-cfn-svc service block added
mycelium-cli/uv.lock                                   # updated
```
