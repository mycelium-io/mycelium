<!-- SPDX-License-Identifier: Apache-2.0 -->
# Dev OIDC issuer (identity Wave 0)

A lightweight, **dev/test-only** OIDC issuer so the identity work
(`docs/design/identity-and-auth.md`, epic #560) has a real token source + JWKS to
build and test the HTTP-API JWT gate (#561) against — without standing up Keycloak.

> ⚠️ **Dev only.** It mints a valid JWT for any client with any secret and
> authenticates nothing. Production issuers are Keycloak (humans) / SPIRE (agents),
> tracked in #565.

## Bring it up

```bash
docker compose \
  -f mycelium-cli/src/mycelium/docker/compose.yml \
  -f mycelium-cli/src/mycelium/docker/compose-dev.yml \
  -f mycelium-cli/src/mycelium/docker/compose-auth-dev.yml \
  up -d
```

## Endpoints

| Caller | Issuer (`iss`) base | Discovery | JWKS |
|--------|---------------------|-----------|------|
| Backend gate (in-network) | `http://mycelium-auth-dev:8080/default` | `<issuer>/.well-known/openid-configuration` | `<issuer>/jwks` |
| Host (CLI / curl) | `http://localhost:9090/default` | same paths | same paths |

Keys are **RS256**, `kid: default`.

## Mint a token

```bash
# Agent token — sub = client_id (the agent's handle). Mock accepts any secret.
curl -s -X POST http://localhost:9090/default/token \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'grant_type=client_credentials&client_id=poc-agent&client_secret=dev&scope=openid'
```

Returns `{ "access_token": "<RS256 JWT>", "token_type": "Bearer", ... }`. Decoded
claims look like:

```json
{ "sub": "poc-agent", "iss": "http://localhost:9090/default", "aud": "...",
  "exp": 1786846481, "iat": 1786842881 }
```

The `sub` claim is the authoritative handle the gate (#561) and handle-binding
(#562) key off.

## Wiring the gate (#561)

The gate is **issuer-agnostic** — point it at this issuer's `iss` + JWKS URL via
config. Use the **in-network** issuer (`http://mycelium-auth-dev:8080/default`) for
the backend, since that is the host the backend reaches and the `iss` it will see.

> `mock-oauth2-server` derives `iss` from the request host, so the in-network and
> host issuers differ. That is fine for dev: configure the backend against the
> in-network one; use the host URLs only for manual token minting. A stable `iss`
> can be pinned later via the mock's `JSON_CONFIG` if needed.

In `~/.mycelium/config.toml`:

```toml
[auth]
enabled  = true
audience = "mycelium"      # the mock echoes the requested `scope` into `aud`

[[auth.issuers]]
issuer   = "http://mycelium-auth-dev:8080/default"
jwks_url = "http://mycelium-auth-dev:8080/default/jwks"
role     = "agent"
```

Then `mycelium config apply` and recreate the backend. Mint a token from the host
(port 9090) and call the API through the published backend port:

```bash
TOKEN=$(curl -s -X POST http://localhost:9090/default/token \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'grant_type=client_credentials&client_id=poc-agent&client_secret=dev&scope=mycelium' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/api/rooms                      # 401
curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/rooms                                                             # 200
```

The `iss` wrinkle above is why the token minted on `:9090` carries
`iss: http://localhost:9090/default` while the backend trusts
`http://mycelium-auth-dev:8080/default` — they must match, so pin the mock's
issuer via `JSON_CONFIG` (or trust both by listing a second `[[auth.issuers]]`
block) when driving the gate from the host.

Operator-facing documentation for the gate itself lives in the docs site under
**Reference → Guides → Authentication**
(`mycelium-cli/src/mycelium/docs/guides/auth.md`).

## Next

- ~~#561 — HTTP-API JWT gate (validate against this issuer's JWKS)~~ — landed
- #562 — verified handle binding (consume the principal this gate resolves)
- ~~#565 — real Keycloak (humans) wiring~~ — landed: a validated operator guide
  (`docs/guides/keycloak-oidc.md`) + an opt-in `compose-keycloak.yml` overlay. SPIRE
  (agents) shipped separately in #588.
