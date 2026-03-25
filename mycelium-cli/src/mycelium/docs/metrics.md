# Metrics System

The Mycelium metrics pipeline collects, aggregates, and displays telemetry from
two sources — **OpenClaw** (via OTLP) and the **Mycelium FastAPI backend** (via
HTTP polling) — and writes it to a single JSON file for the CLI to render.

## Architecture

```
┌──────────────┐   OTLP/HTTP protobuf   ┌────────────────────┐
│   OpenClaw   │ ──────────────────────▶ │  Metrics Collector │
│   Gateway    │   /v1/metrics           │  (localhost:4318)  │
│              │   /v1/traces            │                    │
└──────────────┘                         │  ┌──────────────┐  │
                                         │  │ MetricsStore │  │
┌──────────────┐   GET /api/metrics      │  │  (in-memory) │  │
│  Mycelium    │ ◀ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─  │  └──────┬───────┘  │
│  Backend     │  (polled every 30s)     │         │ flush     │
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
| `memory`     | `writes`, `writes.*`, `writes_embedded`, `searches`              |
| `synthesis`  | `runs`, `errors`                                                 |
| `knowledge`  | `ingestions`, `concepts_extracted`, `relations_extracted`, `errors` |

#### Backend Histograms

| Histogram name                      | Unit |
| ----------------------------------- | ---- |
| `embeddings.latency_ms`             | ms   |
| `llm.latency_ms`                    | ms   |
| `llm.latency_ms.<operation>`        | ms   |
| `indexer.duration_ms`               | ms   |
| `memory.search_latency_ms`          | ms   |
| `synthesis.duration_ms`             | ms   |
| `knowledge.ingestion_duration_ms`   | ms   |

## Display Panels

`mycelium metrics show` renders the following Rich tables:

1. **Overall** — token totals, cost, message count, histograms (run/msg
   duration, queue depth/wait, context window), webhook and stuck-session
   stats, by-model breakdowns.

2. **Cost Savings** — local embedding counts and estimated API cost avoided,
   indexer file stats, prompt cache hit ratio, and estimated cache savings.

3. **Mycelium LLM Usage (backend)** — backend LLM calls, tokens, cost, latency
   by operation and model; knowledge graph, synthesis, and memory stats.

4. **Agents** — per-agent token breakdown, session/turn counts, cost, average
   run duration, and workspace size.

5. **Recent Sessions** — last 20 OTLP session spans with agent, model, turns,
   tokens, and timestamp.

6. **Workspace Files** (opt-in via `--workspace`) — per-file size breakdown of
   each agent's `~/.openclaw` workspace directory.

## Pricing Data (Requires Periodic Update)

### Prompt Cache Savings

The **Cost Savings** panel estimates how much money prompt caching saved. This
is calculated as:

```
savings = cache_read_tokens × input_price_per_token × cache_discount
```

The model is auto-detected from the OTLP `tokens.by_model` data (whichever
model has the most total tokens). Pricing is matched by substring against a
hardcoded table in `mycelium-cli/src/mycelium/commands/metrics.py`:

```python
_MODEL_PRICING: list[tuple[str, dict]] = [
    # (substring pattern, {input: $/token, cache_discount: fraction})
    ("claude-sonnet-4",   {"input": 3.00 / 1e6, "cache_discount": 0.90}),
    ("claude-3-7-sonnet", {"input": 3.00 / 1e6, "cache_discount": 0.90}),
    ("claude-3-5-sonnet", {"input": 3.00 / 1e6, "cache_discount": 0.90}),
    ("claude-3-5-haiku",  {"input": 0.80 / 1e6, "cache_discount": 0.90}),
    ("claude-haiku-4",    {"input": 0.80 / 1e6, "cache_discount": 0.90}),
    ("claude-3-haiku",    {"input": 0.25 / 1e6, "cache_discount": 0.90}),
    ("claude-3-opus",     {"input": 15.0 / 1e6, "cache_discount": 0.90}),
    ("claude-opus-4",     {"input": 15.0 / 1e6, "cache_discount": 0.90}),
    ("gpt-4o-mini",       {"input": 0.15 / 1e6, "cache_discount": 0.50}),
    ("gpt-4o",            {"input": 2.50 / 1e6, "cache_discount": 0.50}),
    ("gpt-4-turbo",       {"input": 10.0 / 1e6, "cache_discount": 0.50}),
    ("o3-mini",           {"input": 1.10 / 1e6, "cache_discount": 0.50}),
    ("o3",                {"input": 10.0 / 1e6, "cache_discount": 0.50}),
    ("o4-mini",           {"input": 1.10 / 1e6, "cache_discount": 0.50}),
]
```

**Fallback**: if no model matches, a conservative Haiku-class estimate is used
($0.80/MTok input, 90% cache discount).

**When to update**: whenever Anthropic or OpenAI change their per-token pricing,
or when a new model is added that doesn't match an existing substring pattern.
Check the `"pricing basis"` row in the Cost Savings output — if it says
"unknown model", the table needs a new entry.

Sources:
- Anthropic: https://docs.anthropic.com/en/docs/about-claude/models
- OpenAI: https://openai.com/api/pricing/
- AWS Bedrock: https://aws.amazon.com/bedrock/pricing/

### Local Embedding Cost Avoidance

The backend estimates how much running embeddings locally (via
`sentence-transformers/all-MiniLM-L6-v2`) saves versus calling a cloud
embedding API. This uses a hardcoded constant in
`fastapi-backend/app/services/metrics.py`:

```python
_OPENAI_EMBEDDING_PRICE_PER_TOKEN = 0.02 / 1_000_000  # text-embedding-3-small
_AVG_TOKENS_PER_EMBEDDING = 60
```

**When to update**: if OpenAI changes `text-embedding-3-small` pricing, or if
the comparison target changes to a different embedding model/provider.

Source: https://openai.com/api/pricing/

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
| `mycelium-cli/src/mycelium/commands/metrics.py` | CLI commands, display rendering, pricing table |
| `mycelium-cli/src/mycelium/collector.py`         | OTLP HTTP receiver, MetricsStore, backend poller |
| `mycelium-cli/src/mycelium/collector_main.py`    | Entrypoint for background collector process |
| `fastapi-backend/app/services/metrics.py`        | Backend in-process metrics store |
| `fastapi-backend/app/main.py`                    | `GET /api/metrics` endpoint |

## Periodic Maintenance Checklist

- [ ] **Model pricing** — check that `_MODEL_PRICING` in `commands/metrics.py`
      matches current Anthropic/OpenAI/Bedrock pricing pages. Look for the
      `"pricing basis"` row in `mycelium metrics show` output showing
      "unknown model" as a signal.
- [ ] **Embedding pricing** — check that `_OPENAI_EMBEDDING_PRICE_PER_TOKEN` in
      `fastapi-backend/app/services/metrics.py` matches OpenAI's current
      `text-embedding-3-small` rate.
- [ ] **New OpenClaw metrics** — if OpenClaw adds new OTLP metrics, add
      handling in `collector.py` `_process_metric` and display in
      `commands/metrics.py`.
- [ ] **New backend operations** — if new LLM-calling or embedding code is
      added to the backend, instrument it with calls to `record_llm_call`,
      `record_embedding`, etc.
- [ ] **Session cap** — the collector retains up to 200 sessions
      (`_MAX_SESSIONS`). Increase if usage grows significantly.
