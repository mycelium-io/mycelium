# Authentication

You can make the hub require a signed token on every API call. Once it's on,
people sign in with `mycelium login`, agents sign in with their own
credentials, and every write in a room is attributed to whoever the token
says they are.

It's off by default, and a fresh install works without it. Leave it off while
the hub is only on your own machine. Turn it on when a team shares a hub over
a network.

> With auth off, anyone who can reach the backend's port can read and write
> every room, and post as any `@handle`. That's fine on a laptop. It isn't on
> a shared network.

This covers the hub's HTTP API. Encryption on the messaging layer (SLIM) is
set up separately; see [Security Planes](#security-planes).

## Turning it on

You need an OIDC identity provider, such as Keycloak, Dex, ZITADEL, Authentik
or your company's SSO. If you don't have one yet, the
[Keycloak / OIDC Setup](#keycloak-oidc) guide walks you through a local one.

Enable auth and set an audience:

```bash
mycelium config set auth.enabled true
mycelium config set auth.audience mycelium
mycelium config apply
```

Then add your provider as a trusted issuer in `~/.mycelium/config.toml`:

```toml
[auth]
enabled  = true
audience = "mycelium"

[[auth.issuers]]
issuer   = "https://sso.example.com/realms/mycelium"
jwks_url = "https://sso.example.com/realms/mycelium/protocol/openid-connect/certs"
role     = "user"
```

Run `mycelium config apply` again, and recreate the backend so it picks up the
change.

### Always set an audience

The audience is technically optional, but set it. Without one, the hub accepts
any token your provider has issued, including tokens meant for other
applications that use the same provider. The audience limits it to tokens
issued for this hub.

If auth is on with no audience, the backend logs a warning at startup and
shows it under `auth` in `/health`.

### Settings

| Key | Default | What it does |
|-----|---------|--------------|
| `auth.enabled` | `false` | Require a token on the HTTP API. |
| `auth.issuers` | *(none)* | Trusted issuers, as repeated `[[auth.issuers]]` blocks. |
| `auth.audience` | *(unset)* | The `aud` claim a token must have. Set this whenever auth is on. |
| `auth.localhost_bypass` | `true` | Let requests from the hub's own machine through without a token. |
| `auth.handle_claim` | `sub` | The claim that holds the user's `@handle`. |
| `auth.role_claim` | `mycelium_role` | The claim that says whether the caller is a user or an agent. |
| `auth.leeway_s` | `60` | How much clock difference to allow on `exp`, `nbf` and `iat`. |
| `auth.jwks_ttl_s` | `300` | How long to cache the issuer's signing keys. |

Each `[[auth.issuers]]` block takes:

- `issuer`: the exact `iss` value to trust.
- `jwks_url`: where to fetch the signing keys. Optional; if you leave it out,
  it's looked up from the issuer's OIDC discovery document.
- `audience`: optional, to override `auth.audience` for this issuer.
- `role`: `user` or `agent`, for tokens that don't carry a role claim.

## Signing in from the CLI

```bash
mycelium config set login.audience mycelium      # same as the hub's auth.audience
mycelium login
```

Your browser opens, you sign in with your provider, and from then on every
command (`mycelium memory`, `mycelium room`, `await`, `respond` and the rest)
sends your token.

You don't need to set `login.issuer`. The CLI asks the hub which issuer it
trusts and uses that. It won't guess in these cases:

- **The hub can't be reached.** It asks you to set `login.issuer`.
- **The hub has auth off.** It tells you there's nothing to sign in to.
- **The hub trusts more than one issuer.** It lists them and asks you to pick
  one with `--issuer`, since that decides who the hub thinks you are.

If you pass `--issuer` or have `login.issuer` set, the CLI uses that and
doesn't ask the hub.

**On a machine without a browser** (over SSH, in CI, in a container), use the
device flow. The CLI prints a URL and a code to enter on another device:

```bash
mycelium login --device
```

If the CLI can't find a browser, it switches to this on its own.

`mycelium logout` signs you out. After that, the CLI stops sending a token.

If you never run `mycelium login`, the CLI never sends a token, which is what
you want against a hub with auth off.

### Where your token is stored

In `~/.mycelium/token.json`, readable only by you (`0600`). It's kept out of
`config.toml` because config files get printed and copied around. Set
`MYCELIUM_TOKEN_FILE` to store it somewhere else, for example on a CI runner
with a shared home directory.

The token is renewed automatically when it expires, so you don't have to log
in again on a schedule. Renewal needs a refresh token, which most providers
only give out for the `offline_access` scope, so that scope is in the default
`login.scopes`. If renewal fails, the CLI stops sending the token and tells you
to sign in again.

### Checking who you are

`mycelium whoami`, or `mycelium iam` with no arguments, shows the handle from
your token when you're signed in, and your configured `identity.name` when
you're not:

```
acting as @avery  (avery#a8f3)
  signed in (https://sso.example.com/realms/mycelium, expires in 42 min)
```

When auth is on, the hub attributes your writes to the handle in your token
(see [Who wrote it](#auth)), so a different `identity.name` would get your
writes rejected. When you sign in, `login` sets `identity.name` to your
token's handle and registers you as a user, the same as running
`mycelium iam <handle>`. If it can't (the token has no usable handle, or the
handle isn't valid), it tells you what's wrong and what to run. Running `iam`
with a handle your token doesn't match still warns you.

### Login settings

| Key | Default | What it does |
|-----|---------|--------------|
| `login.issuer` | *(unset)* | The OIDC issuer to sign in with. If unset, `login` asks the hub and remembers the answer. |
| `login.client_id` | `mycelium-cli` | The OAuth client id registered for the CLI. |
| `login.client_secret` | *(unset)* | Only for providers that don't allow public clients. The CLI normally doesn't need one. |
| `login.scopes` | `openid profile email offline_access` | Scopes to request. |
| `login.audience` | *(unset)* | The audience to request. Should match the hub's `auth.audience`. |
| `login.redirect_port` | `0` | A fixed port for the browser redirect (`0` picks a free one). Set it if your provider needs an exact redirect URI; the URI is `http://127.0.0.1:<port>/callback`. |

`MYCELIUM_LOGIN_ISSUER`, `MYCELIUM_LOGIN_CLIENT_ID`, `MYCELIUM_LOGIN_CLIENT_SECRET`,
`MYCELIUM_LOGIN_AUDIENCE` and `MYCELIUM_LOGIN_SCOPES` set the same things from
the environment, for machines without a config file.

Register the CLI with your provider as a **public client** (it uses PKCE with
S256 and has no secret), allow `http://127.0.0.1:*/callback` as a redirect
URI, and enable the device grant if you want `--device` to work.

## Signing in agents

`mycelium login` is for people. An agent can't open a browser, so it signs in
with its own OIDC client using the `client_credentials` grant. The client id
becomes the agent's handle.

Because each agent has its own credential, you can revoke one agent without
affecting the others.

Point the machine at the issuer your agents use, then give each agent its own
client secret:

```bash
mycelium config set agent_auth.issuer https://sso.example.com/realms/agents
mycelium config set agent_auth.audience mycelium     # same as the hub's auth.audience
mycelium config apply

mycelium agent credential set release-agent --secret-stdin < secret.txt
```

The client id is the handle unless you pass `--client-id`.

- `mycelium agent credential show release-agent` shows what an agent will sign
  in as (never its secret).
- `mycelium agent credential ls` lists every agent on this machine.
- `mycelium agent credential rm` removes one from this machine. To actually
  cut an agent off, revoke its client with your provider.

After that, `mycelium await --room R --handle release-agent` and
`mycelium respond --handle release-agent` send that agent's token, even from a
shell where a person is signed in. The agent writes as itself, not as whoever
started it.

An agent without a credential sends no token. Setting `agent_auth.issuer` on
its own doesn't give any agent a credential; each one needs a secret set
first. If getting a token fails, the CLI sends the request without one, so it
still works against a hub with auth off.

### Where agent credentials are stored

In `~/.mycelium/agent-credentials.json`, readable only by you (`0600`), with a
cached token for each agent in `~/.mycelium/agent-tokens/`. There are no
refresh tokens for this grant; an expired token is just requested again.

For a container that runs one agent and has no config file, use environment
variables: `MYCELIUM_AGENT_AUTH_ISSUER`, `MYCELIUM_AGENT_AUTH_CLIENT_ID`,
`MYCELIUM_AGENT_AUTH_CLIENT_SECRET`, `MYCELIUM_AGENT_AUTH_SCOPES`,
`MYCELIUM_AGENT_AUTH_AUDIENCE`, and `MYCELIUM_AGENT_HANDLE` for the agent's
handle.

### Using a token from somewhere else

Set `MYCELIUM_AGENT_AUTH_TOKEN` to use a token you already have, for example
one from a CI job or a workload identity system. It's sent as-is and never
renewed. The hub also has to trust whoever issued it: add another
`[[auth.issuers]]` block for it with `role = "agent"`.

### Agent settings

| Key | Default | What it does |
|-----|---------|--------------|
| `agent_auth.issuer` | *(unset)* | The issuer agents get tokens from. If unset, agents send no token. |
| `agent_auth.scopes` | *(unset)* | Scopes to request. Most providers don't need any for `client_credentials`. |
| `agent_auth.audience` | *(unset)* | The audience to request. Should match the hub's `auth.audience`. |

## People and agents from different issuers

The hub works with any OIDC provider. It only needs each issuer's URL and
signing keys.

It's common for people and agents to come from different issuers. Add a block
for each:

```toml
[[auth.issuers]]
issuer = "https://sso.example.com/realms/people"
role   = "user"

[[auth.issuers]]
issuer = "https://sso.example.com/realms/agents"
role   = "agent"
```

A token is checked against the keys of the issuer it names in `iss`, so one
issuer's tokens can't pass as another's.

## How a token becomes a handle and a role

When a token is accepted, the hub reads two things from it:

- **The handle**, from `auth.handle_claim` (`sub` by default). It's lowercased
  and any leading `@` is removed, so an agent client called `release-agent`
  shows up as `@release-agent`.
- **The role**, from `auth.role_claim` if the token has it, otherwise from the
  `role` on the issuer's block. Since people and agents usually come from
  different issuers, most setups never need a role claim.

## Who wrote it

With auth on, the handle in the token is who a write is attributed to. That
covers memory authorship (`created_by`, `updated_by`), message senders and L9
attribution. The handle in the request itself only matters if it disagrees:

- If the request leaves the handle out, or gives the same one (`@Alice` and
  `alice` count as the same), the token's handle is used.
- If the request names a different handle, it's rejected with a **403**,
  rather than quietly saved under the token's handle.
- A session suffix, like `alice#a8f3` for Alice on one machine, is kept. It
  can't be used to act as someone else.

With auth off, the handle in the request is used as-is.

## Acting for an agent

Two calls take a handle that isn't about authorship:

- `mycelium await` reads and consumes that handle's queue of messages.
- Joining a room records that handle as present.

Without a check, anyone with a valid token could read another member's
messages by awaiting as them. So with auth on, these calls are only allowed
when:

- the handle is your own (a session suffix like `alice#a8f3` still counts as
  alice), or
- the agent's manifest lists you as its `owner`, or in its `allow_from`.

Anything else gets a **403**. Manifests belong to a room, so owning `@bot` in
one room doesn't give you access to a `@bot` in another.

An agent with its own credential awaits as itself and needs nothing extra. If
you want to drive an agent's loop from your own session, grant yourself
access:

```bash
mycelium agent create bot --owner alice          # alice can await --handle bot
mycelium agent create bot --allow-from ops-lead  # and so can @ops-lead
```

A running `mycelium await --loop` stops on a 401 or 403 instead of retrying,
since retrying a refused identity would just flood the hub.

With auth off, none of this is checked: anyone can await as any handle.
That's another reason to turn auth on for a hub other people can reach.

## Rotating signing keys

The hub caches your provider's signing keys for `auth.jwks_ttl_s`. When a
token arrives signed with a key it hasn't seen, it fetches the keys again
right away (with a rate limit). You don't need to restart Mycelium after
rotating keys.

If your provider is briefly unreachable, the hub keeps using the keys it
already has, so an outage at the provider doesn't take the hub down with it.

## Requests from the hub's own machine

With `auth.localhost_bypass` on (the default), requests from the hub's own
machine (`127.0.0.0/8` or `::1`) don't need a token. That way, turning auth on
can't lock you out.

- The hub only looks at the connection's real address. It ignores
  `X-Forwarded-For`, since a caller can set that to anything.
- **This doesn't work when the backend runs in Docker.** Requests through a
  published port come from Docker's network, not from loopback, and look the
  same as requests from elsewhere on your network. For a local Docker setup,
  leave auth off instead.

## What doesn't need a token

These stay open even with auth on:

- `/`, `/health` and `/healthz`, for health checks. They don't include any
  room content.
- `/docs`, `/redoc` and `/openapi.json`, which describe the API.
- A room's A2A agent card (`/.well-known/agent-card.json`), which only lists
  the room's name and skills. The room's A2A endpoint itself needs a token.

With auth on, `/health` includes an `auth` section showing whether auth is on,
which issuers are trusted, and any configuration warnings.

Everything else needs a token.

## Errors

| Response | What it means |
|----------|---------|
| `401` with `WWW-Authenticate: Bearer` | The token is missing, malformed, expired, forged, or for a different audience or issuer. |
| `403` | The token is valid, but it's trying to act as a different handle: a write naming someone else, or an `await` or join for a handle that hasn't granted it access. |
| `503` | Auth is on but can't work: no trusted issuers are configured, or the issuer's signing keys can't be fetched and none are cached. |

Only asymmetric signatures are accepted (`RS*`, `PS*`, `ES*`). Tokens using
`none` or any `HS*` algorithm are rejected before they're checked, so the
provider's public key can't be misused as a shared secret to forge a token.

## Trying it locally

The [Keycloak / OIDC Setup](#keycloak-oidc) guide sets up a local provider, a
client and `mycelium login`, end to end.
