# Security Planes

Mycelium has **two enforcement planes**. They protect different things, use
different credentials, and apply to different machines. Conflating them is the
most common hub-and-spoke misconfiguration.

## The two planes

| Plane | Port (default) | Who uses it | What it protects | Default | Upgrade |
|-------|----------------|-------------|------------------|---------|---------|
| **HTTP API** | 8000 | Spokes, humans, agents (`memory`, `await`, `respond`) | Memory, participation, handle attribution | Open (no token) | [Authentication](#auth) (`auth.enabled`) |
| **SLIM / MLS** | 46357 | Hub backend (moderator); dev `slim send`; future native connectors | Native SLIM group membership on the coordination fabric | Shared-secret **PSK** (hub only) | SignerJwt (`slim.identity`) |

**Spokes do not use the SLIM plane for normal work.** A spoke is a thin HTTP
client: it points `server.api_url` at the hub backend and never needs
`MYCELIUM_SLIM_MASTER_SECRET`.

The hub backend holds the room's SLIM/MLS session as **moderator**. Spoke agents
participate over HTTP; the backend keeps them present via a **server-held lease**
and delivers turns from the **durable transcript**. That path bypasses PSK
entirely.

## What PSK actually protects

PSK (`MYCELIUM_SLIM_MASTER_SECRET` → HMAC per `workspace/room` →
`create_app_with_secret`) is the **SLIM-plane room gate**:

- It decides who may **authenticate as a SLIM app and join a room's MLS group**.
- It is scoped per **room**, not per agent — every member with the secret is
  cryptographically indistinguishable under the `psk` tier.
- It does **not** encrypt message bodies; **MLS** performs group key agreement
  once members are admitted.
- It does **not** protect spokes, memory, or `@handle` impersonation over HTTP.

With the public dev literal shipped in the repo, PSK protects nothing by itself.
A fresh hub install generates a private `[slim].master_secret` in
`config.toml` on first `mycelium config apply` (rendered to `.env` for Docker).
Override with `mycelium config set slim.master_secret …` to rotate.

## What protects spokes

For hub-and-spoke, the urgent control is the **HTTP API gate**, not PSK:

```bash
mycelium config set auth.enabled true
mycelium config set auth.audience mycelium
# … configure [[auth.issuers]] …
mycelium config apply
```

See [Authentication](#auth) for humans and agent service accounts.

Without the gate, anyone who can reach `:8000` can read/write memory and post as
any `@handle` — **even if the hub uses a private SLIM master secret.**

## Deployment profiles

| Profile | HTTP API | SLIM (hub) | Spoke config |
|---------|----------|------------|--------------|
| **Solo dev** | Open | Dev PSK literal (fallback if no config secret) | N/A (all-in-one) |
| **LAN team** | JWT on | Auto-generated `[slim].master_secret` on hub | `server.api_url` → hub:8000 only |
| **Hosted** | JWT required | Private hub secret + SignerJwt | Same; no master secret on spokes |

`mycelium doctor` reports HTTP auth status from the hub's `/health` endpoint.
In **hub** mode it also warns when `[slim].master_secret` is missing or still
the public dev literal.

## SLIM identity ladder (hub native clients)

| Tier | Plane | Spoke needs it? |
|------|-------|-----------------|
| `psk` | SLIM | No (hub backend only today) |
| `signerjwt` | SLIM | Only if the spoke runs a native SLIM connector |

`mycelium config set slim.identity signerjwt` changes **SLIM channel identity** on
machines that open native SLIM connections. It does **not** turn on HTTP API auth.
Configure `[auth]` separately.

## Related guides

- [Hub & Spoke Setup](#hub-and-spoke) — topology and spoke checklist
- [Authentication](#auth) — HTTP JWT gate (spokes and hub API)
