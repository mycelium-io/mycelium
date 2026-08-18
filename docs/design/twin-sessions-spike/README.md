# Spike: server-side per-actor "twin" SLIM/MLS sessions (#662)

**Status: PASS (validated live against a stock `ghcr.io/agntcy/slim:2.1.0` node).**
This is a spike, not a commitment to rearchitect. It proves the twin model works
end-to-end on the pinned stack, measures its shape, and leaves the current
server-held-membership model untouched so a follow-up can adopt it off-by-default
and additively.

## The problem it addresses

Today the backend is a **single SLIM/MLS member per room that impersonates every
actor** (a service account). Attribution ("@alice said this") is stamped by the
backend at the L9/transcript layer *after the fact*: application-level, forgeable
by the backend, invisible on the wire (`app/services/l9.py` builds the envelope
`sender` field; `app/services/actor.py` binds it from the HTTP principal). One MLS
identity -- the backend's -- carries all traffic.

The decided direction: the backend as a **custodian of N per-actor twin Apps**,
each a *genuine* MLS member carrying its **own** per-actor SignerJwt/SPIRE
credential (the identity epic #585 / #476 already ships the credential; today it
only identifies the backend's single App). Which actor can touch which room is then
enforced by **MLS group membership**, not by mycelium app logic. All twins live in
the backend process, so **all backend cognition still reads plaintext** (aligner,
plan compiler, memory-sync, L9). This is orthogonal to #664 Mode 2 (blind relay)
and does not require it.

## What the spike ran

`twin_sessions_spike.py`, driven by `run.sh`, stands up a stock SLIM 2.1.0 node and
runs a whole twin fleet in **one** host process:

- 1 moderator App (`backend`, the always-on citizen) + 3 per-actor twins
  (`alice`, `bob`, `carol`).
- Each twin is created with `create_app_with_persistence_async(...)` and its **own**
  self-minted ES256 SignerJwt identity (per-member keypair, roster-JWKS verifier --
  the exact #587 floor path), so each is a cryptographically distinct MLS
  participant. The backend cannot mint alice's token without alice's private key.
- All four join **one** GROUP/MLS channel over **one** shared dataplane connection.
- One twin is then "restarted" (its in-memory App is dropped without a graceful
  leave) and resumed with `restore_sessions(conn_id)`.

Reproduce: `./run.sh` (needs docker, openssl, and the `fastapi-backend` uv env with
`slim-bindings==2.1.0`). It self-mints keys, builds the roster JWKS, and execs the
fleet on the host. Tear-down is automatic.

## Results against the six spike questions

### Q1 -- N twins, one process, distinct wire attribution: **YES**

Three persistence-backed, SignerJwt-identified twins joined one MLS GROUP; the
moderator read each message and recovered a **distinct cryptographic sender** off
the inbound `MessageContext`, not a backend-stamped field:

```
[fleet] 3 persistence-backed SignerJwt twins created in ONE process: alice, bob, carol
[backend] invited + MLS-verified twin 'alice'.
[backend] invited + MLS-verified twin 'bob'.
[backend] invited + MLS-verified twin 'carol'.
[backend] wire sender='alice' payload='alice: hello over MLS as myself'
[backend] wire sender='bob'   payload='bob: hello over MLS as myself'
[backend] wire sender='carol' payload='carol: hello over MLS as myself'
[fleet] distinct cryptographic wire senders: ['alice', 'bob', 'carol']
```

Each invite ran MLS peer-verification of a distinct self-signed token against the
room roster. Attribution is now on the wire and non-forgeable by the backend,
because the backend does not hold the actors' private keys in this model (in the
spike it happens to, but nothing *requires* it to -- see the scope boundary).

### Q2 -- persistence API reachable from the pinned 2.1.0 wheel: **YES**

Verified directly against the installed wheel (not just the Rust source). In
`slim_bindings==2.1.0`:

- `Service.create_app_with_persistence_async(name, provider, verifier, direction, persistence) -> App`
  (plus the blocking `create_app_with_persistence`).
- `App.restore_sessions_async(conn_id) -> list[Session]` (plus blocking
  `restore_sessions`).
- `PersistenceConfig(*, path, passphrase)` -- both keyword-only; `passphrase` is
  **required** (no unencrypted store). The docstring: *"Where and how a session's
  MLS/state is persisted at rest ... pass this to create_app_with_persistence to
  get a restorable app."*
- `restore_sessions` docstring: *"conn_id must be the live upstream connection ...
  Each restored session rejoins its MLS group without repeating the invite/welcome
  handshake."*

Note: the top-level module does **not** expose these as free functions (an earlier
read of the Rust source suggested `create_app_with_persistence(...)` as a bare
call); they are **`Service`/`App` methods**. The spike uses the method form.

### Q3 -- resume without a re-invite: **YES**

The twin was dropped without a graceful leave (a graceful `delete_session` removes
the member from the group *and* purges its persisted state -- the opposite of a
crash), re-created against the **same** store path + passphrase, and resumed:

```
[resume] simulating a restart of twin 'alice' ...
[resume] restore_sessions('alice') returned 1 session(s) from persisted MLS state (no invite/welcome replayed).
[resume] moderator decrypted post-restore msg from wire sender='alice': 'alice: back from persisted MLS state'
```

`restore_sessions` recovered the group membership from disk, and the revived twin
immediately **transacted at the group's current epoch** (it encrypted a message to
the live group key it recovered from disk; the moderator decrypted and attributed
it) with no re-invite and no MLS Welcome/Commit replay.

