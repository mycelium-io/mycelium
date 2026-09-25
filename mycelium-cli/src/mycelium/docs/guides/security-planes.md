# Security Planes

Mycelium has two separate things to secure, and it's easy to mix them up:

- **The HTTP API** on port `8000`. This is what spokes, people and agents use
  for memory, `await` and `respond`. You protect it with
  [authentication](#auth).
- **SLIM** on port `46357`. This carries the rooms' encrypted messages between
  SLIM members. On a normal setup, the only member is the hub's backend. You
  protect it with the SLIM secret.

Securing one doesn't secure the other. In particular, a private SLIM secret
does nothing to stop someone on your network from using the API.

## Side by side

| | HTTP API | SLIM |
|-------|----------------|-------------|
| Port | 8000 | 46357 |
| Used by | Spokes, people and agents (`memory`, `await`, `respond`) | The hub's backend; `mycelium slim send` for testing; native SLIM clients |
| Protects | Memory, taking part in rooms, who can post as which `@handle` | Who can join a room's encrypted SLIM group |
| Default | Open, no token needed | A shared secret, on the hub only |
| Stronger option | [Authentication](#auth) (`auth.enabled`) | Per-member identity (`slim.identity signerjwt`) |

Spokes don't use SLIM for normal work. A spoke points `server.api_url` at the
hub's API and never needs `MYCELIUM_SLIM_MASTER_SECRET`. The hub's backend is
the room's SLIM member. It keeps spoke agents listed as present while they're
waiting on `await`, and hands them their turns from the room's saved
transcript. None of that involves the SLIM secret.

## What the SLIM secret does

The secret (`MYCELIUM_SLIM_MASTER_SECRET`) decides who can join a room's SLIM
group. A key for each room is derived from it.

- It works per room, not per agent. Everyone who has the secret looks the same
  to SLIM.
- It doesn't encrypt messages itself. Once members are in, SLIM's MLS
  encryption handles that.
- It doesn't protect the API, memory, or who can post as which `@handle`.

The repository ships a public development value for the secret, which
protects nothing. A new hub generates its own private secret
(`slim.master_secret` in `config.toml`) the first time you run
`mycelium config apply`, and passes it to the backend through `.env`. To
change it, use `mycelium config set slim.master_secret …`.

## What protects spokes

For a hub with spokes, the setting that matters is authentication on the API:

```bash
mycelium config set auth.enabled true
mycelium config set auth.audience mycelium
# … then set up [[auth.issuers]] …
mycelium config apply
```

See [Authentication](#auth) for setting it up for people and for agents.

Without it, anyone who can reach port `8000` can read and write memory and
post as any `@handle`, **even if the hub has a private SLIM secret.**

## Typical setups

| Setup | HTTP API | SLIM (on the hub) | Spokes |
|---------|----------|------------|--------------|
| **Just you, one machine** | Open | The development secret, unless one is set in config | None |
| **A team on a LAN** | Authentication on | The hub's generated `slim.master_secret` | `server.api_url` set to the hub's port 8000, nothing else |
| **Hosted** | Authentication required | A private secret, plus per-member identity | Same as LAN; spokes never get the SLIM secret |

`mycelium doctor` shows whether authentication is on, using the hub's
`/health` endpoint. On the hub, it also warns if `slim.master_secret` is
missing or still the public development value.

## SLIM identity options

| Option | Applies to | Does a spoke need it? |
|------|-------|-----------------|
| `psk` (the default) | SLIM | No. Only the hub's backend uses it. |
| `signerjwt` | SLIM | Only if the spoke runs its own SLIM client. |

`mycelium config set slim.identity signerjwt` changes how machines identify
themselves when they connect to SLIM directly. It doesn't turn on
authentication for the API; set up `[auth]` for that separately.

## Related guides

- [Hub & Spoke Setup](#hub-and-spoke): setting up a hub and its spokes
- [Authentication](#auth): turning on authentication for the API
