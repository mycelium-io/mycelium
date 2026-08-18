# Server-side per-actor twin sessions (#666)

## What this is

Under the PSK default the backend is a single SLIM/MLS member per room that
impersonates every actor. Attribution ("@alice said this") is stamped by the
backend at the L9/transcript layer after the fact: application level, forgeable by
the backend, invisible on the wire. One MLS identity, the backend's, carries all
traffic.

Under an identity tier (`signerjwt`/`spire`) the backend becomes a **custodian of
N twin Apps**, one per `(room, actor)`. Each twin is a genuine MLS member
authenticating with the actor's own credential, so:

- `respond(@alice, …)` sends through @alice's twin, which is cryptographically
  @alice on the wire (verifiable off the inbound `MessageContext`, not a
  backend-stamped field).
- Room access is enforced by **MLS group membership**: a twin is only in the rooms
  its actor belongs to, so "who may touch which room" is crypto, not app logic.

All twins live in the backend process, so the moderator App plus the aligner, plan
compiler, memory-sync, and L9 layers still read plaintext. Cognition is preserved.

## Off by default (#567), non-negotiable

Twins engage **only** when `slim.identity` is `signerjwt`/`spire`. Under the PSK
default nothing changes: the backend stays the single member and the try-it path
is byte-for-byte unchanged. This is additive to, not a replacement of, the
server-held-membership model. `MYCELIUM_TWINS_DISABLE=1` forces the
single-moderator path even under an identity tier, so the migration is reversible
without switching identity off.

The gate is also structural, not just policy. Per spike finding C,
`create_app_with_persistence_async` requires the identity provider/verifier pair,
so a twin cannot run on the PSK tier at all.

## The honest scope boundary (do not oversell)

Twins are **server-side**: the hub holds every twin's private key and plaintext.
So this migration hardens three things:

1. **the wire and attribution**: cryptographic, non-forgeable, verifiable by
   real/remote members;
2. **access-by-membership**: split by MLS group membership rather than app logic;
3. **per-agent identity at the MLS layer**: finally true, where today the identity
   epic only identifies the backend's one App.

It is **NOT** E2E-from-the-hub. A compromised or malicious hub still sees and can
impersonate everything. Confidentiality-from-the-hub is a different axis (#664 Mode
2, deliberately out of scope; twins do not need it, and it would remove cognition).
The pitch is "the trust boundary is now honest, legible, and movable," not "more
secure." The real confidentiality upgrade arrives only with client-held twins (the
next rung, native-only, out of scope here) or a second trust party on the channel.

## How it works in the code

- **`app/services/twins.py`** is the custodian primitive: the `twins_enabled()`
  gate, the per-twin encrypted store (one directory per twin under
  `<data>/twins/{room}/{handle}/`), the at-rest passphrase
  `HMAC(server session secret, workspace/room/handle)`, and the persistence-backed
  App create/join/restore calls proven in the spike
  (`create_app_with_persistence_async`, `restore_sessions_async`).
- **`app/services/room_channels.py`** custodies the fleet. Under an identity tier
  `invite()` stands up a real twin (its listen runs concurrently with the moderator
  invite, single process) instead of inviting a bare Name; `remove()` gracefully
  leaves the group and deletes the store (revocation, no room-wide re-key);
  `send_as_twin()` publishes as the actor; `restore_twins()` revives the fleet on
  restart. The moderator pre-builds the room's SignerJwt roster before its verifier
  is snapshotted so twins verify on admit.
- **`app/routes/participate.py`** routes `respond` through the actor's twin. The
  moderator still `ingest_local`s the reply for the transcript, and dedups its own
  echo of the twin's MLS message by L9 message id, so the transcript stays
  single-copy.
- **`app/main.py`** revives every persisted twin on startup via `restore_sessions`
  with no re-invite. The durable transcript/inbox (`persister.py`) is unchanged and
  stays the offline-replay layer: SLIM persistence resumes crypto state only, never
  missed messages.

## The at-rest passphrase

The per-twin store passphrase is `HMAC(MYCELIUM_TWIN_STORE_SECRET, ws/room/handle)`
so each twin store gets a distinct key and one leaked passphrase opens one twin,
not the fleet. The session secret is server-held, deliberately NOT the actor's
OIDC/SignerJwt token (which rotates hourly and is not a durable at-rest key).
`MYCELIUM_TWIN_STORE_REQUIRE_SECRET=1` makes a host fail closed rather than derive
keys from the public dev literal. Key rotation and whether the secret is per-host
or per-deployment are follow-ups.

## Proven

- `tests/test_twins.py`: the offline surface (the off-by-default gate, the
  passphrase boundary, the store layout, enumeration/deletion).
- `tests/test_twins_roundtrip.py` (SLIM-node-gated): a twin is a distinct MLS
  member with cryptographic wire attribution, plus within-process
  `restore_sessions` resume.
- `tests/test_twin_two_process_restart.py` (SLIM-node-gated): the headline
  acceptance. A real subprocess twin is SIGKILLed and a fresh process resumes it
  from disk with no re-invite, the moderator receiving it with the same wire
  sender. This closes the two-process gap using the shipped `twins.py` code, not a
  spike copy.

## Lifecycle ties

A twin is created on first participation and torn down on removal, tying to: #663
(invite/accept authorization, twin admit is where that gate belongs), #590
(revocation is dropping the twin plus its store and roster JWK, with no room-wide
re-key), and the real-IdP handle fixes #656/#657 (email-shaped handles are valid
twin subjects).

## Non-goals

- #664 (blind-relay / Double Ratchet): orthogonal, cognition-killing, not required.
- Client-held twins: the next rung (native-only; a browser cannot persist), cleanly
  enabled by this but out of scope.
- No change to the message-replay model: the transcript stays.
