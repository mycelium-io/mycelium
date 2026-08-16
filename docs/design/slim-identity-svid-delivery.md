<!-- SPDX-License-Identifier: Apache-2.0 -->
# Design: SLIM identity — SVID delivery / attestation model for resident agents

**Status:** Decided (default path demonstrated; #579 SPIRE impl to follow)
**Related:** #587 (this decision), #476 (SignerJwt floor impl), #579 (SPIRE impl),
#581 (`STATIC_JWT` → `MlsNotSupported`), #585 (SLIM-channel epic),
#560 (umbrella identity epic),
[`identity-and-auth.md`](./identity-and-auth.md) (the umbrella identity design)
**Proven by:** [`signerjwt-floor-spike/`](./signerjwt-floor-spike/) (default path,
PASS 2026-08-16) and [`spire-mls-spike/`](./spire-mls-spike/) (hardened path, #583)

## Problem

Once #586 pinned the matched **slim-bindings 2.1.0 + node 2.1.0** stack, MLS with an
external *signing* identity works. That plumbing is proven. What was undecided is
**how a resident mycelium agent actually gets the credential it presents to the SLIM
channel** — and a resident agent is the hard case: it is the user's own
Claude/Cursor session, turn-based, on the user's own machine, with no SPIRE agent
standing by to attest it and no held socket.

This note fixes the credential-acquisition model **per topology**, with the hard
constraints baked in so the #476/#579 implementations start de-risked.

## The one constraint that rules out the obvious answer

**A static *bearer* token cannot drive MLS.** Presenting an externally-minted bearer
via `STATIC_JWT` panics `MlsOp(IdentityProviderError(MlsNotSupported))` (#581): MLS
needs a *signing* credential (it manages per-member MLS signature keys), and a
bearer token carries no signing key. Only two credential shapes work with MLS:

- **`IdentityProviderConfig.JWT` (SignerJwt)** — a local signing keypair (ES256,
  **PKCS#8** PEM; SEC1 → `InvalidKeyFormat`). The agent self-signs.
- **`IdentityProviderConfig.SPIRE`** — a JWT-SVID from the Workload API; the SPIRE
  agent holds the signing material.

Everything below follows from this: the SLIM-channel credential is always a
**signer**, never a bearer. The `MYCELIUM_AGENT_AUTH_TOKEN` bearer that the CLI
already accepts (`agent_credentials.py`) authenticates to the **HTTP API**; it is
*not* a SLIM-channel credential and must not be conflated with one.

## The decision, per topology

| Topology | Credential model | SLIM provider | Infra weight | Default? |
|---|---|---|---|---|
| A. Laptop / single trust domain | Shared-secret PSK (today) | `create_app_with_secret` | none | ✅ ships today |
| B. Resident agent, identity on, no SPIRE | **SignerJwt floor** (self-minted keypair) | `IdentityProviderConfig.JWT` | none | ✅ **default resident identity path** |
| C. Hardened / appliance | Co-located SPIRE, unix attestor | `IdentityProviderConfig.SPIRE` | SPIRE server+agent | opt-in upgrade |
| D. Externally-minted, handed in | Signing key / JWT-SVID handed in (**not a bearer**) | JWT or SPIRE | issuer-dependent | seam, constrained |

### A — Laptop / single trust domain (unchanged default)

The shared-secret PSK (`mint_shared_secret` → `create_app_with_secret`), scoped to
`workspace/room`. Zero infra, no per-agent identity, every room member
cryptographically indistinguishable. This is the **off-by-default** posture (#567):
identity stays off until an operator turns it on, and turning it on must never block
the try-it path. Nothing here changes it.

### B — SignerJwt floor (the default resident identity path) ✅

When an operator does want per-agent identity but runs no SPIRE, a resident agent
**mints its own credential locally**: generate an ES256 keypair (PKCS#8), self-sign
a short-lived JWT that embeds its public key, present it as
`IdentityProviderConfig.JWT`. No SPIRE agent, no attestor, no Workload API socket, no
shared PID namespace — so it runs on the agent's own machine, which is exactly the
resident topology. **Demonstrated end-to-end on the 2.1.0 stack** (two members
establish MLS, peer-verify, exchange a message):
[`signerjwt-floor-spike/`](./signerjwt-floor-spike/).

**Peer verification without SPIRE.** A SignerJwt token carries the signer's public
key in its claims, and each member's verifier holds a **static roster JWKS**
(`JwtKeyType.DECODING` + `JWKS`) of the trusted members' public keys — a self-signed
token is accepted iff its key is on the roster. That roster JWKS **is the
registration surface**: the mycelium analogue of `mycelium agent credential set`,
one JWK per agent (keyed by `kid = @handle`), added when the agent joins a room. The
moderator (the backend) holds the room roster; each agent trusts the moderator's key
plus its peers'.

**Honest ceiling.** The floor authenticates *possession of a registered key*, not a
machine-attested workload. The handle→key binding is asserted at registration and is
only as trustworthy as the roster's provenance. That is strictly better than today's
self-asserted `name#session` (a key can't be forged, and revocation is
per-agent — drop its JWK from the roster) but weaker than SPIRE's attestation. It is
the right *default* because it needs no infra; C is the upgrade when attestation
matters.

### C — Co-located SPIRE (hardened upgrade)

For hardened / appliance deployments, a co-located SPIRE agent mints JWT-SVIDs via
the `unix` workload attestor. Tightest attestation (the SVID is bound to an attested
workload, not a registered key), heaviest deploy. **Proven on the 2.1.0 stack**
(#583, [`spire-mls-spike/`](./spire-mls-spike/)) — same MLS mechanics as B, only the
provider/verifier pair differs.

The load-bearing operational constraint (surfaced by #584): the `unix` attestor
identifies the workload by `SO_PEERCRED` PID, so the SPIRE agent must **share the
workload's PID namespace** (`pid: "service:spire-agent"` / `hostPID`) and expose the
Workload API socket on a **named volume** (a host bind-mount drops peer creds on
Docker Desktop). Cross-namespace → `could not resolve caller information`, and the
member hangs at "Initializing spire identity manager." This is exactly why SPIRE is
**not** the resident default: a resident Claude/Cursor session does not run
co-located with a SPIRE agent in a shared PID namespace. Where the `unix` attestor
can't be co-located, a non-`unix` attestor (`k8s`, `docker`, `x509pop`, join-token)
sources the SVID instead — which is topology D.

### D — Externally-minted, handed in (a constrained seam)

The `MYCELIUM_AGENT_AUTH_TOKEN` passthrough already accepts a credential this CLI
didn't mint (from CI, a sidecar, a join-token/k8s/OIDC flow). **The constraint:**
for the SLIM channel this must be a **signing** credential (a private key the
SignerJwt provider signs with, or a JWT-SVID a provider can use to sign), **never a
static bearer** — a bearer is `STATIC_JWT`, which is `MlsNotSupported`. So:

- A handed-in **bearer** token → fine for the **HTTP-API** gate, useless for SLIM.
- A handed-in **signing key** → feeds the SignerJwt provider (topology B with an
  externally-provisioned key instead of a self-minted one).
- A handed-in **JWT-SVID + Workload API** → topology C/SPIRE with a non-`unix`
  attestor.

D is not a separate mechanism; it is B or C with the key sourced elsewhere. The doc
records it so no one assumes "we already pass a token through, so we're done" — the
token we pass through today is the wrong *shape* for MLS.

## What this de-risks for #476 / #579

- **#476 (SignerJwt floor):** the default resident path. Implement key mint (ES256
  PKCS#8), the roster-JWKS registration surface (`mycelium agent credential set`
  writing a JWK; the moderator assembling the room roster), and wire
  `IdentityProviderConfig.JWT` into `slim_client.py` behind the same off-by-default
  switch as the PSK. The spike is the reference; `AUTORESOLVE` is a dead end for a
  self-issued floor (use `DECODING` + static JWKS).
- **#579 (SPIRE):** the hardened upgrade. Same MLS mechanics; the work is the deploy
  topology (co-located agent, shared PID ns, named-volume socket) and the SPIFFE-ID
  → `@handle` mapping (#583).
- **Both:** the `@handle` is the JWT `subject` / JWKS `kid` (floor) or SPIFFE leaf
  (SPIRE), and it must reconcile with the HTTP-API OIDC `sub` binding and today's
  `name#session` shape — the open question already flagged in
  [`identity-and-auth.md`](./identity-and-auth.md) §"Verified handle binding".

## Constraints honored

- Identity stays **optional / off by default** (#567); the PSK (topology A) remains
  the zero-infra default. This note wires nothing onto the default path.
- No `STATIC_JWT` anywhere for MLS (#581).
- Matched stack only: `slim-bindings==2.1.0` + `ghcr.io/agntcy/slim:2.1.0`.
