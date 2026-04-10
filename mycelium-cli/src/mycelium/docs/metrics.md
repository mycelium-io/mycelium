# Metrics System

The Mycelium metrics pipeline collects, aggregates, and displays telemetry from
two sources — **OpenClaw** (via OTLP) and the **Mycelium FastAPI backend** (via
HTTP polling) — and writes it to a single JSON file for the CLI to render.

## Architecture

```
┌──────────────┐   OTLP/HTTP protobuf    ┌────────────────────┐
│   OpenClaw   │ ──────────────────────▶ │  Metrics Collector │
│   Gateway    │   /v1/metrics           │  (localhost:4318)  │
│              │   /v1/traces            │                    │
└──────────────┘                         │  ┌──────────────┐  │
                                         │  │ MetricsStore │  │
┌──────────────┐   GET /api/metrics      │  │  (in-memory) │  │
│  Mycelium    │ ◀ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─   │  └──────┬───────┘  │
│  Backend     │  (polled every 30s)     │         │ flush    │
│  (FastAPI)   │                         └─────────┼──────────┘
└──────────────┘                                   ▼
                                         ~/.mycelium/metrics.json
                                                   │
                                                   ▼
                                         ┌──────────────────┐
                                         │  mycelium        │
                                         │  metrics show    │
                                         └──────────────────┘
```

## CLI Commands

| Command                   | Description                                      |
| ------------------------- | ------------------------------------------------ |
| `mycelium metrics install`| Install optional deps (`opentelemetry-proto`, `protobuf`) |
| `mycelium metrics status` | Health check: collector process, data file, OTEL config   |
| `mycelium metrics collect`| Start the OTLP receiver (background by default; `--fg` for foreground) |
| `mycelium metrics stop`   | Stop the background collector                    |
| `mycelium metrics reset`  | Delete `~/.mycelium/metrics.json`                |
| `mycelium metrics show`   | Render collected data as Rich tables              |
| `mycelium metrics show --json` | Dump raw JSON for scripting                  |
| `mycelium metrics show --workspace` | Include per-file workspace breakdowns   |

## Files Created

| Path                            | Purpose                              |
| ------------------------------- | ------------------------------------ |
| `~/.mycelium/metrics.json`      | Aggregated metrics (counters, histograms, sessions, backend snapshot) |
| `~/.mycelium/collector.pid`     | PID and port of the background collector process |
| `~/.mycelium/collector.log`     | Stdout/stderr log from the background collector  |

`metrics.json` is atomically updated (write to `.tmp`, rename) on every OTLP
ingestion and on graceful shutdown.

## What We Collect

### Source 1: OpenClaw OTLP Telemetry

The collector listens on `localhost:4318` and accepts standard OTLP/HTTP
protobuf payloads from OpenClaw's `diagnostics-otel` plugin.

#### Counters (from OTLP `sum` metrics)

| OTLP metric name              | Stored as                        | Attributes used                 |
| ----------------------------- | -------------------------------- | ------------------------------- |
| `openclaw.tokens`             | `counters.tokens.total.*`        | `openclaw.token` (input/output/cache_read/cache_write/total) |
|                               | `counters.tokens.by_agent.*`     | `openclaw.channel`              |
|                               | `counters.tokens.by_model.*`     | `openclaw.model`                |
| `openclaw.cost.usd`           | `counters.cost_usd.total`        | `openclaw.channel`, `openclaw.model` |
| `openclaw.message.processed`  | `counters.messages.processed`    |                                 |
| `openclaw.message.queued`     | `counters.messages.queued`       |                                 |
| `openclaw.webhook.received`   | `counters.webhooks.received`     |                                 |
| `openclaw.webhook.error`      | `counters.webhooks.errors`       |                                 |
| `openclaw.queue.lane.enqueue` | `counters.lanes.enqueue`         |                                 |
| `openclaw.queue.lane.dequeue` | `counters.lanes.dequeue`         |                                 |
| `openclaw.session.state`      | `counters.sessions_state.*`      | `openclaw.state`                |
| `openclaw.session.stuck`      | `counters.sessions_stuck`        |                                 |
| `openclaw.run.attempt`        | `counters.run_attempts`          |                                 |

