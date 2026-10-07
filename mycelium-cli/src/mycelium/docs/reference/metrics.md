# Metrics and observability

A hub keeps three kinds of numbers:

| What | What it answers | Where it goes |
|---|---|---|
| **Usage** | What the hub is used for: tasks filed and resolved, flows and negotiations finished, agents joined | Recorded on the hub, always. Sent on only if the hub shares usage stats |
| **Backend metrics** | What the backend is doing: memory, embeddings, model calls, messaging, latency | Kept in the running backend. Exported over OpenTelemetry if you turn that on |
| **Agent telemetry** | What your agents report over OpenTelemetry | The optional collector |

The app's **Metrics** page shows the first two on its Usage and System tabs.
Open it from the strip along the bottom of the app.

## Usage

Most work in a room is a task, so usage follows tasks. The hub records an event
each time one of these happens:

| Event | When | Carries |
|---|---|---|
| `mycelium.hub_started` | The hub starts | how it runs (`desktop`, `docker`, `server`), OS |
| `mycelium.task_filed` | A row lands on a board | its kind, who filed it (`person`, `agent`, `engine`), whether it was for someone |
| `mycelium.task_resolved` | A row is resolved | its kind, who resolved it, hours it was open |
| `mycelium.flow_completed` | A conductor flow finishes | the flow (`review`, `swarm`, `gated`, ... or `custom`), outcome, steps |
| `mycelium.negotiation_completed` | The aligner reaches an outcome | outcome, rounds |
| `mycelium.agent_joined` | An agent is added to a room | its adapter (`claude_code`, `cursor`, `worker`, ...) |

Each of the app's ways to start work maps onto these. A plain task is filed
and resolved. Review, Split and Settle finish as a flow or a negotiation inside
a task. Split is a swarm.

Every event also carries the release, the time and the hub's id. The id is a
random UUID, either the one `mycelium install` saves in `config.toml` or one
the hub creates for itself. Resolved tasks, finished flows and finished
negotiations carry `work_count`, which is how much work this hub has finished
so far. That tells first use (`1`) apart from repeat use (`2` and up).

**Never recorded:** names, handles, emails, rooms, task titles or text,
prompts, replies, IPs or hostnames. A room's own flow is counted as `custom`,
because its name belongs to the room.

### Where to see it

