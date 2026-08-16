# Authentication

Mycelium's backend can require a signed **bearer token** on every HTTP API call,
validated against an OIDC issuer you configure. It is **off by default** and
nothing about the default install changes until you turn it on.

## Off by default, on purpose

Auth must never be a wall between someone and trying Mycelium. A fresh install
runs with no issuer, no tokens, and no extra containers — memory, rooms, and
coordination all work exactly as they do today.

Turn it on when a **team shares a hub over a network**. Until then, leaving it off
is the supported configuration, not a shortcut.

> Without the gate, anyone who can reach the backend's port can read and write
> every room and post as any `@handle`. On a laptop that's fine. On a shared
> network it is not — that is precisely the moment to enable this.

## Turning it on

```bash
mycelium config set auth.enabled true
mycelium config set auth.audience mycelium
mycelium config apply
```

Then declare at least one trust root in `~/.mycelium/config.toml`:

```toml
[auth]
enabled  = true
audience = "mycelium"

[[auth.issuers]]
issuer   = "https://sso.example.com/realms/mycelium"
jwks_url = "https://sso.example.com/realms/mycelium/protocol/openid-connect/certs"
role     = "user"
```

Re-run `mycelium config apply` and recreate the backend so it picks up the new
environment.

### Always set an audience

`audience` is optional but you should always set it when enabling auth. Without
one, **any** token your issuer has ever minted is accepted — including a token a
user obtained for a completely unrelated application on the same identity
provider. That token's holder was never authorized against your hub.

Setting an audience is what makes "a valid token" mean "a token meant for *this*
hub". The backend logs a warning at startup and flags it in `/health` when auth
is on without one.

## Configuration

| Key | Default | What it does |
|-----|---------|--------------|
| `auth.enabled` | `false` | Enforce bearer-token auth on the HTTP API. |
| `auth.issuers` | *(none)* | Trust roots, as repeatable `[[auth.issuers]]` blocks. |
| `auth.audience` | *(unset)* | Required `aud` claim. Set this whenever auth is on. |
| `auth.localhost_bypass` | `true` | Let loopback callers through without a token. |
| `auth.handle_claim` | `sub` | Claim carrying the canonical `@handle`. |
| `auth.role_claim` | `mycelium_role` | Claim distinguishing a user from an agent. |
| `auth.leeway_s` | `60` | Clock-skew allowance on `exp` / `nbf` / `iat`. |
| `auth.jwks_ttl_s` | `300` | How long a fetched JWKS is cached. |

Each `[[auth.issuers]]` block takes `issuer` (the exact `iss` to trust),
`jwks_url` (optional — omit to resolve it from the issuer's OIDC discovery
document), `audience` (optional per-issuer override), and `role`.

## Issuer-agnostic by design

The backend trusts a configured issuer and its JWKS. It has no idea whether that
is Keycloak, Dex, ZITADEL, Authentik, or your existing corporate SSO, and it never
needs one particular product installed.

**More than one trust root is normal.** Humans log in through an interactive OIDC
issuer; agents present service-account tokens, possibly from an entirely separate
root. List each as its own block:

```toml
[[auth.issuers]]
issuer = "https://sso.example.com/realms/people"
role   = "user"

[[auth.issuers]]
issuer = "https://sso.example.com/realms/agents"
role   = "agent"
```

Roots are matched by exact `iss` and never become interchangeable: a token signed
by the agent root but claiming the human root is checked against the human root's
keys, and fails.

## Handle and role

Once a token validates, the request has a **principal**:

- **handle** — from `auth.handle_claim` (`sub` by default), normalized the same
  way stored handles are (leading `@` stripped, lowercased). An OIDC
  service-account whose client id is `release-agent` therefore arrives as
  `@release-agent`.
- **role** — from `auth.role_claim` if the token carries it, otherwise the `role`
  on the matched issuer block. Which root signed a token is usually the whole
  answer to user-vs-agent, so most deployments never set a role claim at all.

## The token is the author

The principal is not just recorded — it is the **actor of record** for every write
it makes. Memory authorship (`created_by` / `updated_by`), the transcript sender,
and L9 actor attribution all come from the token rather than from the handle the
request body supplies:

- The body **omits** the actor, or names the **same** handle → the token's handle
  is stored. `@Alice` and `alice` are one principal; the comparison uses the same
  normalization as the store.
- The body names a **different** handle → **403**. A caller acting under the wrong
  identity gets told, rather than having its writes quietly re-attributed.
- A **session qualifier** (`alice#a8f3` — the same person on one machine) is kept
  as-is. The suffix rides along on the token's handle, so per-session attribution
  survives without letting the suffix name someone else.

With the gate off there is no principal, so every path keeps the self-asserted
actor from the body exactly as before — the try-it path is unchanged.

## Key rotation

The JWKS is fetched from your issuer and cached for `auth.jwks_ttl_s`. When a
token arrives signed by a key ID the backend hasn't seen, it re-fetches
immediately (rate-limited), so **rotating your signing key does not require
restarting Mycelium**.

If the issuer is briefly unreachable, previously fetched keys keep serving. The
keys are still your issuer's; only their freshness is in doubt, and failing closed
would take the hub down for the length of an IdP blip.

## The localhost bypass

With `auth.localhost_bypass` on (the default), requests whose **peer address** is
real loopback (`127.0.0.0/8`, `::1`) skip the gate, so turning auth on can't lock
you out of the machine the hub runs on.

Two things worth knowing:

- `X-Forwarded-For` is deliberately ignored. It is caller-supplied, so honouring
  it would let any remote request claim to be local.
- **It does not fire for a backend running in Docker.** Traffic through a
  published port arrives from the bridge gateway, not loopback, and is
  indistinguishable from LAN traffic — treating that as local would silently open
  the hub to your whole network. For the containerized local tier, leave
  `auth.enabled` off; that is the honest switch for it.

## What stays open

Health (`/`, `/health`) and the schema/docs routes are served without a token even
when the gate is on: orchestrator probes are unauthenticated by nature, and the
health payload reveals no room content. `/health` gains an `auth` block reporting
whether the hub is gated, which issuers it trusts, and any configuration warnings.

Every other route requires a token.

## Failure modes

| Response | Meaning |
|----------|---------|
| `401` + `WWW-Authenticate: Bearer` | Missing, malformed, expired, forged, wrong-audience, or wrong-issuer token. |
| `403` | A valid token, but the request body claims to act as a different handle. |
| `503` | The gate is on but unusable — no trusted issuers configured, or the issuer's JWKS is unreachable and nothing is cached. |

Only asymmetric signatures are accepted (`RS*`, `PS*`, `ES*`). The `none`
algorithm and the whole `HS*` family are refused before verification, so a public
JWKS key can never be replayed as an HMAC secret.

## Trying it locally

A dev OIDC issuer ships for exactly this, so you can exercise the gate without
standing up Keycloak. See `docs/design/dev-auth-issuer.md`.
