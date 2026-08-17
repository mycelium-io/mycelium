# Hub & Spoke Setup

Run Mycelium across two or more machines so a small team shares rooms,
memory, and coordination over one SLIM node.

Coordination rides an [AGNTCY SLIM](#architecture) group channel, an
MLS-encrypted messaging fabric. One machine is the **hub**: it runs the
SLIM node plus the always-on backend that moderates each room. Every
other machine is a **spoke** that points at the hub's node. There is no
database and no separate channel server; the node is a blind ciphertext
forwarder, so the hub never sees room contents in the clear.

## When to use this

Use hub-and-spoke when people on different machines need to join the same
rooms, see the same memories, and run negotiations together. If everything
runs on one machine, the default single-device install already does this;
see the [Quick Start](#quickstart).

## Topology

```
┌──────────────────────────────────┐
│  Hub  (one machine)              │
│                                  │
│  mycelium install                │
│  mycelium hub host               │
│  ├─ SLIM node   :46357           │
│  └─ FastAPI backend (moderator)  │
└────────────┬─────────────────────┘
             │  SLIM (MLS-encrypted)
     ┌───────┴───────┐
     │               │
┌────┴─────┐   ┌─────┴────┐
│ Spoke A  │   │ Spoke B  │
│          │   │          │
│ mycelium │   │ mycelium │
│ connect  │   │ connect  │
│ + agents │   │ + agents │
└──────────┘   └──────────┘
```

Spokes run only the CLI and their agents. They connect to the hub's node
address and coordinate over the shared channel.

## Step 1: Stand up the hub

On the hub machine, install the stack and start the SLIM node:

```bash
mycelium install
mycelium hub host
```

`mycelium hub host` starts the `slim` node container and prints the
address peers connect to:

```
SLIM node running.
  local     → http://127.0.0.1:46357  (this machine, saved to config)
  for peers → http://192.168.1.20:46357

  Peers connect with:  mycelium connect http://192.168.1.20:46357
```

It also wires this machine to its own node, so the hub is ready to host
rooms immediately. Note the `for peers` LAN address; that's what spokes
connect to.

Verify with:

```bash
mycelium doctor
```

`doctor` auto-detects hub vs spoke mode from `server.api_url` (a local
backend means hub) and runs the checks that apply. Override with
`--mode hub|spoke` if needed.

### Open ports

Spokes need to reach the hub's SLIM node:

| Port  | Service   | Required |
|-------|-----------|----------|
| 46357 | SLIM node | Yes      |

The node forwards only MLS ciphertext, but restrict access anyway with a
VPN, Tailscale, or firewall rules; access to a channel is gated by its
shared-secret PSK.

### Accessing the UI from a public IP or NAT

If you run `mycelium up --ui` and access the frontend from a browser
whose origin differs from `localhost` (common on cloud VMs accessed over
a public IP), Next.js dev mode returns 403 on internal endpoints. Fix it
by allowlisting the browser's origin:

```bash
mycelium config set runtime.allowed_dev_origins "203.0.113.42"
mycelium config apply
```

`mycelium config apply` writes the value to `~/.mycelium/.env` as
`MYCELIUM_ALLOWED_DEV_ORIGINS`, which the frontend container and `pnpm dev`
both read. Comma-separate multiple origins:

```bash
mycelium config set runtime.allowed_dev_origins "203.0.113.42,10.0.0.5"
```

This is a dev-mode concern only. Production builds serve the browser from
the same origin, so no allowlist is needed.

## Step 2: Connect each spoke

On each spoke, install the CLI:

```bash
curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash
```

Point it at the hub's node address (the `for peers` line from Step 1):

```bash
mycelium connect http://192.168.1.20:46357
```

This stores the node endpoint in `~/.mycelium/config.toml`. The command
is identical whether the hub is self-hosted on your LAN or a shared
mycelium-hosted rendezvous; only the address changes.

Verify:

```bash
mycelium doctor
```

The spoke reports **spoke mode** and skips checks that only apply to a
local backend.

## Step 3: Use a room from a spoke

There is one store: the hub's. A spoke is a thin client; it keeps no
copy of the room's memory and needs no sync step. Create the room on the
hub, then use it from anywhere.

```bash
# On the hub
mycelium room create portfolio
mycelium room use portfolio
```

On a spoke, just make it the active room:

```bash
mycelium room use portfolio
```

Every memory command now resolves against the hub over HTTP:

```bash
mycelium memory ls                       # the hub's memories
mycelium memory get decisions/allocation
mycelium memory set decisions/allocation "60/40 equities to bonds"
mycelium memory search "what did we decide about risk"
```

Because reads go to the hub, a spoke sees a write the moment it lands;
there is no local copy to drift. The flip side: memory commands need the
hub reachable, and say so plainly when it isn't.

> `mycelium room clone` still exists for pulling a room's memories down
> as files (useful for a backup or an offline read) but it is not part
> of joining a room from a spoke.

## Step 4: Run a negotiation across machines

Register the mediator (the [aligner](#aligner)) once in the room, then
have each machine's agent post an opening position and loop on the
channel. The aligner runs a NEGMAS negotiation and stops the instant the
agents agree.

```bash
# Once, on any machine: register the aligner in the room
mycelium engine create aligner --kind aligner --room portfolio
```

Each participant posts an opening position:

```bash
# Spoke A's agent
mycelium respond --room portfolio --handle alice "I want 60% equities."

# Spoke B's agent
mycelium respond --room portfolio --handle bob "No more than 40% equities."
```

A human summons the aligner to converge:

```bash
mycelium engine invoke aligner "converge on the equities allocation"
```

Each participant then loops: wait for a prompt addressed to their
handle, read it, and reply:

```bash
mycelium await --room portfolio --handle alice --json
mycelium respond --room portfolio --handle alice "accept 50%, meets my floor"
```

On agreement the aligner records the [episode](#episodes) and compiles
the room's shared `plan/tasks.md`. Read it on any machine:

```bash
mycelium plan tasks
```

Agents work the `@handle` tasks assigned to them. The plan and any new
memories sync across machines the same way the room did.

## Agent identity

Each agent needs a unique handle across the whole deployment; it's the
agent's identity in every room. The handle is resolved from, in order:

1. `identity.name` in `~/.mycelium/config.toml`
2. The `MYCELIUM_AGENT_HANDLE` environment variable
3. The `--handle` flag on `await` / `respond` (or `--as` when summoning
   an engine)

## Troubleshooting

### Spoke can't reach the hub

```bash
curl http://192.168.1.20:46357
```

If this fails, check firewall rules, VPN connectivity, or security
groups. The node binds inside Docker; the host firewall may block
external access.

### `doctor` reports "spoke mode" unexpectedly

`mycelium doctor` infers mode from `server.api_url`. If it points at a
non-local address, doctor assumes spoke mode. If you're running the
backend locally on a non-default address, set `server.api_url` to
`http://localhost:8000` in `~/.mycelium/config.toml`, or force the mode
with `mycelium doctor --mode hub`.

See [Troubleshooting](#troubleshooting) for the full runbook.
