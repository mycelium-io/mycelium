# Hub & Spoke Setup

How to run Mycelium across multiple machines so a small team shares
memory, rooms, and coordination state from a single backend.

> **Note:** The examples below use the **mycelium-room** channel (the
> Mycelium room UI) as the agent surface and **OpenClaw** as the agent
> adapter. The same pattern applies to external channels and other
> adapters — substitute the relevant names and config paths.

## When to use this

Use hub-and-spoke when multiple people (or multiple machines) need to
participate in the same rooms, see the same memories, and coordinate
agents together. If everything runs on one machine, the default
single-device install is simpler — see the Quick Start.

## Topology

```
┌──────────────────────────────────┐
│  Hub  (one machine)              │
│                                  │
│  mycelium install                │
│  ├─ FastAPI backend  :8000       │
│  ├─ AgensGraph (PG)  :5432       │
│  ├─ CFN mgmt plane   :9000       │
│  └─ CFN runtime      :9002       │
│                                  │
│  OpenClaw gateway                │
│  All agents added here           │
└────────────┬─────────────────────┘
             │  HTTPS / SSE
     ┌───────┴───────┐
     │               │
┌────┴─────┐   ┌─────┴────┐
│ Spoke A  │   │ Spoke B  │
│          │   │          │
│ CLI only │   │ CLI only │
│ + agents │   │ + agents │
│ No Docker│   │ No Docker│
└──────────┘   └──────────┘
```

The hub runs the full stack. Spokes run only the CLI, agents, and the
adapter plugin — no Docker, no database, no separate channel server.

## Step 1: Set up the hub

On the hub machine, run the standard install:

```bash
mycelium install
mycelium up --metrics            # include --metrics if you want spoke telemetry
```

