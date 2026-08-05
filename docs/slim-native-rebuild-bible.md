# Mycelium SLIM-Native Rebuild — Implementation Bible

> **What this document is.** A single, self-contained specification for rebuilding
> mycelium's coordination layer on top of AGNTCY **SLIM** (a secure messaging fabric)
> carrying the **L9** epistemic protocol, replacing the now-removed IOC/CFN backend. It is
> written so that an engineer or agent with **zero prior context** can execute it end to
> end. It contains: background, the target architecture, how the pieces interrelate, how to
> proof-of-concept SLIM, a precise map of where the relevant code lives, the decisions and
> constraints that are already fixed, and a step-by-step build plan with a definition of
> done and tests for each step.
>
> **How to use it.** Read Parts I–IV once for orientation, then execute Part V (the build
> plan) step by step. Each step leaves the project in a working, tested state — do not move
> to step N+1 until step N's Definition of Done is met. Part VI is reference material
> (SLIM quickstart, source repos) to consult as needed.
>
> **A companion design doc** — `docs/coordination-transport-pivot.md` — records the
> discussion and rationale behind every decision here, with section numbers referenced as
> `[pivot §N]`. This bible is the authoritative spec; the pivot doc is the "why."
>
> **Do not treat any code block here as implementation to paste.** Code/config blocks are
> *reference* (existing SLIM examples, existing envelope shapes, ops commands). The
> implementation is yours to write.

---

# PART I — ORIENTATION

## 1. What mycelium is (today)

Mycelium is a multi-agent coordination layer with persistent memory. Its two durable ideas:

- **Rooms are folders.** A room is a directory of markdown files (memories) with standard
  subdirs (`decisions/`, `failed/`, `status/`, `context/`, `work/`, `procedures/`, `log/`,
  `plan/`). Memories are markdown with YAML frontmatter.
- **A coordination protocol.** Agents `join → wait → respond → reach consensus → compile a
  plan → work`. This protocol is the product's value; preserve its shape.

Today this runs on a heavy stack: a FastAPI backend + a PostgreSQL fork (AgensGraph) for
search/coordination tables + a 4-service external "CFN" (Cognition Fabric Node) cluster that
performed the actual negotiation/convergence. Agents in different runtimes (Claude Code,
Cursor, OpenClaw, Hermes) participate through per-family adapters.

## 2. The pivot (what is changing, and why)

The IOC/CFN infrastructure is going closed-source and is being removed. Mycelium re-anchors
on the **L9 protocol as a payload** carried over an **open transport (SLIM)**, and takes over
the convergence work itself (as *cognition-engine agents* it owns). The goals:

1. **Remove** the entire CFN/CognitiveEngine/knowledge-service surface and the heavy DB.
2. **Re-home coordination on SLIM**: a room becomes a SLIM group channel; agents exchange L9
   envelopes over it.
3. **Own convergence** as summoned "cognition-engine" agents, so mycelium controls the menu
   of coordination strategies without depending on another team.
4. **Collapse the stack**: markdown + a local JSON-Lines search index replace the database;
   the backend becomes a thin local process; the heaviest thing you run is one SLIM node.
5. **Prove value** with a concrete hero demo (§4) that a single-machine agent framework
   cannot do.

## 3. The target in one paragraph

A room is a **SLIM multicast group channel**. Agents (across frameworks, via per-family
*connectors*) and a mycelium-owned **thin backend process** join the channel. The backend is
the always-on infrastructure: it is the SLIM **moderator** (manages membership), the
**persister** (keeps the durable transcript, because SLIM does *not* retain messages for
offline members), and the **trigger-watcher** (summons cognition engines). Participants
broadcast **L9 envelopes** (belief/exchange messages) over the channel. When convergence is
needed, a **cognition engine** (e.g. the SIEP "aligner") is *summoned* — it reads the
transcript, judges, and emits a `commit:converged` L9 message; the backend then compiles a
shared plan and the converged knowledge is written to markdown memory (synced to each
machine over SLIM). Memory is markdown files + a local JSONL embedding index; there is **no
database**.

## 4. The hero demo (the acceptance goal)

**Cross-person, cross-machine agent collaboration with consent-based wake.** Concretely:
Julia (machine A, backend work) and Sam (machine B, frontend work) each run a local Claude
Code agent + mycelium. They must agree on an API contract.

1. Julia runs `mycelium connect sam` → SLIM joins the two machines (shared/relayed node).
2. Julia `@`-invites Sam's agent to a room on the task. Sam's machine surfaces **"Julia's
   agent wants to coordinate on 'auth contract' — accept?"** Sam accepts; his agent wakes.
3. Julia posts the task. Both agents exchange proposals as L9 messages over the channel.
4. A cognition engine is summoned, converges them, emits `commit:converged` with the agreed
   contract.
5. A shared plan compiles (Julia's tasks + Sam's tasks) into markdown memory, synced to both.
6. Each agent implements its half locally; humans supervise and `@`-steer.

This is `join → converge → plan → work`, stretched across two machines via SLIM. The
protocol inspector (a UI view of the L9/SLIM payloads flowing between machines) is the
"watch the protocol work" showcase. **The value is real but narrow** — it targets teams
already heavy on coding/work agents. That is an honest wedge, and it is deliberately *not*
the "distributed personal-agent memory" pitch.

## 5. Glossary (read this before Part II)

- **SLIM** — *Secure Low-latency Interactive Messaging*, AGNTCY's messaging fabric (Rust,
  gRPC/HTTP2, formerly "AGP"). The running code is a single binary/container: the **`slim`
  node**. Agents connect to it as clients; it routes/fans-out messages by name.
- **SLIM group / channel** — a named **multicast** session. Any member's publish is
  delivered to every current member (a chat-room-like broadcast bus).
- **Moderator** — in a SLIM group, the creator and the only party that can invite/remove
  members. Must be always-on. In mycelium this is the **backend**.
- **MLS** — Message Layer Security; SLIM's optional end-to-end group encryption. Intermediate
  nodes see only ciphertext. Decentralized (no key server).
- **Name** — a SLIM address: a 3-tuple `organization/namespace/application`. Routing is by
  name, not IP.
- **L9 / SSTP** — the epistemic protocol layer ("Layer 9", above A2A/MCP). A JSON **envelope**
  carrying belief state, causal parents, an episode id, and a kind/subkind. Mycelium already
  builds these.
- **Episode** — one coordination cycle sharing an episode id; a causal DAG of L9 messages.
  Grammar: `intent, exchange+, … commit:(converged|rejected), knowledge*`.
