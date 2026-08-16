<!-- SPDX-License-Identifier: Apache-2.0 -->
# Spike report: SignerJwt floor → SLIM MLS member (#587)

**Status:** ✅ **PASS — executed 2026-08-16.** Two members, each self-signing with
its *own* local ES256 keypair and **no SPIRE**, established a GROUP/MLS session,
peer-verified against a shared roster JWKS, and exchanged a message both ways.
Reproduce with `./run.sh` (Docker + openssl + the `fastapi-backend` uv env).
**Feeds:** #476 (SignerJwt floor impl), #587 (SVID-delivery decision), #560 (epic).
**Do not:** use `STATIC_JWT` — proven `MlsNotSupported` for MLS (#581).

## Result

```
== 1/3  stock SLIM 2.1.0 node on :46358 ==
== 2/3  self-mint each member's ES256 keypair (PKCS#8) + roster JWKS ==
wrote /tmp/signerjwt-floor-spike/roster-jwks.json with 2 key(s): alice, bob
== 3/3  two SignerJwt members establish MLS + exchange a message ==
[moderator] creating GROUP/MLS session ...
[moderator] MLS session established (no MlsNotSupported).
[moderator] inviting participant ...
[moderator] participant joined + peer-verified.
[participant] received: 'alice: hello over MLS'
[moderator] received: 'bob: ack -- peer verified'

PASS: two SignerJwt-identified MLS members exchanged a verified message.
```

Stack that produced it: `slim-bindings==2.1.0` (PyPI) + `ghcr.io/agntcy/slim:2.1.0`
node (stock, no identity block, on `:46358`). `IdentityProviderConfig.JWT`
(SignerJwt) drove the MLS moderated session — the `session_moderator.rs` path that
panicked in #581 under `STATIC_JWT` — with **real peer verification and no node
change**, and with **no SPIRE server/agent and no shared PID namespace**.

## Why this spike (vs the #583 SPIRE spike)

#583 proved SPIRE JWT-SVIDs drive MLS — but only inside a container that **shares
the SPIRE agent's PID namespace** (the `unix` attestor gotcha). That is a hardened-
deployment topology, *not* how a resident mycelium agent runs: a resident agent is
the user's own Claude/Cursor session on their own machine, with no SPIRE agent to
attest it. #587 asks how *that* agent gets a credential the MLS channel accepts.

This spike answers it with the **SignerJwt floor**: the agent generates its own
ES256 keypair locally and self-signs a short-lived JWT. No SPIRE, no attestor, no
Workload API socket — so it runs straight on the host, matching the real resident
topology. This is the default resident credential path in
[`../slim-identity-svid-delivery.md`](../slim-identity-svid-delivery.md).

## The load-bearing finding: peer verification without SPIRE

A SignerJwt token **carries the signer's public key in its claims**, so a verifier
can check the signature against the key the token itself presents. But that alone
would let *anyone* self-sign and join — so trust rests on the verifier only
accepting keys it already knows. Each member's verifier holds a **static roster
JWKS** (`JwtKeyType.DECODING` + `JwtKeyFormat.JWKS`) of the trusted members' public
keys; a self-signed token is accepted iff its key is on the roster.

That roster JWKS **is the deployment's registration surface** — the mycelium
analogue of `mycelium agent credential set`: one JWK per agent, added when the agent
joins a room, keyed by `kid = @handle`. Trust is "this public key is on the room's
roster," distributed out of band; there is **no attestation and no issuer
discovery**. (`JwtKeyType.AUTORESOLVE` was tried first and fails on a self-issued
floor: with no static JWKS it falls back to OIDC discovery on the issuer, and
`mycelium-resident` is not a URL → `relative URL without a base`.)

## The proven-working pattern

```python
# Provider — sign our own JWT with our local PKCS#8 ES256 key:
enc = slim_bindings.JwtKeyConfig(
    algorithm=slim_bindings.JwtAlgorithm.ES256,
    format=slim_bindings.JwtKeyFormat.PEM,
    key=slim_bindings.JwtKeyData.DATA(value=my_pkcs8_pem),
)
provider = slim_bindings.IdentityProviderConfig.JWT(config=slim_bindings.ClientJwtAuth(
    key=slim_bindings.JwtKeyType.ENCODING(key=enc),
    audience=["mycelium-slim"], issuer="mycelium-resident",
    subject="alice",  # the @handle == SLIM Name leaf
    duration=datetime.timedelta(seconds=3600),
))
# Verifier — trust the room roster's public keys (static multi-key JWKS):
dec = slim_bindings.JwtKeyConfig(
    algorithm=slim_bindings.JwtAlgorithm.ES256,
    format=slim_bindings.JwtKeyFormat.JWKS,
    key=slim_bindings.JwtKeyData.DATA(value=roster_jwks_json),
)
verifier = slim_bindings.IdentityVerifierConfig.JWT(config=slim_bindings.JwtAuth(
    key=slim_bindings.JwtKeyType.DECODING(key=dec),
    audience=["mycelium-slim"], issuer="mycelium-resident", subject=None,
    duration=datetime.timedelta(seconds=3600),
))
app = svc.create_app(slim_bindings.Name("mycelium","default","alice"), provider, verifier)
# ... identical GROUP + MlsSettings SessionConfig, create_session, invite_async ...
```

Full runnable version: [`signerjwt_floor_spike.py`](./signerjwt_floor_spike.py); the
roster JWKS is assembled by [`build_roster_jwks.py`](./build_roster_jwks.py).

## SLIM `Name` / `subject` ↔ mycelium handle mapping

| JWT `subject` / JWKS `kid` | SLIM `Name` leaf | mycelium `@handle` |
|---|---|---|
| `alice` | `mycelium/default/alice` | `alice` |
| `bob`   | `mycelium/default/bob`   | `bob` |

**Rule:** the JWT `subject` is the `@handle`, and the roster JWKS `kid` is the same
`@handle` — so the verified signer maps 1:1 to the handle the hub binds writes to.
Unlike SPIRE (where the handle is the leaf of an *attested* SPIFFE ID), here the
handle→key binding is asserted at **registration** time and only as trustworthy as
the roster's provenance. That is the floor's honest ceiling: it authenticates
possession of a registered key, not a machine-attested workload identity.

## How to run

Requires Docker, `openssl`, and the `fastapi-backend` uv env
(`slim-bindings==2.1.0` + `cryptography`). From this directory:

```bash
./run.sh
```

It stands up a stock SLIM 2.1.0 node on `:46358` (not `:46357` — the dev node owns
that), self-mints each member's ES256 PKCS#8 keypair, builds the roster JWKS, runs
the two members on the host, and exits non-zero unless it prints `PASS`. The node
container is removed on exit.

## Gotchas (record for the #476 impl)

1. **Signing keys must be PKCS#8 PEM.** `openssl ecparam -genkey` emits SEC1 →
   `InvalidKeyFormat`; convert with `openssl pkcs8 -topk8 -nocrypt` (`run.sh` does).
   SPIRE sidesteps this — it manages its own keys — but the floor mints keys itself,
   so this gotcha is live here.
2. **`AUTORESOLVE` is the wrong verifier for a self-issued floor.** With no static
   JWKS it attempts OIDC discovery on the `issuer`; a non-URL issuer →
   `relative URL without a base`, and the invite fails with
   `message send retries exhausted`. Use `DECODING` + a static roster JWKS.
3. **`STATIC_JWT` still panics.** A handed-in *bearer* token → `StaticTokenProvider`
   → `MlsNotSupported` (#581). The floor works precisely because SignerJwt is a
   *signing* credential, not a bearer. This is the constraint that shapes the
   "handed-in token" option in the decision doc.
4. **Matched stack.** `slim-bindings==2.1.0` + `ghcr.io/agntcy/slim:2.1.0`. No PyPI
   2.2.x Python binding exists yet (the node ships 2.2.0) — pin 2.1.0 on both sides.

## Acceptance checklist (#587)

- [x] Working way for a **resident** agent (no SPIRE, no shared PID ns) to obtain +
      present a credential the MLS channel accepts — self-minted SignerJwt, run on
      the host, matching a real resident topology (not the shared-PID rig).
- [x] Mutual peer verification without SPIRE proven (roster JWKS), with the
      registration-surface implication spelled out.
- [x] PKCS#8 / `AUTORESOLVE` / `STATIC_JWT` constraints recorded so #476/#579 start
      de-risked.
- [x] `subject`/`kid` → `@handle` mapping documented.
- [x] Reproducible harness, one-command `./run.sh`, executed PASS (output above).
- [x] Node change needed? **No** — stock node forwards ciphertext; identity is
      app-level.

## References

- #587 — SVID delivery / attestation model for resident agents (this validates the
  default path) · [`../slim-identity-svid-delivery.md`](../slim-identity-svid-delivery.md)
- #476 — SignerJwt floor impl · #579 — SPIRE (hardened) · #581 — `STATIC_JWT` →
  `MlsNotSupported` · #560 — epic
- [`../spire-mls-spike/`](../spire-mls-spike/) — the hardened SPIRE sibling (#583)
- SLIM examples: `../_slim-research/slim-bindings/python/examples/{common,group}.py`
- deepwiki `agntcy/slim`: SignerJwt tokens embed the signer's public key in claims;
  the verifier's `KeyResolver` checks a static JWKS before attempting issuer
  discovery.
