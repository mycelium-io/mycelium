# CLAUDE.md

## Project

Mycelium — multi-agent coordination + persistent memory, built on the Internet of Cognition.

## Structure

```
.mycelium/              Memory storage (rooms are folders, memories are markdown files)
├── rooms/{name}/       Room directories with standard namespace subdirs
└── config.toml         Project-local configuration

fastapi-backend/    FastAPI coordination engine (Python 3.12, asyncpg, SQLAlchemy)
mycelium-cli/       CLI tool (typer, Rich, typed OpenAPI client)
mycelium-client/    Generated OpenAPI client (openapi-python-client)
mycelium-frontend/  Next.js frontend (TypeScript, Tailwind)
docs/               Presentation deck, demo script
mycelium-promo/     HyperFrames promo video — code-defined HTML→MP4 walkthrough
                    (CLI install → app install → room → adapter → chat → swim
                    lanes → consensus → plan → work). Renders 1920x1080 H.264.
                    `cd mycelium-promo && npm run dev` to preview,
                    `npm run render` to export to renders/*.mp4.
                    The README + docs/index.html embed the rendered MP4 via a
                    `user-attachments/assets/...` URL — these only auto-render
                    inline when uploaded via GitHub's web drag-drop (gh CLI has
                    no equivalent). After re-rendering, drag the new MP4 into a
                    PR comment to mint a fresh URL, then swap it into both
                    embeds.
```

## Development

```bash
# Backend
cd fastapi-backend && uv sync --group dev
uv run pytest tests/ -x -q                    # unit tests (SQLite)
DATABASE_URL=... uv run pytest tests/ -x -q    # integration tests (AgensGraph)
uv run ruff check . && uv run ruff format . && uv run ty check .

# CLI (install globally)
cd mycelium-cli && uv tool install -e . --with mycelium-backend-client@../mycelium-client --force

# CLI quality gate (matches CI) — run before pushing
cd mycelium-cli && uv run ruff check . && uv run ruff format --check . \
  && uv run ty check . && uv run pytest tests/ -x -q

# Frontend
cd mycelium-frontend && pnpm install && pnpm dev
```

## Architecture

**Memory**: Stored as markdown files with YAML frontmatter in `.mycelium/rooms/{room}/{key}.md`.

**AgensGraph** (PostgreSQL 16 fork) is the search index and coordination backend:
- pgvector: semantic vector search over memory embeddings (updated on write)
- SQL tables: rooms, coordination_sessions, sessions (presence), messages, subscriptions
- openCypher: knowledge graph (optional enrichment layer)

**Memory flow**:
1. `memory set` writes a markdown file to `.mycelium/rooms/{room}/{key}.md`
2. Simultaneously upserts a pgvector embedding in AgensGraph for semantic search
3. `memory get` / `memory ls` reads from the filesystem
4. `memory search` queries the pgvector index
5. Direct file writes (cat, editor, agent file I/O) work — run `reindex` to update search index

Real-time: Postgres LISTEN/NOTIFY → asyncpg → SSE streams.

LLM: litellm (provider/model format, e.g. `anthropic/claude-sonnet-4-6`).

Embeddings: sentence-transformers (all-MiniLM-L6-v2, local, 384 dimensions).

## Key design decisions

