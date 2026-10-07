<!-- SPDX-License-Identifier: Apache-2.0 -->
# Keycloak / OIDC Setup

*For contributors working on the Mycelium source.* The commands below run from
a checkout of the repository and use its development compose files. An
installed Mycelium doesn't have those. To turn on sign-in for a real hub, see
[Authentication](#auth).

This guide gets [authentication](#auth) working end to end on your machine with
Keycloak as the identity provider. When you're done, the hub will reject
requests without a valid token. You'll be signed in with `mycelium login` from
the terminal and in the app.

Keycloak is just an example here. Dex, ZITADEL, Authentik or your company's SSO
work the same way, and only the URLs change. Auth stays off unless you turn it
on.

## Start Keycloak

Mycelium comes with a Keycloak setup you can add to the stack. It's a separate
compose file, so it isn't part of the normal install. It comes with a
`mycelium` realm already set up, so you don't need to use the admin console.

```bash
cd mycelium-cli/src/mycelium/docker
docker compose -f compose.yml -f compose-dev.yml -f compose-keycloak.yml \
  up -d keycloak
```

It's ready when this prints the issuer URL:

```bash
curl -s http://localhost:8080/realms/mycelium/.well-known/openid-configuration \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["issuer"])'
# → http://localhost:8080/realms/mycelium
```

> **Port 8080 already in use?** Start it on another port with
> `MYCELIUM_KEYCLOAK_PORT=8085 docker compose … up -d keycloak`. The issuer
> becomes `http://localhost:8085/realms/mycelium`, so use that everywhere below.
> The admin console is at `/admin` and the login is `admin` / `admin`. Change
> it with `MYCELIUM_KEYCLOAK_ADMIN` and `MYCELIUM_KEYCLOAK_ADMIN_PASSWORD`.

## What's in the realm

The realm is defined in `docker/keycloak/mycelium-realm.json`. If you're
setting up your own Keycloak instead, it needs the same things:

- **A public client called `mycelium-cli`**, which `mycelium login` uses. It
  has no secret because the CLI uses PKCE. It allows the redirect
  `http://127.0.0.1:*/callback` for browser sign-in, and it has the device
  grant enabled for signing in without a browser.
- **An audience mapper** that adds `mycelium` to the token's `aud` claim. This
  is what `auth.audience = "mycelium"` checks for. Tokens issued for other apps
  on the same Keycloak are rejected.
- **A demo user** named `demo` with the password `demo`.

Keycloak's `sub` claim is a UUID, so the handle comes from
`preferred_username` instead. Set `auth.handle_claim = "preferred_username"`.
Otherwise every person shows up as a UUID instead of as `@demo`.

> **If you set up your own client:** don't make PKCE required on it with the
> `pkce.code.challenge.method` setting. The CLI's device flow doesn't send PKCE
> parameters, so requiring it breaks `mycelium login --device` with
> `Missing parameter: code_challenge_method`. The browser flow uses PKCE either
> way.

## Point the hub at Keycloak

The backend runs in a container, but your browser and the CLI run on your
machine. So they reach Keycloak at different addresses:

- Your browser and the CLI reach it at `localhost:8080`. Keycloak puts
  `http://localhost:8080/realms/mycelium` in every token's `iss`, so that's the
  `issuer` the hub checks tokens against.
- Inside the backend container, `localhost` is the container itself. The
  backend reaches Keycloak at `keycloak:8080` on the compose network, so that's
  where it fetches the signing keys from (`jwks_url`).

Add this to `~/.mycelium/config.toml`:

```toml
[auth]
enabled      = true
audience     = "mycelium"
handle_claim = "preferred_username"

[[auth.issuers]]
issuer   = "http://localhost:8080/realms/mycelium"
jwks_url = "http://keycloak:8080/realms/mycelium/protocol/openid-connect/certs"
role     = "user"

[login]
issuer    = "http://localhost:8080/realms/mycelium"
client_id = "mycelium-cli"
audience  = "mycelium"
```

Apply it and recreate the backend:

```bash
mycelium config apply
docker compose -f compose.yml -f compose-dev.yml -f compose-keycloak.yml \
  up -d --force-recreate mycelium-backend
```

`/health` should now show auth on with Keycloak as a trusted issuer:

```bash
curl -s http://localhost:8000/health | python3 -m json.tool
# "auth": { "enabled": true, "issuers": ["http://localhost:8080/realms/mycelium"],
#           "audience": "mycelium", "localhost_bypass": true }
```

`localhost_bypass` shows `true`, but it won't let your requests through here.
The backend runs in Docker, so your requests come from Docker's network instead
of from loopback. They need a token like anyone else's. See "Requests from the
hub's own machine" under [Authentication](#auth).

## Sign in

```bash
mycelium login            # opens Keycloak in your browser
mycelium login --device   # no browser: prints a URL and a code to enter on another device
```

Sign in as `demo` with the password `demo`. Every command after that sends your
token:

```bash
mycelium whoami
# acting as @demo
#   signed in (http://localhost:8080/realms/mycelium, expires in 4 min)

mycelium room ls
```

`mycelium logout` signs you out, and the CLI then stops sending a token.

## Check that it's enforced

Get a token for the demo user. Then try the API three times: with no token,
with the real one and with a fake one:

```bash
TOKEN=$(curl -s -X POST \
  http://localhost:8080/realms/mycelium/protocol/openid-connect/token \
  -d 'grant_type=password&client_id=mycelium-cli&username=demo&password=demo&scope=openid profile' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/api/rooms              # 401  (no token)
curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/rooms                                                     # 200  (valid)
curl -s -o /dev/null -w '%{http_code}\n' -H 'Authorization: Bearer not.a.jwt' \
  http://localhost:8000/api/rooms                                                     # 401  (fake)
```

An expired token also gets a `401` with `token rejected: Signature has
expired`. That happens once it's past its `exp` plus `auth.leeway_s`, which is
60 seconds by default.

## Signing in to the app

The app can use the same Keycloak. With auth off, nothing changes and you just
pick a handle. With auth on, the app shows a **Sign in** screen and sends you to
Keycloak. After you sign in, the app sends your token with every request. The
app's server keeps the token in an httpOnly cookie and adds it to requests, so
JavaScript in the browser never sees it.

The realm has a second public client for this called **`mycelium-web`**. Its
redirect is `http://localhost:3000/api/auth/callback`. It's separate from the
CLI's client, so you can revoke one without the other.

Set these for the frontend and bring the stack up:

```bash
export MYCELIUM_OIDC_ISSUER=http://localhost:8080/realms/mycelium
export MYCELIUM_OIDC_INTERNAL_ISSUER=http://keycloak:8080/realms/mycelium
export MYCELIUM_OIDC_CLIENT_ID=mycelium-web
export MYCELIUM_OIDC_AUDIENCE=mycelium
export AUTH_SESSION_SECRET=$(openssl rand -hex 32)

docker compose -f compose.yml -f compose-dev.yml -f compose-keycloak.yml up -d
```

There are two issuer addresses for the same reason as the backend. Your browser
uses `MYCELIUM_OIDC_ISSUER` (`localhost:8080`). The frontend's server inside its
container uses `MYCELIUM_OIDC_INTERNAL_ISSUER` (`keycloak:8080`). If you run the
frontend on your machine with `pnpm dev` instead, leave out
`MYCELIUM_OIDC_INTERNAL_ISSUER`.

If `MYCELIUM_OIDC_ISSUER` or `AUTH_SESSION_SECRET` isn't set, the app doesn't
use sign-in at all. It also only shows the sign-in screen when the backend's
`/health` says auth is on.

## Agents, and more than one issuer

This guide covers people. Agents sign in with their own Keycloak client using
the `client_credentials` grant. See "Signing in agents" under
[Authentication](#auth). People and agents are often in separate realms. Add a
`[[auth.issuers]]` block for each, one with `role = "user"` and one with
`role = "agent"`. A token only passes against the issuer it came from.

To also give each agent its own identity on the SLIM channel, see
[Running a Shared Hub](#security-planes-per-member-slim-identity). That's
separate from the API auth this guide sets up.

## Not for production

This Keycloak setup is for development. It runs in `start-dev` mode with an
in-memory database, plain HTTP and a demo user with a weak password. The tokens
it issues are real, using RS256 with real signing keys. That makes it fine for
building and testing against, but don't use it for a real deployment.

For production, run your own Keycloak over TLS with a persistent database and
real users. Then point the same three settings at it: `issuer`, `jwks_url` and
`login.issuer`.
