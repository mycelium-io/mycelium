# Metrics and observability

Mycelium's observability stack has two tracks that work independently and
complement each other:

| Track | What it measures | Who controls it |
|---|---|---|
| **Operational telemetry** | Every coordinated path the backend runs (HTTP RED, aligner rounds, SLIM channel timing, await long-poll, LLM calls, embeddings, memory) | Always-on in-process store + optional OTel SDK export |
| **Product analytics** | Anonymous adoption signals (install, first session, repeat session) | Explicit opt-in only; off by default |

---

## Operational telemetry

### In-process metrics (always-on)

The backend records what it does as it runs.  No configuration required.  The
metrics store (`app/services/metrics.py`) tracks:

| Namespace | Signals |
|---|---|
| `embeddings` | computed, by source, estimated tokens, cost-avoided |
| `llm` | calls, by operation, by model, tokens, cost, errors, **latency histograms** |
| `aligner` | runs, rounds, by room, outcomes (converged/rejected/stalled), **round_ms histogram** |
| `slim` | provision latency, provision errors, receive errors |
| `participate` | await polls, delivered, timeouts, **await_ms histogram** |
| `memory` | writes, searches, hits, **search_latency_ms histogram** |
| `indexer` | runs, files indexed/skipped/pruned, errors |
| `http` | requests, by method/route/status, errors, **request_ms histogram** |

All histograms include count, sum, min, max, and **p95** (exposed at
`GET /api/observability` → `p95` key).  p95 is computed from a rolling
window of the last 1000 samples.

### Viewing metrics

```bash
mycelium metrics status       # health of collector, backend, and config
mycelium metrics show         # render backend counters + collector data as tables
mycelium metrics show --json  # raw JSON for scripting
mycelium metrics reset        # clear locally collected metrics
```

The app draws the same two surfaces on its **Metrics** page (status bar →
Metrics), alongside per-room episode records.

### /health latency degradation (#453)

`GET /health` includes a `latency` key.  When p95 of a key histogram exceeds
its threshold, `status` flips to `degraded` and `mycelium doctor` surfaces the
signal:

| Signal | Histogram | Default threshold |
|---|---|---|
| LLM p95 | `llm.latency_ms` | 30 000 ms |
| Await p95 (delivered only) | `participate.await_delivered_ms` | 60 000 ms |
| Search p95 | `memory.search_latency_ms` | 500 ms |

Timed-out long-polls (the default 3 600 s window) are recorded in
`participate.await_ms` for throughput accounting but are **excluded** from the
degradation threshold — only polls that actually returned a message are measured,
so the threshold reflects genuine channel slowness rather than idle wait time.

Override defaults in ``config.toml``:

```toml
[health]
llm_p95_threshold_ms   = 60000
await_p95_threshold_ms = 120000
search_p95_threshold_ms = 1000
```

```bash
mycelium config set health.llm_p95_threshold_ms 60000
mycelium config apply
```

Set any threshold to `0` to disable that check.

---

## OTel SDK in the backend (opt-in)

When `telemetry.enabled = true`, the backend initialises the OpenTelemetry SDK
at startup and exports traces + metrics over OTLP to the collector.

```toml
[telemetry]
enabled          = true   # opt in to the OTel SDK
otlp_endpoint    = ""     # default: http://mycelium-collector:4318
```

```bash
mycelium config set telemetry.enabled true
mycelium config apply          # regenerates ~/.mycelium/.env
mycelium up --metrics          # bring up the collector if not already running
```

When `enabled = false` (the default), **no OTel code runs** — not even an
import.  The in-process store is always-on regardless.

### Grafana LGTM — full OTel backend with browser UI

`mycelium up --grafana` starts `grafana/otel-lgtm` — a single container
with OTel Collector, Prometheus, Tempo, Loki, and Grafana UI.  This is the
recommended way to browse telemetry data locally and to see exactly what the
telemetry opt-in exposes before choosing a production destination.

```bash
mycelium config set telemetry.enabled true
mycelium config set telemetry.send_product_analytics true
mycelium config set telemetry.analytics_destination \
  http://host.docker.internal:3100/loki/api/v1/push
mycelium config apply
mycelium up --grafana          # starts Grafana + imports the dashboard
```

Grafana opens at `http://localhost:3001` (admin / admin).  The Mycelium
performance dashboard is imported automatically on first start.