- **CognitiveEngine mediates** — agents never talk to each other directly. All coordination flows through CE.
- **Rooms are folders** — `.mycelium/rooms/{name}/` with standard subdirs: `decisions/`, `failed/`, `status/`, `context/`, `work/`, `procedures/`, `log/`, `plan/`. The `plan/` namespace holds the room's plan: `plan/title.md` is the room's display title (italic hero in the UI), other `plan/{slug}.md` files carry prose + `- [ ]` checklist tasks surfaced to every agent.
- **Rooms are always persistent** — rooms are persistent namespaces for memory and coordination. Spawn sessions within rooms for real-time NegMAS negotiation.
- **The CLI skill is a protocol** — join → wait → respond → consensus → plan → work. This is the value add, don't change it to an augmentation layer.
- **memory set always upserts** — `memory set` overwrites existing keys automatically (version increments).
- **Consensus compiles into the plan** — when a negotiation reaches consensus, `coordination.py:_finish_cfn` hands the agreement to `plan_compiler.py`, an LLM stage that materializes it as `plan/tasks.md` (one shared `- [ ]` checklist) *before* the `coordination_consensus` message is posted (plan-first ordering — `session await` returns once the plan exists). Fail-soft: a compiler outage falls back to writing the raw `issue=value` agreement. The compiler is deliberately **not** a CognitiveEngine step — the CE is the negotiation engine (owned separately); the compiler is a distinct consumer stage that picks up the consensus across an explicit seam. `litellm.acompletion` doesn't work for Bedrock, so the compiler routes Bedrock models through threaded sync `completion`.
- **Git for sharing** — rooms can be shared via git push/pull.
- **No Ensue references in code** — we took inspiration from their API design but the implementation is independent.
- **Two delivery paths for coordination ticks — keep them in sync.** When a `coordination_tick` is posted to a session room, agents see it via one of two paths depending on their adapter:
  - **CLI path (Claude Code, Cursor, plain shell):** the agent runs `mycelium await` (or `mycelium negotiate await`) which streams ticks from the SSE endpoint. Formatting is whatever the agent does with the raw JSON tick payload.
  - **OpenClaw path:** the agent does NOT run `mycelium await`. The `mycelium-room` channel plugin (`mycelium-cli/src/mycelium/integrations/openclaw/assets/mycelium/plugin/src/channel/`) subscribes to the session room's SSE on its behalf and dispatches a *human-readable string* into the agent's session via `formatTickInstruction()` in `route.ts`. The agent only ever sees that formatted string — the raw payload fields are invisible to it.

  This means that **adding a field to the backend tick payload (`coordination.py:_fan_out_cfn_messages`) is not enough on its own** — the openclaw flow won't surface it until you also update `formatTickInstruction()` to render it into the dispatched string. Always change both.

  The same discipline applies to the **`coordination_consensus`** payload (`coordination.py:_finish_cfn`): the openclaw consensus renderer is `formatConsensusSummary()` in the same `route.ts`. The `plan_file` field on the consensus payload, for instance, is only surfaced to openclaw agents because `formatConsensusSummary()` renders it. The L9 epistemic fields follow the same rule: `team_prior` on ticks and `metrics`/`cfn_persisted` on consensus are rendered by both formatters; extend both when adding more.
