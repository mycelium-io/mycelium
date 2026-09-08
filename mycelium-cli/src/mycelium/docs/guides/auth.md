# Authentication

Mycelium's backend can require a signed **bearer token** on every HTTP API call,
validated against an OIDC issuer you configure. It is **off by default** and
nothing about the default install changes until you turn it on.

This is the **HTTP API plane** — what protects spokes in hub-and-spoke
deployments. It is separate from SLIM/MLS PSK or SignerJwt on the coordination
fabric; see [Security Planes](#security-planes).

## Off by default, on purpose

Auth must never be a wall between someone and trying Mycelium. A fresh install
runs with no issuer, no tokens, and no extra containers: memory, rooms, and
coordination all work exactly as they do today.

Turn it on when a **team shares a hub over a network**. Until then, leaving it off
is the supported configuration, not a shortcut.

> Without the gate, anyone who can reach the backend's port can read and write
> every room and post as any `@handle`. On a laptop that's fine. On a shared
> network it is not; that is precisely the moment to enable this.

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
one, **any** token your issuer has ever minted is accepted, including a token a
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
`jwks_url` (optional; omit to resolve it from the issuer's OIDC discovery
document), `audience` (optional per-issuer override), and `role`.

## Signing in from the CLI

The gate above is the hub's half. `mycelium login` is yours: it obtains an OIDC
token for **you**, caches it, and every later command sends it.

```bash
mycelium config set login.audience mycelium      # match the hub's auth.audience
mycelium login
```

Your browser opens, you sign in at your identity provider, and the CLI takes it
from there: `mycelium memory`, `mycelium room`, `await`, `respond` and the rest
now carry `Authorization: Bearer <token>`.

### The issuer comes from the hub

You do not set `login.issuer` to sign in. A gated hub advertises the issuers it
trusts in the `auth` block of its `/health`, and `server.api_url` already points
at it — so with no issuer configured and none passed, `login` asks the hub and
uses the answer, remembering it once the sign-in it drove has actually worked.

Three cases where it steps back and tells you instead, rather than guessing:

- **The hub is unreachable** — nothing to ask, so you get the original "set
  `login.issuer`" error.
- **The hub's gate is off** — it needs no login at all, and says so.
- **The hub trusts more than one issuer** — which one you sign in against decides
  who the hub thinks you are, so it lists them and asks you to pick with
  `--issuer`. The lookup is still done for you; only the choice isn't.

`--issuer` and a configured `login.issuer` both win over discovery, so nothing
about an existing setup changes and the hub is not consulted at all.

**On a machine with no browser** (SSH, CI, a container) use the device flow.
The CLI prints a URL and a short code you enter from any other device:

```bash
mycelium login --device
```

The CLI falls back to this automatically when it finds no browser to open, so
`mycelium login` over SSH does the right thing without the flag.

`mycelium logout` drops the session, and the CLI goes straight back to sending no
token at all.

### Login is opt-in, like the gate

Never running `mycelium login` changes nothing: with no cached session the CLI
sends no `Authorization` header, exactly as before this existed. That is what
keeps it safe against an ungated hub, which is the default one.

### Where the token lives

In `~/.mycelium/token.json`, created mode `0600`, **not** in `config.toml`.
Config is printed, copied between machines, and mirrored to `config.json` for the
frontend; a token in there would leak by routine. Set `MYCELIUM_TOKEN_FILE` to
cache it somewhere else (a CI runner with a shared home, say).

The access token is renewed automatically when it expires, using the refresh
token, on the way into the next call that needs it; you don't re-run `login` on
a schedule. Renewal needs a refresh token, which most issuers grant only for the
`offline_access` scope; it is in the default `login.scopes` for that reason. If
renewal fails, the CLI drops the header and tells you to sign in again rather
than sending a token the hub will reject.

### Who you are

`mycelium whoami` (and `mycelium iam` with no arguments) reports the handle from
your **token** when you're signed in, and the self-asserted `identity.name` when
you're not:

```
acting as @avery  (avery#a8f3)
  signed in (https://sso.example.com/realms/mycelium, expires in 42 min)
```

Because a gated hub attributes writes to the token (see *The token is the author*
below), a self-asserted handle that names someone else is a 403 in waiting. The
token wins that disagreement, so `login` settles it for you: on a successful
sign-in it points `identity.name` at the token's own handle and registers the
`users/` record — the same thing `mycelium iam <handle>` does, without the second
command. If that can't land (no readable handle claim, or a handle the store
rejects), `login` falls back to naming the mismatch and the command that fixes
it. Setting a handle your token won't back with `iam` still warns.

