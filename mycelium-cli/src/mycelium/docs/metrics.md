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
┌──────────────┐   GET /api/observability      │  │  (in-memory) │  │
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

The backend URL for polling defaults to `server.api_url` from the Mycelium
config (typically `http://localhost:8000`). Override with `--backend-url`
on `mycelium metrics collect` or via the `MYCELIUM_API_URL` environment
variable.

## CLI Commands

| Command                   | Description                                      |
| ------------------------- | ------------------------------------------------ |
| `mycelium metrics status` | Health check: deps, collector process, data file, OTEL config, model cost |
| `mycelium metrics collect`| Start the OTLP receiver (background by default; `--fg` for foreground, `--backend-url` to override backend) |
| `mycelium metrics stop`   | Stop the background collector                    |
| `mycelium metrics reset`  | Delete `~/.mycelium/metrics.json`                |
| `mycelium metrics update-pricing` | Fetch latest LLM pricing from LiteLLM API and write to `~/.mycelium/pricing.json` |
| `mycelium metrics update-pricing --add pat:key` | Also fetch pricing for a manually specified model (repeatable) |
| `mycelium metrics show`   | Render collected data as Rich tables              |
| `mycelium metrics show --json` | Dump raw JSON for scripting                  |
| `mycelium metrics show --workspace` | Include per-file workspace breakdowns   |
| `mycelium metrics show --include-heartbeat` | Include OpenClaw `heartbeat` channel tokens in totals (excluded by default) |

## Files Created

| Path                            | Purpose                              |
| ------------------------------- | ------------------------------------ |
| `~/.mycelium/metrics.json`      | Aggregated metrics (counters, histograms, sessions, backend snapshot) |
| `~/.mycelium/pricing.json`      | User-local pricing cache (written by `update-pricing`) |
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

The collector polls `GET /api/observability` on the FastAPI backend every 30 seconds
(URL resolved from `server.api_url` in the Mycelium config, overridable with
`--backend-url`). The backend maintains its own in-process metrics store
(`fastapi-backend/app/services/metrics.py`).

#### Backend Counters

| Namespace    | Keys                                                             |
| ------------ | ---------------------------------------------------------------- |
| `embeddings` | `computed`, `by_source.*`, `estimated_tokens`                    |
| `llm`        | `calls`, `by_operation.*`, `by_model.*`, `input_tokens`, `output_tokens`, `cost_usd`, `errors` |
| `indexer`    | `runs`, `files_indexed`, `files_skipped`, `files_pruned`, `errors`, `by_target.*` |
| `memory`     | `writes`, `writes.*`, `writes_embedded`, `searches`, `search_hits`, `search_misses`, `results_returned` |
| `synthesis`  | `runs`, `errors`, `briefings`, `cache_hits`, `cache_misses`      |
| `knowledge`  | `ingestions`, `concepts_extracted`, `relations_extracted`, `estimated_input_tokens`, `errors`, `queries`, `queries.*` (by type: neighbour, path, concept, semantic), `query_hits`, `query_misses`, `query_errors`, `results_returned`, `cache_hits` |
| `coordination` | `sessions_started`, `sessions_completed`, `rounds`, `by_room.*`, `consensus_reached`, `outcome.*` (success, failure) |
| `cfn`        | `calls`, `calls.<service>`, `calls.<service>.<operation>`, `errors`, `errors.<service>`, `status.<code>` |
| `cfn_llm`    | `calls`, `input_tokens`, `output_tokens`, `cached_tokens`, `total_tokens`, `by_pipeline.*`, `by_llm_operation.*`, `by_room.*` |

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
| `knowledge.estimated_input_tokens`  | count |
| `knowledge.query_latency_ms`        | ms   |
| `coordination.round_duration_ms`    | ms   |
| `coordination.session_participants` | count |
| `coordination.participants`         | count |
| `coordination.rounds_to_completion` | count |
| `coordination.time_to_completion_ms`| ms   |
| `coordination.rounds_to_consensus`  | count |
| `coordination.time_to_consensus_ms` | ms   |
| `cfn.latency_ms`                    | ms   |
| `cfn.latency_ms.<service>`          | ms   |
| `cfn_llm.latency_ms`               | ms   |

## Display Panels

`mycelium metrics show` renders panels grouped by data source, in this order:
OpenClaw → Mycelium backend → CFN → opt-in.

### OpenClaw (OTLP)