#### Histograms (from OTLP `histogram` metrics)

| OTLP metric name                | Stored as                   |
| -------------------------------- | --------------------------- |
| `openclaw.run.duration_ms`       | `histograms.run_duration_ms`       |
| `openclaw.message.duration_ms`   | `histograms.message_duration_ms`   |
| `openclaw.queue.depth`           | `histograms.queue_depth`           |
| `openclaw.queue.wait_ms`         | `histograms.queue_wait_ms`         |
| `openclaw.context.tokens`        | `histograms.context_tokens`        |
| `openclaw.webhook.duration_ms`   | `histograms.webhook_duration_ms`   |
| `openclaw.session.stuck_age_ms`  | `histograms.session_stuck_age_ms`  |

Each histogram stores `{count, sum, min, max}`. Per-agent histograms are
nested under `histograms.by_agent.<agent_name>.<key>`.

#### Session Spans (from OTLP traces)

Spans named `openclaw.model.usage` are tracked per session. Fields extracted:

- `session_id`, `agent`, `model`, `provider`
- Per-turn token breakdown (input, output, cache_read, cache_write, total)
- Duration, timestamp, cumulative turn count

Up to 200 sessions are retained (oldest evicted).

### Source 2: Mycelium Backend Metrics

The collector polls `GET /api/metrics` on the FastAPI backend every 30 seconds.
The backend maintains its own in-process metrics store
(`fastapi-backend/app/services/metrics.py`).

#### Backend Counters

| Namespace    | Keys                                                             |
| ------------ | ---------------------------------------------------------------- |
| `embeddings` | `computed`, `by_source.*`, `estimated_tokens`, `estimated_cost_avoided_usd` |
| `llm`        | `calls`, `by_operation.*`, `by_model.*`, `input_tokens`, `output_tokens`, `cost_usd`, `errors` |
| `indexer`    | `runs`, `files_indexed`, `files_skipped`, `files_pruned`, `errors`, `by_target.*` |
| `memory`     | `writes`, `writes.*`, `writes_embedded`, `searches`, `search_hits`, `search_misses`, `results_returned` |
| `synthesis`  | `runs`, `errors`, `briefings`, `cache_hits`, `cache_misses`      |
| `knowledge`  | `ingestions`, `concepts_extracted`, `relations_extracted`, `errors`, `queries`, `query_hits`, `query_misses`, `results_returned`, `queries.*` (by type) |
| `coordination` | `sessions`, `rounds`, `consensus_reached`, `consensus_failed`, `timeouts` |

#### Backend Histograms

| Histogram name                      | Unit |
| ----------------------------------- | ---- |
| `embeddings.latency_ms`             | ms   |
| `llm.latency_ms`                    | ms   |
| `llm.latency_ms.<operation>`        | ms   |
| `indexer.duration_ms`               | ms   |
| `memory.search_latency_ms`          | ms   |
| `synthesis.duration_ms`             | ms   |
| `synthesis.memories_since_last`     | count |
| `knowledge.ingestion_duration_ms`   | ms   |
| `knowledge.query_latency_ms`        | ms   |
| `coordination.round_duration_ms`    | ms   |
| `coordination.session_duration_ms`  | ms   |

## Display Panels

`mycelium metrics show` renders the following Rich tables:

1. **OpenClaw Agent Activity** — token totals, cost, message count, histograms
   (run/msg duration, queue depth/wait, context window), webhook and
   stuck-session stats, by-model breakdowns.

2. **Cost Savings (OpenClaw + Mycelium)** — local embedding counts and estimated
   API cost avoided, indexer file stats, prompt cache hit ratio, and estimated
   cache savings.

