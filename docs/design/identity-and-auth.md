<!-- SPDX-License-Identifier: Apache-2.0 -->
# Design: Identity & Auth — SPIRE for agents, OIDC/Keycloak for humans

**Status:** Proposed
**Related:** #476 (SLIM channel identity: JWT/JWKS/SPIRE), the D1 debt in `CLAUDE.md`
("real identity is a hard prerequisite before anything hosted / multi-user")

## Problem

Identity today is **self-asserted and unverified**, on two unguarded surfaces:

- **HTTP API** (`fastapi-backend`, bound `0.0.0.0:8000`): no auth of any kind. The
  actor of a write is whatever `created_by` / `sender_handle` the request body
  carries — the backend trusts it verbatim (`app/routes/memory.py`,
  `app/routes/participate.py`). Anyone who can reach `:8000` can read/write all
  memory and impersonate any `@handle`.
- **SLIM channel**: a per-channel key derived from a shared master secret
  (`mint_shared_secret`), scoped to `workspace/room` — the agent segment is
  ignored, so every member of a room is cryptographically indistinguishable, and
  revocation means rotating the secret for everyone (see #476).

`mycelium iam <name>` just generates a local handle (`identity.py:generate_handle`
→ `name#session`); nothing verifies it. This is safe only on localhost / a trusted
LAN. It is **the** gating item before a real team shares a hub over a network.

## Principle: two audiences, two mechanisms

Identity has two distinct kinds of principal, and the ecosystem already points at
a different tool for each:

- **Agents are workloads.** Their identity should bootstrap without a human, rotate
  automatically, and attest what they are. That is exactly **SPIFFE/SPIRE**
  (JWT-SVIDs from the Workload API). It is also upstream slim-bindings' recommended
  production setup (#476), so it is the AGNTCY-native path for the SLIM plane.
- **Humans are users.** They log in interactively and want SSO. That is **OIDC**
  (OAuth2 Authorization Code + PKCE), with **Keycloak** (or any OIDC issuer) as the
  identity provider.

> **Decision: SPIRE for agents, OIDC/Keycloak for humans.**

Both mechanisms ultimately present a **JWT** the services validate against a
**JWKS**. That is the unifying seam — see "Issuer-agnostic" below.

## Two enforcement planes

| Plane | What it protects | Human principal | Agent principal |
|-------|------------------|-----------------|-----------------|
| **HTTP API** (FastAPI `:8000`) | memory read/write, participate, room ops | OIDC bearer JWT (Keycloak) | SPIRE JWT-SVID *or* OIDC service-account token |
| **SLIM channel** (MLS group) | coordination messages, membership | (human acts by proxy through an agent/CLI) | SPIRE JWT-SVID (native), else JWT+JWKS — #476 |

Both planes validate a JWT. The **HTTP-API plane is the urgent 80/20**: it closes
the wide-open `:8000` and the impersonation gap with a standard FastAPI dependency,
independent of the deeper SLIM/MLS work.

## Issuer-agnostic (Keycloak is *a* provider, not *the* dependency)

Services validate a bearer JWT against a **configured issuer + JWKS URL** — they do
not know or care that the issuer is Keycloak. Consequences:

- The **appliance stays light.** Keycloak is heavy (JVM + its own Postgres), which
  fights Mycelium's no-database, single-appliance ethos. Making it a *supported
  issuer* rather than a baked-in dependency lets deployment weight scale with need:
  - **Laptop / single-operator:** a local dev issuer (or auth disabled on
    localhost). No IdP to run.
  - **Team hub / appliance:** a lightweight OIDC issuer (Dex / ZITADEL / Authentik)
    **or** Keycloak, whichever the team already runs.
  - **Hosted / enterprise:** Keycloak or the org's existing SSO.
- **Agents** get JWT-SVIDs from **SPIRE** regardless of the human IdP; the two are
  independent trust roots the API is configured to accept.

## Verified handle binding

Once a request carries a validated token, the **authoritative `@handle` and role
come from the token**, not the request body:

- `sub` (or a configured claim) → the canonical handle.
- a role/claim distinguishes **user** vs **agent**.
- `created_by` / `sender_handle` from the body are ignored (or must match the token).

This is what actually kills impersonation and makes attribution trustworthy across
the whole system (memory authorship, transcript senders, L9 actors).

## Rollout (phased, each independently shippable)

1. **HTTP-API JWT gate** — FastAPI dependency validating a bearer JWT against a
   configured JWKS/issuer; reject unauthenticated. Auth-optional on localhost for
   the laptop tier.
2. **Verified handle binding** — derive handle + role from claims; stop trusting
   body-supplied actor fields.
3. **CLI human login** — `mycelium login` obtains a token (Authorization Code +
   PKCE, or device-code for headless), stores + refreshes it; `mycelium iam`
   becomes "who am I per the token," not self-assert.
4. **Agent identity issuance** — per-agent credentials: SPIRE JWT-SVID (native) and
   an OIDC service-account fallback for environments without SPIRE.
5. **SLIM channel identity** — move the MLS group off the shared PSK to per-member
   JWT/SPIRE (#476). Deeper; partly gated on slim-bindings wiring.
6. **Reference IdP wiring** — an optional Keycloak compose profile + a SPIRE
   quickstart, with issuer-agnostic config documented.

## Non-goals

- **Baking Keycloak in as a hard dependency.** It is a supported issuer only.
- **Authorization / RBAC beyond identity + role.** Fine-grained per-room
  permissions are a later layer; this doc is authentication + attribution.
- **Replacing SPIRE with Keycloak for agents** (or vice versa). The split is
  deliberate: workload identity vs human SSO.

## Open questions

- Do agents present their SPIRE JWT-SVID **directly to the HTTP API** (one token,
  both planes), or hold separate credentials per plane? One token is simpler if the
  API can be configured to trust the SPIRE trust domain as an issuer.
- Handle namespace: is the canonical handle the raw `sub`, or a claim mapped to the
  existing `name#session` shape? Migration of existing self-asserted handles.
- Localhost auth posture: auth-off by default on `127.0.0.1`, or always-on with a
  zero-config local issuer?

## References

- #476 — SLIM channel identity (JWT/JWKS/SPIRE); confirms slim-bindings supports
  both natively, `sub` = per-agent identity, SPIRE = upstream's prod recommendation.
- `fastapi-backend/app/services/slim_client.py` — `mint_shared_secret` (the D1 PSK).
- `mycelium-cli/src/mycelium/identity.py` — current self-asserted handle generation.