![The Metrics page's Usage tab](app-metrics.png)

The Metrics page opens on its **Usage** tab and covers the last 30 or 90 days.
It shows:

- tasks filed and resolved, how long tasks stay open and active days;
- whether the board keeps up, as filed against resolved by day or by week;
- each way of starting work and how often it ends well;
- who files the work, and how long tasks stay open by who resolved them;
- agents joined, by adapter.

Its **System** tab shows the backend's own metrics, described below. The same
figures are at `GET /api/observability/usage?days=30`. The events themselves are
in `$MYCELIUM_DATA_DIR/usage/events.jsonl`, one JSON object per line.

### Sharing usage stats

Sharing sends each event to `telemetry.analytics_destination` as it happens.
It's off unless you turn it on. You're asked in two places:

- **The Mac app** asks on its first screen when it runs a hub, and again under
  Settings. The app's answer is the one that counts for the hub it starts.
- **`mycelium install`** asks as its last question.

To change it by hand:

```bash
mycelium config set telemetry.send_product_analytics true   # or false
mycelium config apply
```

Events go only to the address in `telemetry.analytics_destination`. No address
is set by default, so turning sharing on sends nothing until one is set. Events
are POSTed as JSON. When the address contains `/loki/`, they're sent in Loki's
push format instead. The destination must be HTTPS or plain HTTP to this
machine (`localhost`, `127.0.0.1`, `host.docker.internal`).

## Backend metrics

**What the backend records.** It records memory writes and searches,
embeddings, index runs and model calls by operation and model, with how long
each took. Model calls go through `pi`, which doesn't report token usage. So
calls, failures and timings are recorded but cost isn't. Read them as JSON at
`GET /api/observability`.

**Health.** `GET /health` tells you whether messaging is working. It reports
channels set up and failed, failed invites and per-room counts of messages
re-sent and dropped. It also reports the state of storage, embeddings and the
model. This is what `mycelium doctor` checks.

When a latency p95 passes its threshold, `/health` reports `degraded` and
`mycelium doctor` says so:

| Signal | Default threshold |
|---|---|
| Model call p95 | 30 000 ms |
| `await` p95, for calls that delivered a message | 60 000 ms |
| Memory search p95 | 500 ms |

```bash
mycelium config set health.llm_p95_threshold_ms 60000   # 0 turns a check off
mycelium config apply
```

### Viewing them

```bash
mycelium metrics status         # is the collector running, and is the config right
mycelium metrics show           # an overview
mycelium metrics show mycelium  # the backend's activity in detail
mycelium metrics show cost      # estimated model cost, where token counts were reported
mycelium metrics show --json    # everything collected, as JSON
mycelium metrics reset          # clear the metrics collected on this machine
```

`metrics show cost` multiplies token counts by each model's price. Engine calls
go through Pi, which reports no token counts, so it has nothing to show for
them.

### Exporting them over OpenTelemetry (optional)

With `telemetry.enabled`, the backend also exports traces and metrics over
OTLP. It sends a span per HTTP route and timings for aligner rounds, SLIM
channels, `await` and model calls. It's off by default, and when it's off none
of that code runs.

```bash
mycelium config set telemetry.enabled true
mycelium config set telemetry.otlp_endpoint <url>
mycelium config apply
```

Where to point it:

- **A hosted OTLP backend**, such as Grafana Cloud or Honeycomb. Set the
  endpoint to it. Set its auth header with
  `mycelium config set telemetry.otlp_headers "x-honeycomb-team=<key>"`.
- **A local Grafana** with the Docker stack. Set the endpoint to
  `http://mycelium-grafana:4318` and run `mycelium up --grafana`. That starts
  Grafana's all-in-one image and imports Mycelium's dashboard. It opens at
  `http://localhost:3001` with the login admin / admin. To also forward
  everything it receives to a hosted backend, set `telemetry.forward_endpoint`.
  Use `telemetry.otlp_headers` for that backend's auth.
- **The Mac app** runs no collector or Grafana. Set the endpoint to one you run
  yourself, such as `http://127.0.0.1:4318` for a collector on the same Mac.

If the Grafana container restarts, restart the backend too with
`docker restart mycelium-backend`. Its OTLP connection doesn't reconnect.

The spans follow OpenTelemetry's `gen_ai.*` conventions, which are still marked
Development. The versions tested against are pinned in
`fastapi-backend/pyproject.toml`.

## Agent telemetry over OTLP (optional)

The collector receives OpenTelemetry data. Start it with `mycelium up --metrics`.
It listens for OTLP metrics and traces on `localhost:4318` and also reads the
backend's `/api/observability`. It saves a combined snapshot to
`$MYCELIUM_DATA_DIR/metrics/`, which is what `mycelium metrics` reads.

Point any OTLP exporter at `http://<host>:4318` to send data to it. Traces are
stored in full. Spans that carry OpenTelemetry's GenAI attributes can be grouped
by agent, model and tool. Those attributes are `gen_ai.agent.name`,
`gen_ai.request.model`, `gen_ai.tool.name` and `gen_ai.usage.*`. For metrics,
the collector only counts how many data points each host has sent.

```bash
mycelium metrics traces summary    # totals over a time window
mycelium metrics traces by-agent   # spans grouped by agent, room, model, tool and more
```

## Files

Under `$MYCELIUM_DATA_DIR` (`~/.mycelium/` by default):

- `usage/events.jsonl`: the hub's usage events. It's rotated at 5 MB and keeps
  one previous file.
- `usage/hub_id`: the hub's id, when the hub made its own.
- `metrics/metrics.json`: the collector's combined snapshot.
- `metrics/traces.db`: the OTLP traces the collector received.

```toml
[telemetry]
enabled                = false  # export backend traces and metrics over OTLP
otlp_endpoint          = ""     # where to; the Docker stack's collector if unset
otlp_headers           = ""     # headers on every export, such as a hosted backend's auth
forward_endpoint       = ""     # the local Grafana also forwards here
send_product_analytics = false  # share usage stats
analytics_destination  = ""     # where shared usage events go
install_id             = ""     # set by `mycelium install`; a hub without one makes its own
```
