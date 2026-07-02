# L9 Protocol Integration Plan

Scope: give mycelium a native understanding of the IOC L9 protocol
(`outshift-open/ioc-protocols-models`) and use it to communicate with the new
Go CFN service (`outshift-open/ioc-cfn-svc`), which exposes a native L9
endpoint (`POST /api/l9/messages`) and renames the negotiation API from
`semantic-negotiation` to `semantic-alignment`.

Context: CFN will eventually speak L9 natively end-to-end. The old Python CFN
(`ioc-cognition-fabric-node-svc`) → new Go CFN (`ioc-cfn-svc`) instance
migration is WIP on the CFN side. Mycelium's role is: L9 envelopes + transport
+ persistence + agent-side protocol; convergence/epistemic engines stay in
CFN/CEs. Where mycelium computes anything epistemic (agreement-quality
metrics), it is interim and designed to be ceded to the CE later.

---

> **2.0.0 addendum (2026-07-02):** the dual-stack `CFN_API_FLAVOR` migration
> vehicle described below was built, then removed the same day by team
> decision — mycelium 2.0.0 targets the Go CFN (ioc-cfn-svc) exclusively.
> The python CFN's semantic-negotiation path and the generated
> `ioc_cfn_svc_api_client` are gone; all CFN calls are plain httpx against
> the semantic-alignment API. The compose service keeps the historical
> `ioc-cognition-fabric-node-svc` name for existing installs' saved URLs.

## 0. Open questions — RESOLVED (2026-07-02)

1. **Subkind vocabulary: the Go CFN table is authoritative** (confirmed by
   team Confluence doc, 2026-06-30). Mycelium emits the vocabulary validated
   in `ioc-cfn-svc/pkg/app/handlers_l9.go:23-29`: `commit:
   converged|resolved|abort`, `intent: coordinator-assignment|mission`,
   `exchange: team-formation`, `contingency: negotiation`, `knowledge:
   query|distillation|extraction|feedback`. The spec repo's
   `converged|rejected|resolved|ready` grammar is stale. Failed negotiations
   therefore commit as `abort`, not `rejected`.
2. **Knowledge CE: `ghcr.io/outshift-open/ioc-cfn-cognition-engines`**
   (`:latest` on main pushes, versioned on tags). The repo ships three agents
   behind one gateway image: Ingestion (OTel extraction), Evidence Gathering
   (knowledge-graph retrieval), and Semantic Alignment (NegMAS + SSTP
   negotiation). Evidence/ingestion store and retrieve via the CFN, which
   routes to ioc-knowledge-memory-svc.
3. **knowledge-mem-svc: `outshift-open/ioc-knowledge-memory`** —
   `ioc-knowledge-memory-svc` (HTTP port 9003) plus a companion
   `ioc-knowledge-memory-svc-db:0.1.0` postgres image on ghcr. Its CI builds
   the service image; confirm a non-PR service tag is published before wiring
   compose (PR builds tag `pr-N`; check ghcr for a main/latest tag).
4. **Go CFN image: `ghcr.io/outshift-open/ioc-cfn-svc:latest`** — published
   on every main push (linux/amd64+arm64, also `{date}-{sha}` tags). The image
   is alpine with curl installed (existing curl-style healthchecks work),
   exposes 9002 (HTTP) + 9001 (MCP), bakes `docs/swagger.json` in, and has its
   own HEALTHCHECK against `/api/internal/diagnostics/health`. Mgmt-plane
   compatibility with `ioc-cfn-mgmt-plane-svc:0.1.1` still needs a smoke test
   at swap time (same `MGMT_URL` pattern, unverified in practice).

---

## 1. New shared foundation: L9 models + envelope module

**Dependency** (`fastapi-backend/pyproject.toml`, via `uv add`):

- `ioc-l9-all-models` (PyPI, pydantic ≥2, Python ≥3.10 — compatible with the
  backend's 3.12). Provides `ai.outshift.data_model` (L9, L9Header, L9Payload,
  Message, Actor, ParticipantSet, Kind).

**New module `fastapi-backend/app/services/l9.py`:**

- Envelope construction helpers: `build_envelope(kind, subkind, actors,
  episode, parents, topic, epistemic, payload_parts)` returning a validated
  `L9` model; serialization to/from the JSON stored in `Message.content`.
- Episode URN minting from coordination sessions:
  `urn:ioc:mycelium:episode:{parent_room}:{coordination_session_id}`.
