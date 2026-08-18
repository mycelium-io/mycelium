<!-- SPDX-License-Identifier: Apache-2.0 -->
# Attested identity (SPIRE)

Mycelium's default channel identity is a shared-secret PSK: zero infrastructure,
every room member derives the same group key. That's the try-it path, and it never
changes. **SPIRE identity** is an optional, off-by-default upgrade: each member
presents a SPIRE-attested JWT-SVID as its MLS identity, so members are
cryptographically distinct, individually attested, and individually revocable:
the tightest attestation tier, and the heaviest to deploy.

Turning it on is **one switch**. You never touch a SPIFFE socket path, a trust
domain, or type `spire-server entry create` by hand.

## What "distinct members" actually means

With any channel-identity tier on (`signerjwt` or `spire`), each actor participates
as its **own MLS member** — a *custodial session* the hub holds on the actor's
behalf, server-side. A message is then cryptographically attributable to the actor
on the wire (not stamped by the backend after the fact), and room access is enforced
by **MLS group membership**, not application logic. These sessions survive a backend
restart — they're revived from encrypted local state with no re-invite. Under the
`psk` default there are no custodial sessions; the backend is the single member and
nothing here applies.

**Honest boundary — this is not E2E from the hub.** Custodial sessions live *in the
hub process*, so the hub still holds every actor's key and reads all plaintext —
that's what lets the aligner, plan compiler, and memory sync work at all. Turning on
identity hardens **attribution and access** and makes per-agent identity real at the
MLS layer; it does **not** mean the hub can no longer read your messages. It means
the hub represents each actor as a distinct, verifiable member — not that the room is
end-to-end encrypted away from the hub.

## Turn it on

```bash
mycelium config set slim.identity spire
mycelium config apply
mycelium up
```

`mycelium up` reads `slim.identity` and, when it's `spire`, brings a co-located
SPIRE **server + node daemon** up alongside the hub automatically; the compose
`spire` profile is an implementation detail the config drives. You do **not** pass
`--profile spire` by hand. On the default (`psk`) nothing extra starts and the
stack is byte-for-byte unchanged.

> The SPIRE **node daemon** (upstream image `spire-agent`, container
> `mycelium-spire-noded`) is SPIRE's per-node identity daemon: it serves the
> Workload API socket and fetches SVIDs. It is unrelated to mycelium coordination
> **agents** (`@alice` etc.); the shared word is an upstream-SPIRE coincidence.

## Registration is automatic

```bash
mycelium agent create @alice
```

With SPIRE on, `agent create` registers the SVID entry
(`spiffe://<trust-domain>/agent/alice`) against the running SPIRE server itself,
with no printed copy-paste operator step. `agent rm @alice` deletes the entry, revoking
the identity. Both go through the normal mycelium CLI.

## Check it

```bash
mycelium doctor
```

When SPIRE is on, doctor shows a legible line (`SPIRE up, @alice attested`) so a
misconfiguration is a clear message rather than a member silently hanging at
"Initializing spire identity manager."

## Trust domain

The trust domain defaults to `mycelium.dev`. Override it (server, agent, backend
MLS identity, and registration all read the same value) with:

```bash
export MYCELIUM_SLIM_SPIRE_TRUST_DOMAIN=corp.example.com
```

Set it in `~/.mycelium/.env` (or the shell that runs `mycelium up`) before bringing
the stack up.

## The honest ceiling

The appliance uses SPIRE's `unix` workload attestor, which identifies a workload by
its process credentials. That requires the SPIRE node daemon to share the workload's
PID namespace, which the shipped compose does for the **backend** (the always-on
moderator that holds membership for turn-based agents). A **resident** Claude or
Cursor session on a user's own machine is *not* co-located with a SPIRE node daemon,
so it cannot be `unix`-attested; on a spoke, identity degrades to the PSK unless you
front it with a non-`unix` attestor (k8s, docker, x509pop, join-token). This is why
SPIRE is off by default and never lands on the default path.

The appliance SPIRE profile is **dev-grade** (SQLite datastore, join-token node
attestation, short SVID TTLs): a real product surface for attested identity, not
yet a hardened production deployment.
