<!-- SPDX-License-Identifier: Apache-2.0 -->
# Design: Identity & Auth — optional by default; OIDC/Keycloak for humans, SPIRE optional for agents

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

## Guiding principle: optional, off by default

**Auth must never be a wall between someone and "try this app out."** Setup
friction is the thing Mycelium exists to *remove*, so identity is **opt-in and off
by default** — the whole stack runs with no issuer, no tokens, and no SPIRE until an
operator deliberately turns it on.

- **Default (try-it / laptop / single trust domain):** no auth. Handles are
  self-asserted; the SLIM channel uses the dev PSK — exactly today's behavior. Zero
  new containers, zero config, nothing to stand up.
- **Opt-in (a team shares a hub over a network):** flip one switch → the HTTP-API
  JWT gate enforces OIDC tokens and binds handles from claims. A lightweight issuer,
  no heavy infra.
- **Opt-in, heavier (hardened / workload attestation):** add SPIRE. **This is the
  one piece with real operational *and* onboarding weight — a SPIRE server + agent +
  attestation — so it is strictly optional and never on the default path.**

Every layer below has an off switch, and "off" is the shipped default. If turning a
layer on gets in the way of trying or running Mycelium, that is a **bug in this
design**, not a tradeoff to accept.

## Principle: two audiences, two mechanisms

Identity has two distinct kinds of principal, and the ecosystem already points at
a different tool for each:

- **Agents are workloads.** By default they authenticate the **same OIDC way as
  humans** — a service-account token — so nothing extra is needed to run an agent.
  Where an operator wants zero-secret bootstrap, auto-rotation, and workload
  attestation, **SPIFFE/SPIRE** is an *optional* upgrade (JWT-SVIDs from the Workload
  API; upstream slim-bindings' recommended hardened setup for the SLIM plane, #476).
  SPIRE is never required to run an agent.
- **Humans are users.** They log in interactively and want SSO. That is **OIDC**
  (OAuth2 Authorization Code + PKCE), with **Keycloak** (or any OIDC issuer) as the
  identity provider.

> **Decision:** OIDC/Keycloak for humans; agents use an OIDC service-account by
> default, with **SPIRE as an optional hardening upgrade** — and **all of it off by
> default** (see the guiding principle above).

Both mechanisms ultimately present a **JWT** the services validate against a
**JWKS**. That is the unifying seam — see "Issuer-agnostic" below.

## Two enforcement planes

| Plane | What it protects | Human principal | Agent principal |
|-------|------------------|-----------------|-----------------|
| **HTTP API** (FastAPI `:8000`) | memory read/write, participate, room ops | OIDC bearer JWT (any issuer) | OIDC service-account JWT (default) · SPIRE JWT-SVID (optional) |
| **SLIM channel** (MLS group) | coordination messages, membership | (human acts by proxy through an agent/CLI) | dev PSK (default) · JWT+JWKS or SPIRE (opt-in — #476) |

Each cell above has an **off state that is the default** (no token / dev PSK); the
table describes what's enforced *once auth is turned on*. The **HTTP-API plane is
the urgent 80/20**: it closes the wide-open `:8000` and the impersonation gap with a
standard FastAPI dependency, independent of the deeper (optional) SLIM/MLS work.

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

Every layer ships **off by default** (see the guiding principle); enabling it is a
per-deployment opt-in.

1. **HTTP-API JWT gate** — FastAPI dependency validating a bearer JWT against a
   configured JWKS/issuer; reject unauthenticated. **Disabled by default** (and
   auto-off on localhost) so the try-it path is untouched.
2. **Verified handle binding** — derive handle + role from claims; stop trusting
   body-supplied actor fields. Only active when the gate is on.
3. **CLI human login** — `mycelium login` obtains a token (Authorization Code +
   PKCE, or device-code for headless), stores + refreshes it; `mycelium iam`
   becomes "who am I per the token," not self-assert.
4. **Agent identity issuance** — per-agent **OIDC service-account** credentials by
   default; **SPIRE JWT-SVID as an optional upgrade** where workload attestation is
   wanted.
5. **SLIM channel identity** — *optionally* move the MLS group off the dev PSK to
   per-member JWT/SPIRE (#476); the PSK remains the default. Deeper; partly gated on
   slim-bindings wiring.
6. **Reference IdP wiring** — an optional Keycloak compose profile + an optional
   SPIRE quickstart, with issuer-agnostic config documented.

## Non-goals

- **Requiring auth to try or run Mycelium.** Off-by-default is a hard requirement,
  not a nicety; the try-it / laptop path stays zero-config, zero-container.
- **Making SPIRE mandatory.** It is an optional hardening upgrade for agents, never
  the default and never a prerequisite — its weight (server + agent + attestation)
  must never land on someone just trying the app.
- **Baking Keycloak in as a hard dependency.** It is a supported issuer only.
- **Authorization / RBAC beyond identity + role.** Fine-grained per-room
  permissions are a later layer; this doc is authentication + attribution.

## Open questions

- Do agents present their SPIRE JWT-SVID **directly to the HTTP API** (one token,
  both planes), or hold separate credentials per plane? One token is simpler if the
  API can be configured to trust the SPIRE trust domain as an issuer.
- Handle namespace: is the canonical handle the raw `sub`, or a claim mapped to the
  existing `name#session` shape? Migration of existing self-asserted handles.
- ~~Localhost auth posture~~ — **resolved:** off by default everywhere, opt-in per
  deployment (see the guiding principle).

## References

- #476 — SLIM channel identity (JWT/JWKS/SPIRE); confirms slim-bindings supports
  both natively, `sub` = per-agent identity, SPIRE = upstream's prod recommendation.
- `fastapi-backend/app/services/slim_client.py` — `mint_shared_secret` (the D1 PSK).
- `mycelium-cli/src/mycelium/identity.py` — current self-asserted handle generation.
