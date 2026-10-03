# Metrics and observability

A hub keeps three kinds of numbers:

| What | What it answers | Where it goes |
|---|---|---|
| **Usage** | What the hub is used for: tasks filed and resolved, flows and negotiations finished, agents joined | Recorded on the hub, always. Sent on only if the hub shares usage stats |
| **Backend metrics** | What the backend is doing: memory, embeddings, model calls, messaging, latency | Kept in the running backend. Exported over OpenTelemetry if you turn that on |
| **Agent telemetry** | What your agents report over OpenTelemetry | The optional collector |

The app's **Metrics** page (open it from the status bar) shows the first two,
as its Usage and System tabs.

## Usage

Every piece of work a room does is a task, so usage follows tasks. The hub
records one event each time:

| Event | When | Carries |
|---|---|---|
| `mycelium.hub_started` | The hub starts | how it runs (`desktop`, `docker`, `server`), OS |
| `mycelium.task_filed` | A row lands on a board | its kind, who filed it (`person`, `agent`, `engine`), whether it was for someone |
| `mycelium.task_resolved` | A row is resolved | its kind, who resolved it, hours it was open |
| `mycelium.flow_completed` | A conductor flow finishes | the flow (`review`, `swarm`, `gated`, ... or `custom`), outcome, steps |
| `mycelium.negotiation_completed` | The aligner reaches an outcome | outcome, rounds |
| `mycelium.agent_joined` | An agent is added to a room | its adapter (`claude_code`, `cursor`, `worker`, ...) |

Each of the app's ways to start work maps onto these. A plain task is filed
and resolved. Review, Split and Settle finish as a flow or a negotiation
inside a task.

Every event also carries the release, the time, and the hub's id: a random
UUID (the one `mycelium install` saves in `config.toml`, or one the hub
creates for itself). Resolved tasks, finished flows and finished
negotiations carry `work_count`, how much work this hub has finished so far,
so first use (`1`) and repeat use (`2` and up) can be told apart.

**Never recorded:** names, handles, emails, rooms, task titles or text,
prompts, replies, IPs or hostnames. A room's own flow is counted as `custom`,
since its name is the room's.

### Where to see it

![The Metrics page's Usage tab](app-metrics.png)

The Metrics page opens on its **Usage** tab, over the last 30 or 90 days:
tasks filed and resolved, how long tasks stay open, and active days; whether
the board keeps up (filed against resolved, by day or by week); each way of
starting work and how often it ends well; who files the work, and how long
tasks stay open by who resolved them; and agents joined by adapter. Its
**System** tab is the backend's own metrics, below. The same figures are at
`GET /api/observability/usage?days=30`. The events themselves
are in `$MYCELIUM_DATA_DIR/usage/events.jsonl`, one JSON object per line.

### Sharing usage stats

Sharing sends each event to `telemetry.analytics_destination` as it happens,
so the people building Mycelium can see what's working. It's off unless you
turn it on. You're asked in two places:

- **The Mac app**, on its first screen (and again under Settings), when it
  runs a hub. The app's answer is the one that counts for the hub it starts.
- **`mycelium install`**, as its last question.

To change it by hand:

```bash
mycelium config set telemetry.send_product_analytics true   # or false
mycelium config apply
```

Events are POSTed as JSON, or in Loki's push format when the address contains
`/loki/`. The destination must be HTTPS, or plain HTTP to this machine
(`localhost`, `127.0.0.1`, `host.docker.internal`).

## Backend metrics

**What the backend records.** Memory writes and searches, embeddings, index
runs, and model calls (by operation and model), with how long each took. Model
calls go through `pi`, which doesn't report token usage, so calls, failures
and timings are recorded but cost isn't. Read them as JSON at
`GET /api/observability`.

**Health.** `GET /health` tells you whether messaging is working: channels set
up and failed, failed invites, and per-room counts of messages re-sent and
dropped, plus the state of storage, embeddings and the model. This is what
`mycelium doctor` checks.

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
mycelium metrics show cost      # estimated cost of the backend's model calls, by room
mycelium metrics show --json    # everything collected, as JSON
mycelium metrics reset          # clear the metrics collected on this machine
```

### Exporting them over OpenTelemetry (optional)

With `telemetry.enabled`, the backend also exports traces and metrics over
OTLP: a span per HTTP route, and timings for aligner rounds, SLIM channels,
`await` and model calls. Off by default, and when it's off none of that code
runs.

```bash
mycelium config set telemetry.enabled true
mycelium config set telemetry.otlp_endpoint <url>
mycelium config apply
```

Where to point it:

- **A hosted OTLP backend**, such as Grafana Cloud or Honeycomb. Put its auth
  header in `~/.mycelium/.env` as `OTEL_EXPORTER_OTLP_HEADERS`.
- **A local Grafana**, with the Docker stack: set the endpoint to
  `http://mycelium-grafana:4318` and run `mycelium up --grafana`. That starts
  Grafana's all-in-one image and imports Mycelium's dashboard. It opens at
  `http://localhost:3001` (admin / admin). To also forward to a hosted
  backend, set `OTEL_EXPORTER_OTLP_ENDPOINT` and its headers in
  `~/.mycelium/.env`.
- **The Mac app** runs no collector or Grafana, so set the endpoint to one you
  run yourself, for example `http://127.0.0.1:4318` for a collector on the
  same Mac.

If the Grafana container restarts, restart the backend too
(`docker restart mycelium-backend`): its OTLP connection doesn't reconnect.

The spans follow OpenTelemetry's `gen_ai.*` conventions, which are still
marked Development. The versions tested against are pinned in
`fastapi-backend/pyproject.toml`.

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
collector only counts how many data points each host has sent.

```bash
mycelium metrics traces summary    # totals over a time window
mycelium metrics traces by-agent   # spans grouped by agent, room, model, tool and more
```

## Files

Under `$MYCELIUM_DATA_DIR` (`~/.mycelium/` by default):

- `usage/events.jsonl`: the hub's usage events (rotated at 5 MB, keeping one
  previous file), and `usage/hub_id` when the hub made its own id.
- `metrics/metrics.json`: the collector's combined snapshot.
- `metrics/traces.db`: the OTLP traces the collector received.

```toml
[telemetry]
enabled                = false  # export backend traces and metrics over OTLP
otlp_endpoint          = ""     # where to; the Docker stack's collector if unset
send_product_analytics = false  # share usage stats
analytics_destination  = ""     # where shared usage events go
install_id             = ""     # set by `mycelium install`; a hub without one makes its own
```