1. **OpenClaw Agent Activity** — token totals (excluding the `heartbeat`
   background channel by default), cost, message count, histograms
   (run/msg duration, queue depth/wait, context window), webhook and
   stuck-session stats, by-model breakdowns. The heartbeat share of total
   tokens is shown as a separate dimmed row so its contribution is visible
   without dominating the headline number. Pass `--include-heartbeat` to
   fold it back into all OpenClaw totals.

2. **OpenClaw Cache Efficiency** — diagnostic-only panel showing the LLM
   provider's prompt cache behaviour: hit rate, read/write/uncached input
   token volumes, and a "reads per write" ratio (higher = more reuse before
   the cache entry is rewritten). Intentionally has no dollar figure: prompt
   caching is a feature of the LLM provider (e.g. Anthropic), not Mycelium,
   so attributing the saving to us would be misleading.

3. **OpenClaw Agents** — per-agent token breakdown, session/turn counts, cost,
   average run duration, and workspace size. Plus a "Tokens by Channel"
   sub-table that breaks tokens out by `openclaw.channel` (heartbeat,
   matrix, webhook, etc.) — so heartbeat traffic is always visible here
   even when excluded from headline panels.

4. **OpenClaw Recent Sessions** — last 20 OTLP session spans with agent, model,
   turns, tokens, and timestamp.

### Mycelium backend (polled)

5. **Local Embeddings & Indexer** — operational metrics for local embedding
   computation (counts, latency, by-source breakdown) and the indexer's
   skip-unchanged file stats (skip rate, files indexed/pruned, run duration).

6. **Mycelium Backend LLM Usage** — backend LLM calls, tokens, cost, latency
   by operation and model; knowledge graph, synthesis, and memory stats.

7. **Mycelium Data Reuse** — memory search hit/miss rates and results returned,
   synthesis briefing cache stats, knowledge graph query stats by type.

### CFN (via backend)

8. **CFN Coordination** — negotiation session counts, rounds, consensus
   success/failure rates, timeouts, and timing histograms.

9. **CFN LLM Token Usage** — actual LLM token usage reported by the cognition
   engines via the `_usage` response field. Shows total calls, prompt/completion
   tokens, latency, and breakdowns by pipeline, operation, and room.

10. **CFN Transport Health** — outbound HTTP call counts to CFN node and mgmt
    plane, error rates, latency histograms, per-operation and per-status-code
    breakdowns.

11. **CFN /metrics Scrape** — opt-in. Direct HTTP-RED rollup
    (requests, errors, latency) of any CFN service that exposes a Prometheus
    metrics endpoint via `prometheus-fastapi-instrumentator`. Today that's
    `ioc-cfn-mgmt-backend-svc` (port 9000), `ioc-knowledge-memory`, and
    `ioc-cognition-fabric-node-svc` (port 9002, at `/api/internal/metrics`).

    Configured under `[[metrics.scrape]]` in `~/.mycelium/config.toml`:

    ```toml
    [[metrics.scrape]]
    name = "cfn-mgmt"
    url  = "http://localhost:9000/metrics"
    kind = "http_red"

    [[metrics.scrape]]
    name = "knowledge-memory"
    url  = "http://localhost:9001/metrics"
    kind = "http_red"

    [[metrics.scrape]]
    name = "cfn-node"
    url  = "http://localhost:9002/api/internal/metrics"
    kind = "http_red"
    ```

    Targets are polled on the same 30-second cadence as the backend `/api/observability`
    poll, results are stored under the top-level `scrape` key in
    `~/.mycelium/metrics.json`, and unreachable targets are surfaced as
    `[degraded]` rather than dropped silently. Restart `mycelium metrics
    collect` after editing config so the new targets are picked up.

    The complementary panel is #10 (CFN Transport Health), which measures
    *outbound* CFN calls *as observed by the Mycelium backend*. Panel #11
    measures the *inbound* HTTP surface of the CFN service itself. The two
    will not generally agree (different vantage points; #10 sees calls from
    every client, not just Mycelium) but large divergence is itself a useful
    signal.

### Opt-in

12. **Workspace Files** (via `--workspace`) — per-file size breakdown of
    each agent's `~/.openclaw` workspace directory.

## Pricing Data

Pricing data is resolved in this order:

1. **User-local cache** — `~/.mycelium/pricing.json` (written by `mycelium metrics update-pricing`)
2. **Bundled default** — `mycelium-cli/src/mycelium/data/pricing.json` (shipped with the CLI package)

The first file found with a non-empty `models` list wins. The `generated_at`
timestamp and source are shown in the footer of the cost table.

### Updating Pricing at Runtime

```bash
mycelium metrics update-pricing
```