- Subkind validation table mirroring the CFN's accepted combinations (single
  source of truth in this module; revisit when open question 1 resolves).
- `participants.groups = {"workspace_id": ..., "mas_id": ...}` — both already
  exist per room (`Room.workspace_id` / `Room.mas_id`), which is exactly what
  the CFN's content-based routing extracts.
- Parent/causality helpers: given a session's message history, compute the
  `message.parents` list for a new message (ticks parent the reply they answer;
  replies parent the tick that prompted them; consensus parents the final round
  replies).

No DB migration: envelopes and parent links live inside the existing
`Message.content` TEXT JSON. `message_type` stays as-is so SSE routing,
the openclaw plugin, and the frontend keep working unmodified where they
don't care about L9.

---

## 2. Backend changes (`fastapi-backend/`)

### 2.1 CFN client migration (old Python CFN → Go CFN)

- **Regenerate `ioc_cfn_svc_api_client`** from the Go service.
  `scripts/gen-cfn-client.sh` currently curls `$CFN_URL/openapi.json`; the Go
  service serves its spec at `/docs/swagger.json` (swaggo) — update the script
  to try both paths. Alternatively generate from the checked-in
  `~/Documents/GitHub/ioc-cfn-svc/docs/swagger.json`.
- **Dual-stack `app/services/cfn_negotiation.py`.** New setting
  `CFN_API_FLAVOR: Literal["negotiation", "alignment"]` (default
  `negotiation` until the instance migration lands) in `app/config.py`:
  - `negotiation` → existing `semantic-negotiation/start|decide` paths.
  - `alignment` → `semantic-alignment/start|decide` paths.
  - Request schemas are compatible (`session_id`, `content_text`, `agents`,
    `n_steps` / `agent_replies` with `participant_id`, `action`, `offer`).
- **Decide-response parsing** in `_normalize_cfn_decide_response()`
  (`app/services/coordination.py:284-324`): add the Go-CFN shape — agreement
  arrives as a terminal `final_result` SSTP envelope rather than
  `semantic_context.final_agreement`. Keep the old path for the Python CFN.
- **Consume new response fields** (alignment flavor only):
  - `trace` (full SAO history) → attach to `_RoundTrace` telemetry.
  - `meta` (token usage / cost / latency) → attach to round trace.
  - `shared_memory.persisted` → log; surface on the consensus payload as
    `cfn_persisted: bool`.

### 2.2 L9 envelopes on mycelium's own coordination messages

All inside `app/services/coordination.py`, additive to the existing content
JSON (existing keys unchanged — both delivery paths keep working):

- `_fan_out_cfn_messages()` (line ~693): add an `l9` key to each
  `coordination_tick` content — header with `kind=exchange`, episode URN,
  `message.id`, `message.parents`, actors (sender=CognitiveEngine,
  recipient=the agent), `context.topic` derived from the room
  (`urn:concept:mycelium:{room}`).
- `on_agent_response()` (line ~1318): accept an optional `l9` key on replies;
  validate parent linkage when present; never reject replies that omit it
  (non-L9 agents must keep working).
- `_finish_cfn()` (line ~1169): wrap `coordination_consensus` as
  `kind=commit, subkind=converged` (or the failure subkind per open question
  1), parents = final-round reply IDs. After the plan write, emit an L9
  `kind=knowledge` record of the agreement (see 2.4).
- Episode record persistence: on commit, write the full ordered envelope list
  to room memory `log/episodes/{session_short_id}.md` (markdown summary —
  episode URN, outcome, metrics — plus a fenced JSONL block of envelopes). Uses the existing
  memory-write path, so it is git-shareable and pgvector-indexed for free.

### 2.3 Epistemic reply fields + agreement-quality metrics (interim)

- Optional reply fields parsed by `_parse_agent_reply()`: `confidence`
  (float 0-1), `evidence` (list of strings), `deferred_to` (agent handle or
  null), `reasoning` (string). Stored per-agent per-round in
  `_CfnRoundState` / `_RoundTrace` (`_PerAgentTrace` gains
  `confidence: float | None`, `deferred_to: str | None`).
- At `_finish_cfn()`, when at least N-1 agents supplied confidences, compute
  and attach to the consensus payload:
  - `mpc` — mean final confidence,
  - `gar` — fraction whose confidence moved toward the consensus relative to
    their round-0 value,
  - `scr` — fraction of accepts carrying `deferred_to`,
  - `provenance_weight = (1 - scr) * gar`.
  Definitions per the SIEP spec (`ioc-protocols-models
  SSTP/subprotocol/siep`). Marked interim: when the CE computes these
  natively, mycelium switches to passing them through.
