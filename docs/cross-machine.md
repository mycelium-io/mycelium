# Cross-machine coordination

How two people on two laptops run the mycelium hero flow through **one shared SLIM
node**. This is the LAN path; the open-internet path is documented at the bottom.

> **Watching it in the browser.** The flow below is headless. To watch it, start the
> stack with the UI (`mycelium up --ui`) and see [Watching it in the
> browser](#watching-it-in-the-browser) at the bottom.

## Roles

- **Hub (owner / moderator).** Runs the shared SLIM node (`mycelium hub host`) **and**
  the always-on backend that provisions and **moderates** each room channel (creates
  the group, invites members, persists the transcript, runs the aligner + plan sync).
  One moderator per room; see the traps below.
- **Spoke (member).** Points at the hub's node with `mycelium connect
  http://<hub-ip>:46357`, then registers an agent that participates as a resident
  runtime (`mycelium await --loop`) on the room channel. A spoke is a *member* of
  the channel, never a second moderator.

Membership is addressed by **identity** (`workspace/room/agent`), never by host, so the
moderator invites a spoke's agent exactly as it would a local one: the consent →
invite → join path needs no cross-machine mechanism.

## The hero flow, across two hosts

Bring up the fabric and point the spoke at it:

```bash
# Hub
mycelium hub host                          # SLIM node + backend; prints the LAN address

# Spoke
mycelium connect http://<hub-ip>:46357     # point at the hub's node
```

Share a room and register participants (the room is created on the hub; the spoke's
agent joins the same room channel):

```bash
# Hub
mycelium room create planning
mycelium room use planning
mycelium engine create aligner --kind aligner --room planning   # register the mediator once
mycelium agent create hub-agent --room planning

# Spoke
mycelium agent create spoke-agent --room planning               # resident runtime joins the channel
```

Run the negotiation. Each participant posts an opening position, a human summons the
aligner, and participants loop await → respond until it converges:

```bash
# Each participant posts an opening position
mycelium respond --room planning --handle hub-agent   "I want blue-green deploys."
mycelium respond --room planning --handle spoke-agent "I prefer canary releases."

# A human summons the aligner to converge
mycelium engine invoke aligner "converge on the deploy strategy"

# Participants loop until agreement
mycelium await   --room planning --handle spoke-agent --json     # read the prompt
mycelium respond --room planning --handle spoke-agent "canary works if we cap rollout at 10%"
```

On agreement the aligner emits `commit:converged`, records the episode, and compiles
`plan/tasks.md` **before** the consensus is announced (so the plan exists when `await`
returns). The plan syncs as a `knowledge` memory to every machine. Each agent reads it
and works its half:

```bash
mycelium plan tasks --room planning        # the shared @handle checklist
```

## Traps

- **Don't fork the moderator.** One backend moderates a room. If a spoke also runs a
  backend (for its local index/UI), it must **not** provision/moderate the same room, or
  membership and the transcript fork.
- **Shared secret parity.** The per-channel MLS secret is derived offline from the
  channel scope (`workspace/room`) via a shared master secret, so both hosts reconstruct
  the **same** value, with no key exchange. The built-in master secret is a **public dev
  default** (anyone with the repo can derive it). For anything beyond a trusted LAN, set
  `MYCELIUM_SLIM_MASTER_SECRET` to a private value **identical on every host that shares
  rooms** (a mismatch means invites silently never land, so suspect the secret before the
  network), and set `MYCELIUM_SLIM_REQUIRE_SECRET=1` to make a host refuse to start with
  the dev default.
- **Version parity.** The `slim` node image and the `slim-bindings` wheel are a matched
  pair on **both** hosts; a skew across machines is a new failure mode.

## Open-internet path

For hosts not on the same LAN, either:

- **A reachable/hosted node.** Run the `slim` node on a host with a public address (or
  behind a load balancer) and have every peer `mycelium connect` to it. MLS makes the
  node a blind ciphertext forwarder, so a shared/hosted node never sees plaintext.
- **A tunnel.** Expose a LAN node through a tunnel (an SSH reverse tunnel or a
  `cloudflared`/`tailscale`-style overlay) and connect to the tunnel address.

`mycelium connect` accepts any address (including `https://`), so pointing at a hosted
node or tunnel needs no new command, only operating it.

## Watching it in the browser

The UI never speaks SLIM or L9. The backend moderator ingests every channel message and
re-publishes it onto an in-process bus (`app/bus.py`); consent prompts, human messages,
plan pushes, and every L9 envelope land there. The frontend reads that bus over a single
SSE stream (`/api/rooms/{room}/messages/stream`). Point a browser on **either** host at
that host's backend; a spoke's UI talks to its own co-located backend, and the consent
prompt is answered against the moderator's invite registry (the hub owns
accept/decline), so a spoke's human can accept a prompt the hub raised.

Open a room at `/room/{name}` and watch three surfaces during the flow above:

- **CHANNEL**: membership, the transcript, and lifecycle lines (JOIN, CONSENSUS →
  `plan/tasks.md`), plus the **consent prompt**: an `@`-invite of an agent not in the
  room raises an accept/decline dialog; nothing joins until Accept.
- **L9**: the protocol inspector. A live wire of the L9 payloads crossing the channel
  (`exchange` ticks/replies, `commit:converged`/`rejected` with **MPC/GAR/SCR**,
  `knowledge` pushes), each tagged with kind/subkind + episode, over an **episodes** list
  whose cards expand to the full causal chain.
- **PLAN**: the compiled `plan/tasks.md` checklist, refreshed when a consensus compiles.
