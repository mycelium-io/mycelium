# Metrics and observability

Mycelium surfaces its own operational metrics today, and can ingest agent
telemetry over OpenTelemetry (OTLP) for a fuller picture. The v1 story is
deliberately minimal; it will grow as the agent-telemetry side lands.

## What you get today

**Mycelium's own metrics.** The backend records what it does as it runs:
embeddings computed, LLM calls (by operation, model, and room), index runs,
memory reads and writes, and coordination activity. It exposes them as JSON at
`GET /api/observability` (counters plus latency histograms).

**The coordination health surface.** `GET /health` reports whether the fabric is
actually working: channels provisioned and failed, invite failures, and per-room
re-serve and drop counts, plus storage, embedding, and LLM status. This is the
one call that answers "is the room bus healthy?" and is what `mycelium doctor`
reads.

## Viewing metrics

```bash
mycelium metrics status     # health of the collector, backend, and config
mycelium metrics show       # render the collected metrics as tables
mycelium metrics show --json  # raw JSON for scripting
mycelium metrics reset      # clear locally collected metrics
```

`mycelium metrics show` renders Mycelium's backend metrics, and any agent
telemetry the collector has received (see below).

## Agent telemetry over OTLP (optional, minimal in v1)

The **collector** is an OpenTelemetry receiver: start it with
`mycelium up --metrics` and it listens for OTLP metrics and traces on
`localhost:4318`, alongside polling the backend's `/api/observability`. It writes
an aggregated snapshot to `$MYCELIUM_DATA_DIR/metrics/` that `mycelium metrics`
reads.

Point any OTLP source at the receiver to feed it. The intended source is an
agent-side observability plugin such as
[InsightClaw](https://github.com/outshift-open/InsightClaw), which emits
per-request, agent, tool, and LLM cost/token telemetry. Wiring a first-party
emitter is future work; for now the receiver is present and any OTLP exporter
configured to `http://<host>:4318` will populate the trace and metric views.

Collected trace spans are queryable:

```bash
mycelium metrics traces summary      # rollup over a time window
mycelium metrics traces by-agent     # pivot spans by agent, room, model, tool, …
```

## Files

All metrics data lives under `$MYCELIUM_DATA_DIR/metrics/` (default
`~/.mycelium/metrics/`): `metrics.json` (the aggregated snapshot) and
`traces.db` (the OTLP span store).
