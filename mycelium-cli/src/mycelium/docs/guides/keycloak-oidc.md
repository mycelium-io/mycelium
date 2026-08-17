<!-- SPDX-License-Identifier: Apache-2.0 -->
# Keycloak / OIDC setup

[Authentication](#auth) explains the gate in the abstract: the backend trusts an
OIDC issuer and validates a bearer token against its JWKS. This guide makes the
**human OIDC tier** concrete against real **Keycloak**: realm, client, the claims
the gate keys off, and a human `mycelium login`. Every command here was run against
a live Keycloak: the wiring below is confirmed, not aspirational.

Keycloak is a *supported* issuer, not the default. The gate stays **off by default**
(the try-it path never touches it); you turn it on when a team shares a hub over a
network. Dex, ZITADEL, Authentik, or your corporate SSO slot in exactly the same
way; nothing here is Keycloak-specific except the URLs.

## Stand up Keycloak

A ready-to-run Keycloak ships as an **opt-in compose overlay**, off the default
stack, added with an extra `-f` exactly like the dev issuer. It imports a `mycelium`
realm with a public CLI client, an audience mapper, and a demo user, so there is
nothing to click in the admin console.

```bash
cd mycelium-cli/src/mycelium/docker
docker compose -f compose.yml -f compose-dev.yml -f compose-keycloak.yml \
  up -d keycloak
```

The realm is ready when discovery answers:

```bash
curl -s http://localhost:8080/realms/mycelium/.well-known/openid-configuration \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["issuer"])'
# → http://localhost:8080/realms/mycelium
```

> **Port already in use?** Publish it elsewhere with
> `MYCELIUM_KEYCLOAK_PORT=8085 docker compose … up -d keycloak`. The overlay pins
> Keycloak's advertised URL to the same port, so the issuer becomes
> `http://localhost:8085/realms/mycelium`; use that everywhere below. The admin
> console is at `/admin` (`admin` / `admin`, override with
> `MYCELIUM_KEYCLOAK_ADMIN[_PASSWORD]`).

## What the realm ships (and what the gate expects)

The imported realm (`docker/keycloak/mycelium-realm.json`) is the whole anatomy the
gate needs. Point your own Keycloak at these same four things:

- **A public client `mycelium-cli`**: this is the client `mycelium login` uses.
  Public (no secret; it authenticates with PKCE), with the loopback redirect
  `http://127.0.0.1:*/callback` for the browser flow and the **device grant** enabled
  for headless login.
- **An audience mapper** stamping `mycelium` into the access token's `aud`. This is
  what makes `auth.audience = "mycelium"` meaningful: a token minted for some other
  app on the same Keycloak is refused.
- **`sub` is a UUID, so the human handle comes from `preferred_username`.** Set
  `auth.handle_claim = "preferred_username"` for the human tier; otherwise every
  human arrives as an opaque UUID instead of `@demo`.
- **A demo user** (`demo` / `demo`) so a human login has someone to sign in as.

> **A gotcha worth knowing if you build your own client:** the CLI's *device* flow
> does not send PKCE parameters, so do **not** set the client to *require* PKCE
> (`pkce.code.challenge.method`); that rejects the device grant with
> `Missing parameter: code_challenge_method`. Leave enforcement off; the CLI still
> uses PKCE on the browser flow, Keycloak just doesn't mandate it on every grant.

## Wire the gate

The one subtlety worth understanding is **which URL goes where**, because the
backend runs in a container and the browser/CLI run on the host:

- Keycloak stamps the token `iss` as `http://localhost:8080/realms/mycelium` for
  every caller (the overlay pins its advertised URL). That is what the browser and
  CLI reach it by, so it is the `issuer` the gate matches.
- The **backend can't use `localhost`**: inside the container that is the backend
  itself. On the compose network Keycloak is reachable as `keycloak:8080`, so that
  is where the backend fetches keys from.

The gate matches `iss` by **exact string** but fetches keys from a **separately
configured `jwks_url`**, so you point them at different hostnames on purpose. In
`~/.mycelium/config.toml`:

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

Apply it and recreate the backend so it picks up the gate:

```bash
mycelium config apply
docker compose -f compose.yml -f compose-dev.yml -f compose-keycloak.yml \
  up -d --force-recreate mycelium-backend
```

`/health` now reports the gate on and the issuer trusted:

```bash
curl -s http://localhost:8000/health | python3 -m json.tool
# "auth": { "enabled": true, "issuers": ["http://localhost:8080/realms/mycelium"],
#           "audience": "mycelium", "localhost_bypass": true }
```

> **The localhost bypass does not save you here**, and that is the point. Traffic
> from the CLI to the containerized backend arrives from the Docker bridge, not real
> loopback, so the gate genuinely enforces. See
> [Authentication → The localhost bypass](#auth).

## Sign in with `mycelium login`

```bash
mycelium login            # opens your browser to Keycloak
mycelium login --device   # headless: prints a URL + code to approve from any device
```

Sign in as `demo` / `demo`. The CLI caches the token (`~/.mycelium/token.json`,
mode `0600`) and every later command carries it:

```bash
mycelium whoami
# acting as @demo
#   signed in (http://localhost:8080/realms/mycelium, expires in 4 min)

mycelium room ls          # now authorized through the Keycloak token
```

`mycelium logout` drops the session and the CLI goes back to sending no token.

## Prove the gate (what "validated" means)

The same three checks that were run to confirm this guide, against the published
backend port:

```bash
# A real Keycloak token for the demo user
TOKEN=$(curl -s -X POST \
  http://localhost:8080/realms/mycelium/protocol/openid-connect/token \
  -d 'grant_type=password&client_id=mycelium-cli&username=demo&password=demo&scope=openid profile' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/api/rooms              # 401  (no token)
curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/rooms                                                     # 200  (valid)
curl -s -o /dev/null -w '%{http_code}\n' -H 'Authorization: Bearer not.a.jwt' \
  http://localhost:8000/api/rooms                                                     # 401  (garbage)
```

An **expired** token is refused the same way: the response is
`401` with `token rejected: Signature has expired` once it ages past `exp` plus
`auth.leeway_s` (default 60s).

## Agents, and more than one issuer

This guide is the **human** tier. Agents authenticate as workloads with the
`client_credentials` grant from their own Keycloak client; see
[Authentication → Agents sign in as themselves](#auth). Humans and agents are often
separate realms; list each as its own `[[auth.issuers]]` block (a human root with
`role = "user"`, an agent root with `role = "agent"`), matched by exact `iss` and
never interchangeable.

For the tightest, individually-attested agent identity on the SLIM channel itself,
see [Attested Identity (SPIRE)](#spire-identity), a different, heavier tier from
this HTTP-API gate.

## Browser login (the frontend)

The Next.js frontend does the same OIDC flow for humans in a browser. With the
gate **off** it is unchanged: the localStorage handle-picker, no login. With the
gate **on**, the app shows a **Sign in** screen and redirects to Keycloak; after
you authenticate it carries your token on every `/api/*` call (sealed in an
httpOnly cookie, injected server-side by the proxy; it never reaches browser JS).

The realm import ships a second public client, **`mycelium-web`**, with the web
redirect `http://localhost:3000/api/auth/callback` (the CLI's `mycelium-cli`
client uses a loopback redirect instead: separate clients, separately revocable).

Configure the frontend (server-side env) and bring the UI up:

```bash
export MYCELIUM_OIDC_ISSUER=http://localhost:8080/realms/mycelium
export MYCELIUM_OIDC_INTERNAL_ISSUER=http://keycloak:8080/realms/mycelium
export MYCELIUM_OIDC_CLIENT_ID=mycelium-web
export MYCELIUM_OIDC_AUDIENCE=mycelium
export AUTH_SESSION_SECRET=$(openssl rand -hex 32)

docker compose -f compose.yml -f compose-dev.yml -f compose-keycloak.yml \
  --profile ui up -d
```

The **issuer split is the same as the backend's**, for the same reason: the
browser reaches Keycloak at `MYCELIUM_OIDC_ISSUER` (`localhost:8080`) and the
token's `iss` matches it, but the containerized frontend server can't use
`localhost`, so it runs discovery + token exchange against
`MYCELIUM_OIDC_INTERNAL_ISSUER` (`keycloak:8080`). Running the frontend on the
host with `pnpm dev` instead? Drop `INTERNAL_ISSUER`; the two coincide.

> **Off by default here too.** With `MYCELIUM_OIDC_ISSUER` / `AUTH_SESSION_SECRET`
> unset, the frontend never engages OIDC. And it only shows the sign-in screen
> when the backend's `/health` reports the gate on; the try-it path is untouched.

## The honest ceiling

The shipped overlay is **dev-grade**: Keycloak in `start-dev` (in-memory H2, HTTP,
a demo user with a weak password). It is a real OIDC provider minting real RS256
tokens against a real JWKS (enough to build and prove against) but it is **not** a
hardened production Keycloak. For a real deployment, run your own Keycloak over TLS
with a persistent datastore and real users, then point the same three config values
(`issuer`, `jwks_url`, `login.issuer`) at it. Nothing else changes.