- CIP contingency/repair (mid-round grounding-failure branches) is **out of
  scope** for this integration — it requires a new turn-taking pattern in the
  tick/reply cycle and is owned by the IE-CE in the target architecture.

### 2.4 Speaking L9 to the CFN

New module `app/services/l9_cfn.py` (thin httpx client, no generated client —
the endpoint takes/returns one model):

- `post_l9(envelope) -> L9`: `POST {COGNITION_FABRIC_NODE_URL}/api/l9/messages`.
- **Knowledge write** after consensus: `kind=knowledge` (subkind per CFN
  vocabulary) carrying the agreement, metrics, and `plan_file` reference.
  Fire-and-forget with logged failure — consensus must not block on it.
- **Knowledge query** at session start (`_run_tick(tick=0)`): `kind=knowledge,
  subkind=query` for prior agreements on the room's topic; when a result comes
  back, inject as `team_prior` into the tick payload (and its formatted
  rendering, section 4.3).
- Both calls are feature-gated (`L9_CFN_ENABLED` setting, default false) —
  merge dark, enable once the cognition-engines gateway and
  ioc-knowledge-memory-svc are running and the knowledge CE is registered
  with the CFN.

### 2.5 Config (`app/config.py`)

- `CFN_API_FLAVOR: str = "negotiation"`
- `L9_CFN_ENABLED: bool = False`

### 2.6 Tests (`fastapi-backend/tests/`)

- Unit (SQLite): envelope build/validate round-trips; parent-linkage
  computation; subkind table; `_normalize_cfn_decide_response` with the
  `final_result` shape; reply parsing with/without epistemic fields; metric
  computation (fixtures with known GAR/SCR/MPC); episode record writing.
- Integration (AgensGraph + `--profile cfn`): dual-flavor negotiation
  end-to-end once a Go CFN dev image exists.

---

## 3. CLI changes (`mycelium-cli/`)

### 3.1 Wire protocol (`src/mycelium/protocol.py`)

- `ProposeReply`: optional `confidence`, `evidence`, `reasoning`.
- `RespondReply`: optional `confidence`, `evidence`, `deferred_to`,
  `reasoning`.
- `NegotiatePayload` / tick parsing: optional `team_prior` and `l9` keys.

### 3.2 Commands (`src/mycelium/commands/negotiate.py`, `session.py`)

- `mycelium negotiate propose ... --confidence 0.8 --evidence "..."
  --reasoning "..."` (repeatable `--evidence`).
- `mycelium negotiate respond accept --confidence 0.7 --defer-to <handle>`
  — `--defer-to` marks a compliance accept (feeds SCR).
- `mycelium session await`: render `team_prior` when present in the tick JSON
  output; render `mpc/gar/scr` in the consensus output.
- All flags optional; omitting them produces byte-identical requests to today.

### 3.3 Config schema (`src/mycelium/config.py` + `docker_utils.py`)

- `runtime.cfn_api_flavor` (`negotiation` | `alignment`) → emitted into
  `~/.mycelium/.env` as `CFN_API_FLAVOR` by `generate_env_file()`.
- (No other env plumbing changes: `COGNITION_FABRIC_NODE_URL`,
  `WORKSPACE_ID`, `MAS_ID` already flow through.)

### 3.4 Agent skill/protocol docs — all three adapters

Update the negotiation section in each (same content, three copies):

- `src/mycelium/integrations/claude_code/assets/skills/mycelium/SKILL.md`
- `src/mycelium/integrations/hermes/assets/mycelium/plugin/skills/mycelium/SKILL.md`
- `src/mycelium/integrations/openclaw/assets/mycelium/plugin/skills/mycelium/SKILL.md`