This fetches current pricing from the **LiteLLM Model Catalog API**
(`api.litellm.ai/model_catalog/{model_id}`) — a free public API that refreshes
from LiteLLM's GitHub every 60 seconds. No new dependencies are needed (uses
the CLI's existing `httpx` client).

Models are sourced from three places:

1. **Built-in tracked models** (14 common Anthropic/OpenAI models) — always fetched
2. **Auto-discovered models** — the command reads `~/.mycelium/metrics.json` and
   finds model names (from OTLP `by_model` and backend `llm.by_model.*`) that
   aren't covered by the built-in list. Provider prefixes like `bedrock/global.`
   and `anthropic.` are stripped to derive a LiteLLM catalog key.
3. **Manually added models** via `--add` — for models not yet in collected metrics:

```bash
mycelium metrics update-pricing --add "deepseek-v3:deepseek-chat"
mycelium metrics update-pricing --add "mistral-large:mistral-large-latest"
```

The `--add` format is `pattern:litellm_key` (or just `litellm_key` if both
are the same). The flag is repeatable.

### Updating Pricing at Build Time

The bundled `pricing.json` is regenerated by:

```bash
cd fastapi-backend && uv run python ../scripts/update-pricing.py
```

This script runs in the backend's `uv` environment (where litellm is installed)
and reads `litellm.model_cost` directly. It serves as the fallback when users
haven't run `update-pricing`.

### OpenClaw Model Configuration for Cost Tracking

OpenClaw calculates `openclaw.cost.usd` from the `cost` block on each model
entry in `~/.openclaw/openclaw.json`. If these are all zero (the default from
`openclaw configure`), the OTLP cost metric will always be $0 — even when
token counts are correct.

Two model-level settings are required for full metrics accuracy:

| Setting | Purpose | Default |
| ------- | ------- | ------- |
| `cost.{input,output,cacheRead,cacheWrite}` | USD per 1M tokens, used by OpenClaw to compute `openclaw.cost.usd` | `0` (from `openclaw configure`) |
| `compat.supportsUsageInStreaming` | Tells OpenClaw to request token usage in streamed responses | `false` |

**Automated fix:**

```bash
mycelium adapter add openclaw --step=otel
```

