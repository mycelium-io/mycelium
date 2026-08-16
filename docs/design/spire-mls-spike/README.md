<!-- SPDX-License-Identifier: Apache-2.0 -->
# Spike report: SPIRE JWT-SVID → SLIM MLS member (#583)

**Status:** ✅ **PASS — executed 2026-08-16.** Two SPIRE-attested members
established a GROUP/MLS session, peer-verified, and exchanged a message both ways.
Reproduce with `./run.sh` (Docker required). Verbatim output below.
**Feeds:** #476 (SignerJwt floor), #579 (SPIRE recommended), #560 (epic).
**Do not:** use `STATIC_JWT` — proven `MlsNotSupported` for MLS (#581).

## Result

```
[moderator] creating GROUP/MLS session ...
[moderator] MLS session established (no MlsNotSupported).
[moderator] inviting participant ...
[moderator] participant joined + peer-verified.
[participant] received: 'alice: hello over MLS'
[moderator] received: 'bob: ack -- peer verified'
PASS: two SPIRE-identified MLS members exchanged a verified message.
```

Stack that produced it: `slim-bindings==2.1.0` (PyPI) + `ghcr.io/agntcy/slim:2.1.0`
node (stock, no identity block) + SPIRE server/agent `1.9.6`. `IdentityProviderConfig.SPIRE`
drove the MLS moderated session — the `session_moderator.rs` path that panicked in
#581 under `STATIC_JWT` — with **real peer verification and no node change**. This
confirms the flagship channel-identity direction for #476/#579.

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

Requires Docker. From this directory:

```bash
./run.sh
```

That is the whole thing: it stands up SPIRE server + agent + a stock SLIM 2.1.0
node, registers the two workloads, runs the two members inside a Linux `runner`
container, and exits non-zero unless it prints `PASS`. Reaching "MLS session
established" alone already clears the #581 bar (the path `STATIC_JWT` panicked on);
the `bob: ack` round-trip additionally proves peer verification of a second
member's SVID. Tear down with `docker compose down -v`.

The members run **inside a container**, not on the host — that is load-bearing, see
the gotchas below.

## Gotchas hit while getting to PASS (record for the #476/#579 rework)

1. **The `unix` workload attestor needs the agent to share the workload's PID
   namespace.** SPIRE resolves the caller by reading `/proc/<pid>` for the PID it
   gets from `SO_PEERCRED`; across separate PID namespaces that PID is meaningless
   to the agent and it fails every fetch with **`could not resolve caller
   information`** (the member then hangs at "Initializing spire identity manager").
   The runner joins the agent's namespace via `pid: "service:spire-agent"` — the
   Compose analogue of the agent's `hostPID` on Kubernetes. **Implication for
   mycelium:** an agent authenticating to SLIM via SPIRE must obtain its SVID from
   a Workload API the SPIRE agent can introspect (same node / shared PID ns), or
   use a non-`unix` attestor (`docker`, `k8s`, `x509pop`). A host-side process
   talking to a containerized SPIRE agent over a **bind-mounted** socket does *not*
   work on Docker Desktop — the file-sharing layer also drops `SO_PEERCRED`; the
   socket must live on a **named volume**.
2. **SLIM 2.1.0 node config uses `dataplane:`, not `pubsub:`.** Under
   `services.<id>` the server list is `dataplane.servers[].endpoint` (+ `clients:
   []`). A `pubsub:` block fails with `unknown field 'pubsub'`. See `slim-node.yaml`.
3. **The `spire-agent` image ENTRYPOINT already includes `run`.** Pass only the
   flags as `command` (`-config … -joinToken …`); a leading `run` doubles it and
   the agent silently drops `-joinToken` → `join token was not provided`. See the
   `spire-agent` service in `docker-compose.yml`.

The earlier-known SEC1-vs-PKCS#8 signing-key gotcha does **not** recur here: SPIRE
mints and manages its own keys via the Workload API, so no manual key conversion.

## Acceptance checklist (#583)

- [x] Proven-working SignerJwt+MLS pattern captured and adapted to SPIRE (inline + `spire_mls_spike.py`).
- [x] Matched stack + no-node-change + PKCS#8 gotcha + 2.2.x-bindings gap recorded.
- [x] SPIFFE-ID → `@handle` mapping documented.
- [x] Reproducible harness (SPIRE server/agent + stock SLIM node + runner), one-command `./run.sh`.
- [x] **Two SPIRE-identified MLS members exchange a verified message** — PASS,
      executed 2026-08-16 (output above). No `MlsNotSupported`, real peer verification.
- [x] Node change needed? **No** — the stock SLIM node forwards ciphertext; identity is app-level.

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
