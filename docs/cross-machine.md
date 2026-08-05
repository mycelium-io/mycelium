# Cross-machine coordination (Step 9)

How two people on two laptops run the mycelium hero flow through **one shared SLIM
node**. This is the LAN MVP; the open-internet path is documented but not built
(bible §Step 9: *LAN first, don't block on NAT*).

## Roles

- **Host A — the owner / moderator.** Runs the shared SLIM node (`mycelium hub
  host`) **and** the always-on backend that provisions and **moderates** the room
  channel (creates the group, invites members, persists the transcript, runs the
  aligner + plan-sync). One moderator per room — see the trap below.
- **Host B — a member.** Runs a **daemon (connector)** pointed at host A's node
  via `mycelium connect <A-LAN-IP>:46357`. It is a *member* of the channel, never
  a second moderator.

Membership is addressed by **identity** (`workspace/room/agent`), never by host,
so the moderator invites host B's agent exactly as it would a local one — the
consent → invite → join path needs no new cross-machine mechanism.

## The hero flow, across two hosts

```
Host A:  mycelium hub host              # SLIM node + backend/moderator; prints the LAN address
Host B:  mycelium connect http://<A-LAN-IP>:46357
Host B:  mycelium agent create ...      # its daemon joins A's room channel
Host A:  (human) @agent-b let's plan …  # consent prompt → accept → B's connector invited in
         agents exchange L9 → @aligner converges → commit:converged
         backend compiles plan/tasks.md → knowledge push carries the plan
Both:    plan/tasks.md (markdown + JSONL) lands on each machine; each agent works its half
```

## Two decisions this step resolved (flagged)

1. **Hub location — self-hosted shared node (default).** The owner runs the node
   with `mycelium hub host`; peers `mycelium connect` to its LAN IP. A hosted
   rendezvous is optional and **post-MVP**. `mycelium connect` already accepts any
   address (incl. `https://` for a hosted node or tunnel), so no code changes are
   needed to point at one later — only operating it.

2. **Reindex on a member host — the connector reindexes explicitly.** Memory
   content is canonical markdown; the JSONL search index is derived. On host A the
   backend's file watcher re-embeds a write, but a member host with no watcher
   would leave the pushed markdown **invisible to search**. So after applying a
   `knowledge` write, the connector triggers a room-scoped reindex against its
   co-located backend (`mycelium/daemon/connector.py:reindex_after_knowledge`,
   best-effort, idempotent). The CLI has no local embedder — embeddings live in
   the backend — so this is an HTTP call, exactly like `mycelium memory reindex`.

## Traps

- **Don't fork the moderator.** One backend moderates a room. If host B also runs
  a backend (for its local index/UI), it must **not** provision/moderate the same
  room, or membership and the transcript fork.
- **Shared secret parity.** The per-channel MLS secret is derived offline from the
  channel scope (`workspace/room`) via a shared dev master secret, so both hosts
  reconstruct the **same** value — no key exchange. If a cross-host invite
  "silently never lands," suspect a secret/version mismatch before the network.
- **Version parity.** `slim:1.4.0` / `slim-bindings` 1.4.x is a matched pair on
  **both** hosts; a skew across machines is a new failure mode.

## Open-internet path (documented, not built)

For hosts not on the same LAN, either:

- **A reachable/hosted node** — run the `slim` node on a host with a public
  address (or behind a load balancer) and have every peer `mycelium connect` to
  it. MLS makes the node a blind ciphertext forwarder, so a shared/hosted node
  never sees plaintext.
- **A tunnel** — expose a LAN node through a tunnel (e.g. an SSH reverse tunnel or
  a `cloudflared`/`tailscale`-style overlay) and connect to the tunnel address.

NAT traversal / hole-punching is **out of scope for the MVP** — do not build it.
