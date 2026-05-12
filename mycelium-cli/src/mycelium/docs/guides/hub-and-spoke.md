# Hub & Spoke Setup

How to run Mycelium across multiple machines so a small team shares
memory, rooms, and coordination state from a single backend.

> **Note:** The examples below use **Matrix** as the channel server and
> **OpenClaw** as the agent adapter. The same pattern applies to other
> channels (Discord, Slack, etc.) and adapters — substitute the
> relevant names and config paths.

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
│  ├─ Channel server   :8008       │
│  ├─ CFN mgmt plane   :9000       │
│  └─ CFN runtime      :9002       │
│                                  │
│  Channel servers                 │
│  All agent accounts defined here │
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
adapter plugin — no Docker, no database, no channel servers.

## Step 1: Set up the hub

On the hub machine, run the standard install:

```bash
mycelium install
```

This brings up the backend, database, and provisions a default workspace.
Verify with:

```bash
mycelium doctor
```

### Open ports

Spokes need to reach the hub on these ports:

| Port | Service | Required |
|------|---------|----------|
| 8000 | Mycelium backend (API + SSE) | Yes |
| 8008 | Channel server (Matrix/Synapse in this example) | If using a channel server |
| 9000 | CFN management plane | If using CognitiveEngine |
| 9002 | CFN runtime | If using CognitiveEngine |

Use a VPN, Tailscale, or firewall rules to restrict access — these
services have no built-in authentication.

### Configure the channel server

Run the channel server on the hub and create accounts for every agent
across all spokes. For Matrix, this means running Synapse on the hub
and registering each agent:

```bash
# Register agent accounts on the hub's Synapse instance
register_new_matrix_user -c /etc/synapse/homeserver.yaml http://localhost:8008
```

Add all agent accounts to `channels.matrix.accounts` in the hub's
`~/.openclaw/openclaw.json`. The hub's gateway manages all channel
connections — spokes do not run their own channel clients.

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

Agent handles should match their channel user IDs. For Matrix, use the
localpart before the colon: `@agent-alpha:local` → `agent-alpha`.

## Token management

Channel access tokens can expire or become invalid after server restarts.
When this happens, agents silently stop receiving messages.

Signs of expired tokens:

- Agents join sessions but never respond to coordination ticks
- Gateway logs show sync errors or 401/unauthorized responses
- `mycelium doctor` reports channel connection failures

To refresh tokens, re-authenticate with the channel server (for Matrix,
log in again via the Synapse admin API), update the token in
`channels.<channel>.accounts[agent]` in each node's `openclaw.json`,
and restart the gateway.

## Step 4: Set up spoke metrics

Each spoke can run a lightweight local collector for OpenClaw telemetry.
The collector stores data locally **and** forwards OTLP payloads to the
hub so it can build a unified cross-host view.

```bash
# Point the spoke's metrics at the hub collector
mycelium config set metrics.collector_url "http://<hub-ip>:4318"

# Configure OTLP plugins (endpoint defaults to localhost:4318)
mycelium adapter add openclaw --step=otel --step=deep-observability

# Start the spoke collector (foreground)
mycelium metrics collect
```

`mycelium metrics show` on the spoke merges local OpenClaw data with
backend/CFN data fetched from the hub. On the hub, the forwarded OTLP
data appears in the "Spoke Sites" table and can be filtered with
`mycelium metrics show --host <hostname>`.

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