**Caveat this exposed (a real finding).** In a single-process simulation the
crashed App's *subscription for the victim's Name* is still registered over the
shared connection (a real crash drops the connection and the node forgets it). So
inbound re-delivery to the fresh subscription is confounded here; the spike proves
the resume by having the revived twin **send**, which is the stronger crypto proof
(the recovered MLS epoch is usable) and does not depend on node re-routing.
Follow-up: a true two-process kill/restart validates inbound re-delivery cleanly.
Independently, note that **SLIM does not replay messages missed while offline** --
it only tracks missed *heartbeats*. Persistence resumes *crypto state*, not *missed
messages*, so the durable transcript/inbox (`app/services/persister.py`) stays
exactly as-is; it remains the offline-replay mechanism.

### Q4 -- where the store lives + the passphrase boundary

Per-twin, server-side, one SQLite MLS-state store per actor, AES-256-GCM at rest:

```
[store] per-twin server-side MLS state (Q4):
  backend    .../twin-store/backend/mls-state.sqlite  (AES-256-GCM at rest)
  alice      .../twin-store/alice/mls-state.sqlite    (AES-256-GCM at rest)
  bob        .../twin-store/bob/mls-state.sqlite       (AES-256-GCM at rest)
  carol      .../twin-store/carol/mls-state.sqlite     (AES-256-GCM at rest)
```

In production this sits under the hub's data dir (`~/.mycelium/`-style), one path
per twin. **The passphrase is the real at-rest confidentiality boundary and needs
its own hardening pass.** The spike derives it as `HMAC(server session secret,
handle)` so each twin store gets a distinct key and one leaked passphrase does not
open every twin. The session secret must be a **server-held** secret
(`MYCELIUM_TWIN_STORE_SECRET` or a KMS-wrapped value) -- deliberately **NOT** the
actor's OIDC/SignerJwt token, which rotates hourly (`TOKEN_DURATION_S = 3600`) and
is not a durable at-rest key. Open question for the follow-up: key rotation and
whether the secret should be per-host or per-deployment.

### Q6 -- cost: one socket for the whole fleet

```
[fleet] one shared dataplane connection: conn_id=0
```

