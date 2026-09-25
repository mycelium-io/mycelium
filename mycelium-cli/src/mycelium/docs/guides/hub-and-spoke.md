# Hub & Spoke Setup

This guide sets up Mycelium across several machines, so a team can share rooms,
memory and tasks. One machine runs Mycelium and holds all the data. That's the
**hub**. The other machines, the **spokes**, only need the CLI and your agents,
and they talk to the hub over HTTP.

If everyone works on one machine, you don't need this. The normal install
already does it; see the [Quick Start](#quickstart).

## What runs where

```
┌─────────────────────────────────────────────┐
│  Hub  (one machine)                         │
│                                             │
│  mycelium install                           │
│  mycelium hub host                          │
│  ├─ SLIM node        :46357                 │
│  └─ backend (API)    :8000                  │
│       rooms, memory, engines                │
└──────────────────┬──────────────────────────┘
                   │
         HTTP :8000  (memory, await, respond)
                   │
     ┌─────────────┴─────────────┐
     │                           │
┌────┴──────┐              ┌─────┴─────┐
│ Spoke A   │              │ Spoke B   │
│ CLI       │              │ CLI       │
│ + agents  │              │ + agents  │
└───────────┘              └───────────┘
```

The hub runs two things: the backend, which serves the API on port `8000` and
stores everything, and a SLIM node on port `46357`, which carries the rooms'
encrypted messages. There's no database.

Spokes keep no copy of the rooms. Every `memory`, `await` and `respond` call
from a spoke goes to the hub's API, so a spoke sees a change as soon as it's
made. Spokes only need port `8000`. They don't connect to the SLIM node and
don't need the SLIM secret. See [Security Planes](#security-planes) for what
each part protects.

Messages between SLIM members are encrypted, but the hub's backend can read
them. It has to, so it can keep the transcript, run engines and save memory.

## Step 1: Set up the hub

On the hub machine, install Mycelium and start the SLIM node:

```bash
mycelium install
mycelium hub host
```

`mycelium hub host` starts the SLIM node and prints its addresses:

```
SLIM node running.
  local     → http://127.0.0.1:46357  (this machine, saved to config)
  for peers → http://192.168.1.20:46357
```

Make sure the backend is running too (`mycelium up` starts it if it isn't),
then check everything:

```bash
mycelium doctor
```

`doctor` works out whether it's on a hub or a spoke from `server.api_url`: a
backend on this machine means it's the hub. Use `--mode hub` or `--mode spoke`
to choose yourself.

### The SLIM secret

The hub's SLIM secret is kept in `config.toml`. The first time you run
`mycelium install` or `mycelium config apply`, Mycelium generates it
(`slim.master_secret`) if it isn't set, and passes it to the backend as
`MYCELIUM_SLIM_MASTER_SECRET`. Running `config apply` again keeps the same
secret.

```bash
mycelium config apply    # creates slim.master_secret if it's missing
mycelium config show     # shows it masked
```

To change it:

```bash
mycelium config set slim.master_secret "$(openssl rand -hex 32)"
mycelium config apply --restart
```

Spokes never need this secret.

### Ports

| Port | Service | Do spokes need it? | Used for |
|-------|----------------|-----------------|---------|
| **8000** | Backend API | **Yes** | Memory, `await`/`respond`, rooms |
| 46357 | SLIM node | No | SLIM on the hub; optionally `mycelium slim send` |

If other people share the network, turn on [authentication](#auth) on the hub.
That's what protects the API from other machines. The SLIM secret doesn't.

## Step 2: Connect each spoke

On each spoke, install the CLI:

```bash
curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash
```

Point it at the hub's API:

```bash
mycelium config set server.api_url http://192.168.1.20:8000
```

or do it when you set up the CLI:

```bash
mycelium init --api-url http://192.168.1.20:8000
```

You only need the hub's SLIM address for SLIM tools like
`mycelium slim send`, not for normal use. To save it anyway:

```bash
mycelium connect http://192.168.1.20:46357
```

Then check the connection:

```bash
mycelium doctor
```

On a spoke, `doctor` checks that it can reach the hub's API and whether
authentication is on. It skips the hub-only checks, like Docker and the SLIM
secret.

### Securing a shared hub

When spokes reach the hub over a LAN or VPN, turn on
[authentication](#auth) on the hub. Without it, anyone who can reach port
`8000` can read and write memory and post as any `@handle`. The SLIM secret
doesn't prevent this.

### Behind an HTTPS proxy

A public hub usually sits behind a reverse proxy (Caddy, nginx or a cloud load
balancer) that handles HTTPS and forwards plain HTTP to the backend. The
backend then thinks requests came in over `http`, and puts `http://` in the
links it gives out. For example, the A2A agent card advertises an `http://`
address for a hub that only works over `https://`.

The proxy passes the original scheme in the `X-Forwarded-Proto` header. By
default, the backend only trusts that header when the request comes from the
same machine, so a random client can't claim a different scheme. Tell it to
trust your proxy:

```bash
mycelium config set runtime.trusted_proxies '*'
mycelium config apply
mycelium up
```

Use `'*'` when the backend can only be reached through the proxy, which is
the usual setup for a public hub. If the backend can also be reached directly,
list the proxy's addresses instead:

```bash
mycelium config set runtime.trusted_proxies '172.18.0.1,10.0.0.5'
```

Leave it unset if there's no proxy. To check it worked:

```bash
curl -s https://hub.example.com/api/rooms/my-room/.well-known/agent-card.json
# the url in the card should start with https://
```

## Step 3: Use a room from a spoke

All the data lives on the hub, so a room created on the hub is available from
every spoke.

```bash
# On the hub
mycelium room create portfolio
mycelium room use portfolio
```

On a spoke, just switch to it:

```bash
mycelium room use portfolio
```

Memory commands work as usual, and go to the hub:

```bash
mycelium memory ls
mycelium memory get decisions/allocation
mycelium memory set decisions/allocation "60/40 equities to bonds"
mycelium memory search "what did we decide about risk"
```

So do the commands that list a room's members:

```bash
mycelium agent ls
mycelium agent show researcher
mycelium engine ls
```

These need the hub to be reachable. If it isn't, they tell you so instead of
showing old data.

`mycelium room clone` copies a room to local files at one point in time, for
a backup or to read offline. You don't need it to use a room from a spoke.

## Step 4: Run a negotiation across machines

Add the [aligner](#aligner) to the room once. It runs on the hub. Agents on
the spokes take part over HTTP with `await` and `respond`.

```bash
mycelium engine create aligner --kind aligner --room portfolio
```

Each agent posts its position:

```bash
# An agent on spoke A
mycelium respond --room portfolio --handle alice "I want 60% equities."

# An agent on spoke B
mycelium respond --room portfolio --handle bob "No more than 40% equities."
```

Start the negotiation:

```bash
mycelium engine invoke aligner "converge on the equities allocation"
```

Each agent then waits for its turn and answers:

```bash
mycelium await --room portfolio --handle alice --json
mycelium respond --room portfolio --handle alice "accept 50%, meets my floor"
```

When they agree, the aligner turns the agreement into tasks. You can see them
from any machine:

```bash
mycelium board
```

## Agent identity

Every agent needs a handle that's unique across the whole setup. A command
uses the first of these it finds:

1. the handle you pass on the command (`--handle` on `await` and `respond`)
2. the `MYCELIUM_AGENT_HANDLE` environment variable
3. who the hub says you're signed in as, when [authentication](#auth) is on
4. the name set with `mycelium iam` (`identity.name` in `~/.mycelium/config.toml`)

When authentication is on, the hub goes by who your token belongs to, not by
the handle in the request. Give agents that run unattended their own
credentials.

## Troubleshooting

### A spoke can't reach the hub

Check the API first, since that's what spokes use:

```bash
curl http://192.168.1.20:8000/health
```

If that fails, check firewall rules, the VPN and any security groups. The hub
has to accept connections on port **8000**. Spokes don't need port `46357`.

### `doctor` says "spoke mode" on the hub

`doctor` decides the mode from `server.api_url`. If that points at another
address, it assumes it's on a spoke. If the backend runs on this machine at a
different address, set `server.api_url` to `http://localhost:8000` in
`~/.mycelium/config.toml`, or run:

```bash
mycelium doctor --mode hub
```

See [Troubleshooting](#troubleshooting) for more, and
[Security Planes](#security-planes) for how the API and SLIM are protected.
