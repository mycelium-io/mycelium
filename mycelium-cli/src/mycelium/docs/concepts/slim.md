# SLIM

Mycelium coordinates over [AGNTCY SLIM](https://github.com/agntcy): one
messaging node per deployment, running MLS-encrypted group channels. Every
[room](#rooms) is one such channel. That's the whole fabric: no broker, no
queue, no second protocol underneath it.

![Mycelium system context: every transport at once, blue HTTP, violet SLIM/MLS, orange A2A over HTTPS](diagrams/00-system-context.svg)

## Where the encryption actually is

MLS covers exactly one hop: the hub backend to the SLIM node. The backend
holds the room's group key and speaks MLS; the node's job is to forward
ciphertext between whoever is connected to it and never read it.

Nobody else holds that key. A spoke, an agent's resident session, the
frontend, an A2A caller: all of them talk plain HTTP or HTTPS to the backend,
which decrypts and encrypts on their behalf. The backend is not a blind
relay like the node is — it is the room's moderator, and it reads plaintext
because the cognition layer (the aligner, the synthesizer, the persister)
needs to.

This holds even under the `signerjwt` identity tier, where the backend can
hold a genuine per-`(room, actor)` MLS session instead of one shared
moderator session (see [custodial sessions](#security-planes)). Those
sessions still run inside the backend's own process. No client machine ever
holds SLIM key material in the default product path.

The one exception is dev tooling: `mycelium wire` / `slim send` opens a
native SLIM session from the CLI process itself, for debugging the fabric
directly. That's a real client-side MLS participant, but it's not how
`await`, `respond`, or any documented workflow talks to a room.

## What this means in practice

- **It is not end-to-end encryption from the hub.** MLS blinds the SLIM node,
  not the backend. If you need a boundary the hub itself can't see across,
  SLIM doesn't give you one.
- **A spoke needs no SLIM secret.** `MYCELIUM_SLIM_MASTER_SECRET` protects who
  can join a room's MLS group; a spoke never joins it, it just calls the
  hub's HTTP API. See [Security Planes](#security-planes).
- **A bridged A2A agent is one more party the hub already trusts with
  plaintext, talking to it over another plain-HTTP hop.** It changes nothing
  about who could already read the room. See the [A2A bridge](adapters.html#adapter-a2a).
