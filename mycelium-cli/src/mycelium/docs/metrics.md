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
│  (diagnostics│   /v1/logs              │  ┌──────────────┐  │
│  -otel  and  │                         │  │ MetricsStore │  │
│  deep-obs    │                         │  │  (in-memory) │  │
│  plugins)    │                         │  └──────┬───────┘  │
└──────────────┘                         │         │ flush    │
                                         │  ┌──────┴───────┐  │
┌──────────────┐   GET /api/observability │  │  TraceStore  │  │
│  Mycelium    │ ◀ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─   │  │  (SQLite)    │  │
│  Backend     │  (polled every 30s)     │  └──────┬───────┘  │
│  (FastAPI)   │                         └─────────┼──────────┘
│              │                                   ▼
│  GET /api/   │                   ┌─────────────────────────────────┐
│  traces/     │ ◀─reads─────────  │ $DATA_DIR/metrics/metrics.json  │
│  recent      │                   │ $DATA_DIR/metrics/traces.db     │
└──────────────┘                   └─────────────────────────────────┘
                                                   │
                                                   ▼
                                         ┌──────────────────┐
                                         │  mycelium        │
                                         │  metrics show    │
                                         └──────────────────┘
```

The backend URL for polling defaults to `server.api_url` from the Mycelium
config (typically `http://localhost:8000`). Override with `--backend-url`
in the Docker Compose command or via the `MYCELIUM_API_URL` environment
variable.

## Hub-and-Spoke Setup

In a multi-device deployment, spoke nodes run a **lightweight local collector**
for their own OpenClaw OTLP data and fetch Mycelium backend + CFN metrics from
the hub. `mycelium metrics show` merges both sources automatically.

The spoke collector also **forwards** every OTLP payload to the hub collector
(agent-to-gateway pattern), so the hub maintains a unified cross-host view
with per-host breakdowns (the "Spoke Sites" table and `--host` filter).

```
┌──────────────────────────────────┐        ┌──────────────────────────────────┐
│         Spoke Node               │        │          Hub Node                │
│                                  │        │                                  │
│  OpenClaw ─── OTLP ──▶ Local    │        │  Collector (:4318)               │
│  Gateway        Collector       │        │    ├─▶ MetricsStore              │
│                  (:4318,     ────┼─ OTLP ─┼──▶├─▶ TraceStore (by_host)     │
│                   no-backend)    │ forward │    └─▶ poll Backend + CFN scrape │
│                   │              │        │                                  │
│                   ▼              │        │  Backend (:8000)                 │
│            local metrics.json    │        │  CFN services                    │
│            (OpenClaw only)       │        └──────────────┬───────────────────┘
│                                  │                       │
│  mycelium metrics show ──────────┼── HTTP GET ──────────▶│
│   merges local OpenClaw          │  /collector/metrics    │
│   + hub backend/CFN data         │  (backend + CFN)       │
└──────────────────────────────────┘                       │
```

### Spoke Configuration

1. Set `collector_url` in the spoke's `~/.mycelium/config.toml`:

```toml
[metrics]
collector_url = "http://<hub-ip>:4318"
```

Or via environment variable:

```bash
export MYCELIUM_COLLECTOR_URL="http://<hub-ip>:4318"
```

2. Configure the OTLP plugins (the endpoint defaults to `localhost:4318`
for the local spoke collector):

```bash
mycelium adapter add openclaw --step=otel --step=deep-observability
```

3. Start the local spoke collector:

```bash
mycelium metrics collect          # daemonizes into the background
mycelium metrics collect -f       # or run in foreground (Ctrl+C to stop)
mycelium metrics stop             # stop the background collector
```

The collector runs in `--no-backend` mode: it accepts OpenClaw telemetry
pushes and writes to the local `metrics.json` but does **not** poll the
backend or scrape Prometheus targets. It automatically forwards OTLP
/v1/metrics and /v1/traces payloads to the hub's collector (the
`collector_url` from config) via fire-and-forget HTTP POSTs in background
threads. Logs are written to `$DATA_DIR/metrics/collector.log`.

### How it works

