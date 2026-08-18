# Server-side custodial sessions (#666)

## What this is

Under the PSK default the backend is a single SLIM/MLS member per room that
impersonates every actor. Attribution ("@alice said this") is stamped by the
backend at the L9/transcript layer after the fact: application level, forgeable by
the backend, invisible on the wire. One MLS identity, the backend's, carries all
traffic.

Under an identity tier (`signerjwt`/`spire`) the backend becomes the **custodian**
of N **custodial sessions**, one per `(room, actor)`. Each is a genuine MLS member
holding the actor's own credential and MLS state on the actor's behalf, so:

- `respond(@alice, …)` sends through @alice's custodial session, which is
  cryptographically @alice on the wire (verifiable off the inbound `MessageContext`,
  not a backend-stamped field).
- Room access is enforced by **MLS group membership**: a session is only in the
  rooms its actor belongs to, so "who may touch which room" is crypto, not app logic.

All sessions live in the backend process, so the moderator App plus the aligner,
plan compiler, memory-sync, and L9 layers still read plaintext. Cognition is
preserved.

## Why "custodial"

The name is the term of art. This is **custodial** in the key-management sense: the
custodian holds your keys for you, exactly as a custodial wallet does. The axis is
server-side versus client-held, and it maps cleanly onto custodial versus
non-custodial:

- **This rung is custodial.** The hub holds each actor's key and MLS state.
- **The next rung is non-custodial.** A native client holds its own session (a
  browser cannot; persistence is native-only). Out of scope here, cleanly enabled
  by this.

Naming it "custodial" makes the trust boundary self-describing: custodial inherently
means the custodian can see and act, so "this is custodial, not E2E" needs no extra
caveat, and "client-held is non-custodial" names the real confidentiality upgrade
for free.

## Off by default (#567), non-negotiable

Custodial sessions engage **only** when `slim.identity` is `signerjwt`/`spire`.
Under the PSK default nothing changes: the backend stays the single member and the
try-it path is byte-for-byte unchanged. This is additive to, not a replacement of,
the server-held-membership model. `MYCELIUM_CUSTODY_DISABLE=1` forces the
single-moderator path even under an identity tier, so the migration is reversible
without switching identity off.

The gate is also structural, not just policy. Per spike finding C,
`create_app_with_persistence_async` requires the identity provider/verifier pair, so
a custodial session cannot run on the PSK tier at all.

## The honest scope boundary (do not oversell)

Because it is custodial, the hub holds every session's private key and plaintext. So
this migration hardens three things:

1. **the wire and attribution**: cryptographic, non-forgeable, verifiable by
   real/remote members;
2. **access-by-membership**: split by MLS group membership rather than app logic;
3. **per-agent identity at the MLS layer**: finally true, where today the identity
   epic only identifies the backend's one App.

It is **NOT** E2E-from-the-hub. A compromised or malicious hub still sees and can
impersonate everything, which is just what "custodial" means. Confidentiality from
the hub is a different axis (#664 Mode 2, deliberately out of scope; custody does
not need it, and it would remove cognition). The pitch is "the trust boundary is now
honest, legible, and movable," not "more secure." The real confidentiality upgrade
arrives only with non-custodial (client-held) sessions or a second trust party on
the channel.

## How it works in the code

- **`app/services/custody.py`** is the primitive: the `custody_enabled()` gate, the
  per-session encrypted store (one directory per session under
  `<data>/custody/{room}/{handle}/`), the at-rest passphrase
  `HMAC(server session secret, workspace/room/handle)`, and the persistence-backed
  App create/join/restore calls proven in the spike
  (`create_app_with_persistence_async`, `restore_sessions_async`).
- **`app/services/room_channels.py`** custodies the fleet. Under an identity tier
  `invite()` stands up a real session (its listen runs concurrently with the
  moderator invite, single process) instead of inviting a bare Name; `remove()`
  gracefully leaves the group and deletes the store (revocation, no room-wide
  re-key); `send_as_custodian()` publishes as the actor; `restore_custody()` revives
  the fleet on restart. The moderator pre-builds the room's SignerJwt roster before
  its verifier is snapshotted so sessions verify on admit.
- **`app/routes/participate.py`** routes `respond` through the actor's custodial
  session. The moderator still `ingest_local`s the reply for the transcript, and
  dedups its own echo of the real MLS message by L9 message id, so the transcript
  stays single-copy.
- **`app/main.py`** revives every persisted session on startup via `restore_sessions`
  with no re-invite. The durable transcript/inbox (`persister.py`) is unchanged and
  stays the offline-replay layer: SLIM persistence resumes crypto state only, never
  missed messages.

## The at-rest passphrase

The per-session store passphrase is
`HMAC(MYCELIUM_CUSTODY_STORE_SECRET, ws/room/handle)` so each store gets a distinct
key and one leaked passphrase opens one session, not the fleet. The session secret
is server-held, deliberately NOT the actor's OIDC/SignerJwt token (which rotates
hourly and is not a durable at-rest key). `MYCELIUM_CUSTODY_REQUIRE_SECRET=1` makes
a host fail closed rather than derive keys from the public dev literal. Key rotation
and whether the secret is per-host or per-deployment are follow-ups.

## Proven

- `tests/test_custody.py`: the offline surface (the off-by-default gate, the
  passphrase boundary, the store layout, enumeration/deletion).
- `tests/test_custody_roundtrip.py` (SLIM-node-gated): a custodial session is a
  distinct MLS member with cryptographic wire attribution, plus within-process
  `restore_sessions` resume.
- `tests/test_custody_two_process_restart.py` (SLIM-node-gated): the headline
  acceptance. A real subprocess session is SIGKILLed and a fresh process resumes it
  from disk with no re-invite, the moderator receiving it with the same wire sender.
  This closes the two-process gap using the shipped `custody.py` code, not a spike
  copy.

## Lifecycle ties

A custodial session is created on first participation and torn down on removal,
tying to: #663 (invite/accept authorization, admit is where that gate belongs), #590
(revocation is dropping the session plus its store and roster JWK, with no room-wide
re-key), and the real-IdP handle fixes #656/#657 (email-shaped handles are valid
subjects).

## Non-goals

- #664 (blind-relay / Double Ratchet): orthogonal, cognition-killing, not required.
- Non-custodial (client-held) sessions: the next rung (native-only; a browser cannot
  persist), cleanly enabled by this but out of scope.
- No change to the message-replay model: the transcript stays.