### Configuration

| Key | Default | What it does |
|-----|---------|--------------|
| `login.issuer` | *(unset)* | OIDC issuer to log in against. Unset means `login` asks the hub for one and caches what it gets. |
| `login.client_id` | `mycelium-cli` | OAuth client id registered for the CLI. |
| `login.client_secret` | *(unset)* | Only for issuers that refuse public clients; PKCE means the CLI normally needs none. |
| `login.scopes` | `openid profile email offline_access` | Scopes requested at login. |
| `login.audience` | *(unset)* | Audience to request; should match the hub's `auth.audience`. |
| `login.redirect_port` | `0` | Fixed loopback port for the browser redirect (`0` picks a free one). Set it when your issuer requires an exact registered redirect URI: the URI is `http://127.0.0.1:<port>/callback`. |

`MYCELIUM_LOGIN_ISSUER`, `MYCELIUM_LOGIN_CLIENT_ID`, `MYCELIUM_LOGIN_CLIENT_SECRET`,
`MYCELIUM_LOGIN_AUDIENCE` and `MYCELIUM_LOGIN_SCOPES` override the same settings,
for a runner that has no config file to edit.

The CLI is a **public client**: it authenticates with PKCE (S256) and ships no
secret. Register it at your issuer as a public client with
`http://127.0.0.1:*/callback` as an allowed redirect, and enable the device grant
if you want `--device` to work.

## Agents sign in as themselves

`mycelium login` is for a human. An agent has no browser to open and nobody
sitting there to click through a consent screen, so it authenticates as a
**workload**: its own OIDC client, minted with the `client_credentials` grant.
The token's `sub` is the client id, which is the agent's handle: the same handle
the hub binds its writes to.

That is the property a shared secret can't give you: each agent holds a different
credential, so **revoking one agent's client leaves every other agent working**.

Point the machine at the issuer agents mint from, then give each agent its own
client:

```bash
mycelium config set agent_auth.issuer https://sso.example.com/realms/agents
mycelium config set agent_auth.audience mycelium     # match the hub's auth.audience
mycelium config apply

mycelium agent credential set release-agent --secret-stdin < secret.txt
```

The client id defaults to the handle; pass `--client-id` when your issuer names
it differently. `mycelium agent credential show release-agent` reports what an
agent resolves to (never its secret), `... ls` lists every agent on the machine,
and `... rm` forgets one locally; revoke the client at your issuer to actually
kill it.

From then on, `mycelium await --room R --handle release-agent` and
`mycelium respond --handle release-agent` carry **that agent's** token, including
when they run from a shell where a human is logged in: a resident agent writes as
itself, not as whoever started it.

### Off by default here too

An agent with no credential sends no token, exactly as before. Configuring
`agent_auth.issuer` alone is *not* a credential: something has to have been issued
to that specific agent first, or a shared issuer would quietly turn every handle
into a token request. And if minting fails, the CLI drops the header rather than
inventing an error; against an ungated hub the call still works.

### Where the credential lives

In `~/.mycelium/agent-credentials.json`, mode `0600`, alongside a cached token per
agent under `~/.mycelium/agent-tokens/`. Client secrets are secrets, so they stay
out of `config.toml` for the same reason your session does. `client_credentials`
issues no refresh token; an expired agent token is simply re-minted from the
client.

For a container that runs exactly one agent and has no config file,
`MYCELIUM_AGENT_AUTH_ISSUER`, `MYCELIUM_AGENT_AUTH_CLIENT_ID`,
`MYCELIUM_AGENT_AUTH_CLIENT_SECRET`, `MYCELIUM_AGENT_AUTH_SCOPES` and
`MYCELIUM_AGENT_AUTH_AUDIENCE` say the same thing in environment variables, and
`MYCELIUM_AGENT_HANDLE` names the agent it is running as.

### A credential Mycelium didn't mint