- `mycelium metrics show` on the spoke reads local OpenClaw data (counters,
  histograms, sessions) from the local `metrics.json`, then fetches backend
  and CFN data from the hub's `/collector/metrics` endpoint. The two are
  merged into a single view.
- `mycelium metrics status` probes both the hub collector (reachability)
  and the local collector (port check).
- The `collect` command is only available in spoke mode (when `collector_url`
  points to a remote host). On hub/local nodes, use `mycelium up --metrics`
  instead.
- **OTLP forwarding**: the spoke collector transparently forwards raw OTLP
  payloads to the hub, enabling the hub's `by_host` aggregation (Spoke Sites
  table, `--host` filter) and unified trace database. Forwarding failures
  are logged at debug level but never block local ingest — the spoke always
  stores data locally first.

## CLI Commands

| Command                   | Description                                      |
| ------------------------- | ------------------------------------------------ |
| `mycelium metrics status` | Health check: deps, collector process, data file, OTEL config, model cost |
| `mycelium metrics collect` | Start the spoke OTLP collector (background by default, `--foreground` for interactive) |
| `mycelium metrics stop`   | Stop the collector (spoke: background process, hub: Docker container) |
| `mycelium metrics reset`  | Delete collected metrics data                    |
| `mycelium metrics update-pricing` | Fetch latest LLM pricing from LiteLLM API |
| `mycelium metrics update-pricing --add pat:key` | Also fetch pricing for a manually specified model (repeatable) |
| `mycelium metrics show`   | Render collected data as Rich tables              |
| `mycelium metrics show --json` | Dump raw JSON for scripting                  |
| `mycelium metrics show --workspace` | Include per-file workspace breakdowns   |
| `mycelium metrics show --include-heartbeat` | Include OpenClaw `heartbeat` channel tokens in totals (excluded by default) |
| `mycelium up --metrics`   | Start the stack with the Dockerized OTLP collector (hub/local mode) |
| `mycelium adapter add openclaw --step=otel --step=deep-observability` | Configure both OTLP plugins in one command (see below) |
| `mycelium metrics traces …` | Query and pivot the trace spans collected in `traces.db` (see [Viewing Traces](#viewing-traces)) |

## Files Created

All metrics files live under `$MYCELIUM_DATA_DIR/metrics/` (default `~/.mycelium/metrics/`).
Set `MYCELIUM_DATA_DIR` to override the root.

| Path                              | Purpose                              |
| --------------------------------- | ------------------------------------ |
| `metrics/metrics.json`            | Aggregated metrics (counters, histograms, sessions, backend snapshot) |
| `metrics/traces.db`               | SQLite database of OTLP trace spans (7-day retention) |
| `metrics/pricing.json`            | User-local pricing cache (written by `update-pricing`) |
| `metrics/collector.pid`           | PID file for the background spoke collector |
| `metrics/collector.log`           | Log output from the background spoke collector |

`metrics.json` is atomically updated (write to `.tmp`, rename) on every OTLP
ingestion and on graceful shutdown.

`traces.db` is a WAL-mode SQLite database written by the `TraceStore`.
Spans older than 7 days are automatically purged hourly and at shutdown.

## What We Collect

### Source 1: OpenClaw OTLP Telemetry

The collector listens on `localhost:4318` and accepts standard OTLP/HTTP
protobuf payloads on `/v1/metrics`, `/v1/traces`, and `/v1/logs`. The
`/v1/logs` endpoint is acknowledged (200) but not stored — it exists so
the deep observability plugin doesn't get rejected for log payloads.

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

### Deep Observability Plugin

The `openclaw-deep-observability` plugin provides richer, hierarchical OTLP
traces compared to the built-in `diagnostics-otel` plugin. It emits
parent-child span trees with per-tool timing, LLM call isolation, and
session lifecycle spans.

The plugin works for **root agents** and **peer agents** (independent
OpenClaw sessions) — which is how Mycelium's agents are structured. It
does **not** emit traces for internal sub-agent calls within a single
OpenClaw session.

#### Setup

```bash
mycelium adapter add openclaw --step=otel --step=deep-observability
```

Both steps should be run together. `--step=otel` configures the built-in
`diagnostics-otel` plugin which emits the flat counters and histograms
that power `mycelium metrics show`. `--step=deep-observability` adds the
hierarchical trace spans stored in `traces.db`. Without `--step=otel`,
the OpenClaw panels in `mycelium metrics show` will have no data.

The `--step=deep-observability` portion:

1. Clones https://github.com/outshift-open/openclaw-deep-observability into
   `~/.mycelium/deep-observability-src/` (or updates it with `git pull`).
2. Runs `npm install && npm run build` in the `observability-plugin/` subdir.
3. Installs the built plugin via `openclaw plugins install <path> --force`.
   If a legacy symlink at `~/.openclaw/extensions/openclaw-deep-observability`
   from a prior `--link` install is present, it's removed first.
4. Adds the plugin to `plugins.allow` and `plugins.entries` in
   `~/.openclaw/openclaw.json` with the OTLP endpoint matching the
   collector port.
5. Patches model cost and `compat.supportsUsageInStreaming` settings.
6. Restarts the OpenClaw gateway to pick up the config.

The resulting `openclaw.json` plugin entry looks like:

```json
{
  "plugins": {
    "allow": ["openclaw-deep-observability"],
    "entries": {
      "openclaw-deep-observability": {
        "enabled": true,
        "config": {
          "endpoint": "http://localhost:4318",
          "protocol": "http",
          "traces": true,
          "metrics": true,
          "logs": false,
          "captureContent": false,
          "metricsIntervalMs": 5000
        }
      }
    }
  }
}
```

When running OpenClaw in a Docker container, the endpoint is automatically
set to `http://host.docker.internal:4318`.

The deep observability plugin and the built-in `diagnostics-otel` plugin
can run side by side. Both emit to the same collector. The deep plugin's
traces are richer (hierarchical spans) while `diagnostics-otel` provides
the flat counter/histogram metrics used by `mycelium metrics show`.

### Trace Storage (TraceStore)

Raw OTLP trace spans are persisted to `$DATA_DIR/metrics/traces.db` (SQLite,
WAL mode) by the `TraceStore` class in `collector.py`. This runs in
parallel with the `MetricsStore` — on every `/v1/traces` POST, the
collector feeds bytes to both stores.

**Schema:**

| Column           | Type  | Description                                     |
| ---------------- | ----- | ----------------------------------------------- |
| `trace_id`       | TEXT  | Hex trace ID                                    |
| `span_id`        | TEXT  | Hex span ID (primary key)                       |
| `parent_span_id` | TEXT  | Parent span ID (empty for root spans)           |
| `name`           | TEXT  | Span operation name                             |
| `kind`           | TEXT  | `internal`, `server`, `client`, `producer`, `consumer` |
| `service`        | TEXT  | `service.name` from the OTLP resource           |
| `start_time`     | TEXT  | ISO 8601 timestamp                              |
| `duration_ms`    | REAL  | Span duration in milliseconds                   |
| `status`         | TEXT  | `unset`, `ok`, or `error`                       |
| `status_message` | TEXT  | Error message when status is `error`            |
| `attributes`     | TEXT  | JSON-encoded span attributes                    |
| `created_at`     | TEXT  | Insertion timestamp (used for retention cleanup) |

**Retention:** Spans older than 7 days are deleted automatically
(checked hourly and at collector shutdown). The cleanup runs
`PRAGMA incremental_vacuum` to reclaim disk space.

**API access:** The FastAPI backend exposes `GET /api/observability/traces/recent?limit=100`
which reads `traces.db` directly and returns trace summaries with full span
trees for waterfall rendering. Each trace includes `root_span`, `agent`,
`duration_ms`, `span_count`, `has_error`, and the full `spans` array.

The backend also exposes `GET /api/observability/collector` which returns the
collector-written `metrics.json` contents (counters, histograms, sessions,
scrape) — excluding the `backend` key that duplicates `GET /api/observability`.

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
    `metrics/metrics.json`, and unreachable targets are surfaced as
    `[degraded]` rather than dropped silently. Restart the collector
    (`mycelium down && mycelium up --metrics`) after editing config so
    the new targets are picked up.

    The complementary panel is #10 (CFN Transport Health), which measures
    *outbound* CFN calls *as observed by the Mycelium backend*. Panel #11
    measures the *inbound* HTTP surface of the CFN service itself. The two
    will not generally agree (different vantage points; #10 sees calls from
    every client, not just Mycelium) but large divergence is itself a useful
    signal.

### Opt-in

12. **Workspace Files** (via `--workspace`) — per-file size breakdown of
    each agent's `~/.openclaw` workspace directory.

## Viewing Traces

`mycelium metrics show` rolls everything up into a few high-level panels;
`mycelium metrics traces …` lets you slice the raw spans in
`$DATA_DIR/metrics/traces.db` by every dimension the spans actually carry.

The deep-observability plugin annotates each span with rich identity and
behavior info, so you can pivot on:

| Pivot | Source field(s) | What it tells you |
|---|---|---|
| **Host** | `host` column | Which OpenClaw machine emitted the span |
| **Agent** | `openclaw.agent`, `gen_ai.agent.id`, `ioa_observe.entity.name` | Which agent did the work |
| **Room** | parsed from `gen_ai.conversation.id` / `openclaw.session.key` (`agent:<a>:<chan-kind>:<chan-type>:<room-id>`) | Matrix room id _or_ Mycelium room name — both are first-class |
| **Channel kind** | parsed from same key, plus `openclaw.channel` | `matrix` vs `mycelium-room` (lets you tell coordination spans from chat spans) |
| **Session** | `session.id`, `openclaw.session.key` | One conversation/turn lifecycle |
| **Model** | `gen_ai.request.model`, `gen_ai.response.model` | Which LLM was called |
| **Tool** | `openclaw.toolName`, `gen_ai.tool.name`, `openclaw.exec.exit_code` | Which tool was invoked and its exit code |
| **Outcome** | `openclaw.outcome` | `completed` / `failed` / etc. |
| **Status** | `status`, `status_message` columns | Span-level `ok` / `error` plus the message |
| **Latency** | `duration_ms` column | Span duration |
| **Trace tree** | `trace_id` + `parent_span_id` | Full parent → child call hierarchy |

### Subcommands

| Command | What it shows |
|---------|---------------|
| `mycelium metrics traces summary` | Total spans, errors, hosts, agents, rooms, channel kinds, models, tool calls, tokens, span p50/p95/p99 |
| `mycelium metrics traces by-host` | Group by source host (spans, errors, avg/p95 latency, tokens) |
| `mycelium metrics traces by-agent` | Group by agent |
| `mycelium metrics traces by-room` | Group by Matrix room id or Mycelium room name |
| `mycelium metrics traces by-channel` | Group by channel kind (`matrix`, `mycelium-room`, …) |
| `mycelium metrics traces by-model` | Group by LLM model |
| `mycelium metrics traces by-name` | Group by span name (`openclaw.agent.turn`, `openclaw.tool.execution`, …) |
| `mycelium metrics traces by-tool` | Group tool-call spans by tool name |
| `mycelium metrics traces errors` | Recent `status=error` spans with message |
| `mycelium metrics traces slow` | Slowest spans in the window |
| `mycelium metrics traces list` | Recent spans with the most useful columns inline |
| `mycelium metrics traces show <trace_id_or_span_id>` | Render one trace as a parent → child tree with model, tokens, tool name, exit code, and error message inlined per span. Pass `--events` to interleave any OTel span events (log-like records) under their parent spans. |
| `mycelium metrics traces show-attrs <span_id>` | Dump the full attribute JSON (and any captured span events) for one span |
| `mycelium metrics traces events [trace_or_span_id]` | Show OTel **span events** as a flat, time-ordered log. Span events are the OTel-native way to attach log-like records to a span (exceptions with stack traces, prompt build steps, tool I/O snapshots, etc.). With no argument, lists events across all spans matching the filters in the time window. |
| `mycelium metrics traces rooms` | Active rooms with span counts and which agents/hosts touched each |
| `mycelium metrics traces agents` | Per-agent rollup with hosts, rooms, models, tokens, errors |
| `mycelium metrics traces schema` | Print the SQLite schema and the most common attribute keys (handy when authoring ad-hoc SQL) |

### Common flags

Most pivot subcommands accept the same filter set:

| Flag | Meaning |
|------|---------|
| `--since 30s\|15m\|2h\|1d` | Time window (default `1h`). Bare numbers are minutes. |
| `--host <name>` | Filter to one host (e.g. `--host oclw3`) |
| `--agent <id>` | Filter to one agent |
| `--room <id_substring>` | Filter to a Matrix room id or Mycelium room name (substring match) |
| `--name '<glob>'` | Filter span name (`*` wildcard) |
| `--status ok\|error\|unset` | Filter by span status |
| `--limit N` / `-n N` | Cap the number of rows |
| `--all` | (For `errors` / `slow` only) Include the gateway's CPU/event-loop watchdog spans (`openclaw.diagnostic.phase`, `openclaw.liveness.warning`), which are excluded by default so real workload spans stand out |

### Examples

```bash
# Top-level health check across the whole fleet
mycelium metrics traces summary --since=1h

# Which Mycelium rooms are active right now, and which agents are in them?
mycelium metrics traces rooms --since=30m

# What's claire-agent doing on oclw3 in the last 15 minutes?
mycelium metrics traces list --agent=claire-agent --host=oclw3 --since=15m

# All tool-call spans for the mycelium-room (negotiation activity)
mycelium metrics traces by-tool --room=mycelium_room --since=1h

# Real failures (skips the gateway's CPU watchdog noise)
mycelium metrics traces errors --since=1h

# Slowest user-facing spans (skips the same noise)
mycelium metrics traces slow --since=1h

# Drill into one trace as a tree
mycelium metrics traces show 6df3b9b5e3832b7247a2079346ec3dc5

# Dump everything OpenTelemetry knows about one span
mycelium metrics traces show-attrs <span_id>
```

### Span events ("log lines")

OpenTelemetry spans can carry zero or more **events** — timestamped,
log-like records the instrumentation attached mid-span (exceptions with
stack traces, prompt build steps, tool I/O snapshots, etc.). The
collector persists them into the `events` column of the `spans` table
as a JSON list (each entry is `{time, name, attributes}`), and the
viewer surfaces them in two ways:

- `traces show <id> --events` interleaves them inline under their
  parent spans in the tree view.
- `traces events [id]` renders them as a flat, time-ordered log,
  optionally scoped to one trace, agent, room, host, or time window.

Whether and how often events show up is a function of what the
deep-observability plugin is configured to emit:

- Exceptions are always recorded (OTel convention).
- LLM prompt / completion content is only attached when the plugin's
  `captureContent` flag is `true`. The adapter sets this to `false` by
  default for privacy; flip it in `~/.openclaw/openclaw.json` under
  `plugins.entries.openclaw-deep-observability.config.captureContent`
  if you want full prompt visibility.

The OTLP `/v1/logs` endpoint is currently *acked but discarded* — if
you want general OpenClaw log lines forwarded to the hub, that's a
follow-up (would require a `LogStore` sibling to `TraceStore`).

### Host normalization

The same physical host can show up in `spans.host` under multiple
labels:

- `oclw3` — the new canonical name (post-adapter-baked-in
  `OTEL_RESOURCE_ATTRIBUTES=host.name=…`)
- `oclw-3` — legacy `service.instance.id` from before the adapter
  managed the systemd override
- `10.0.50.171` / `ip-10-0-50-171` — deep-obs spans where `host.name`
  wasn't set, so the OTLP receiver fell back to the source IP

The viewer normalizes these for display in three layers, in priority
order:

1. **Explicit overrides** in `~/.mycelium/config.toml`:

   ```toml
   [metrics.traces.host_aliases]
   "10.0.50.171"     = "oclw3"
   "ip-10-0-50-171"  = "oclw3"
   "10.0.50.142"     = "oclw5"
   ```

2. **Built-in pattern**: `oclw-N` → `oclwN`.
3. **Best-effort reverse DNS** for raw IPv4 addresses.

Filtering also follows the alias map: `--host=oclw3` matches every raw
host label that resolves to `oclw3`, so `traces by-agent --host=oclw3`
or `traces list --host=oclw3` give you a unified per-machine view even
across legacy data.

For new spans, the adapter's `--step=deep-observability` writes a
systemd drop-in (`~/.config/systemd/user/openclaw-gateway.service.d/deep-obs.conf`)
that sets:

```
Environment="OTEL_RESOURCE_ATTRIBUTES=host.name=$(hostname),service.instance.id=$(hostname)"
```

so the gateway's deep-obs spans always carry the canonical hostname
and the IP-fallback path in the OTLP receiver never fires.

### Read-only access

`traces` opens `traces.db` via SQLite URI mode (`mode=ro`), so it never
contends with the OTLP receiver writing new spans. This is safe to run
against a live hub.

## Pricing Data

Pricing data is resolved in this order:

1. **User-local cache** — `$DATA_DIR/metrics/pricing.json` (written by `mycelium metrics update-pricing`)
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
2. **Auto-discovered models** — the command reads `metrics/metrics.json` and
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

## Containerized Collector (Docker)

The OTLP collector runs as a Docker Compose service alongside the rest of
the Mycelium stack.

### Starting

```bash
mycelium up --metrics
```

This adds `--profile metrics` to the `docker compose up` command, which
starts the `mycelium-collector` service. It depends on `mycelium-backend`
being healthy before starting.

The collector is accessible at `http://localhost:4318` (configurable via
`MYCELIUM_METRICS_PORT` in `~/.mycelium/.env`).

### How It Works

The `mycelium-collector` service is defined in `compose.yml` under the
`metrics` profile:

- **Image:** Built from `Dockerfile.collector` (Python 3.12-slim with
  only the OTLP/protobuf dependencies, no full CLI install)
- **Port:** `${MYCELIUM_METRICS_PORT:-4318}:4318`
- **Volume:** `~/.mycelium` is mounted at `/root/.mycelium` so
  `metrics.json` and `traces.db` are shared with the host
- **Backend URL:** `http://mycelium-backend:8000` (Docker network, not
  localhost)
- **Health check:** `GET /health` on port 4318 returns `{"status":"ok"}`

### Management

`mycelium down` and `mycelium logs` automatically include
`--profile metrics` when they detect the collector container is running,
so they manage it correctly without needing the `--metrics` flag.

### Development Overrides

`compose-dev.yml` provides a `mycelium-collector` entry with
`image: mycelium-collector:dev` and the `~/.mycelium/.env` env file,
matching the pattern used by other dev-mode services.

### Environment Variables

| Variable                | Default          | Purpose                              |
| ----------------------- | ---------------- | ------------------------------------ |
| `MYCELIUM_METRICS_PORT` | `4318`           | Host port for the collector          |
| `MYCELIUM_DATA_DIR`     | `~/.mycelium`    | Data directory mounted into container |

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
| `mycelium-cli/src/mycelium/commands/adapter.py`  | `--step=otel` and `--step=deep-observability` setup |
| `mycelium-cli/src/mycelium/commands/instance.py`  | `mycelium up --metrics`, `down`, `logs` with collector awareness |
| `mycelium-cli/src/mycelium/data/pricing.json`    | Generated model and embedding pricing data |
| `mycelium-cli/src/mycelium/collector.py`          | OTLP HTTP receiver, MetricsStore, TraceStore, backend poller, hub forwarding |
| `mycelium-cli/src/mycelium/collector_main.py`     | Entrypoint for the Docker collector process |
| `mycelium-cli/Dockerfile.collector`               | Minimal image for the containerized collector |
| `mycelium-cli/src/mycelium/docker/compose.yml`    | `mycelium-collector` service definition (metrics profile) |
| `mycelium-cli/src/mycelium/docker/compose-dev.yml`| Dev overrides for collector image/env |
| `fastapi-backend/app/services/metrics.py`         | Backend in-process metrics store |
| `fastapi-backend/app/main.py`                     | `GET /api/observability`, `GET /api/observability/collector`, `GET /api/observability/traces/recent` |
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
- [ ] **Deep observability plugin** — if not yet installed, run
      `mycelium adapter add openclaw --step=deep-observability` on each
      machine running an OpenClaw gateway. Verify with
      `grep deep-observability ~/.openclaw/openclaw.json`.
- [ ] **Pricing update** — run `mycelium metrics update-pricing` to fetch the
      latest pricing from the LiteLLM API and write `metrics/pricing.json`.
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