Additions: state your confidence when proposing/responding; cite evidence;
use `--defer-to` when yielding without being persuaded (and why honesty there
matters — it's measured, not punished); how to read a team prior in a tick;
what the consensus quality metrics mean. This keeps the skill a protocol
(join → wait → respond → consensus → plan → work), extending the respond step
— not an augmentation layer.

### 3.5 OpenClaw channel plugin (two-delivery-paths rule)

`src/mycelium/integrations/openclaw/assets/mycelium/plugin/src/channel/route.ts`:

- `formatTickInstruction()`: render `team_prior` ("The team's prior on this
  topic is X (provenance weight Y, from N prior episodes)") and the epistemic
  instructions ("include your confidence 0-1 in your reply; if you accept only
  to defer, say so").
- `formatConsensusSummary()`: render `mpc/gar/scr` and `cfn_persisted` when
  present.

### 3.6 Vendored backend client

If any backend HTTP schema changes (it shouldn't — all changes ride inside
message content), regenerate via `scripts/gen-mycelium-client.sh` into both
`mycelium-client/` and `mycelium-cli/src/mycelium_backend_client/`.

### 3.7 CLI quality gate

`cd mycelium-cli && uv run ruff check . && uv run ruff format --check . &&
uv run ty check . && uv run pytest tests/ -x -q` — plus new tests for flag
parsing and reply serialization.

---

## 4. UI changes (`mycelium-frontend/`)

Types are hand-written; extend interfaces in place.

### 4.1 Session detail view (`src/components/session-view.tsx`)

- `Event` interface: add optional `confidence`, `evidence`, `deferredTo`,
  `parents`.
- `EventRow` (lines ~596-630): confidence chip next to the action label when
  present; `deferred_to` rendered as a compliance marker.
- `SwimLanes` (lines ~439-527): cell tooltip/subscript with confidence; a
  distinct glyph or muted style for deferred accepts (extend the existing
  action-glyph legend).
- `ConsensusBanner` (lines ~529-568): metrics row under the assignments grid —
  `MPC 0.82 · GAR 0.75 · SCR 0.25` with plain-language tooltips; failure
  states unchanged.

### 4.2 Session feed cards (`src/components/sessions-view.tsx`)

- `TickCard`: show team prior line when the tick carries one.
- `ConsensusCard`: metrics chips (same values as the banner).
- `ResponseCard`: confidence chip.

### 4.3 Room event stream (`src/components/event-stream.tsx`)

- Consensus notice line (lines ~376-427): append quality summary when present,
  e.g. `CONSENSUS in {session} · 3 issues · GAR 0.75`.

### 4.4 Episode record access

- The episode log written to `log/episodes/{id}.md` (section 2.2) is already
  browsable via the existing memory panel — no new UI required for v1. A
  dedicated causal-graph view of `message.parents` is explicitly deferred.

All fields optional → sessions run by non-L9 agents render exactly as today.

---

## 5. Compose / deployment changes (`mycelium-cli/src/mycelium/docker/`)

### 5.1 `compose.yml` (cfn profile) — when the Go CFN image is published

- Swap `ioc-cognition-fabric-node-svc` image
  (`ghcr.io/outshift-open/ioc-cognition-fabric-node-svc:0.1.7`) for the
  `ioc-cfn-svc` image. Env mapping is nearly 1:1 (verified against the Go
  repo's README): `MGMT_URL`, `DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD`,
  `PORT=9002` all carry over; the existing `cfn_cp` database (created by
  `docker/initdb/create-cfn-cp-db.sh`) can be reused via `DB_NAME`.
  New optional env: `ENABLE_TIMESCALEDB` (default false), `MCP_PORT` (9001).
- Healthcheck: the Go service exposes the same
  `/api/internal/diagnostics/health` path — existing check works; the
  container may not ship python3, so switch the check to `wget`/`curl` per
  whatever the published image contains (verify at swap time).
- Keep `ioc-cfn-mgmt-plane-svc` as-is (the Go CFN consumes the same
  `MGMT_URL` config-push pattern) pending open question 4.
- Backend env: add `CFN_API_FLAVOR` passthrough next to the existing
  `COGNITION_FABRIC_NODE_URL` wiring in `compose.yml`/`compose-dev.yml`.
- New services for the L9 knowledge path (behind the cfn profile or a new
  `l9` profile): `ghcr.io/outshift-open/ioc-cfn-cognition-engines` (CE
  gateway: ingestion + evidence + semantic-alignment agents) and
  `outshift-open`'s `ioc-knowledge-memory-svc` (port 9003) with its
  `ioc-knowledge-memory-svc-db:0.1.0` postgres companion. Exact env contracts
  to be lifted from each repo's own compose/README at wiring time.

### 5.2 `compose-dev.yml`

- Mirror the `CFN_API_FLAVOR` env into the dev backend service.
- Optionally a commented-out service block for running a locally-built
  `ioc-cfn-svc` (`docker build` from the sibling checkout) for dual-stack
  testing before the image is published.

### 5.3 Install flow (`src/mycelium/commands/install.py`)

- No structural change: workspace provisioning already goes through the mgmt
  plane (`_get_cfn_workspace_id`), MAS-per-room creation already goes through
  `_ensure_mas()` in `fastapi-backend/app/routes/rooms.py` — both are
  mgmt-plane APIs, unaffected by the node-svc swap.
- `_write_mycelium_config()`: persist `runtime.cfn_api_flavor` when IOC is
  enabled.

---

## 6. Documentation changes

### 6.1 Docs site (`mycelium-cli/src/mycelium/docs/` → `docs/*.html`)

- New content section `l9-protocol.md`: what L9 is, the envelope on
  coordination messages, episode URNs, epistemic reply fields, quality
  metrics, team priors, the CFN L9 endpoint relationship. Register it in
  `docs/generate_docs.py`'s section list (Concepts page).
- Update `cognitive-engine.md`: the Go CFN, semantic-alignment naming,
  content-based CE routing, `CFN_API_FLAVOR`.
- Update `sessions.md`: the new optional reply fields and consensus metrics.
- Configuration reference regenerates automatically from the pydantic
  `Field(description=...)` on the new config keys — write good descriptions.
- CLI reference regenerates from `@doc_ref` decorators — decorate the new
  flags' commands appropriately.
- Regenerate: `cd mycelium-cli && uv run python ../docs/generate_docs.py`.

### 6.2 README.md

- Architecture section: one paragraph on L9 (mycelium speaks the IOC L9
  protocol with the CFN; negotiations leave spec-shaped episode records).

### 6.3 CLAUDE.md

- Extend the "two delivery paths" section: epistemic tick/consensus fields
  must be rendered in `formatTickInstruction()` / `formatConsensusSummary()`.
- New key-design-decision bullets: L9 envelopes are additive inside message
  content (never required of agents); subkind vocabulary lives in
  `app/services/l9.py`; `CFN_API_FLAVOR` dual-stack rationale.

### 6.4 Skill docs

- Covered in 3.4 (three SKILL.md copies) — they are the agent-facing docs.

---

## 7. Testing & validation

- Backend unit tests: section 2.6.
- CLI tests: flag → wire-format serialization; tick/consensus parsing with the
  new keys.
- e2e: extend the `e2e` skill's coordination scenario to have agents pass
  `--confidence`/`--evidence` and assert metrics appear in the consensus
  message and `log/episodes/` record. The `claude-code-e2e` / `cursor-e2e`
  skills exercise the SKILL.md protocol updates implicitly.
- Dual-stack validation: run the same negotiation against the Python CFN
  (`CFN_API_FLAVOR=negotiation`) and the Go CFN (`alignment`) and diff the
  consensus payloads.
- `/verify` against the UI: run a demo negotiation, confirm confidence chips,
  swim-lane markers, and the consensus metrics row render, and that a session
  without epistemic fields renders unchanged.

---

## 8. Explicitly out of scope

- CIP contingency/repair branches (mid-round grounding repair) — new
  turn-taking pattern, owned by IE-CE in the target architecture.
- Negotiation *transport* over `/api/l9/messages` (replacing
  semantic-alignment REST) — the CFN team is mid-flight on the CE side; the
  alignment endpoints remain the contract.
- Team-process episodes (role negotiation) — join+intent already covers it.
- A2A binding, SAB/TFP subprotocols, policy/attestation enforcement.
- Frontend causal-graph visualization of `message.parents`.
- Modifying the cognition-engines or knowledge-memory services themselves —
  mycelium only deploys and calls them.

---

## 9. Suggested build order (within one integrated change)

Dependencies only — not split-PR boundaries:

1. Section 1 (models + envelope module) — everything else imports it.
2. Section 2.1 (dual-stack CFN client) + 5 (compose/config plumbing) — can be
   validated against the Python CFN immediately, Go CFN when available.
3. Sections 2.2/2.3 (envelopes + epistemic fields + metrics) with 3 (CLI) and
   4 (UI) together — the fields are only useful once emitted, parsed, and
   rendered; the openclaw formatter must land in the same change as the tick
   payload additions (CLAUDE.md rule).
4. Section 2.4 (L9 to CFN) merged dark behind `L9_CFN_ENABLED`.
5. Section 6 (docs) regenerated last, over the final flag/config surface.
