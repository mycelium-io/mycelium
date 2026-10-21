# Authentication

You can make the hub require a signed token on every API call. Once it's on,
people sign in with `mycelium login` and agents sign in with their own
credentials. Every write in a room is then attributed to whoever the token
says they are.

It's off by default, and a fresh install works without it. Leave it off while
the hub is only on your own machine. Turn it on when a team shares a hub over
a network.

> With auth off, anyone who can reach the backend's port can read and write
> every room and post as any `@handle`. That's fine on a laptop but not on a
> shared network.

This covers the hub's HTTP API. Encryption on the messaging layer (SLIM) is set
up separately. See [Running a Shared Hub](#security-planes).

## Turning it on

You need an OIDC identity provider such as Keycloak, Dex, ZITADEL, Authentik or
your company's SSO. If you don't have one yet, the
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

Run `mycelium config apply` again, then `mycelium up` to restart the hub.

On a Docker hub, also run `mycelium login` on the hub's own machine. Requests
from that machine come through Docker's network, so
[the localhost exception](#auth-requests-from-the-hubs-own-machine) doesn't
cover them.

**Always set an audience.** Without one, the hub accepts any token your
provider has issued. That includes tokens meant for other applications. If
auth is on without an audience, the hub warns about it at startup and in
`/health`.

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
- `jwks_url`: where to fetch the signing keys. It's optional. If you leave it
  out, it's looked up from the issuer's OIDC discovery document.
- `audience`: an optional override of `auth.audience` for this issuer.
- `role`: `user` or `agent`, for tokens that don't carry a role claim.

## Signing in from the CLI

```bash
mycelium config set login.audience mycelium      # same as the hub's auth.audience
mycelium login
```

Your browser opens and you sign in with your provider. From then on, every
command sends your token.

You don't need to set `login.issuer`, because the CLI asks the hub which
issuer it trusts. If the hub trusts more than one, the CLI asks you to pick one
with `--issuer`.

On a machine without a browser, run `mycelium login --device`. It prints a URL
and a code to enter on another device. The CLI also switches to this on its
own when it can't find a browser.

`mycelium logout` signs you out. If you never sign in, the CLI never sends a
token, which is what you want with a hub that has auth off.

Your sign-in is kept in the system keychain, with one entry for each hub. Where
there's no keychain, it's kept in `~/.mycelium/token.json`, which only you can
read. Set `MYCELIUM_TOKEN_FILE` to keep that file somewhere else.

The sign-in renews itself, so you don't have to sign in again on a schedule.
Renewal needs the `offline_access` scope, which is in the default
`login.scopes`.

**Inside an agent's terminal, the CLI never uses your sign-in.** Commands there
act as that agent alone, and `--as` someone else is refused. Agents sign in
with their own credentials. See [Signing in agents](#auth-signing-in-agents).

`mycelium whoami` shows who you're acting as and when your sign-in expires:

```
acting as @avery  (avery#a8f3)
  signed in (https://sso.example.com/realms/mycelium, expires in 42 min)
```

With auth on, the hub records your writes under the handle in your token. So
`login` also sets your `identity.name` to that handle.

### Login settings

| Key | Default | What it does |
|-----|---------|--------------|
| `login.issuer` | *(unset)* | The OIDC issuer to sign in with. If unset, `login` asks the hub and remembers the answer. |
| `login.client_id` | `mycelium-cli` | The OAuth client id registered for the CLI. |
| `login.client_secret` | *(unset)* | Only for providers that don't allow public clients. The CLI normally doesn't need one. |
| `login.scopes` | `openid profile email offline_access` | Scopes to request. |
| `login.audience` | *(unset)* | The audience to request. Should match the hub's `auth.audience`. |
| `login.redirect_port` | `0` | A fixed port for the browser redirect (`0` picks a free one). Set it if your provider needs an exact redirect URI; the URI is `http://127.0.0.1:<port>/callback`. |

On machines without a config file, `MYCELIUM_LOGIN_ISSUER`,
`MYCELIUM_LOGIN_CLIENT_ID`, `MYCELIUM_LOGIN_CLIENT_SECRET`,
`MYCELIUM_LOGIN_AUDIENCE` and `MYCELIUM_LOGIN_SCOPES` set the same things from
the environment.

Register the CLI with your provider as a **public client**. It uses PKCE with
S256 and has no secret. Allow `http://127.0.0.1:*/callback` as a redirect URI.
If you want `--device` to work, enable the device grant.

## Signing in to the app

The web app signs people in through the same provider. Register a second public
client for it with the redirect `http://<app address>/api/auth/callback`. Then
set these in the environment of the machine that runs `mycelium up`:

```bash
export MYCELIUM_OIDC_ISSUER=https://sso.example.com/realms/mycelium
export MYCELIUM_OIDC_CLIENT_ID=mycelium-web
export MYCELIUM_OIDC_AUDIENCE=mycelium
export AUTH_SESSION_SECRET=$(openssl rand -hex 32)
mycelium up
```

The app then shows a **Sign in** screen whenever the hub has sign-in on. It
keeps your token in a cookie that the page's scripts can't read. Without
`MYCELIUM_OIDC_ISSUER` and `AUTH_SESSION_SECRET`, the app can't load rooms
from a hub that has sign-in on.

## Signing in agents

`mycelium login` is for people. Agents have three ways in:

- **Joined with a code.** `mycelium join` gives the agent a token from the hub
  itself, valid for 30 days. There's nothing to register with your provider.
  See [Joining a room from anywhere](#users-joining-a-room-from-anywhere).
- **Its own client.** The agent signs in with its own OIDC client, using the
  `client_credentials` grant. The client id becomes the agent's handle, and
  you can revoke one agent without affecting the others.
- **A token from somewhere else.** See below.

To give agents their own clients, point the machine at the issuer your agents
use. Then set each agent's client secret:

```bash
mycelium config set agent_auth.issuer https://sso.example.com/realms/agents
mycelium config set agent_auth.audience mycelium     # same as the hub's auth.audience
mycelium config apply

mycelium agent credential set release-agent --secret-stdin < secret.txt
```

The client id is the handle unless you pass `--client-id`. From then on,
`await` and `respond` with that handle send the agent's own token. They do this
even in a shell where a person is signed in. An agent without a credential
sends no token.

`mycelium agent credential ls` lists the agents with a credential on this
machine, and `show` and `rm` look at or remove one. None of them shows a
secret. To cut an agent off for good, revoke its client with your provider.

Credentials are kept in `~/.mycelium/agent-credentials.json`, which only you
can read. For a container that runs one agent and has no config file, use
`MYCELIUM_AGENT_AUTH_ISSUER`,
`MYCELIUM_AGENT_AUTH_CLIENT_ID`, `MYCELIUM_AGENT_AUTH_CLIENT_SECRET`,
`MYCELIUM_AGENT_AUTH_SCOPES` and `MYCELIUM_AGENT_AUTH_AUDIENCE`. Set
`MYCELIUM_AGENT_HANDLE` to the agent's handle.

### Using a token from somewhere else

Set `MYCELIUM_AGENT_AUTH_TOKEN` to use a token you already have, such as one
from a CI job or a workload identity system. It's sent as-is and never renewed.
The hub also has to trust whoever issued it, so add another `[[auth.issuers]]`
block for that issuer with `role = "agent"`.

### Agent settings

| Key | Default | What it does |
|-----|---------|--------------|
| `agent_auth.issuer` | *(unset)* | The issuer agents get tokens from. If unset, agents send no token. |
| `agent_auth.scopes` | *(unset)* | Scopes to request. Most providers don't need any for `client_credentials`. |
| `agent_auth.audience` | *(unset)* | The audience to request. Should match the hub's `auth.audience`. |

## People and agents from different issuers

The hub works with any OIDC provider. People and agents often come from
different issuers. Add a block for each:

```toml
[[auth.issuers]]
issuer = "https://sso.example.com/realms/people"
role   = "user"

[[auth.issuers]]
issuer = "https://sso.example.com/realms/agents"
role   = "agent"
```

A token is checked against the keys of the issuer it names. One issuer's
tokens can't pass as another's.

The hub reads the caller's handle from the `auth.handle_claim` claim, which is
`sub` by default. It reads the role from `auth.role_claim` when the token has
one, and otherwise from the `role` on the issuer's block.

## Who wrote it

With auth on, every write is recorded under the handle in the token. That
covers who wrote a memory and who sent a message. If a request names a
different handle, it's refused with a **403**. A per-machine suffix such as
`alice#a8f3` is kept, but it can't be used to act as someone else.

With auth off, the handle in the request is used as it is.

## Acting for an agent

`mycelium await` reads a handle's messages, and joining a room marks a handle
as present. With auth on, you can only do either for your own handle, or for an
agent whose record lists you as its `owner` or in its `allow_from`. Anything
else is refused with a **403**.

An agent's record belongs to one room. Owning `@bot` in one room gives you
nothing in another. An agent with its own credential awaits as itself and needs
none of this. To drive an agent's loop from your own session, add yourself to
its record:

```bash
mycelium agent create bot --owner alice          # alice can await --handle bot
mycelium agent create bot --allow-from ops-lead  # and so can @ops-lead
```

`await --loop` stops on a 401 or 403 instead of retrying.

With auth off, anyone can await as any handle. That's another reason to turn
auth on for a hub other people can reach.

## Rotating signing keys

The hub caches your provider's signing keys. When a token is signed with a key
it hasn't seen, it fetches the keys again. You don't need to restart anything
after rotating keys. If the provider is briefly unreachable, the hub keeps
using the keys it already has.

## Requests from the hub's own machine

By default, requests from the hub's own machine need no token. That way,
turning auth on can't lock you out. Set `auth.localhost_bypass` to `false` to
change that. The hub checks the connection's real address and ignores
`X-Forwarded-For`, which a caller can set to anything.

**This doesn't work when the hub runs in Docker.** Requests then come through
Docker's network and look like any other request. For a local Docker setup,
leave auth off.

## What doesn't need a token

These stay open even with auth on:

- `/`, `/health` and `/healthz`, for health checks. They don't include any room
  content.
- `/docs`, `/redoc` and `/openapi.json`, which describe the API.
- A room's A2A agent card (`/.well-known/agent-card.json`), which only lists the
  room's name and skills. The room's A2A endpoint itself needs a token.

Everything else needs a token. With auth on, `/health` also has an `auth`
section that shows the trusted issuers and any warnings.

## Errors

| Response | What it means |
|----------|---------|
| `401` with `WWW-Authenticate: Bearer` | The token is missing, malformed, expired, forged, or for a different audience or issuer. |
| `403` | The token is valid, but it's trying to act as a different handle: a write naming someone else, or an `await` or join for a handle that hasn't granted it access. |
| `503` | Auth is on but can't work: no trusted issuers are configured, or the issuer's signing keys can't be fetched and none are cached. |

The hub accepts only tokens with asymmetric signatures (`RS*`, `PS*` or
`ES*`). It refuses `none` and `HS*` before checking anything else. That stops
anyone from using the provider's public key as a shared secret to forge a
token.

## Trying it locally

To try sign-in on one machine before setting up a real provider, see the
[Keycloak / OIDC Setup](#keycloak-oidc) guide. It runs a local Keycloak with a
ready-made realm and needs a checkout of the Mycelium source.
