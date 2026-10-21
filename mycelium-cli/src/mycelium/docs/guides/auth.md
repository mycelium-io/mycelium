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

Run `mycelium config apply` again, then `mycelium up` to restart the hub. On a
Docker hub, run `mycelium login` on the hub's own machine too: its requests
come through Docker's network, so
[the localhost exception](#auth-requests-from-the-hubs-own-machine) doesn't
apply.

**Always set an audience.** Without one, the hub accepts any token your
provider issued, including tokens meant for other applications. With auth on
and no audience, the backend warns at startup and in `/health`.

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

Your browser opens to sign in with your provider, and every command then sends
your token. The CLI asks the hub which issuer it trusts, so you don't set
`login.issuer` unless the hub can't be reached or trusts more than one (then
pick with `--issuer`).

Without a browser (SSH, CI, a container), `mycelium login --device` prints a
URL and a code to enter elsewhere; the CLI switches to it on its own when it
finds no browser. `mycelium logout` signs you out. If you never sign in, the
CLI never sends a token, which is right for a hub with auth off.

Your sign-in is kept in the system keychain (macOS Keychain, Windows
Credential Manager or the Secret Service on Linux), one entry per hub, or in a
`0600` `~/.mycelium/token.json` where there's no keychain. It renews itself, so
you don't sign in on a schedule; that needs the `offline_access` scope, which
is in the default `login.scopes`. `MYCELIUM_TOKEN_FILE` moves the file, which
helps on a CI runner with a shared home folder.

**Inside an agent's terminal,** the CLI never uses your sign-in: commands act
as that agent alone, and `--as` someone else is refused. Agents sign in with
their own credentials (see [Signing in agents](#auth-signing-in-agents)).

`mycelium whoami` shows who you're acting as and when your sign-in expires:

```
acting as @avery  (avery#a8f3)
  signed in (https://sso.example.com/realms/mycelium, expires in 42 min)
```

With auth on, the hub writes as the handle in your token, so `login` also sets
`identity.name` to it and registers you as a user.

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

The app then shows a **Sign in** screen when the hub's sign-in is on, and keeps
your token in a cookie its scripts can't read. Without `MYCELIUM_OIDC_ISSUER`
and `AUTH_SESSION_SECRET`, it can't load rooms on such a hub.

## Signing in agents

`mycelium login` is for people. Agents have three ways in:

- **Joined with a code.** `mycelium join` gives the agent a 30-day token from
  the hub, with nothing to register. See
  [Joining a room from anywhere](#users-joining-a-room-from-anywhere).
- **Its own client**, with the `client_credentials` grant; the client id is
  its handle. Each agent can be revoked on its own.
- **A token from somewhere else**, below.

For its own client, point the machine at your agents' issuer and give each
agent its client secret:

```bash
mycelium config set agent_auth.issuer https://sso.example.com/realms/agents
mycelium config set agent_auth.audience mycelium     # same as the hub's auth.audience
mycelium config apply

mycelium agent credential set release-agent --secret-stdin < secret.txt
```

The client id is the handle unless you pass `--client-id`. `agent credential
show`, `ls` and `rm` inspect and remove them (never showing a secret); to cut
an agent off, revoke its client with your provider. From then on, `await` and
`respond` as that handle send its token, even from a shell where a person is
signed in. An agent without a credential sends no token.

Credentials are kept in a `0600` `~/.mycelium/agent-credentials.json`, with
cached tokens in `~/.mycelium/agent-state/agent-tokens/`. For a container that
runs one agent with no config file, use `MYCELIUM_AGENT_AUTH_ISSUER`,
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
different issuers; add a block for each:

```toml
[[auth.issuers]]
issuer = "https://sso.example.com/realms/people"
role   = "user"

[[auth.issuers]]
issuer = "https://sso.example.com/realms/agents"
role   = "agent"
```

A token is checked against the keys of the issuer it names, so one issuer's
tokens can't pass as another's. The hub takes the handle from
`auth.handle_claim` (`sub` by default, lowercased, without a leading `@`) and
the role from `auth.role_claim`, or else from the issuer block's `role`.

## Who wrote it

With auth on, every write (memory authorship, message senders) is attributed
to the handle in the token. A request naming a different handle gets a **403**
rather than being quietly saved under the token's. A per-machine suffix, like
`alice#a8f3`, is kept and can't be used to act as someone else. With auth off,
the request's handle is used as-is.

## Acting for an agent

`mycelium await` reads that handle's messages, and joining a room records it as
present, so with auth on both need the handle to be your own, or the agent's
record (`agents/<handle>` in the room) to list you as its `owner` or in
`allow_from`. Anything else gets a **403**, and owning `@bot` in one room gives
nothing in another. An agent with its own credential awaits as itself. To drive
an agent's loop from your own session:

```bash
mycelium agent create bot --owner alice          # alice can await --handle bot
mycelium agent create bot --allow-from ops-lead  # and so can @ops-lead
```

`await --loop` stops on a 401 or 403 rather than retrying. With auth off,
anyone can await as any handle, another reason to turn auth on for a hub other
people can reach.

## Rotating signing keys

The hub caches signing keys for `auth.jwks_ttl_s` and fetches them again when a
token uses a key it hasn't seen, so rotating keys needs no restart. If the
provider is briefly unreachable, the hub keeps using the keys it has.

## Requests from the hub's own machine

With `auth.localhost_bypass` on (the default), requests from the hub's own
machine (`127.0.0.0/8` or `::1`) need no token, so turning auth on can't lock
you out. The hub checks the connection's real address and ignores
`X-Forwarded-For`. **This doesn't work in Docker**, where requests come from
Docker's network like any other; for a local Docker setup, leave auth off.

## What doesn't need a token

These stay open even with auth on:

- `/`, `/health` and `/healthz`, for health checks. They don't include any room
  content.
- `/docs`, `/redoc` and `/openapi.json`, which describe the API.
- A room's A2A agent card (`/.well-known/agent-card.json`), which only lists the
  room's name and skills. The room's A2A endpoint itself needs a token.

Everything else needs a token. With auth on, `/health` has an `auth` section:
whether it's on, the trusted issuers, and any warnings.

## Errors

| Response | What it means |
|----------|---------|
| `401` with `WWW-Authenticate: Bearer` | The token is missing, malformed, expired, forged, or for a different audience or issuer. |
| `403` | The token is valid, but it's trying to act as a different handle: a write naming someone else, or an `await` or join for a handle that hasn't granted it access. |
| `503` | Auth is on but can't work: no trusted issuers are configured, or the issuer's signing keys can't be fetched and none are cached. |

Only asymmetric signatures (`RS*`, `PS*`, `ES*`) are accepted; `none` and
`HS*` are refused, so the provider's public key can't be misused to forge one.

## Trying it locally

To try sign-in on one machine before setting up a real provider, see the
[Keycloak / OIDC Setup](#keycloak-oidc) guide. It runs a local Keycloak with a
ready-made realm and needs a checkout of the Mycelium source.