3. **Mycelium LLM Usage (backend)** — backend LLM calls, tokens, cost, latency
   by operation and model; knowledge graph, synthesis, and memory stats.

4. **Mycelium Data Reuse** — memory search hit/miss rates and results returned,
   synthesis briefing cache stats, knowledge graph query stats by type.

5. **IOC/CFN Coordination** — negotiation session counts, rounds, consensus
   success/failure rates, timeouts, and timing histograms.

6. **OpenClaw Agents** — per-agent token breakdown, session/turn counts, cost,
   average run duration, and workspace size.

7. **OpenClaw Recent Sessions** — last 20 OTLP session spans with agent, model,
   turns, tokens, and timestamp.

8. **Workspace Files** (opt-in via `--workspace`) — per-file size breakdown of
   each agent's `~/.openclaw` workspace directory.

## Pricing Data

All pricing lives in a single generated file:

```
mycelium-cli/src/mycelium/data/pricing.json
```

This file is consumed by both the CLI (prompt cache savings calculations) and
the backend (embedding cost avoidance baseline). It is **not hand-edited** —
run the update script to regenerate it from litellm's `model_cost` map:

```bash
pnpm run update:pricing          # from either mycelium-cli/ or fastapi-backend/
```

The script (`scripts/update-pricing.py`) runs in the backend's `uv`
environment (where litellm is installed) and:

1. Iterates a `TRACKED_MODELS` list of substring patterns (e.g. `"claude-sonnet-4"`,
   `"gpt-4o"`) and finds the best matching litellm entry
2. Extracts `input_cost_per_token` and computes `cache_discount` from
   `cache_read_input_token_cost` (falling back to 90% if no cache pricing)
3. Extracts the `text-embedding-3-small` price for the embedding baseline
4. Writes `pricing.json` and prints a diff of any changes

### Prompt Cache Savings

The **Cost Savings** panel estimates how much money prompt caching saved:

```
savings = cache_read_tokens × input_price_per_token × cache_discount
```

The model is auto-detected from OTLP `tokens.by_model` data (whichever model
has the most total tokens). Pricing is matched by substring against the
`models` array in `pricing.json`.

**Fallback**: if no model matches, a conservative Haiku-class estimate is used
($0.80/MTok input, 90% cache discount). The `"pricing basis"` row in the CLI
output shows "unknown model" when the fallback is used — add the new pattern
to `TRACKED_MODELS` in `scripts/update-pricing.py` and re-run.

### Local Embedding Cost Avoidance

The backend estimates how much running embeddings locally (via
`sentence-transformers/all-MiniLM-L6-v2`) saves versus calling a cloud
embedding API. It loads the `text-embedding-3-small` input price from
`pricing.json` at startup (`embedding_baseline.input_per_token`).

To change the comparison target model, edit `EMBEDDING_MODEL` in
`scripts/update-pricing.py` and re-run.

### OpenClaw-Reported Cost

The `"Cost (openclaw)"` line comes directly from the `openclaw.cost.usd` OTLP
metric emitted by the OpenClaw gateway. This value is controlled by OpenClaw
and is not calculated by Mycelium. We display it as-is.

## Schema Evolution

When new counter or histogram keys are added to the collector, old
`metrics.json` files may lack them. On startup, the collector uses a
`_deep_merge` strategy: it loads existing data into the default structure,
preserving new keys that only exist in the defaults. This prevents `KeyError`
crashes when loading older data files.

If a breaking schema change is made (e.g. restructuring a nested dict),
users can run `mycelium metrics reset` to start fresh.

## Key Source Files

