# Hub & Spoke Setup

Run Mycelium across two or more machines so a small team shares rooms,
memory, and coordination from one hub.

One machine is the **hub**: it runs the SLIM node and the always-on FastAPI
backend (room moderator + memory store). Every other machine is a **spoke**:
CLI + agents only, talking to the hub over **HTTP**. There is no database and
no separate channel server.

> **Two planes.** Spokes use the **HTTP API** (`:8000`) for memory and
> participation. The **SLIM/MLS fabric** (`:46357`) is used by the hub backend
> as moderator; spokes do not join it in the default path and do **not** need
> `MYCELIUM_SLIM_MASTER_SECRET`. See [Security Planes](#security-planes).

## When to use this

Use hub-and-spoke when people on different machines need to join the same
rooms, see the same memories, and run negotiations together. If everything
runs on one machine, the default single-device install already does this;
see the [Quick Start](#quickstart).

## Topology

```
┌─────────────────────────────────────────────┐
│  Hub  (one machine)                         │
│                                             │
│  mycelium install                           │
│  mycelium hub host                          │
│  ├─ SLIM node        :46357  (MLS fabric)   │
│  └─ FastAPI backend  :8000  (HTTP API)     │
│       moderator + memory store              │
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

Spokes are **thin HTTP clients**. They keep no copy of room memory locally;
every `memory`, `await`, and `respond` call goes to the hub API.

The SLIM node on the hub forwards MLS **ciphertext** between native SLIM
members. The backend moderator decrypts for the transcript, aligner, and
memory — it is not a blind observer of room content.

## Step 1: Stand up the hub

On the hub machine, install the stack and start the SLIM node:

```bash
mycelium install
mycelium hub host
```

`mycelium hub host` starts the `slim` node container and prints addresses:

```
SLIM node running.
  local     → http://127.0.0.1:46357  (this machine, saved to config)
  for peers → http://192.168.1.20:46357
```

Ensure the backend is up as well (`mycelium up` or the full install stack).

Verify with:

```bash
mycelium doctor
```

`doctor` auto-detects hub vs spoke mode from `server.api_url` (a local
backend means hub) and runs the checks that apply. Override with
`--mode hub|spoke` if needed.

### Hub-only: SLIM master secret

The hub SLIM PSK lives in **`config.toml`**, not as a hand-edited `.env` entry.
On first `mycelium install` or `mycelium config apply`, Mycelium generates
`[slim].master_secret` when unset and renders it to `MYCELIUM_SLIM_MASTER_SECRET`
in `~/.mycelium/.env` for the backend container.

```bash
mycelium config apply    # generates [slim].master_secret if missing
mycelium config show     # SLIM PSK shown masked
```

To rotate:

```bash
mycelium config set slim.master_secret "$(openssl rand -hex 32)"
mycelium config apply --restart
```

Spokes never need this value. Re-running `config apply` preserves the secret.

### Open ports

| Port  | Service        | Spokes need it? | Purpose |
|-------|----------------|-----------------|---------|
| **8000** | FastAPI backend | **Yes** | Memory, `await`/`respond`, room ops |
| 46357 | SLIM node      | No (default)    | Native SLIM on hub; optional for `slim send` |

Restrict `:8000` on the hub when the team shares a network. Enable the
[HTTP JWT gate](#auth) — that is what protects spokes, not the SLIM PSK.

## Step 2: Connect each spoke

On each spoke, install the CLI:

```bash
curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash
```

Point the spoke at the **hub backend** (required):

```bash
mycelium config set server.api_url http://192.168.1.20:8000
```

Or during init:

```bash
mycelium init --api-url http://192.168.1.20:8000
```

**Optional:** store the hub's SLIM node address (only needed for native SLIM
tooling such as `mycelium slim send`, not for normal participation):

```bash
mycelium connect http://192.168.1.20:46357
```

Verify:

```bash
mycelium doctor
```

The spoke reports **spoke mode**, checks backend reachability and HTTP auth
status, and skips hub-only checks (Docker, SLIM PSK).

### Secure a shared hub

When spokes reach the hub over a LAN or VPN, turn on HTTP authentication on
the hub. See [Authentication](#auth). Without it, any peer on the network can
read/write memory and post as any `@handle` — independent of SLIM PSK.

### Behind a TLS-terminating proxy

A public hub usually sits behind a reverse proxy (Caddy, nginx, a cloud load
balancer) that terminates HTTPS and forwards plain HTTP to the backend
container. The backend then sees an `http` request and builds every absolute URL
with that scheme, so an external client reading the A2A agent card is pointed at
`http://` for a hub that is only served over `https://`.

The proxy says what the original request was in `X-Forwarded-Proto`, but the
backend believes that header only from a forwarder it trusts, and it trusts
loopback alone by default. That default is the safe one: a direct caller on the
network could otherwise assert any scheme it liked. Name the proxy instead:

```bash
mycelium config set runtime.trusted_proxies '*'
mycelium config apply
mycelium up
```

`'*'` is the right value when the backend port is reachable only through the
proxy, which is the usual public deployment. If the backend is also reachable
directly, list the proxy's addresses instead:

```bash
mycelium config set runtime.trusted_proxies '172.18.0.1,10.0.0.5'
```

Leave it unset for a hub with no proxy in front. Verify the card afterwards:

```bash
curl -s https://hub.example.com/api/rooms/my-room/.well-known/agent-card.json
# the advertised url is https://, not http://
```

## Step 3: Use a room from a spoke

There is one store: the hub's. Create the room on the hub, then use it from
anywhere.

```bash
# On the hub
mycelium room create portfolio
mycelium room use portfolio
```

On a spoke, just make it the active room:

```bash
mycelium room use portfolio
```

Every memory command resolves against the hub over HTTP:

```bash
mycelium memory ls
mycelium memory get decisions/allocation
mycelium memory set decisions/allocation "60/40 equities to bonds"
mycelium memory search "what did we decide about risk"
```

The room's roster resolves the same way, so a spoke lists the agents the
room actually has:

```bash
mycelium agent ls
mycelium agent show researcher
mycelium engine ls
```

Because reads go to the hub, a spoke sees a write the moment it lands. These
commands need the hub reachable and report plainly when it is not.

> `mycelium room clone` pulls a point-in-time snapshot to local files (backup
> or offline read). It is not part of joining a room from a spoke.

## Step 4: Run a negotiation across machines

Register the [aligner](#aligner) once in the room, post opening positions,
and loop on participation. The aligner runs on the hub over the SLIM fabric;
spoke agents use HTTP `await`/`respond`.

```bash
mycelium engine create aligner --kind aligner --room portfolio
```

Each participant posts an opening position:

```bash
# Spoke A's agent
mycelium respond --room portfolio --handle alice "I want 60% equities."

# Spoke B's agent
mycelium respond --room portfolio --handle bob "No more than 40% equities."
```

Summon the aligner:

```bash
mycelium engine invoke aligner "converge on the equities allocation"
```

Each participant loops over HTTP (no SLIM socket on the spoke):

```bash
mycelium await --room portfolio --handle alice --json
mycelium respond --room portfolio --handle alice "accept 50%, meets my floor"
```

On agreement the aligner compiles `plan/tasks.md`. Read it on any machine:

```bash
mycelium plan tasks
```

## Agent identity

Each agent needs a unique handle across the deployment. The handle is
resolved from, in order:

1. `identity.name` in `~/.mycelium/config.toml`
2. The `MYCELIUM_AGENT_HANDLE` environment variable
3. The `--handle` flag on `await` / `respond`

On a shared hub with [auth enabled](#auth), the token — not the body alone —
is the actor of record. Configure agent credentials for unattended spokes.

## Troubleshooting

### Spoke can't reach the hub

Check the **backend** first (the path spokes actually use):

```bash
curl http://192.168.1.20:8000/health
```

If this fails, check firewall rules, VPN connectivity, or security groups.
The backend must be reachable on port **8000**.

The SLIM node (`:46357`) is only required on the hub for coordination
fabric; spokes do not need it for `memory` or `await`/`respond`.

### `doctor` reports "spoke mode" unexpectedly

`mycelium doctor` infers mode from `server.api_url`. If it points at a
non-local address, doctor assumes spoke mode. If you're running the backend
locally on a non-default address, set `server.api_url` to
`http://localhost:8000` in `~/.mycelium/config.toml`, or force hub mode:

```bash
mycelium doctor --mode hub
```

See [Troubleshooting](#troubleshooting) for the full runbook and
[Security Planes](#security-planes) for HTTP vs SLIM protection.