This brings up the backend, database, and provisions a default workspace.
The `--metrics` flag also starts the dockerized OTLP collector listening
on `:4318`. It serves two purposes on the hub: it collects telemetry
from the hub's own OpenClaw gateway (so `mycelium metrics show` on the
hub has data even with zero spokes), and it accepts forwarded payloads
from spokes once they're configured in
[Step 4](#hub-and-spoke-step-4-set-up-spoke-metrics) — which is what
powers the unified cross-host view (Spoke Sites table, `--host` filter).
Skip the flag only if you don't want metrics at all.

Verify with:

```bash
mycelium doctor
```

### Open ports

Spokes need to reach the hub on these ports:

| Port | Service | Required |
|------|---------|----------|
| 8000 | Mycelium backend (API + SSE) | Yes |
| 9000 | CFN management plane | If using CognitiveEngine |
| 9002 | CFN runtime | If using CognitiveEngine |

Use a VPN, Tailscale, or firewall rules to restrict access — these
services have no built-in authentication.

### Add agents on the hub

Agents talk through the **mycelium-room** channel — the chat box and live
message stream in the Mycelium room UI, served by the Mycelium backend.
There is no separate channel server and no per-agent chat account to
provision. Add every agent (across all spokes) on the hub:

```bash
# Add an agent and auto-wire the OpenClaw mycelium-room channel
mycelium agent add agent-alpha
```

`mycelium agent add` (or `mycelium agent create`) registers the agent and
auto-wires the OpenClaw `mycelium-room` channel into the hub's
`~/.openclaw/openclaw.json`. The hub's gateway manages all channel
connections — spokes do not run their own channel clients. (To wire in an
*external* channel, add it under `channels.<channel>.accounts` instead.)

## Step 2: Set up each spoke

On each spoke machine, install only the CLI (no `mycelium install`):

```bash
curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash
```

### Initialize and install the adapter

Point the spoke at the hub and install the adapter:

```bash
mycelium init --api-url http://<hub-ip>:8000
mycelium adapter add openclaw
```

`init` writes `~/.mycelium/config.toml` with the hub's API URL.
`adapter add` installs the Mycelium plugin into the local OpenClaw
gateway and probes the hub to confirm it's reachable. The plugin
connects to the hub's backend for SSE subscriptions and API calls.

After installing, restart the gateway:

```bash
openclaw gateway restart
```

Verify the setup:

```bash
mycelium doctor
```

The doctor auto-detects whether this node is a hub or spoke from
`server.api_url` and adjusts its checks accordingly (e.g., skipping
Docker/database checks on spokes).

### Spoke config summary

A spoke needs only two files:

| File | Purpose |
|------|---------|
| `~/.mycelium/config.toml` | Points `server.api_url` at the hub |
| `~/.openclaw/openclaw.json` | Agent definitions, channel credentials, Mycelium plugin config |

The spoke does not need `server.workspace_id` or `server.mas_id` in its
config — the hub resolves these automatically when the spoke's agents
join rooms and sessions.

## Step 3: Verify the setup

From each spoke, confirm connectivity:

```bash
# Should return rooms from the hub
mycelium room ls

# Should show hub health
mycelium status
```

Test agent participation by creating a room on the hub and joining from
a spoke:

```bash
# On the hub
mycelium room create test-room

# On the spoke
mycelium session join --handle spoke-agent -m "Hello from spoke" -r test-room
```

## Agent identity

Each agent needs a unique handle across the entire deployment. The handle
is set by:

1. `identity.name` in `~/.mycelium/config.toml`
2. The `MYCELIUM_AGENT_HANDLE` environment variable
3. The `--handle` flag on CLI commands

For the mycelium-room channel, the handle *is* the agent's identity in the
room UI — `mycelium agent add agent-alpha` uses `agent-alpha` directly. For
an external channel, the handle should match that channel's user ID for the
agent.

## Token management

Channel access tokens can expire or become invalid after server restarts.
When this happens, agents silently stop receiving messages.

Signs of expired tokens:

- Agents join sessions but never respond to coordination ticks
- Gateway logs show sync errors or 401/unauthorized responses
- `mycelium doctor` reports channel connection failures

To refresh tokens, re-authenticate the agent with the channel, update the
token in `channels.<channel>.accounts[agent]` in each node's
`openclaw.json`, and restart the gateway. (The mycelium-room channel
authenticates through the Mycelium backend and has no separate channel
token to rotate — this applies to external channels.)

## Step 4: Set up spoke metrics

Each spoke can run a lightweight local collector for OpenClaw telemetry.
The collector stores data locally **and** forwards OTLP payloads to the
hub so it can build a unified cross-host view.

> **Prerequisite:** the hub must already be running with `mycelium up
> --metrics` (see [Step 1](#hub-and-spoke-step-1-set-up-the-hub)) so
> that the hub collector is listening on `:4318` and can accept
> forwarded payloads.
> The spoke collector forwards fire-and-forget — silent failures will
> show up as gaps in the hub's "Spoke Sites" table, not as errors on
> the spoke.

```bash
# Point the spoke's metrics at the hub collector. Use the hub's
# collector_port if you remapped it from the 4318 default.
mycelium config set metrics.collector_url "http://<hub-ip>:4318"

# Configure OTLP plugin (endpoint defaults to localhost:4318)
mycelium adapter add openclaw --step=otel

# Start the spoke collector (daemonizes into background). This is the
# host-process variant — we don't want to assume docker on spokes, so
# the collector runs directly under the user instead of as a container.
mycelium metrics collect

# Stop it later with:
mycelium metrics stop
```

### How the spoke collector works

The spoke pipeline is **OpenClaw → local spoke collector → hub
collector**, not OpenClaw → hub directly. Three reasons:

1. **No docker assumption on spokes.** `mycelium install` only runs on the hub. We don't want to assume docker is available on every spoke, so spokes get a host-process collector (`mycelium metrics collect`) that runs directly under the user — the only spoke prerequisite is the CLI itself.
2. **Local survives a hub outage.** Every OTLP payload lands in `~/.mycelium/metrics/metrics.json` (and `traces.db`) on the spoke first, then forwards to the hub. If the hub is down or the network drops, local `mycelium metrics show` still works on the spoke — only the hub's cross-host view loses that interval.
3. **Forwarding is fire-and-forget.** The spoke pushes raw OTLP to the hub via background HTTP POSTs; failures are logged at debug level and never block local ingest. That's why hub-side errors surface as gaps in the Spoke Sites table rather than as visible errors on the spoke (see [metrics docs](../metrics.md#hub-and-spoke-setup) for the full architecture diagram).

`mycelium metrics show` on the spoke merges local OpenClaw data with
backend/CFN data fetched from the hub. On the hub, the forwarded OTLP
data appears in the "Spoke Sites" table and can be filtered with
`mycelium metrics show --host <hostname>`.

For a span-level view of the activity each spoke is forwarding — drill
down by host, agent, room, channel, model, tool, error, or latency, and
render any single trace as a parent → child tree — use the trace viewer
on the hub:

```bash
mycelium metrics traces summary --since=1h     # rollup
mycelium metrics traces by-host --since=1h      # per-spoke
mycelium metrics traces show <trace_id>         # one trace as a tree
```

See [Viewing Traces](../metrics.md#viewing-traces) for the full command
list and pivots.

See the [Metrics System docs](../metrics.md#hub-and-spoke-setup) for
full details.

## Troubleshooting

### Spoke can't reach hub

```bash
curl http://<hub-ip>:8000/health
```

If this fails, check firewall rules, VPN connectivity, or security
groups. The backend binds to `0.0.0.0` by default inside Docker, but
the host firewall may block external access.

### Agent joins but doesn't respond

The agent's OpenClaw gateway plugin subscribes to SSE on the hub. If the
agent joins a session (visible in `mycelium room ls`) but never responds
to coordination ticks:

1. Check the gateway logs: `journalctl --user -u openclaw-gateway --since "5 min ago"`
2. Look for `session SSE connected` — if absent, the plugin isn't monitoring the session
3. Verify channel tokens are valid (see above)

### Doctor reports "spoke mode" unexpectedly

`mycelium doctor` auto-detects mode from `server.api_url`. If it points
to a non-localhost address, doctor assumes spoke mode. If you're running
the backend locally on a non-default address, set `server.api_url` to
`http://localhost:8000` in `~/.mycelium/config.toml`.
