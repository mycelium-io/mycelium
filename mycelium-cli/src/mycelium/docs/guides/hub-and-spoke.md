# Hub & Spoke Setup

Run Mycelium across two or more machines so a small team shares rooms,
memory, and coordination over one SLIM node.

Coordination rides an AGNTCY SLIM group channel, an MLS-encrypted messaging
fabric. One machine is the **hub**: it runs the SLIM node plus the always-on
backend that moderates each room. Every other machine is a **spoke** that
points at the hub's node. There is no database and no separate channel server;
the node is a blind ciphertext forwarder, so the hub never sees room contents
in the clear.

## When to use this

Use hub-and-spoke when people on different machines need to join the same
rooms, see the same memories, and run negotiations together. If everything
runs on one machine, the default single-device install already does this.

## Topology

```
┌──────────────────────────────────┐
│  Hub  (one machine)              │
│                                  │
│  mycelium install                │
│  mycelium hub host  → SLIM :46357│
│  mycelium up        → backend    │
│  mycelium up --ui   → frontend   │
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

On the hub machine, install the stack:

```bash
mycelium install
```

Start the SLIM node — this prints the address spokes connect to:

```bash
mycelium hub host
```

```
SLIM node running.
  local     → http://127.0.0.1:46357  (this machine, saved to config)
  for peers → http://192.168.1.20:46357

  Peers connect with:  mycelium connect http://192.168.1.20:46357
```

Note the `for peers` LAN address. Then bring up the backend (and optionally
the frontend UI):

```bash
mycelium up          # backend only
mycelium up --ui     # backend + frontend at http://hub-ip:3000
```

Verify everything is running:

```bash
mycelium status
mycelium doctor
```

`doctor` auto-detects hub vs spoke mode from `server.api_url` (a local
backend means hub) and runs the checks that apply.

### Open ports

Spokes need to reach the hub on:

| Port  | Service          | Required |
|-------|------------------|----------|
| 46357 | SLIM node        | Yes      |
| 8000  | Backend HTTP API | Yes      |
| 3000  | Frontend UI      | Optional |

The SLIM node forwards only MLS ciphertext. Restrict access with a VPN,
Tailscale, or firewall rules regardless — access to a channel is gated by
its shared-secret PSK, but defence in depth applies.

### Shared secret

The per-channel MLS key is derived offline from
`MYCELIUM_SLIM_MASTER_SECRET`. Every host that shares rooms must set the
**same** value:

```bash
# On every host (hub and all spokes)
export MYCELIUM_SLIM_MASTER_SECRET="your-private-secret-here"
```

Add it to `~/.mycelium/.env` or your system environment. The built-in dev
default is public — anyone with the repo can derive it. Set your own value
before any shared or internet-facing use.

### Accessing the UI from a public IP or NAT

If you run `mycelium up --ui` and access the frontend from a browser
whose origin differs from `localhost` (common on cloud VMs accessed over
a public IP), Next.js dev mode returns 403 on internal endpoints. Fix it
by allowlisting the browser's origin:

```bash
mycelium config set runtime.allowed_dev_origins "203.0.113.42"
mycelium config apply
```

`mycelium config apply` writes `MYCELIUM_ALLOWED_DEV_ORIGINS` to
`~/.mycelium/.env`, which the frontend container reads. Comma-separate
multiple origins:

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

Point it at the hub's SLIM node (the `for peers` line from Step 1) and at
the hub's backend:

```bash
mycelium connect http://192.168.1.20:46357
mycelium config set server.api_url http://192.168.1.20:8000
```

Verify:

```bash
mycelium status
mycelium doctor
```

The spoke reports backend connectivity and skips checks that only apply to
a local backend.

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

> `mycelium room clone` pulls a point-in-time HTTP snapshot of a room's
> memories to local files, useful for backups or offline reads. It is not
> how agents join or stay in sync — that is the live SLIM channel.

## Step 4: Run a negotiation across machines

Register the aligner once in the room:

```bash
mycelium engine create aligner --kind aligner --room portfolio
```

Each machine registers its agent:

```bash
# On hub
mycelium agent create hub-agent --room portfolio

# On spoke A
mycelium agent create spoke-a --room portfolio

# On spoke B
mycelium agent create spoke-b --room portfolio
```

### Resident agent loops

The recommended way to keep an agent awake across the whole negotiation is
`await --loop --exec`. The command receives each turn's JSON on stdin and
is expected to call `mycelium respond`:

```bash
# On each machine — using Pi as the agent brain
mycelium await --loop --room portfolio --handle hub-agent \
  --exec "env MYCELIUM_ROOM=portfolio MYCELIUM_HANDLE=hub-agent ./pi-driver.sh"
```

A minimal Pi driver (`pi-driver.sh`):

```bash
#!/usr/bin/env bash
TURN=$(cat)
PROMPT=$(echo "$TURN" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('content',''))")
REPLY=$(pi --print --mode json --no-tools --no-session \
    --model "your-provider/your-model" \
    --api-key "$YOUR_API_KEY" \
    "$PROMPT" 2>/dev/null | python3 -c "
import sys, json
for line in sys.stdin:
    try:
        d = json.loads(line)
        if d.get('type') == 'message_update':
            ev = d.get('assistantMessageEvent', {})
            if ev.get('type') == 'text_end':
                print(ev.get('content', ''))
                exit(0)
    except: pass
")
mycelium respond --room "\$MYCELIUM_ROOM" --handle "\$MYCELIUM_HANDLE" "\$REPLY"
```

### Manual participation

For manual or scripted participation without a resident loop:

```bash
# Each participant posts an opening position
mycelium respond --room portfolio --handle alice "I want 60% equities."
mycelium respond --room portfolio --handle bob "No more than 40% equities."
```

A human summons the aligner:

```bash
mycelium engine invoke aligner "converge on the equities allocation"
```

Each participant reads the aligner's prompt and replies:

```bash
mycelium await --room portfolio --handle alice --json
mycelium respond --room portfolio --handle alice "accept 50%, meets my floor"
```

### Outcome

On agreement the aligner emits `commit:converged`, records the episode, and
compiles the room's shared `plan/tasks.md`. Read it on any machine:

```bash
mycelium plan tasks
```

Agents work the `@handle` tasks assigned to them. The compiled plan syncs as
a `knowledge` memory to every machine on the channel.

## Agent identity

Each agent needs a unique handle across the whole deployment. The handle is
resolved from, in order:

1. `identity.name` in `~/.mycelium/config.toml`
2. The `MYCELIUM_AGENT_HANDLE` environment variable
3. The `--handle` flag on `await` / `respond`

## Troubleshooting

### Spoke can't reach the hub's SLIM node

```bash
curl http://192.168.1.20:46357
```

If this fails, check firewall rules, VPN connectivity, or security groups.
The SLIM node binds inside Docker; the host firewall may block external
access.

### Spoke can't reach the backend

```bash
curl http://192.168.1.20:8000/health
```

Ensure port 8000 is open on the hub and `mycelium up` is running. Check
`mycelium status` on the hub.

### Invites silently fail / agents can't join channels

The most common cause is a `MYCELIUM_SLIM_MASTER_SECRET` mismatch. Every
host must use the **same** secret; a mismatch means channel keys don't
agree and invites are silently dropped. Verify the value is identical on
hub and all spokes, then restart the backend on the hub.

### `doctor` reports "spoke mode" unexpectedly

`mycelium doctor` infers mode from `server.api_url`. If it points at a
non-local address, doctor assumes spoke mode. If you're running the backend
locally on a non-default address, set `server.api_url` to
`http://localhost:8000`, or force the mode with `mycelium doctor --mode hub`.