| File | Role |
| ---- | ---- |
| `mycelium-cli/src/mycelium/commands/metrics.py`  | CLI commands, display rendering, pricing lookup |
| `mycelium-cli/src/mycelium/data/pricing.json`    | Generated model and embedding pricing data |
| `mycelium-cli/src/mycelium/collector.py`          | OTLP HTTP receiver, MetricsStore, backend poller |
| `mycelium-cli/src/mycelium/collector_main.py`     | Entrypoint for background collector process |
| `fastapi-backend/app/services/metrics.py`         | Backend in-process metrics store |
| `fastapi-backend/app/main.py`                     | `GET /api/metrics` endpoint |
| `scripts/update-pricing.py`                       | Generates pricing.json from litellm |

## Metrics Roadmap

The following areas have working code paths but are **not yet instrumented**.
Prioritised by effort and value.

### Recently Implemented

- **Coordination / Negotiation** (`services/coordination.py`) ✓
  Sessions, rounds, consensus success/failure, timeouts, round and session
  duration histograms. Instrumented in `_run_cfn_negotiation`, `_cfn_decide_round`,
  and `_finish_cfn`.

- **Knowledge graph queries** (`knowledge/service.py`) ✓
  Query counts by type (neighbor, path, concept), hit/miss rates, results
  returned, and latency. Instrumented in `query_graph_store`.

- **Synthesis data reuse** (`routes/rooms.py`) ✓
  Briefing requests, cache hits/misses, and memories-since-last-synthesis
  histogram. Instrumented in the briefing endpoint.

- **Memory search reuse** (`routes/memory.py`) ✓
  Search hit/miss rates and total results returned. Instrumented in
  `search_memories`.

### Tier 1 — Straightforward (Mycelium-only)

- **Session join / leave** (`routes/sessions.py`)
  Simple activity counters: joins, leaves, active sessions.

### Tier 2 — Moderate effort (Mycelium-only)

- **Cognition engine endpoints** (`routes/cognition_engine.py`)
  Endpoint-level request count and duration for extraction and evidence
  endpoints. The LLM calls inside are already tracked; this adds the
  outer request envelope.

- **CFN proxy** (`routes/cfn_proxy.py`)
  Outbound memory-provider call latency, errors, and status codes.
  Shows IoC integration health from Mycelium's perspective.

- **Evidence gathering LLM calls** (`agents/evidence_gathering/llm_clients.py`)
  Currently uses Azure OpenAI directly with its own counter but does
  not feed into the metrics system. Bridge into `record_llm_call`.

### Tier 3 — Requires IoC owner coordination

- **IoC service health** — instrument Mycelium's outbound REST calls
  to `:9000` and `:9002`. Track latency, errors, and availability.
  For deeper metrics IoC owners would need to expose OTLP or a
  `/metrics` endpoint.

- **Management plane registration** — track startup registration
  success/failure/retry when `--ioc` is enabled.

### Not yet implementable (stubbed / planned)

These exist in ARCHITECTURE.md or as stubs — metrics will follow once
the features are wired up:

- `/api/semantic-negotiation` endpoint (stub in `cognition_engine.py`)
- `get_llm_provider()` in `agents/llm_provider.py` (defined but unused)
- Memory + agent query strategies in `options_generation.py` (mocks)
- Multi-device Matrix transport metrics

## Periodic Maintenance Checklist

- [ ] **Pricing update** — run `pnpm run update:pricing` from either package
      to regenerate `pricing.json` from litellm. Do this when litellm is
      updated or when provider pricing changes. The script prints a diff.
- [ ] **New models** — if a new model isn't matched (the `"pricing basis"` row
      says "unknown model"), add the substring pattern to `TRACKED_MODELS` in
      `scripts/update-pricing.py` and re-run.
- [ ] **New OpenClaw metrics** — if OpenClaw adds new OTLP metrics, add
      handling in `collector.py` `_process_metric` and display in
      `commands/metrics.py`.
- [ ] **New backend operations** — if new LLM-calling or embedding code is
      added to the backend, instrument it with calls to `record_llm_call`,
      `record_embedding`, etc.
- [ ] **Session cap** — the collector retains up to 200 sessions
      (`_MAX_SESSIONS`). Increase if usage grows significantly.