- **kind / subkind** — L9 message type. Kinds: `intent, exchange, contingency, commit,
  knowledge`. Failure closes as **`commit:rejected`** (the SLIM-native/spec value; the old
  Go CFN used `abort` — do not carry `abort` forward).
- **MPC / GAR / SCR** — consensus-quality metrics computed from the transcript (mean
  posterior confidence; group alignment ratio; social-compliance ratio — SCR catches
  "agents capitulating to authority rather than being convinced"). Deterministic; already
  implemented in `l9_episode.py`.
- **CIP / SIEP / SAB / TFP** — L9 sub-protocols: pairwise grounding / group convergence /
  bilateral bargaining / team formation. The MVP implements **SIEP** (group convergence).
- **Cognition engine** — an agent mycelium spawns that performs the *cognitive judgment*
  ("is this converged? what's the agreement?"). It is **summoned, not always-on**. The SIEP
  engine is nicknamed the **"aligner"** (placeholder name).
- **Connector** — mycelium's per-runtime edge that holds the SLIM connection on an agent's
  behalf and bridges the agent's native behavior to the channel. Agents never speak SLIM
  themselves.
- **Cold-spawn daemon** — mycelium's existing local process that, for CLI-family agents
  (Claude Code, Cursor), spawns a fresh agent turn per incoming message. It is the seam that
  becomes the SLIM connector + wake bridge.
- **Persister / durable inbox** — the always-on component that stores the transcript and
  re-serves messages an agent missed while asleep (necessary because SLIM drops messages for
  offline members).

---

# PART II — THE ARCHITECTURE

## 6. The layering

```
L9 / SSTP     epistemic payload (belief, episode id, causal parents, kind/subkind)
   rides on ↓
SLIM group    secure multicast channel (MLS-encrypted), routed by org/ns/app name
   on ↓
gRPC / HTTP2 / TLS
```

The general AGNTCY layering nests L9 inside **A2A** over SLIM. **Our design skips A2A for the
room bus**: for a symmetric "everyone hears everyone" room, raw SLIM **group sessions** fit
better than A2A multicast (which is request/response fan-out). So the room bus is **L9
straight over SLIM group sessions**. A2A stays optional, only for future point-to-point task
invocation across frameworks. [pivot §2, §8, §11]

## 7. SLIM primer + how to proof-of-concept it

**You must internalize these SLIM facts before building.** They are verified against the
SLIM source (cloned under `~/Documents/GitHub/_slim-research/`).

**(a) What runs.** SLIM's running code is the **`slim` node** — one stateless Rust binary
(`ghcr.io/agntcy/slim`), default port **46357**, ~100m CPU / 128Mi. No database. Agents embed
a **language binding** (`slim-bindings`, published for Python and Node) and connect to the
node as clients. A control-plane + SPIRE + channel-manager exist but are **only** needed for
multi-cluster/cross-org federation — ignore them for the MVP.

Minimal node config and run (reference):
```yaml
# slim-config.yaml
services:
  slim/0:
    node_id: mycelium-slim
    dataplane:
      servers:
        - endpoint: "0.0.0.0:46357"
          tls: { insecure: true }   # local only; SPIRE/mTLS in prod
      clients: []                    # no peers = single standalone hub
```
```
docker run -p 46357:46357 ghcr.io/agntcy/slim:latest /slim --config /slim-config.yaml
# or, for a zero-config dev node:  slimctl slim start   → node on :46357
```

**(b) Naming.** Addresses are `org/namespace/app`. Proposed mycelium mapping: **org =
workspace/tenant, namespace = room, app = agent id**; a room's channel is a Name whose third
segment is the channel/topic. Mycelium must **mint per-agent identities** (dev = a shared
secret ≥32 chars, which also seeds MLS; prod = JWT or SPIRE).

**(c) Group model (the room).** A group is a **multicast channel**. The **moderator** creates
the session for a channel Name and **invites** each member; other agents `subscribe` their
own name and block until invited. **Any member's `publish` is delivered to all current
members.** Presence (online/offline) is built in via heartbeats. MLS group encryption is
optional, decentralized, no key server.

**(d) THE CRITICAL CAVEAT — no durable inbox.** SLIM does **not** retain messages for an
offline/asleep member. Its "persistence" only restores a member's *own* session/MLS state
across a restart; a member that was gone when a message was broadcast **never receives it**,
and rejoin only re-keys — it does not replay. **Therefore mycelium must build the durable
inbox** (the always-on persister). This single fact drives much of the architecture.

**(e) Client API shape (reference, from `slim-bindings` examples).** Names via
`Name(org, ns, app)` / `Name.from_string("org/ns/app")`. Lifecycle: `initialize... →
get_global_service() → create_app_with_secret(name, secret) → connect_async(client_config)
→ subscribe_async(name, conn_id)`. Group moderator: `create_session(GROUP, channel_name)`
then `invite(member)` per member. Receiving is a **blocking async pull**
(`get_message_async(timeout)`) — this pull loop *is* the wake monitor. Broadcast:
`publish(bytes)`; targeted reply: `publish_to(ctx, ...)`.

**POC exit criterion:** you can run one `slim` node and have two local processes join one
group channel and exchange a message. That is Step 2 of the build plan.

## 8. Target system components

| Component | Role | Notes |
|---|---|---|
| **`slim` node** | the hub — routes/fans out messages by name | one container; the only heavy thing |
| **thin backend process** | moderator + persister/durable-inbox + trigger-watcher + memory read/write + UI server + fabric provisioner + identity/naming + agent/engine spawner | replaces FastAPI+Postgres; always-on, cheap |
| **local files** | markdown (memory content) + JSONL (embedding search index) | canonical store; no DB |
| **connectors** | per-family edge holding the SLIM connection for each agent | Claude Code first (§ build plan) |
| **cognition engines** | summoned agents that judge convergence | dormant by default; SIEP/aligner for MVP |

## 9. Room = SLIM channel; the backend as room infrastructure

- Creating a room **provisions a SLIM group channel**. The **backend is the moderator** (it
  must be — the moderator manages membership and must be always-on).
- The backend is the **persister / durable inbox**: it stays in the channel, records the full
  transcript to markdown, and **re-serves missed messages** to any agent that reconnects.
- The backend is the **trigger-watcher**: it watches the stream and **summons** cognition
  engines on `@`-summon / configured trigger words. (This is cheap; the LLM engine only runs
  when summoned.)
- On `commit:converged`, the backend fires the **plan compiler** (existing
  `plan_compiler.py`) to materialize `plan/tasks.md`.

## 10. Cognition engines