`MYCELIUM_AGENT_AUTH_TOKEN` supplies a bearer token directly, used as-is and never
renewed here. That is the seam for a token minted elsewhere: a CI job, or a JWT
issued by a workload-identity system. Trusting one is a config entry on the hub
side too: another `[[auth.issuers]]` block with `role = "agent"`.
Nothing about it is required, and nothing about it is on by default.

### Configuration

| Key | Default | What it does |
|-----|---------|--------------|
| `agent_auth.issuer` | *(unset)* | Issuer agents mint service-account tokens from. Unset means agents send no token. |
| `agent_auth.scopes` | *(unset)* | Scopes requested for an agent token. Most issuers want none for `client_credentials`. |
| `agent_auth.audience` | *(unset)* | Audience to request; should match the hub's `auth.audience`. |

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

- **handle**, from `auth.handle_claim` (`sub` by default), normalized the same
  way stored handles are (leading `@` stripped, lowercased). An OIDC
  service-account whose client id is `release-agent` therefore arrives as
  `@release-agent`.
- **role**, from `auth.role_claim` if the token carries it, otherwise the `role`
  on the matched issuer block. Which root signed a token is usually the whole
  answer to user-vs-agent, so most deployments never set a role claim at all.

## The token is the author

The principal is not just recorded; it is the **actor of record** for every write
it makes. Memory authorship (`created_by` / `updated_by`), the transcript sender,
and L9 actor attribution all come from the token rather than from the handle the
request body supplies:

- The body **omits** the actor, or names the **same** handle, and the token's handle
  is stored. `@Alice` and `alice` are one principal; the comparison uses the same
  normalization as the store.
- The body names a **different** handle → **403**. A caller acting under the wrong
  identity gets told, rather than having its writes quietly re-attributed.
- A **session qualifier** (`alice#a8f3`, the same person on one machine) is kept
  as-is. The suffix rides along on the token's handle, so per-session attribution
  survives without letting the suffix name someone else.

With the gate off there is no principal, so every path keeps the self-asserted
actor from the body exactly as before; the try-it path is unchanged.

## Acting as another handle

Attribution answers *who wrote this*. Two calls ask something different: `mycelium
await` names **whose queue to drain**, and joining a room names **whose presence to
register**. Both take the handle as a request parameter, and draining a queue
consumes it (a turn served to one caller is not served again) so an unchecked
handle there means a valid token for `@bob` could read and swallow `@alice`'s
coordination stream.

A gated hub allows the call when either is true:

- the handle **is** the token's own (a session qualifier like `alice#a8f3` still names alice), or
- the handle's agent manifest **grants** the token's principal: its `owner`, or an entry in its `allow_from`.

Anything else is a **403**. Grants are per-room, because manifests are: owning
`@bot` in one room says nothing about a `@bot` in another.

The grant is what makes "await on behalf of" explicit rather than universal. An
agent running with its own credential needs nothing: it awaits itself. A human
driving an agent's loop from their own session does:

```bash
mycelium agent create bot --owner alice          # alice may now await --handle bot
mycelium agent create bot --allow-from ops-lead  # …and so may @ops-lead
```

A resident loop (`mycelium await --loop`) **stops** on a 401 or 403 rather than
retrying. A refused identity is not a blip, and re-polling it would flood the hub
for as long as the loop ran.

With the gate off nothing is checked here either, so an ungated hub still lets any
caller await any handle, which is also why a hub reachable beyond your machine
wants the gate on.

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

- `X-Forwarded-For` is deliberately ignored. It is caller-supplied, so honoring
  it would let any remote request claim to be local.
- **It does not fire for a backend running in Docker.** Traffic through a
  published port arrives from the bridge gateway, not loopback, and is
  indistinguishable from LAN traffic; treating that as local would silently open
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
| `403` | A valid token acting as a handle that is not its own: a body claiming a different author, or an `await`/join naming a handle that has not granted it. |
| `503` | The gate is on but unusable: no trusted issuers configured, or the issuer's JWKS is unreachable and nothing is cached. |

Only asymmetric signatures are accepted (`RS*`, `PS*`, `ES*`). The `none`
algorithm and the whole `HS*` family are refused before verification, so a public
JWKS key can never be replayed as an HMAC secret.

## Trying it locally

Follow the [Keycloak / OIDC Setup](#keycloak-oidc) guide to stand up a realm,
client, and human `mycelium login`, wired end-to-end.
