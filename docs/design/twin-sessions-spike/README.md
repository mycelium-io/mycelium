# Spike: server-side per-actor "twin" SLIM/MLS sessions (#662)

**Status: PASS (validated live against a stock `ghcr.io/agntcy/slim:2.1.0` node).**
This is a spike, not a commitment to rearchitect. It proves the twin model works
end-to-end on the pinned stack, measures its shape, and leaves the current
server-held-membership model untouched so a follow-up can adopt it off-by-default
and additively.

Two rounds: **v1** (`twin_sessions_spike.py`) proved the primitive in one process;
**v2** (`spike_v2.py`) then stress-tested the cases v1 could not, with real
kill-able subprocesses -- restart-and-receive, epoch change while offline,
moderator restart, wrong-passphrase rejection, multi-room resume, and the
PSK-cannot-persist constraint. **All six v2 scenarios pass** (see the v2 matrix
below). One apparent v1/early-v2 limitation (a restored member could send but not
receive) was chased down, cross-checked against the SLIM source via deepwiki, and
resolved: it is correct SLIM behavior, satisfied by mycelium's existing
always-draining moderator loop.

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

v1 proved the resume by having the revived twin **send** (the single-process sim
left a stale subscription that confounded *inbound* re-delivery). **v2 removed that
confound with real subprocesses and validated inbound too** -- see the v2 matrix
(D1). Independently, note that **SLIM does not replay messages missed while
offline** -- it only tracks missed *heartbeats* (v2/D1 confirms the missed message
is not replayed). Persistence resumes *crypto state*, not *missed messages*, so the
durable transcript/inbox (`app/services/persister.py`) stays exactly as-is; it
remains the offline-replay mechanism.

## v2 -- the cases v1 could not test (all pass)

`spike_v2.py` (run: `./run_v2.sh`) runs each twin as a real, SIGKILL-able
subprocess (`twin_runner.py`), so a restart drops the connection and the node
forgets the subscription -- a faithful backend/twin bounce, without v1's
single-process confound. Each scenario is isolated (its own SLIM Names, store root,
and rooms; reusing a Name leaks the node's per-Name multicast queue between tests).

| # | Scenario | Verdict | What it establishes |
|---|----------|---------|---------------------|
| C | PSK cannot persist | **PASS** | There is no `create_app_with_secret_and_persistence` in the 2.1.0 wheel: persistence **requires** the identity provider/verifier pair, so a twin cannot run on the default PSK tier. **Twins mandate `signerjwt`/`spire`.** |
| D1 | Clean restart, receive a NEW message | **PASS** | After a real kill + `restore_sessions`, the twin both sends and **receives** new broadcasts. Inbound resumes once the moderator processes the twin's `rejoin` -- which it does only while **actively draining** its session. The moderator's message sent while the twin was down is **not** replayed (confirms no offline replay). |
| D2 | Epoch change while offline | **PASS** | Twin killed, moderator rekeys the group (removes another member -> MLS Commit), twin restores: it still sends and receives. A twin that missed a Commit is **not** stranded -- `rejoin()` heals the epoch. |
| D3 | Moderator (backend) restart | **PASS** | The **group creator** is killed and `restore_sessions`'d: the room stays live -- the member keeps receiving moderator broadcasts and the restored moderator receives member replies. A backend bounce resumes the room from disk. |
| A | Wrong passphrase | **PASS** | Re-opening a twin's store with the wrong passphrase fails with `decryption failed (wrong key or corrupt data)`. **The at-rest passphrase is load-bearing**, not decorative. |
| B | Multi-room resume | **PASS** | A twin in two rooms gets **both** sessions back from a single `restore_sessions` call (`n=2`). |

**The D1 chase (why this matters, and the deepwiki cross-check).** v1 and the first
v2 pass showed a restored member could *send* but not *receive*. Rather than ship
that as a limitation, it was run down against the SLIM source via deepwiki:
`restore_sessions` re-establishes the member's routes/subscriptions and emits an
online `rejoin()`, but the **moderator only re-adds the member to its fan-out list
when it processes that rejoin control message -- which happens only while the
moderator is actively draining `get_message`** (confirmed present in 2.1.0, not a
newer-branch feature). The failing runs had an idle moderator that only published.
This is exactly mycelium's production posture: the backend moderator's persister
(`RoomPersister.run()`) *is* an always-on `receive_with_context()` drain loop. With
a draining moderator, D1 passes in a single round. So it is **correct SLIM
behavior**, already satisfied by the existing backend -- not a bug and not a gap.

### Q4 -- where the store lives + the passphrase boundary

Per-twin, server-side, backed by the **`agntcy-slim-persistence` SQLite store**
(`SlimGroupStateStorage`, the crate the issue pointed at -- we did not hand-roll
persistence, only passed `PersistenceConfig(path, passphrase)`). The `path` is
treated by the crate as a **directory**, into which it writes a real SQLite
database in WAL mode, one per app:

```
twin-store/alice/mls-state.sqlite/            <- the `path` we pass (a directory)
  slim-<hex>.db        (magic: "SQLite format 3", ~120-240 KB per twin here)
  slim-<hex>.db-wal    (WAL sidecar)
  slim-<hex>.db-shm    (shared-memory index)
```

`<hex>` is the app/session id. The DB *container* is a standard (plaintext-schema)
SQLite file; the **passphrase encrypts the stored MLS state blobs (AES-256-GCM)**,
per the crate -- it is value-level at-rest encryption, not whole-file/SQLCipher
encryption. In production this sits under the hub's data dir (`~/.mycelium/`-style),
one directory per twin. **The passphrase is the real at-rest confidentiality boundary and needs
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
sockets. The per-twin SQLite MLS-state stores were ~120-240 KB each in this run
(the `agntcy-slim-persistence` DB + WAL, see Q4). Persistence makes a
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
| `twin_sessions_spike.py` | **v1** fleet: N persistence-backed SignerJwt twins in one process, one GROUP, one restore. |
| `run.sh` | v1 repro: stock SLIM 2.1.0 node + key mint + roster JWKS + exec. |
| `spike_v2.py` | **v2** restart matrix (C/D1/D2/D3/A/B): orchestrates kill-able twin subprocesses, asserts a PASS/FAIL/FINDING table. |
| `twin_runner.py` | v2: one twin as its own OS process, driven by a file-command protocol; SIGKILL-able for faithful restarts. |
| `twin_common.py` | Shared identity/persistence/session helpers for the v2 harness. |
| `run_v2.sh` | v2 repro: node + per-test key mint + exec `spike_v2.py`. |
| `build_roster_jwks.py` | Assemble the room-roster JWKS from the twins' public keys (shared with #587). |

## Matched stack (proven)

`slim-bindings==2.1.0` (PyPI) + `ghcr.io/agntcy/slim:2.1.0`. Signing keys must be
PKCS#8 PEM (`run.sh` converts SEC1 -> PKCS#8). Do not substitute `STATIC_JWT`: it
returns `MlsNotSupported` for MLS signature keys (#581).