This patches `openclaw.json` with correct per-1M-token costs (converted from
Mycelium's pricing data) and adds the `compat` flag for any model that's
missing it.  It also configures the diagnostics-otel plugin if not already
enabled.

**Manual fix** — add to each model entry in `~/.openclaw/openclaw.json`:

```json5
{
  "id": "bedrock/global.anthropic.claude-haiku-4-5-20251001-v1:0",
  // ...
  "cost": {
    "input": 1,       // $/1M tokens for prompt input
    "output": 5,      // $/1M tokens for completion output
    "cacheRead": 0.1, // $/1M tokens for cached input reads
    "cacheWrite": 1.25 // $/1M tokens for cache writes
  },
  "compat": {
    "supportsUsageInStreaming": true
  }
}
```

`mycelium metrics status` warns when it detects zero-cost models or missing
compat flags.

### Cost Estimation

`mycelium metrics show cost` compiles costs from three sources:

| Source | Method | Notes |
| ------ | ------ | ----- |
| **OpenClaw Agents** | Provider-reported via `openclaw.cost.usd` OTLP metric | Displayed as-is; $0.00 if model cost config is missing or gateway was restarted (counter resets) |
| **CFN Engines** | Estimated from actual engine-reported token counts × `pricing.json` rates | Token counts come from the CFN `_usage` response, not estimated |
| **Mycelium LLM** | Provider-reported `cost_usd` from litellm's `response_cost` | Falls back to estimation if provider cost unavailable |

### Per-Model Pricing Fields

`pricing.json` carries these fields per model:

| Field                  | Meaning                                                                 |
| ---------------------- | ----------------------------------------------------------------------- |
| `input_per_token`      | Price per input token                                                   |
| `output_per_token`     | Price per output token                                                  |
| `cache_discount`       | Fraction off `input_per_token` for cache reads (e.g. 0.90 = 90% off)    |
| `cache_write_premium`  | Fraction more than `input_per_token` for cache writes (e.g. 0.25 = 1.25×) |

Pricing is matched by substring against the `models` array. The model string
comes from the Mycelium config (`llm.model`).

**Fallback**: if no model matches, a conservative default is used ($0.80/MTok
input, $3.20/MTok output, 90% cache discount, 25% write premium). Add the new
substring pattern to `TRACKED_MODELS` in `scripts/update-pricing.py` and
re-run.

### Prompt Cache Pricing (reference only)

The Cache Efficiency panel shows the LLM provider's prompt cache behaviour:
hit rate, read/write/uncached input token volumes, and reads-per-write ratio.
It intentionally has no dollar figure — prompt caching is a feature of the LLM
provider (e.g. Anthropic), not Mycelium.

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
| `fastapi-backend/app/main.py`                     | `GET /api/observability` endpoint |
| `scripts/update-pricing.py`                       | Generates pricing.json from litellm |

## Metrics Roadmap

The following areas have working code paths but are **not yet instrumented**.
Prioritised by effort and value.

### Recently Implemented

- **Coordination / Negotiation** (`services/coordination.py`) ✓
  Sessions started/completed, rounds, consensus outcome (success/failure),
  per-room breakdowns, round duration, time-to-completion and
  time-to-consensus histograms. Instrumented in `_run_cfn_negotiation`,
  `_cfn_decide_round`, and `_finish_cfn`.

- **Knowledge graph queries** (`services/cfn_knowledge.py`) ✓
  Query counts by type (neighbour, path, concept, semantic), hit/miss/error
  rates, results returned, and latency. Instrumented in
  `query_shared_memories`, `get_concepts_by_ids`, `get_concept_neighbors`,
  and `get_graph_paths`.

- **Knowledge ingestion** (`routes/knowledge.py`) ✓
  Ingestion counts, duration, and error tracking for the CFN-proxied
  knowledge extraction pipeline.

- **Synthesis data reuse** (`routes/rooms.py`) ✓
  Briefing requests, cache hits/misses, and memories-since-last-synthesis
  histogram. Instrumented in the briefing endpoint.

- **Memory search reuse** (`routes/memory.py`) ✓
  Search hit/miss rates and total results returned. Instrumented in
  `search_memories`.

- **CFN outbound call health** (`services/cfn_knowledge.py`, `services/cfn_negotiation.py`, `routes/rooms.py`, `routes/sessions.py`, `main.py`) ✓
  Transport-level metrics for all outbound HTTP calls to CFN node (:9002)
  and mgmt plane (:9000). Tracks call counts, error rates, status codes,
  and latency histograms per service and operation. Estimated input tokens
  (cl100k_base) recorded for knowledge ingestion payloads.

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

- **CFN provider-reported cost** — CFN engines now report actual LLM token
  counts via the `_usage` response field (see panel 9), but not dollar cost.
  The cost table estimates CFN cost from tokens × `pricing.json` rates. To
  get provider-reported cost, the `UsageAccumulator` in
  `common/metrics/usage_callback.py` would need to extract
  `response._hidden_params["response_cost"]` from litellm and propagate it
  through the `_usage` snapshot.

### Not yet implementable (stubbed / planned)

These exist in ARCHITECTURE.md or as stubs — metrics will follow once
the features are wired up:

- `get_llm_provider()` in `agents/llm_provider.py` (defined but unused)
- Multi-device Matrix transport metrics

## Periodic Maintenance Checklist

- [ ] **OpenClaw model config** — run `mycelium metrics status` and check for
      zero-cost or missing-compat warnings. Fix with
      `mycelium adapter add openclaw --step=otel` or manually in
      `~/.openclaw/openclaw.json`. Required after adding new models or
      re-running `openclaw configure`.
- [ ] **Pricing update** — run `mycelium metrics update-pricing` to fetch the
      latest pricing from the LiteLLM API and write `~/.mycelium/pricing.json`.
      Any models found in collected metrics that aren't in the built-in list are
      auto-discovered and priced. The `generated_at` date appears in the
      `mycelium metrics show cost` footer.
- [ ] **Bundled pricing refresh** — run `cd fastapi-backend && uv run python ../scripts/update-pricing.py`
      to update the bundled `data/pricing.json` shipped with the CLI package.
      This is the fallback when users haven't run `update-pricing`.
- [ ] **New models** — if a new model isn't matched (the `"pricing basis"` row
      says "unknown model"), either:
      - Run `mycelium metrics update-pricing` (auto-discovers from metrics), or
      - Use `--add pattern:litellm_key` for models not yet in collected metrics, or
      - Add the substring pattern to `_TRACKED_MODELS` in `metrics.py` for
        permanent built-in tracking.
- [ ] **New OpenClaw metrics** — if OpenClaw adds new OTLP metrics, add
      handling in `collector.py` `_process_metric` and display in
      `commands/metrics.py`.
- [ ] **New backend operations** — if new LLM-calling or embedding code is
      added to the backend, instrument it with calls to `record_llm_call`,
      `record_embedding`, etc.
- [ ] **Session cap** — the collector retains up to 200 sessions
      (`_MAX_SESSIONS`). Increase if usage grows significantly.