**Separate three things that were bundled under one name** [pivot §15]:

1. **Room infrastructure** — membership + durable transcript → **the backend** (always-on,
   cheap). *Not* cognition.
2. **Protocol machinery** — grounding checks and MPC/GAR/SCR computation → **a library**
   (already largely in `l9_episode.py`). Deterministic math over the transcript.
3. **Cognitive judgment** — "is this converged? what's the agreement?" → **the cognition
   engine** (an LLM agent), using #2 as tooling over the transcript #1 keeps.

**"Cognition engine" = only #3.** It is a **family** (one per L9 sub-protocol: SIEP converge,
SAB bargain, TFP team-formation); the MVP ships **SIEP** only. Mycelium owning this menu is
the strategic value.

**Cost is a first-class constraint.** Engines are **dormant by default (zero idle cost)**.
The cheap always-on backend does the listening and **summons** the engine; the expensive LLM
never idles-but-bills. Invocation (three ways): **explicit `@`-summon by a human (the
default/floor)**, agent-invocation, or a **configured trigger-word** (opt-in, default off —
whoever runs the stack tunes it).

**Two modes, once invoked:** **observer** (one-shot: read transcript, emit verdict, sleep) and
**driver** (takes the wheel, runs rounds, then steps aside). Intended shape is a
**cost-proportional escalation ladder**: agents talk for free → cheap observer spot-check →
expensive driver only when they're stuck. The MVP must support **both modes at a base level**.

## 11. Memory (markdown + JSONL; sync over SLIM)

- **Content** → markdown files (canonical), unchanged model.
- **Search index** → a **local JSONL** file of embeddings + metadata; **brute-force cosine**
  in-process. Fine at personal scale (hundreds–low-thousands); add a real index only if it
  reaches tens-of-thousands. **Postgres/AgensGraph is dropped entirely.**
- **Sync** → an L9 **`knowledge`** message (emitted at the end of an episode) **carries the
  content**; each connector writes the markdown locally + reindexes on arrival. This replaces
  today's notify-then-pull with push-with-content. Cross-machine = per-machine local stores
  kept in sync by the knowledge stream. Local memory CRUD stays local file/JSONL ops.
- **Conflict policy [decided]: last-write-wins, no merge handler.** Order by version/timestamp
  (memory already carries an incrementing `version`). On a genuine conflict (a write on a
  stale base), **fail the write with details** (current content + `updated_by` + `updated_at`)
  and move on. Do **not** build a merge-conflict handler.
- **The seam:** L9's `knowledge` phase *is* the write path into memory. Converged cognition →
  `knowledge` messages → markdown → synced.
- **Why this over git:** mycelium is *not* a VCS. The one thing git cannot do is stream a live
  delta into a running agent's working set mid-task; that is exactly what memory-over-SLIM is.

## 12. Human-in-the-room (`@`-mention, wake, consent)

- The product is **multi-user chat**: humans and agents in a room. The human **does not run a
  connector** — the backend/UI represents the human on the fabric (publishes their messages,
  shows them the persisted transcript).
- **`@`-mention is an application concept, not a SLIM address.** A group publish has no
  required "to" — it broadcasts to all. Three levels: SLIM broadcast → L9 `participants`
  (sender/recipient/observer, the semantic "to") → UX `@agent-x` (compiles to L9 recipients).
  This is exactly Slack semantics.
- **Two flavors of `@`:** `@`-mention an agent **already in the room** = a **wake** (the
  persister sees the mention, wakes the agent, re-serves what it missed). `@`-invoke an agent
  **not in the room** = a **membership change** (moderator invites + spawns).
- **Consent-to-be-woken** is the hero-demo differentiator: "someone's agent wants to reach
  yours — accept?" It should feel like accepting a call. This UX *is* the product surface.
- **Collision to handle:** `@`-inviting a *new* agent mid-episode violates L9's stable-
  membership rule (mid-episode join aborts/restarts the episode). Policy: **queue the invite
  until the episode closes, or accept a restart.**

## 13. How one full cycle flows (the glue)

```
[join]     backend provisions a SLIM channel for the room and is the moderator + persister.
           Each agent's connector joins (invited by the backend). A human joins via the UI/backend.

[exchange] Participants broadcast L9 `exchange` messages on the channel (peer-to-peer over SLIM).
           The backend persists every message to the markdown transcript and re-serves any that a
           reconnecting agent missed. Wake: when an agent is @-mentioned, the backend wakes it.

[converge] Someone @-summons a cognition engine (or a trigger fires). The engine (observer or
           driver) reads the transcript, computes MPC/GAR/SCR via the protocol library, and emits
           an L9 `commit:converged` (or `commit:rejected`) message onto the channel.

[plan]     The backend sees `commit:converged` and fires plan_compiler → writes plan/tasks.md into
           the room's markdown memory. The L9 `knowledge` phase carries converged content to each
           machine over SLIM; connectors write it locally + reindex.

[work]     Each agent picks up its plan tasks and works locally. Humans supervise and @-steer.
```

Everything that is "coordination" rides SLIM; everything that is "memory" is local files +
JSONL, propagated by the `knowledge` stream. There is no database and no central negotiation
service.

---

# PART III — WHERE THE CODE LIVES (repo map)

Base: `/Users/juliavalenti/Documents/GitHub/mycelium`. Classifications: **[keep]**,
**[remove]** (CFN/coordination surface to delete), **[rework]** (survives but changes),
**[L9-keep]** (epistemic core to preserve).

## 14a. Backend — `fastapi-backend/app/`

**Routes (`app/routes/`):**
- `memory.py` **[rework]** — memory CRUD + search. Core, but has a gated fire-and-forget CFN
  fan-in (via `services/knowledge_fanin.py`) to strip.
- `rooms.py` **[rework]** — room CRUD. Strip `_ensure_mas`/`_create_mas`/`_fetch_mas_id_by_name`
  (CFN MAS provisioning, gated on `CFN_MGMT_URL`).
- `sessions.py` **[rework]** — agent presence (core) + coordination-session spawn (CFN-adjacent,
  gated on `cfn_enabled`). Keep presence, remove the negotiation-session spawn.
- `messages.py` **[rework]** — post message + Postgres NOTIFY. Remove the
  `coordination.on_agent_response` dispatch and CFN fan-in.
- `stream.py` **[rework]** — SSE via raw asyncpg LISTEN/NOTIFY. Becomes moot once presence/bus
  move to SLIM; today's UI uses it.
