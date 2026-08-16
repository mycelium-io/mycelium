<!-- SPDX-License-Identifier: Apache-2.0 -->
# Spike report: SPIRE JWT-SVID → SLIM MLS member (#583)

**Status:** Harness complete + proven facts recorded; the SPIRE two-member
exchange is **reproducible but not yet executed in CI** (needs a Docker host to
stand up SPIRE + a SLIM node — see [How to run](#how-to-run)).
**Feeds:** #476 (SignerJwt floor), #579 (SPIRE recommended), #560 (epic).
**Do not:** use `STATIC_JWT` — proven `MlsNotSupported` for MLS (#581).

## What this spike answers

Can `IdentityProviderConfig.SPIRE` (a per-member, SPIRE-attested JWT-SVID) drive a
SLIM **GROUP/MLS** moderated session end-to-end — two members establish the group,
verify each other's SVIDs, and exchange a message — with **no node change** and
**no `MlsNotSupported`**?

The direction is already proven one layer down; this spike extends it to the
managed/attested provider.

## Proven this session (build on these — don't re-derive)

- **`SignerJwt` + MLS works.** A rig spike proved `IdentityProviderConfig.JWT`
  (SignerJwt, per-member keypair) creates the MLS moderated group session
  successfully — hitting the exact `session_moderator.rs:150` MLS-state path that
  **panicked in #581**. #581's failure was purely its provider choice, not MLS.
- **`STATIC_JWT` is the wrong provider.** `StaticTokenProvider` returns
  `MlsNotSupported` for MLS signature keys; `SignerJwt`/`SPIRE` manage them.
  Confirmed against deepwiki (`agntcy/slim`) + live. **SPIRE is the attested
  sibling of the SignerJwt path**, so the MLS mechanics are identical.
- **Matched stack:** `slim-bindings==2.1.0` (PyPI) + `ghcr.io/agntcy/slim:2.1.0`
  node. ⚠️ **No PyPI 2.2.x Python bindings exist yet** (the node ships 2.2.0). Pin
  **2.1.0 on both sides**; the 2.2.x-bindings gap should be flagged upstream.
- **No node identity config needed.** Identity/verifier is app-level
  (`create_app(name, provider, verifier)`); the stock node forwards ciphertext.
  The `slim-node.yaml` here has **no identity block** on purpose. (Vindicates
  #581's claim #1.)
- **Signing keys must be PKCS#8 PEM.** `openssl ecparam -genkey` emits SEC1 →
  `InvalidKeyFormat`; convert with `openssl pkcs8 -topk8 -nocrypt`. (Relevant to
  the SignerJwt floor; SPIRE manages its own keys via the Workload API, so this
  gotcha does **not** recur on the SPIRE path.)
- **Working reference:** SLIM examples at
  `../_slim-research/slim-bindings/python/examples/` — `common.py:spire_identity`
  / `jwt_identity`, and `group.py` (`SessionType.GROUP` + `MlsSettings` +
  `invite_async`). `spire_mls_spike.py` here is adapted straight from them.

## The proven-working pattern (adapted to SPIRE)

The only delta from the proven SignerJwt run is the provider/verifier pair — the
GROUP/MLS session creation, invite, and message exchange are byte-for-byte the same
mechanism:

```python
# SignerJwt (proven):  provider = IdentityProviderConfig.JWT(ClientJwtAuth(...))
# SPIRE (this spike):
cfg = slim_bindings.SpireConfig(
    trust_domains=["mycelium.dev"],
    socket_path="/tmp/spire-agent/public/api.sock",
    target_spiffe_id="spiffe://mycelium.dev/agent/alice",
    jwt_audiences=["mycelium-slim"],
)
provider = slim_bindings.IdentityProviderConfig.SPIRE(config=cfg)
verifier = slim_bindings.IdentityVerifierConfig.SPIRE(config=cfg)
app = svc.create_app(slim_bindings.Name("mycelium","default","alice"), provider, verifier)
# ... identical GROUP + MlsSettings SessionConfig, create_session, invite_async ...
```

Full runnable version: [`spire_mls_spike.py`](./spire_mls_spike.py).

## SPIFFE-ID ↔ mycelium handle mapping

SPIRE names a workload by its **SPIFFE ID**: `spiffe://<trust_domain>/<path>`. The
spike mints one per member:

| SPIFFE ID | SLIM `Name` leaf | mycelium `@handle` |
|---|---|---|
| `spiffe://mycelium.dev/agent/alice` | `mycelium/default/alice` | `alice` |
| `spiffe://mycelium.dev/agent/bob`   | `mycelium/default/bob`   | `bob` |

**Rule:** the SPIFFE **path leaf** (`/agent/<name>` → `<name>`) is the canonical
`@handle`. This *replaces* today's self-asserted `name#session`
(`identity.py:generate_handle`): under SPIRE the handle is no longer the client's
claim but the leaf of a verified, attested SVID the client cannot forge. The trust
domain (`mycelium.dev`) scopes the namespace; the `/agent/` path segment
distinguishes agents from human/service principals if we later split them.

Open question for the #476/#579 rework (not for this spike to settle): whether the
HTTP-API handle binding keys off the full SPIFFE ID, the path, or just the leaf,
and how it reconciles with the existing `name#session` shape and OIDC `sub`
binding (`docs/design/identity-and-auth.md` §"Verified handle binding").

## How to run

Requires Docker + a POSIX host. From this directory:

```bash
# 1. SPIRE server + agent + stock SLIM node (2.1.0)
docker compose up -d

# 2. Register the two member workloads and boot the agent
./register-workloads.sh

# 3. Two SPIRE-identified MLS members join, verify, exchange a message
SPIRE_SOCKET=$PWD/spire-agent-socket/api.sock \
SLIM_ENDPOINT=http://127.0.0.1:46357 \
    uv run --with 'slim-bindings==2.1.0' python spire_mls_spike.py
```

### Expected PASS output

```
[moderator] creating GROUP/MLS session ...
[moderator] MLS session established (no MlsNotSupported).
[moderator] inviting participant ...
[moderator] participant joined + peer-verified.
[moderator] received: 'bob: ack -- peer verified'
PASS: two SPIRE-identified MLS members exchanged a verified message.
```

Reaching "MLS session established" alone already clears the #581 bar (it's the path
`STATIC_JWT` panicked on). The `bob: ack` round-trip additionally proves peer
verification of a second member's SVID.

## Acceptance checklist (#583)

- [x] Proven-working SignerJwt+MLS pattern captured and adapted to SPIRE (inline + `spire_mls_spike.py`).
- [x] Matched stack + no-node-change + PKCS#8 gotcha + 2.2.x-bindings gap recorded.
- [x] SPIFFE-ID → `@handle` mapping documented.
- [x] Reproducible harness (SPIRE server/agent + stock SLIM node + runner).
- [ ] **Two SPIRE-identified MLS members exchange a verified message** — harness
      ready; run on a Docker host and paste the PASS output here to close.

## Constraints honored

- SPIRE stays **optional / off by default** (#567); the PSK remains the zero-infra
  default. This spike lives under `docs/design/`, wired into nothing on the default
  path.
- No `STATIC_JWT` anywhere (#581).

## References

- #581 — what not to do (`STATIC_JWT` → `MlsNotSupported`)
- #476 — SignerJwt floor · #579 — SPIRE (this validates it) · #560 — epic
- `docs/design/identity-and-auth.md` — where SPIRE slots into the identity design
- SLIM examples: `../_slim-research/slim-bindings/python/examples/{common,group}.py`
- deepwiki `agntcy/slim`: `StaticTokenProvider` → `MlsNotSupported`; `SignerJwt`/`SPIRE` manage MLS signature keys
