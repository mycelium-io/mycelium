# Metrics and observability

Mycelium records metrics about what its own backend does. It can also collect
telemetry from your agents over OpenTelemetry (OTLP), though that side is still
basic.

## What the backend records

**Backend metrics.** The backend counts memory writes and searches, embeddings,
index runs and model calls (by operation and model), with how long each took.
You can read them as JSON at `GET /api/observability`. Model calls go through
`pi`, which doesn't report token usage, so calls, failures and timings are
recorded but cost isn't.

**Health.** `GET /health` tells you whether messaging is working: channels set
up and failed, failed invites, and per-room counts of messages re-sent and
dropped, plus the state of storage, embeddings and the model. This is what
`mycelium doctor` checks.

## Viewing metrics

```bash
mycelium metrics status       # is the collector running, and is the config right
mycelium metrics show         # an overview
mycelium metrics show mycelium  # the backend's activity in detail
mycelium metrics show cost    # estimated cost of the backend's model calls, by room
mycelium metrics show --json  # everything collected, as JSON
mycelium metrics reset        # clear the metrics collected on this machine
```

The overview also lists the hosts that have sent the collector traces, with
the agents their spans named.

In the app, the **Metrics** page (open it from the status bar) shows the
backend's metrics, the `/health` messaging details, and every room's episode
records.

## Agent telemetry over OTLP (optional)

The collector receives OpenTelemetry data. Start it with
`mycelium up --metrics`, and it listens for OTLP metrics and traces on
`localhost:4318`, and also reads the backend's `/api/observability`. It saves
a combined snapshot to `$MYCELIUM_DATA_DIR/metrics/`, which is what
`mycelium metrics` reads.

Point any OTLP exporter at `http://<host>:4318` to send data to it. Traces are
stored in full. Spans that carry OpenTelemetry's GenAI attributes
(`gen_ai.agent.name`, `gen_ai.request.model`, `gen_ai.tool.name`,
`gen_ai.usage.*`) can be grouped by agent, model and tool. For metrics, the
collector only counts how many data points each host has sent. Mycelium
doesn't ship its own exporter yet.

You can query the traces it collects:

```bash
mycelium metrics traces summary    # totals over a time window
mycelium metrics traces by-agent   # spans grouped by agent, room, model, tool and more
```

## Files

Metrics are stored in `$MYCELIUM_DATA_DIR/metrics/` (`~/.mycelium/metrics/` by
default): `metrics.json` is the combined snapshot, and `traces.db` holds the
OTLP traces.