- `plan.py` **[keep]** — plan projection + `/agent-context`. No CFN import.
- `coordination_sessions.py` **[remove]** — negotiation session resource.
- `coordination.py` (route) **[remove]** — round-trace observability.
- `cfn_proxy.py` **[remove]**, `knowledge.py` **[remove]**, `audit.py` **[remove]** — CFN surface.

**Services (`app/services/`):**
- `coordination.py` **[remove]** — the CFN negotiation orchestrator (large).
- `cfn_negotiation.py`, `cfn_resolve.py`, `cfn_http.py`, `cfn_knowledge.py`,
  `_cfn_call_timing.py`, `knowledge_fanin.py`, `ingest_dedupe.py`, `ingest_log_buffer.py`
  **[remove]** — CFN clients/plumbing.
- `l9.py` **[L9-keep]** — envelope construction + `VALID_SUBKINDS` (update the failure subkind
  to `rejected`; drop `abort`).
- `l9_episode.py` **[L9-keep]** — episode tracking + **MPC/GAR/SCR** (this becomes the
  cognition engine's protocol library).
- `l9_models.py` **[L9-keep]** — vendored pydantic bindings.
- `l9_cfn.py` **[remove]** — the CFN L9 poster (the only CFN-coupled L9 file).
- `filesystem.py` **[keep]** — the markdown memory store (the real store).
- `embedding.py` **[keep]** — local embeddings (fastembed, BAAI/bge-small-en-v1.5, 384-dim).
- `indexer.py` / `reindex.py` **[rework]** — today upsert into pgvector; retarget to the JSONL
  index.
- `plan_compiler.py` **[keep]** — consensus → `plan/tasks.md`. Re-trigger it from the backend's
  `commit:converged` watcher instead of from CFN.
- `plan.py`, `event_sweep.py`, `llm_health.py`, `metrics.py` **[keep]**.

**App core:**
- `main.py` **[rework]** — lifespan calls `create_db_and_tables()` and `_register_memory_provider()`
  (CFN, gated — remove); reindex watcher/warmup startup. Rework for the no-DB world.
- `config.py` **[rework]** — remove `CFN_*`, `WORKSPACE_ID`, `MAS_ID`, `GRAPH_DB_URL`; keep
  `MYCELIUM_DATA_DIR`, embedding settings; `DATABASE_URL` goes away with the DB.
- `models.py` **[rework/remove]** — SQLAlchemy models. Tables: `agents`, `rooms`,
  `coordination_sessions`, `messages`, `participants` (presence — note: **not** "sessions"),
  `audit_events`, `memories`, `memory_subscriptions`. With the DB dropped, most of this goes;
  what survives (rooms/presence) moves to files/SLIM.
- `database.py` **[remove]** — async SQLAlchemy engine (goes with the DB). Note `stream.py`
  opens a **separate raw asyncpg** connection for LISTEN/NOTIFY.
- Migrations: `alembic_migrations/` exists but is **bypassed at runtime** (`main.py` uses
  `create_all`). Dropping the DB removes both paths.

## 14b. CLI + daemon — `mycelium-cli/src/mycelium/`

- `cli.py` **[rework]** — registers command groups. Remove `session`, `negotiate`, `cfn`; add
  `hub host` / `connect` (SLIM).
- `commands/` — `memory.py` **[keep]**, `room.py` **[rework]** (drop `sync-mas`),
  `plan.py` **[keep]**, `config.py` **[rework]** (drop `cfn_*`/`negotiation`/`knowledge_ingest`
  settings), `instance.py`/`install.py`/`doctor.py` **[rework]** (compose changes),
  `agent.py` **[rework]** (agent registry — keep, adapt to SLIM identities),
  `daemon.py` **[keep/rework]**, `metrics.py`/`traces.py`/`docs.py`/`ui.py` **[keep]**.
  `session.py`, `negotiate.py`, `cfn.py` **[remove]**.
- `config.py` (module) — `MyceliumConfig` pydantic tree; loads `~/.mycelium/config.toml` +
  project `./.mycelium/config.toml`, writes `.env` via `config apply`. Remove the CFN blocks.
- **`daemon/` [rework — this is the connector + wake-bridge seam]:**
  - `dispatch.py` — the heart. Today holds an **httpx SSE** stream per room and cold-spawns an
    agent turn per `@`-mention / `coordination_tick`. **Retarget: hold a SLIM group
    subscription instead of SSE; wake the agent on inbound L9 messages addressed to it.**
  - `spawn.py` — `spawn_claude()` shells `claude -p ... --output-format json
    --permission-mode bypassPermissions`, parses cost/output. **[keep]** — this is how a Claude
    Code turn runs.
  - `runner.py` — orchestrator (per-room tasks, reload, health). **[rework]** for SLIM.
  - `config.py` — `DaemonConfig` (`~/.mycelium/daemon.toml`: rooms, owned handles, depth_cap,
    binaries, spawn timeout). `state.py` — per-handle locks, dedupe, budget, running procs.
    `mentions.py`, `health.py`, `preamble.py`, `install.py` (systemd/launchd). **[keep/rework]**.
- **Adapters — `integrations/`:** `base.py` (the `Integration` ABC: install + dispatch facets,
  `spawn()`), `__init__.py` (registry), `_spawn_common.py` (`SpawnRequest`/`SpawnResult`).
  - `claude_code/` **[rework — MVP first]** — `dispatch.py`, `spawn.py`, `install.py`,
    `assets/skills/mycelium/SKILL.md`. Lifecycle: **cold_spawn** via the daemon.
  - `cursor/` **[later]** — same cold_spawn shape via `cursor-agent -p`.
  - `openclaw/` **[later]** — lifecycle **long_lived_gateway** (daemon ignores it); a TS plugin
    under `assets/mycelium/plugin/` owns SSE + tick formatting (`src/channel/route.ts`).
  - `hermes/` **[later]** — long_lived_gateway; a Python gateway plugin under
    `assets/mycelium/plugin/`. (Exists.)
- **HTTP clients:** the generated `mycelium_backend_client/` (typed) and raw `httpx` (for SSE).
  Both shrink as coordination leaves HTTP for SLIM.

## 14c. Frontend — `mycelium-frontend/` (Next.js App Router, TS + Tailwind)

- `src/app/` — `room/[name]/page.tsx` (room view), `room/[name]/session/[session]/page.tsx`
  (session view), `metrics/page.tsx`, `app/api/[...path]/route.ts` (catch-all backend proxy),
  `app/api/rooms/[name]/messages/stream/route.ts` (SSE proxy).
- `src/components/` — `event-stream.tsx` (live feed via `EventSource`), `session-view.tsx`
  (session SSE), **`round-traces-panel.tsx` (nearest prior art for a "protocol inspector")**,
  room subpanels (`room-chat-box`, `memory-panel`, `agents-panel`, `participants-panel`),
  `components/ui/` shadcn primitives (**`dialog.tsx` + `button.tsx` → the consent prompt**).
- `src/lib/api.ts` — the flat API-client functions + `getSSEUrl()`. **Add new backend calls
  here.** `lib/backend.ts` resolves the backend URL server-side.
- **For new views:** the *protocol inspector* reuses the `EventSource` pattern (model on
  `event-stream.tsx`/`round-traces-panel.tsx`); the *consent prompt* builds on `ui/dialog.tsx`.

## 14d. Docker — `mycelium-cli/src/mycelium/docker/`

- `compose.yml` — services: `mycelium-db` (5432) **[remove]**, `mycelium-backend` (8000)
  **[rework]**, `mycelium-frontend` (3000, profile `ui`) **[keep]**, `mycelium-collector`
  (profile `metrics`) **[keep/optional]**, `mycelium-graph-viewer` (profile `dev`) **[remove]**,
  and the **`cfn` profile's 5 services** (`cfn-db-init` + 4 `ioc-*`) **[remove]**.
- `compose-dev.yml` — build/env overlay. **Add a `slim` node service** here and in `compose.yml`
  (image `ghcr.io/agntcy/slim`, port 46357, mount a node config).
- Net target stack: **`slim` node + `mycelium-backend` (thin) + `mycelium-frontend`** (+ optional
  collector). No DB, no CFN.

---

# PART IV — DECISIONS & CONSTRAINTS (the rules)

**Fixed decisions (do not relitigate):**
- Room bus = **L9 straight over SLIM group sessions**; **no A2A** for the room.
- Backend = the **always-on** moderator + persister + trigger-watcher. Cognition engines are
  **summoned, ephemeral**. Never make an engine always-on.
- Memory = **markdown + local JSONL**; **no database**. Conflict = **last-write-wins**, fail
  stale writes with details, **no merge handler**.
- Failure subkind is **`commit:rejected`** (not `abort`).
- Engine invocation floor = **explicit `@`-summon**; trigger-words are **opt-in, default off**.
- Cognition MVP = **SIEP only**, supporting **observer + driver** modes at a base level.
- First adapter = **Claude Code** (the one the org can actually dogfood).
- Hosting = **self-hosted by default**; a minimal mycelium-hosted rendezvous is an *optional*
  getting-started convenience (de-risked because MLS makes the node a blind ciphertext
  forwarder). Same `mycelium hub host` command regardless of who runs it.
- The `join → converge → plan → work` protocol shape is the product value — **preserve it**.

**Open questions (resolve just-in-time, at the step noted). Recommended defaults given:**
- **Native-vs-CLI per family** (Step 5). *Default:* Claude Code participates via the existing
  cold-spawn **daemon** retargeted to SLIM (no change to the agent's contract).
- **Group lifecycle: per-room vs per-negotiation** (Step 3/4). *Default:* durable channel
  per room; a negotiation is an **episode** within it (membership stable per episode).
- **Causal-ordering + episode-abort enforcement location** (Step 3/4). *Default:* enforce in
  the L9-over-SLIM binding / backend persister.
- **Aligner runtime** (Step 7). *Default:* run the engine as another cold-spawned agent turn
  (reuse the spawn path) so it needs no special infra.
- **Human's own SLIM identity vs spoken-for by backend** (Step 6). *Default:* spoken-for by
  the backend for the MVP.
- **Hermes/Cursor/OpenClaw** — post-MVP; not on the critical path. Inspect Hermes before
  attempting it.

**Testing — two tiers, both required.**
- **Fast unit tests (the merge gate).** Delete the CFN-coupled tests up front (Step 0). Write
  new unit tests at the end of each step (see each step's *Tests*). They are fast, need no
  running node, and **gate every PR** — the project must be runnable and green at every step.
- **Cumulative live-node integration suite (from Step 3 on).** Starting at Step 3 (the first
  real wiring), each step also adds an **integration slice** to a *growing* end-to-end suite
  that runs against a real `slim` node (seeded by Step 2's `test_slim_roundtrip.py`). Each
  step's slice **plus all prior slices** must pass with a node up. By Step 8 the suite *is* the
  full same-machine hero flow; Step 9 makes it cross-machine. Keep it a **separate, guarded,
  slower job** (skip-if-no-node, its own CI lane) — it must **never** block or slow the fast
  unit gate. **Shipping the step's integration slice is part of its Definition of Done
  (Steps 3–9).** Why grow it from Step 3 rather than build it all at Step 8: this is a
  distributed async system whose real bugs live in the *seams* (ordering, wake timing, the
  durable inbox, episode/membership lifecycle) — unit tests can't reach them, and a seam bug
  caught at Step 3 costs an afternoon vs. a week of bisecting at Step 8.

---

# PART V — THE BUILD PLAN

Execute in order. This is a **build sequence**, not a phased shipping plan — it all lands as
one cohesive effort; the order exists so each step has a working foundation to stand on.
**Do not start a step until the previous step's Definition of Done (DoD) is met.** Each step
ends with a runnable, unit-tested project.

Legend for each step: **Goal · Scope (tasks) · Key files · DoD · Tests (fast, unit) ·
Integration slice (Steps 3–9: the cumulative live-node suite; part of DoD) · Depends on ·
Resolve first** (open decisions that gate the step).

---

## Step 0 · Rip it out (clean slate that still runs)

- **Goal:** Remove the entire CFN/CognitiveEngine/knowledge surface. Project still builds and
  basic memory/rooms still work (on the existing DB for now — the DB comes out in Step 1).
- **Scope:**
  - Delete backend `[remove]` routes: `coordination_sessions.py`, `coordination.py` (route),
    `cfn_proxy.py`, `knowledge.py`, `audit.py`.
  - Delete backend `[remove]` services: `coordination.py`, `cfn_negotiation.py`,
    `cfn_resolve.py`, `cfn_http.py`, `cfn_knowledge.py`, `_cfn_call_timing.py`,
    `knowledge_fanin.py`, `ingest_dedupe.py`, `ingest_log_buffer.py`, `l9_cfn.py`.
  - Delete the generated CFN client (`ioc_cfn_svc_api_client/`), `cfn_swagger.json`,
    `scripts/gen-cfn-client.sh` if present.
  - Strip gated CFN branches from `[rework]` routes: `memory.py` (fan-in), `rooms.py` (MAS
    provisioning), `sessions.py` (coordination-session spawn), `messages.py`
    (`coordination.on_agent_response` + fan-in). Remove `_register_memory_provider` from
    `main.py`.
  - Remove CLI `session.py`, `negotiate.py`, `cfn.py` and unregister them in `cli.py`; drop
    `room sync-mas`; remove `cfn_*` / `negotiation` / `knowledge_ingest` config blocks in the
    CLI `config.py`.
  - Remove the `cfn` Docker profile (5 services) and `mycelium-graph-viewer`; remove `CFN_*`
    env from compose + `config.py`.
  - **Delete the CFN-coupled tests** (backend `tests/test_cfn_*`, `test_knowledge_*`,
    coordination/session tests; CLI `test_session_*`, `test_negotiate_*`,
    `test_doctor_cfn_intent`, etc.).
  - **Keep** `l9.py`, `l9_episode.py`, `l9_models.py`, all memory/rooms/plan code.
- **Key files:** everything under `[remove]` in §14a/§14b/§14d.
- **DoD:** backend starts; `mycelium memory set/get/ls/search` and `room` commands work; no
  import references CFN modules; no CFN containers in the default compose.
- **Tests:** memory CRUD + rooms basic ops (retain/adapt existing non-CFN tests). `grep`
  proves zero `cfn`/`coordination` imports remain in kept modules.
- **Depends on:** nothing. **Resolve first:** nothing.

## Step 1 · Kill the database (local store: markdown + JSONL)

- **Goal:** Replace Postgres/AgensGraph with markdown files + a local JSONL embedding index;
  the backend becomes a thin local process. All memory ops work with **no database**.
- **Scope:**
  - Point search at a **local JSONL index** (embeddings + metadata per memory), computed with
    the existing `embedding.py`. Implement brute-force cosine `memory search` over it.
  - Retarget `indexer.py` / `reindex.py` from pgvector → the JSONL index (rebuild-from-files).
  - Remove `database.py`, `models.py` DB usage, the `create_db_and_tables()` call, and
    `DATABASE_URL`/`GRAPH_DB_URL` from `config.py`. Whatever room/presence state is still
    needed becomes files/in-memory (presence will move to SLIM in Step 3–4).
  - Remove `mycelium-db` from compose; update `instance.py`/`install.py`/`doctor.py`.
  - Today's `stream.py` uses asyncpg LISTEN/NOTIFY — mark it deprecated (UI still uses it
    until Step 10; the coordination bus moves to SLIM in Step 3). Keep a minimal SSE for the
    UI or stub it; do not block on it.
- **Key files:** `services/embedding.py` [keep], `services/indexer.py`/`reindex.py` [rework],
  `services/filesystem.py` [keep], `routes/memory.py` [rework], `main.py`/`config.py`/
  `database.py`/`models.py` [rework/remove], `docker/compose*.yml`.
- **DoD:** the stack runs with **no `mycelium-db` container**; `memory set/get/ls/search`
  (including semantic search) all work against files + JSONL.
- **Tests:** memory CRUD; `memory search` returns correct top-k over a seeded JSONL; reindex
  rebuilds the JSONL from files; conflict = last-write-wins with stale-base rejection.
- **Depends on:** Step 0. **Resolve first:** nothing (JSONL is decided).

## Step 2 · SLIM node + hello-world over a group

- **Goal:** Stand up a `slim` node and prove two local processes can exchange a message over a
  group channel via the bindings.
- **Scope:**
  - Add a **`slim` node service** to `compose.yml`/`compose-dev.yml` (image
    `ghcr.io/agntcy/slim`, port 46357, minimal config from §7a).
  - Add the SLIM binding dependency (Python `slim-bindings` for the backend/daemon; Node
    `@agntcy/slim-bindings` later if a TS connector is needed).
  - Implement the **naming/identity** helper: map `workspace/room/agent` → a SLIM `Name`; mint
    a dev shared secret (≥32 chars) per agent.
  - Add `mycelium hub host` (spin the node, print the connect address) and `mycelium connect
    <address>` (store the node endpoint in config). Same command whether self- or
    mycelium-hosted.
  - Write a tiny throwaway harness: a moderator process creates a group channel and invites a
    second process; the second `publish`es; the moderator receives it.
- **Key files:** new SLIM client wrapper module (backend + daemon), `docker/compose*.yml`,
  CLI `cli.py` + a new `commands/hub.py` (or fold into `instance.py`), CLI `config.py`
  (node endpoint).
- **DoD:** `mycelium hub host` runs a node; a test exchanges a broadcast between two clients on
  one channel.
- **Tests:** SLIM round-trip integration test (two clients, one group, one broadcast, received
  by the other); Name-mapping unit test.
- **Depends on:** Step 1. **Resolve first:** identity tier — default to **shared-secret** for
  the MVP.

## Step 3 · L9 over SLIM (the bus) + room = channel

- **Goal:** L9 envelopes flow over a room's SLIM group; the backend provisions the channel and
  is its moderator.
- **Scope:**
  - Implement the **L9↔SLIM binding** (a `NetworkHandle`-style adapter): `send(header)`
    serializes an L9 envelope and `publish`es it to the room channel; inbound SLIM messages are
    parsed back to L9 and dispatched to local handlers. (Mycelium already builds envelopes via
    `l9.py`.)
  - **Room provisioning:** creating/opening a room provisions a SLIM group channel; the backend
    creates the session and is the **moderator** (invites members).
  - Enforce L9 transport requirements the app must own: **causal ordering** by
    `message.parents`, and **episode↔channel lifecycle** (a mid-episode membership change aborts
    the episode).
  - Presence now comes from SLIM (online/offline), replacing the DB presence for coordination.
- **Key files:** new L9-over-SLIM binding module; `services/l9.py` [L9-keep] (set failure
  subkind to `rejected`); `routes/rooms.py`/`sessions.py` [rework] (provision channel, presence
  from SLIM).
- **DoD:** an L9 `exchange` message published by one participant is received (and correctly
  parsed) by another over a room channel; parents-ordering holds.
- **Tests:** L9-over-SLIM round trip; envelope integrity (kind/subkind/parents/episode);
  out-of-order arrival is reordered by `parents`; mid-episode membership change triggers abort.
- **Integration slice (seeds the suite):** on a live `slim` node, two clients exchange L9 over
  a room channel; assert `parents`-ordering and episode-abort-on-membership-change end-to-end.
- **Depends on:** Step 2. **Resolve first:** group lifecycle (default: durable channel per
  room, episode = a negotiation within it); enforcement location (default: the binding/backend).

## Step 4 · Backend as room infrastructure (persister + wake)

- **Goal:** The backend joins the channel as the always-on **persister/durable inbox** and
  **trigger-watcher**; offline agents no longer lose messages.
- **Scope:**
  - **Persister:** record the full transcript to the room's markdown (`log/`), so it survives
    and is queryable.
  - **Durable inbox:** when an agent reconnects, **re-serve** the messages it missed while
    offline (SLIM will not — §7d). Track per-agent delivery position.
  - **Trigger-watcher skeleton:** watch the stream; recognize `@`-summon tokens and (later)
    trigger-words; expose a hook to summon an engine (wired in Step 7).
  - **plan-compile hook:** watch for `commit:converged` and (in Step 8) fire `plan_compiler`.
- **Key files:** the backend room-infra module(s); `services/plan_compiler.py` [keep] (re-wire
  its trigger); the L9-over-SLIM binding from Step 3.
- **DoD:** an agent that is offline during a broadcast **receives the missed messages on
  reconnect**; the transcript is persisted to markdown.
- **Tests:** durable-inbox test (broadcast while offline → reconnect → missed messages
  delivered, in order); transcript persistence test; trigger-watcher recognizes an `@`-summon.
- **Integration slice:** on a live node, an agent offline during a broadcast reconnects and is
  re-served the missed messages in order (durable inbox). All prior slices still pass.
- **Depends on:** Step 3. **Resolve first:** nothing new.

## Step 5 · Claude Code connector + wake bridge (the dogfood milestone)

- **Goal:** A Claude Code agent participates in a room: it is woken on relevant messages,
  spawned to take a turn, and its reply lands in the channel.
- **Scope:**
  - **Retarget the daemon** (`daemon/dispatch.py`) from an httpx **SSE** stream to a **SLIM
    group subscription**: hold the subscription, and on an inbound L9 message addressed to a
    handle (via L9 `participants` / an `@`-mention), **wake** that agent.
  - Keep `spawn.py`'s `spawn_claude()` (headless `claude -p`) as the turn-runner; publish the
    agent's reply back to the channel as an L9 `exchange` message.
  - Preserve the existing gates (per-handle lock, budget, depth, ownership) and control verbs
    (`abort`/`status`).
  - The agent's **contract is unchanged** — it does not speak SLIM; the daemon (the connector)
    does. (Native-vs-CLI default: keep cold-spawn.)
- **Key files:** `daemon/dispatch.py` [rework — the seam], `daemon/spawn.py` [keep],
  `daemon/runner.py`/`state.py`/`config.py` [rework], `integrations/claude_code/` [rework],
  the L9-over-SLIM binding.
- **DoD:** a registered Claude Code agent joins a room, is woken by an inbound message, spawns
  a turn, and its reply appears in the room for others.
- **Tests:** connector wake path (inbound L9 → spawn invoked, mock the `claude` binary);
  reply is published as valid L9; budget/depth/ownership gates still hold; `abort`/`status`.
- **Integration slice:** on a live node, a connector (mock `claude` binary) wakes on an inbound
  L9 message and its reply appears in the room. All prior slices still pass.
- **Depends on:** Step 4. **Resolve first:** native-vs-CLI (default: cold-spawn daemon).

## Step 6 · Human-in-the-room + `@`-mention + consent

- **Goal:** A human posts to the room and `@`-mentions agents; consent-to-be-woken works.
- **Scope:**
  - Backend/UI publishes the human's messages onto the channel (human **spoken-for** by the
    backend — no human connector for the MVP).
  - **`@`-parse → L9 participants:** map `@agent-x` to L9 recipients (others = observers).
  - **`@`-mention (in-room) = wake** (via Step 5's bridge); **`@`-invite (not-in-room) =
    membership change** (moderator invites + spawns).
  - **Consent-to-be-woken:** when a remote/foreign invite arrives, surface an accept/decline
    prompt on the target side; only join on accept. This is the hero-demo differentiator —
    make it feel like accepting a call.
  - **`@`-invite-mid-episode policy:** queue the invite until the episode closes (default) or
    accept a restart.
- **Key files:** backend `@`-parse + participants mapping; `integrations/*/` invite path;
  CLI/UI consent surface (frontend `components/ui/dialog.tsx` for the prompt).
- **DoD:** a human `@`-mentions the Claude Code agent and it wakes and answers; an `@`-invite of
  a not-present agent shows a consent prompt and only joins on accept.
- **Tests:** `@`-parse → participants; in-room mention wakes; not-in-room invite triggers
  consent; declined invite does not join; mid-episode invite is queued.
- **Integration slice:** on a live node, an `@`-mention wakes the connector; a not-in-room
  `@`-invite raises consent and only joins on accept. All prior slices still pass.
- **Depends on:** Step 5. **Resolve first:** human identity (default: spoken-for by backend).

## Step 7 · Cognition engine — base layer (observer + driver)

- **Goal:** A summoned SIEP cognition engine can **observe** an exchange and emit a verdict, and
  can **drive** a simple multi-round convergence. De-risked — SIEP only; no SAB/TFP/escalation
  sophistication yet.
- **Scope:**
  - **Protocol library:** reuse `l9_episode.py`'s MPC/GAR/SCR computation over the transcript
    as the engine's deterministic tooling.
  - **The aligner (SIEP) engine**, dormant by default, **summoned** (default runtime: a
    cold-spawned agent turn, reusing `spawn.py`):
    - **Observer mode:** read the transcript, compute metrics, emit an L9
      `commit:converged`/`commit:rejected`.
    - **Driver mode:** run N rounds — prompt each participant for a position, collect, score,
      repeat — then emit a verdict.
  - **Invocation:** explicit `@`-summon (floor) via the Step 4 trigger-watcher; agent-invoke;
    (optional, off by default) a configured trigger-word.
- **Key files:** `services/l9_episode.py` [L9-keep, as library]; the new engine module; the
  trigger-watcher (Step 4); the spawn path (Step 5).
- **DoD:** `@`-summoning the aligner in observer mode over a seeded exchange emits a correct
  `commit:converged`; driver mode runs the configured number of rounds and emits a verdict.
- **Tests:** observer emits verdict with correct MPC/GAR/SCR; driver runs the round loop and
  terminates; a below-threshold exchange yields `commit:rejected`.
- **Integration slice:** on a live node, `@`-summoning the aligner in a room makes it observe
  the exchange and emit `commit:converged`. All prior slices still pass.
- **Depends on:** Steps 4–6. **Resolve first:** aligner runtime (default: cold-spawned turn).

## Step 8 · Plan + memory sync (the full loop, same-machine)

- **Goal:** A converged negotiation compiles a shared plan and writes/synchronizes memory —
  the whole `join → converge → plan → work` loop works **on one machine**.
- **Scope:**
  - On `commit:converged`, the backend fires **`plan_compiler.py`** → `plan/tasks.md`.
  - Implement the L9 **`knowledge`** write path: converged content becomes `knowledge`
    messages that **carry content**; each connector writes markdown locally + reindexes the
    JSONL on arrival (push-with-content, replacing notify-then-pull).
  - Apply the conflict policy: last-write-wins; stale-base writes fail with details.
- **Key files:** `services/plan_compiler.py` [keep, re-triggered]; the L9-over-SLIM binding
  (knowledge kind); `indexer.py`/`reindex.py` (write + reindex on knowledge arrival).
- **DoD:** a converged negotiation produces `plan/tasks.md` and propagates converged memory to
  all participants' local stores. **← same-machine mini-demo of the hero flow works here.**
- **Tests:** converged → plan file exists with expected tasks; `knowledge` message writes
  markdown + updates JSONL on a second local store; conflict rejects a stale write with details.
- **Integration slice (same-machine acceptance):** the full flow end-to-end on one machine —
  join → exchange → summon/converge → plan compiles → memory syncs to a second local store.
  This is the same-machine hero-flow test; all prior slices roll up into it.
- **Depends on:** Step 7. **Resolve first:** nothing new.

## Step 9 · Cross-machine

- **Goal:** The whole loop runs across two machines.
- **Scope:**
  - Extend `mycelium connect` to join a **remote/shared** SLIM node. Start with **LAN
    reachability** (copy the host's LAN IP); document the open-internet path (a reachable/
    hosted node or tunnel) but do not block on NAT traversal for the MVP.
  - Per-machine local stores kept in sync by the `knowledge` stream (Step 8) over the shared
    channel.
  - Consent-based invite (Step 6) across machines.
- **Key files:** CLI `hub`/`connect`; the SLIM client wrapper (remote endpoint); the sync path.
- **DoD:** two machines on a LAN run the full hero flow: connect → consent-invite → exchange →
  converge → plan → synced memory → work.
- **Tests:** cross-machine integration (two nodes/one shared node on a LAN or two containers on
  a bridge network); memory sync arrives on the remote store.
- **Integration slice (cross-machine acceptance):** the full hero flow across two nodes / a
  bridge network. This is the final acceptance test — the whole suite green, end to end.
- **Depends on:** Step 8. **Resolve first:** hub location for cross-machine (default:
  self-hosted shared node; hosted rendezvous optional).

## Step 10 · UI: protocol inspector (+ room view)

- **Goal:** Watch the protocol work — the AOP showcase — and surface the consent prompt.
- **Scope:**
  - **Protocol inspector:** a view that renders the L9 payloads flowing on a room's channel
    (kind/subkind, episode id, causal parents), modeled on `event-stream.tsx` /
    `round-traces-panel.tsx`; add its fetch/stream in `lib/api.ts`. Feed it from the backend
    persister (the transcript), which is on the wire by construction.
  - **Room view** over the new store (persisted transcript + memory).
  - **Consent prompt** UI (built on `components/ui/dialog.tsx`).
- **Key files:** `mycelium-frontend/src/components/` (new inspector component + consent dialog),
  `src/lib/api.ts`, `src/app/room/[name]/...`.
- **DoD:** you can open a room in the UI, watch L9 messages stream during a negotiation, and
  accept/decline a consent prompt.
- **Tests:** inspector renders a seeded transcript; consent dialog action reaches the backend.
- **Depends on:** Step 8 (Step 9 for the cross-machine visual). **Resolve first:** nothing new.
  *(Optional: land this right after Step 8 so the same-machine demo already looks like
  something.)*

---

## Acceptance (the hero demo)

The build is "done" for the MVP when, on two LAN machines each running a Claude Code agent +
mycelium: `mycelium connect` joins them; an `@`-invite with a consent prompt brings the second
agent in; the agents exchange L9 messages; a summoned aligner converges them and emits
`commit:converged`; a shared plan compiles into markdown memory synced to both machines; each
agent works its half; and the UI inspector shows the L9 payloads crossing between machines.

---

# PART VI — REFERENCE

## SLIM proof-of-concept quickstart

```
# 1. Run a node (either)
docker run -p 46357:46357 ghcr.io/agntcy/slim:latest /slim --config /slim-config.yaml
slimctl slim start            # zero-config dev node on :46357

# 2. Client lifecycle (Python slim-bindings, from the repo examples)
#    Name("org","ns","app") → create_app_with_secret → connect_async → subscribe_async
#    moderator: create_session(GROUP, channel) → invite(member) per member
#    send: publish(bytes)   receive: get_message_async(timeout)  (blocking pull = wake monitor)
```

Key SLIM facts to keep front-of-mind: **broadcast to all members** (no per-message "to");
**no durable inbox** (build the persister); **presence built in**; **MLS = optional E2E,
ciphertext-only at intermediate nodes**; **one node covers local + LAN**, federation only for
cross-org.

## Cloned source (ground truth for APIs and behavior)

Under `~/Documents/GitHub/_slim-research/`:
- `slim/` — the node, config examples (`config/`), Helm charts, crates
  (`session`, `channel-manager`, `mls`, `persistence`, `datapath`, `control-plane`).
- `slim-bindings/` — client SDKs (`python/`, `node/`, examples for point-to-point and group).
- `slim-a2a-python/` — A2A-over-SLIM (reference only; the room bus does not use A2A).
- `ioc-protocols-models/` — L9/SSTP spec (`SSTP/`): envelope structure, the `NetworkHandle`
  transport seam, sub-protocols (CIP/SIEP/SAB/TFP), the MPC/GAR/SCR formulas, and the
  kind/subkind grammar (failure = `commit:rejected`).

## Companion documents

- `docs/coordination-transport-pivot.md` — the design discussion and rationale (`[pivot §N]`).
- `CLAUDE.md` — project conventions. **Note:** its "Git for sharing" line is stale — memory
  sharing is not git-based; see §11 here.

## External references

- SLIM: github.com/agntcy/slim · bindings: github.com/agntcy/slim-bindings ·
  npm `@agntcy/slim-bindings` · PyPI `slim-bindings`
- L9/IOC: github.com/outshift-open/ioc-protocols-models
- A2A (optional/future): github.com/a2aproject/A2A · JS: github.com/a2aproject/a2a-js