N twins multiplex over **one** dataplane connection (`Service` allows one per
endpoint per process anyway; the existing `slim_client._shared_connection` cache
already relies on this). So the footprint is N Apps + N MLS group states, **not** N
sockets. The MLS state stores were ~160 bytes each in this run. Persistence makes a
connect-per-turn footprint viable as an alternative to N always-live Apps, but the
spike did not stress a room's worth of actors; scale-testing the App/MLS-state
memory footprint at (say) 20-50 twins is a follow-up measurement, not a blocker.

## The honest scope boundary (do not oversell)

Twins are **server-side**: the hub still holds every twin's private key + plaintext.
So this hardens:

- **the wire and attribution** -- cryptographic, non-forgeable, verifiable by
  real/remote members; access split by MLS group membership rather than app logic;
- **per-agent identity at the MLS layer** -- finally true, where today the identity
  epic only identifies the backend's single App.

It is **NOT** E2E-from-the-hub. A compromised or malicious hub still sees and can
impersonate everything. Confidentiality-from-the-hub is a **different axis** (#664
Mode 2, deliberately out of scope; twins do not need it, and it would remove
cognition). For a single-hub deployment the near-term win is honest attribution +
access-by-membership + a multi-hub / remote-member future, not "the server can't
read your data."

## Where this plugs into the existing code (follow-up, not this spike)

The seams already exist; adopting twins is additive and off-by-default:

- **Identity** -- `app/services/slim_identity.py` already mints per-agent SignerJwt
  material (`ensure_agent_keypair`, `resolve_identity_material`) and provisions it
  on `agent create`. Today `SlimClient._create_app` (`slim_client.py:392`) selects
  the identity tier for the *backend's* single App; the twin model calls the same
  resolver per actor.
- **App creation** -- `SlimClient` would gain a persistence-backed variant that
  calls `create_app_with_persistence_async` instead of `create_app`, keyed by the
  per-twin store path. `room_channels.py` (`RoomChannelManager.provision` /
  `invite`) is where the fleet would be custodied: one twin App per member instead
  of inviting a bare Name.
- **Attribution** -- `l9.py` / `actor.py` keep stamping the L9 `sender` for the
  transcript, but it becomes a *mirror* of the now-authoritative MLS wire identity
  rather than the sole source of truth.
- **Transcript/inbox** -- `persister.py` is unchanged; it stays the offline-replay
  mechanism (SLIM persistence resumes crypto state only, per Q3).

## Lifecycle ties (Q5, noted not built)

A twin is created/torn down with the actor, tying to: **#663** (invite/accept
authorization -- twin creation is where that gate belongs), **#590** (revocation =
drop the twin + delete its store), and the real-IdP handle fixes **#656/#657**. The
spike does not implement lifecycle; it proves the primitive the lifecycle would
manage.

## Non-goals (unchanged from the issue)

- Not rearchitecting `participate.py`'s await/respond model before the twin path is
  proven end-to-end.
- Not #664 Mode 2 (blind relay) -- orthogonal.
- Not client-held memberships yet -- a native client holding its own twin is the
  *next* rung (a browser can't; persistence is native-only), cleanly enabled by
  this but not required.

## Files

| File | Purpose |
|------|---------|
| `twin_sessions_spike.py` | The fleet: N persistence-backed SignerJwt twins in one process, one GROUP, one restore. |
| `run.sh` | One-command repro: stock SLIM 2.1.0 node + key mint + roster JWKS + exec. |
| `build_roster_jwks.py` | Assemble the room-roster JWKS from the twins' public keys (shared with #587). |

## Matched stack (proven)

`slim-bindings==2.1.0` (PyPI) + `ghcr.io/agntcy/slim:2.1.0`. Signing keys must be
PKCS#8 PEM (`run.sh` converts SEC1 -> PKCS#8). Do not substitute `STATIC_JWT`: it
returns `MlsNotSupported` for MLS signature keys (#581).