| Signal | Where it lands |
|---|---|
| OTel traces | Tempo → Explore |
| OTel metrics | Prometheus → Explore + dashboard panels |
| Product analytics events | Loki → "Product analytics events" panel |

`--grafana` and `--metrics` cannot run simultaneously — both bind port 4318.
Use `--grafana` when you want the browser UI; use `--metrics` for the
lightweight JSON + traces.db collector without the UI overhead.

The bundled dashboard JSON is at
`mycelium-cli/src/mycelium/data/grafana-mycelium-performance.json` and is
packaged with the CLI, so it is available on any install.

### What the SDK adds

- **Per-route HTTP spans** (`FastAPIInstrumentor` — stable OTel HTTP conventions)
- **OTLP trace export** to the collector (`BatchSpanProcessor`, async flush)
- **OTLP metric export** to the collector (`PeriodicExportingMetricReader`, 5 s)
- **Resource attributes** on every span: `service.name=mycelium-backend`,
  `service.version`, `deployment.environment`

### gen_ai.* conventions — version pin (Sep 2026)

The `gen_ai.*` semantic conventions moved to the dedicated
[`open-telemetry/semantic-conventions-genai`](https://github.com/open-telemetry/semantic-conventions-genai)
repository in June 2026 and remain in **Development** status (0 of 63
attributes are stable as of Sep 2026).  The OTel packages pinned in
`fastapi-backend/pyproject.toml` (`opentelemetry-sdk>=1.29.0`) are the
versions tested against — update the pin comment when you bump the version.

### Collector

The **collector** is an opt-in OTLP receiver on `:4318` that receives traces
and metrics from the backend (when `telemetry.enabled=true`), polls
`/api/observability`, and aggregates everything into
`$MYCELIUM_DATA_DIR/metrics/`.

```bash
mycelium up --metrics          # start the collector
mycelium metrics status        # verify it is reachable
mycelium metrics traces summary
mycelium metrics traces by-agent
```

---

## Agent telemetry over OTLP (external sources)

Point any OTLP exporter at `http://<host>:4318` to feed the collector.  The
intended source is an agent-side observability plugin such as
[InsightClaw](https://github.com/outshift-open/InsightClaw), which emits
per-request LLM cost/token telemetry.  Third-party spans and metrics land in
the same `metrics.json` + `traces.db` the CLI and app read.

---

## Product analytics (opt-in, off by default)

Separate from operational telemetry.  Fires only when the user explicitly
enables it at interactive install (or via `mycelium config set`).

### Events

| Event | When | Fields |
|---|---|---|
| `mycelium.install` | First interactive install | `install_id`, `release`, `platform` |
| `mycelium.session` | Each coordinated session that reaches a terminal outcome | `install_id`, `release`, `adapter_class`, `outcome`, `session_count` |

`session_count` is the cumulative number of completed sessions on this installation (1 = first,
2+ = repeat). Use it to compute time-to-first-session and retention curves without separate event types.

### Privacy contract

- Every event is identified only by a random `install_id` (UUID4, generated at
  first install, stored in `config.toml`).
- **Never included**: room names, task content, prompts, replies, handles, IP
  addresses, hostnames, or any content from a coordinated session.
- `adapter_class` is the *kind* string (`claude_code`, `cursor`), never a name.
- `outcome` is a status word (`converged`, `resolved`, `rejected`).

### Enabling / disabling

```bash
# Enable (interactive install shows this disclosure before asking)
mycelium config set telemetry.send_product_analytics true

# Disable at any time
mycelium config set telemetry.send_product_analytics false
mycelium config apply
```

Non-interactive installs (`mycelium install --non-interactive`) stay off
unconditionally.  The destination (`telemetry.analytics_destination`) is not
yet configured — events are no-ops until the go/no-go decision in #937 is
made.

---

## Files

All metrics data lives under `$MYCELIUM_DATA_DIR/metrics/` (default
`~/.mycelium/metrics/`): `metrics.json` (the aggregated snapshot) and
`traces.db` (the OTLP span store).

### config.toml telemetry section

```toml
[telemetry]
# OTel SDK — off by default; zero cost when disabled
enabled                  = false
otlp_endpoint            = ""     # defaults to http://mycelium-collector:4318

# Product analytics — off by default, never enabled non-interactively
send_product_analytics   = false
analytics_destination    = ""     # set once #937 go/no-go is decided
install_id               = ""     # auto-generated at first interactive install
```