- **L9 envelopes are additive, never required of agents.** Coordination messages carry IOC L9 envelopes (`l9` key inside content JSON): ticks are `exchange`, consensus is `commit:converged`/`commit:abort`, with episode URNs and causal `message.parents`. The backend synthesizes reply envelopes from parsed agent replies; agents never need to speak L9. Modules: `app/services/l9.py` (envelope construction + the subkind table), `l9_episode.py` (episode tracking, consensus quality metrics MPC/GAR/SCR, `log/episodes/{short_id}.md` records), `l9_cfn.py` (client for the Go CFN's `POST /api/l9/messages`; off by default behind `L9_CFN_ENABLED`), `l9_models.py` (pydantic bindings **vendored** from outshift-open/ioc-protocols-models because the `ioc-l9-all-models` PyPI package requires litellm>=1.89.3, conflicting with our security pin).
- **The Go CFN's subkind table is authoritative** (per team decision 2026-06-30), not the spec repo's docs: `commit: converged|resolved|abort`; a failed negotiation commits as `abort`, not `rejected`. The table lives in `app/services/l9.py:VALID_SUBKINDS`.
- **The CFN is the Go ioc-cfn-svc; the python CFN is gone (2.0.0).** The env var is `CFN_SVC_URL` (was `COGNITION_FABRIC_NODE_URL`) and the compose service is `ioc-cfn-svc`. The cfn profile runs the full validated 4-service stack (mgmt-plane, knowledge-memory-svc, ioc-cfn-svc, cognition-engine) pinned to a coherent `2026-06-26-*` set (ioc-cfn-svc's `2026-06-23` tag was pruned upstream, so the whole set moved to the nearest reproducible date). Decide replies key on `participant_id`; the agreement arrives as a `final_result` envelope. Epistemic reply extras (confidence/evidence/deferred_to/reasoning) are parsed mycelium-side but never forwarded to CFN.
- **CFN timeout boundary: mycelium owns agent-waiting, CFN owns compute.** The round watchdog (`coordination.py:_CFN_ROUND_TIMEOUT_SECS`) restarts per agent reply (`_reset_round_timeout` on each first-reply), so single-threaded/serialized agent runtimes get a fresh budget each reply. That runs *before* `/decide`. The CFN never waits for agents; it takes the full reply batch and computes. So the CFN's timeout is a flat bound on its own scoring, returning a structured `status:"timeout"`. mycelium's `CFN_DECIDE_TIMEOUT_SECONDS` (600s) is a **dead-connection backstop above** the CFN's internal timeout so that status always wins over an opaque transport error. Do NOT collapse these into one session-wide deadline; a flat wall-clock would re-break the single-threaded case the per-reply restart protects.
- **CFN retry policy is set via MAS config, not env on the CFN.** `retry_max_attempts` (CFN default 3) restarts a negotiation from round 1 on a low alignment score, silently running a session several times over. `rooms.py:_ensure_mas` sends `mas_config={retry_max_attempts, validation_score_intervention}` at MAS creation (settings `CFN_RETRY_MAX_ATTEMPTS` default **1**, `CFN_VALIDATION_SCORE_INTERVENTION` default 0.6). A CFN-internal retry is surfaced as a `coordination_retry` message (detected via round regression in `_cfn_decide_round`).
- **CFN contract enforcement: typed client for negotiation, httpx for knowledge.** `cfn_negotiation.py` goes through the generated `ioc_cfn_svc_api_client` (regenerated from the Go CFN's swagger by `scripts/gen-cfn-client.sh`: swagger 2.0 → OAS3 via `npx swagger2openapi`, then `openapi-python-client`; source of truth is the committed `fastapi-backend/cfn_swagger.json` snapshot). Three enforcement layers: typed request construction (ty-checked), schema-validated response parsing, and explicit **presence assertions** on depended-on fields (swaggo marks everything optional, so a rename would silently be `UNSET`; `_require()` makes it a loud `CfnNegotiationError`). Two response fields stay dict-navigated because the CFN's own swagger under-types them (`messages` is Go `json.RawMessage` mis-rendered as `[]int`; `final_result` is `map[string]interface{}`). `cfn_knowledge.py` stays on plain httpx **deliberately**: its `payload.data` is `json.RawMessage` (a list at runtime), so typing it would be fragile, not robust. Regenerate + `git diff --exit-code` is the CI-able drift check. **This whole sem-neg REST contract is transitional** (per CFN team 2026-07-07): the Semantic Alignment CE (renamed from "sem neg") is being reworked to process L9 natively via the SAB subprotocol, and once that lands the `semantic-alignment/start|decide` endpoints are removed and negotiation migrates onto the L9 envelope layer (`l9.py`/`l9_episode.py`). The typed client is a bridge; don't over-invest. The shared-memories write is fire-and-forget: extraction is hardwired server-side, CFN acks async with 202, nothing comes back to process. (The `graph/*` read endpoints CFN never supported were removed from mycelium in 2.0.0.)

## Local development

> **This section is for contributors iterating on the backend source.** End users should follow the normal install path: `curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash` then `mycelium install`.

### Starting the stack

The normal `mycelium up` / `mycelium install` flow uses `compose.yml` with `pull_policy: always` — it always pulls released images and is the correct path for end users. For dev, use `compose-dev.yml` instead, which builds `mycelium-backend` from local source and wires `~/.mycelium/.env` into all service containers. **Always run from the repo root.**

```bash
# Full stack with CFN (required for negotiate/session commands)
docker compose \
  -f mycelium-cli/src/mycelium/docker/compose.yml \
  -f mycelium-cli/src/mycelium/docker/compose-dev.yml \
  --profile cfn up -d --build

# Memory only (no CFN)
docker compose \
  -f mycelium-cli/src/mycelium/docker/compose.yml \
  -f mycelium-cli/src/mycelium/docker/compose-dev.yml \
  up -d --build
```

On subsequent runs, drop `--build` unless you've changed backend code.

### LLM config

All containers get their LLM settings from `~/.mycelium/.env`, which is generated from `config.toml`. Set these once:

```bash
mycelium config set llm.model "anthropic/bedrock/global.anthropic.claude-sonnet-4-6"
mycelium config set llm.api_key "<key>"
mycelium config set llm.base_url "<base-url>"
mycelium config apply
```

Then recreate any running CFN containers to pick up the new env:
```bash
docker compose -f mycelium-cli/src/mycelium/docker/compose.yml \
  -f mycelium-cli/src/mycelium/docker/compose-dev.yml \
  --profile cfn up -d --force-recreate ioc-cfn-svc
```

**Important:** `mycelium config apply` regenerates `.env` from `config.toml`. If you edit `.env` directly, those changes will be overwritten. Always use `mycelium config set` to persist values.

### After restarting the CFN stack (or wiping volumes)

The CFN management plane assigns a workspace UUID and a MAS UUID per room. These
IDs are stored in `config.toml` and the mycelium backend DB, but they rotate any
time the mgmt plane DB is wiped. Run this after restarting the dev stack to
re-associate the workspace with the running CFN node and refresh all room MAS IDs:

```bash
mycelium config sync-cfn
```

This is idempotent — safe to run at any time. If the workspace UUID changed (e.g.
full volume wipe), the command updates `config.toml` and `.env` automatically and
prompts you to restart the backend to pick up the new `WORKSPACE_ID`.

If `sync-cfn` reports a workspace ID change (full volume wipe scenario), it updates
`config.toml` and `.env` then exits — run `mycelium doctor` next to restart the
backend with the new `WORKSPACE_ID` and sync room MAS IDs:

```bash
mycelium config sync-cfn   # updates config, exits early if workspace rotated
mycelium doctor            # restarts backend, patches any remaining drift
mycelium config sync-cfn   # re-run to sync room MAS IDs now backend is current
```

### MAS ID

`mas_id` in `config.toml` is a CFN Multi-Agent System UUID required for `session join`/`await`/`negotiate`. Each room gets its own MAS ID on creation — use the one for the room you're testing:

```bash
mycelium room create my-room        # prints MAS ID on creation
mycelium config set server.mas_id <uuid-from-above>
```

After a volume wipe, run `mycelium config sync-cfn` to re-provision all room MAS IDs at once.

### Running the backend outside Docker (hot-reload)

```bash
cd fastapi-backend
DATABASE_URL="postgresql+asyncpg://postgres:password@localhost:5432/mycelium" \
  uv run uvicorn app.main:app --reload --port 8000
```

DB container still needs to be running (`docker compose up -d mycelium-db`). Update `config.toml` if you change the backend port:
```bash
mycelium config set server.api_url "http://localhost:8000"
mycelium config apply
```

## Conventions

- Use `uv run` for all Python commands, never bare `python` or `pip install`
- Use `uv add` to manage dependencies, not manual pyproject.toml edits
- Ruff for linting and formatting (`select = ["ALL"]` with explicit ignores)
- Tests: SQLite for unit tests (conftest.py), real AgensGraph for integration tests
- Tests use temp directories for `.mycelium/` data (conftest.py sets MYCELIUM_DATA_DIR)
- Live-LLM tests guarded by `MYCELIUM_LLM_TESTS=1` (costs tokens)
- Commit messages: imperative, concise, body for context if needed
