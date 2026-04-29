# Hub & Spoke Setup

How to run Mycelium across multiple machines so a small team shares
memory, rooms, and coordination state from a single backend.

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
│  ├─ Matrix / Synapse :8008       │
│  ├─ CFN mgmt plane   :9000      │
│  └─ CFN runtime      :9002      │
│                                  │
│  Channel servers (Matrix, etc)   │
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
mycelium doctor --mode hub
```

### Open ports

Spokes need to reach the hub on these ports:

| Port | Service | Required |
|------|---------|----------|
| 8000 | Mycelium backend (API + SSE) | Yes |
| 8008 | Matrix homeserver (Synapse) | If using Matrix channel |
| 9000 | CFN management plane | If using CognitiveEngine |
| 9002 | CFN runtime | If using CognitiveEngine |

Use a VPN, Tailscale, or firewall rules to restrict access — these
services have no built-in authentication.

### Configure channel servers

If agents coordinate via Matrix, set up Synapse on the hub and create
accounts for every agent across all spokes:

```bash
# Register agent accounts (on the hub)
# Each spoke's agents need a Matrix account on the hub's homeserver
```

Add all agent accounts to `channels.matrix.accounts` in the hub's
`~/.openclaw/openclaw.json`. The hub's gateway manages all Matrix
connections — spokes do not run their own Matrix clients.

## Step 2: Set up each spoke

On each spoke machine, install only the CLI (no `mycelium install`):

```bash
pip install mycelium-cli
# or
uv tool install mycelium-cli
```

### Point the spoke at the hub

```bash
mycelium init --api-url http://<hub-ip>:8000
```

This writes `~/.mycelium/config.toml` with the hub's API URL. Verify
the connection:

```bash
mycelium doctor --mode spoke
```

The doctor checks that the hub's backend is reachable and skips
Docker/database checks that only apply to hubs.

### Install the adapter

For OpenClaw agents:

```bash
mycelium adapter add openclaw
```

The adapter installs the Mycelium plugin into the local OpenClaw gateway.
The plugin connects to the hub's backend URL (from `config.toml`) for
SSE subscriptions and API calls.

After installing, restart the gateway:

```bash
openclaw gateway restart
```

### Spoke config summary

A spoke needs only two files:

| File | Purpose |
|------|---------|
| `~/.mycelium/config.toml` | Points `server.api_url` at the hub |
| `~/.openclaw/openclaw.json` | Agent definitions, Matrix credentials, plugin config |

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

When using OpenClaw with Matrix, agent handles should match their Matrix
user IDs (the localpart before the colon, e.g., `@agent-alpha:local` →
`agent-alpha`).

## Matrix token management

Matrix access tokens expire or become invalid after homeserver restarts.
When this happens, agents silently stop receiving messages.

Signs of expired tokens:

- Agents join sessions but never respond to coordination ticks
- Gateway logs show Matrix sync errors
- `mycelium doctor` reports Matrix connection failures

To refresh tokens, log in again via the Synapse admin API or re-register
the accounts, then update `channels.matrix.accounts[agent].accessToken`
in each node's `openclaw.json` and restart the gateway.

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
3. Verify Matrix tokens are valid (see above)

### Doctor reports "spoke mode" unexpectedly

`mycelium doctor` auto-detects mode from `server.api_url`. If it points
to a non-localhost address, doctor assumes spoke mode. Override with:

```bash
mycelium doctor --mode hub
```
