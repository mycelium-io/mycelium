# Metrics and observability

A hub keeps three kinds of numbers:

| What | What it answers | Where it goes |
|---|---|---|
| **Usage** | What the hub is used for: tasks filed and resolved, flows and negotiations finished, agents joined | Recorded on the hub, always. Sent on only if the hub shares usage stats |
| **Backend metrics** | What the backend is doing: memory, embeddings, model calls, messaging, latency | Kept in the running backend. Exported over OpenTelemetry if you turn that on |
| **Agent telemetry** | What your agents report over OpenTelemetry | The optional collector |

The app's **Metrics** page shows the first two, on its Usage and System tabs.
Open it from the strip along the bottom of the app.

![The Metrics page's Usage tab](app-metrics.png)

## Usage

The hub records an event each time one of these happens:

| Event | When | Carries |
|---|---|---|
| `mycelium.hub_started` | The hub starts | how it runs (`desktop`, `docker`, `server`), OS |
| `mycelium.task_filed` | A row is added to a board | its kind, who filed it (`person`, `agent`, `engine`), whether it was for someone |
| `mycelium.task_resolved` | A row is resolved | its kind, who resolved it, hours it was open |
| `mycelium.flow_completed` | A conductor flow finishes | the flow (`review`, `swarm`, `gated`, ... or `custom`), outcome, steps |
| `mycelium.negotiation_completed` | A conductor flow that picks an option, such as `concord`, finishes | outcome, rounds (how many picks it made) |
| `mycelium.agent_joined` | An agent is added to a room | its adapter (`claude_code`, `cursor`, `worker`, ...) |

Every event also carries the release, the time and the hub's id, which is a
random UUID. Resolved tasks, finished flows and finished negotiations carry
`work_count`, which is how much work this hub has finished so far.

**Never recorded:** names, handles, emails, rooms, task titles or text,
prompts, replies, IPs or hostnames. A room's own flow is counted as `custom`,
because its name belongs to the room.

The Usage tab's figures are also at `GET /api/observability/usage?days=30`. The
events themselves are in `$MYCELIUM_DATA_DIR/usage/events.jsonl`, one JSON
object per line.

### Sharing usage stats

Sharing sends each event to `telemetry.analytics_destination` as it happens.
It's off unless you turn it on. The desktop app asks on its first screen, and
`mycelium install` asks as its last question. To change it by hand:

```bash
mycelium config set telemetry.send_product_analytics true   # or false
mycelium config apply
```

No destination is set by default, so turning sharing on sends nothing until one
is set. Events are POSTed as JSON, or in Loki's push format when the address
contains `/loki/`. The destination must be HTTPS, or plain HTTP to this machine.

## Backend metrics

The backend records memory writes and searches, embeddings, index runs and
model calls, with how long each took. Read them as JSON at
`GET /api/observability`. Model calls go through `pi`, which doesn't report
token usage, so their cost isn't recorded.

`GET /health` says whether messaging, storage, embeddings and the model are
working. This is what `mycelium doctor` checks. When a latency p95 passes its
threshold, `/health` reports `degraded`:

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

### Exporting them over OpenTelemetry

With `telemetry.enabled`, the backend also exports traces and metrics over
OTLP. It's off by default.

```bash
mycelium config set telemetry.enabled true
mycelium config set telemetry.otlp_endpoint <url>
mycelium config apply
```

You can point it at any of these:

- **A hosted OTLP backend**, such as Grafana Cloud or Honeycomb. Set its auth
  header with `mycelium config set telemetry.otlp_headers "x-honeycomb-team=<key>"`.
- **A local Grafana** with the Docker stack. Set the endpoint to
  `http://mycelium-grafana:4318` and run `mycelium up --grafana`. Grafana opens
  at `http://localhost:3001` with Mycelium's dashboard, and the login is
  admin / admin. To also forward everything to a hosted backend, set
  `telemetry.forward_endpoint`.
- **A collector you run yourself.** The desktop app runs no collector or
  Grafana, so use one such as `http://127.0.0.1:4318`.

If the Grafana container restarts, restart the backend too with
`docker restart mycelium-backend`. Its OTLP connection doesn't reconnect.

## Agent telemetry over OTLP

The collector receives OpenTelemetry data from your agents. Start it with
`mycelium up --metrics`. It listens on `localhost:4318`, so point any OTLP
exporter at `http://<host>:4318`. It saves a combined snapshot that
`mycelium metrics` reads.

Spans that carry OpenTelemetry's GenAI attributes, such as `gen_ai.agent.name`
and `gen_ai.request.model`, can be grouped by agent, model and tool:

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
