<!-- SPDX-License-Identifier: Apache-2.0 -->
# Dev SPIRE quickstart — SPIRE-attested MLS members (#579)

An **optional, dev-grade** rig for the `spire` SLIM channel identity mode: a SPIRE
server + agent mint JWT-SVIDs over the SPIFFE Workload API, and two mycelium members
present those SVIDs as their MLS identity (`IdentityProviderConfig.SPIRE` /
`IdentityVerifierConfig.SPIRE`). It is the productization starting point for the
`spire` mode wired into `slim_client.py`; the full appliance deployment profile is
**#588** (not this) and revocation semantics are **#590**.

> **Off by default (#567).** `psk` is the default identity mode, `signerjwt` the
> light opt-in, `spire` the heavy opt-in. Nothing here touches the try-it path — you
> only stand this up to exercise attested identity.

> **Status.** The provider/verifier wiring and the off-by-default / degrade /
> fail-closed behavior are unit-tested offline (`tests/test_slim_identity.py`). The
> **live SPIRE→MLS path needs the rig** (a co-located SPIRE agent sharing the
> workload PID namespace — see the gotcha below); it is validated on matched infra,
> not in the offline suite. The proven reference is the #583/#584 spike
> (`docs/design/spire-mls-spike/`, PASS on the 2.1.0 stack: two SPIRE-attested
> members established a GROUP/MLS session on a stock `slim:2.1.0` node).

## What the `spire` mode does

`MYCELIUM_SLIM_IDENTITY=spire` makes each member build its SLIM app identity from a
SPIRE `SpireConfig`:

```python
provider = slim_bindings.IdentityProviderConfig.SPIRE(config=slim_bindings.SpireConfig(
    socket_path=socket,                                   # Workload API socket
    target_spiffe_id="spiffe://mycelium.dev/agent/alice", # this member's SVID
    jwt_audiences=["mycelium-slim"],                      # the MLS audience label
    trust_domains=["mycelium.dev"],
))
verifier = slim_bindings.IdentityVerifierConfig.SPIRE(config=slim_bindings.SpireConfig(
    socket_path=socket,
    target_spiffe_id=None,          # accept any peer in the trust domain
    jwt_audiences=["mycelium-slim"],
    trust_domains=["mycelium.dev"],
))
app = svc.create_app(name, provider, verifier)
# ... identical GROUP + MlsSettings SessionConfig as psk/signerjwt ...
```

Unlike the SignerJwt floor (#476), there is **no on-disk key** to mint: SPIRE owns
the key material and mints the SVID on demand, and peers verify against the SPIRE
bundle the same socket serves instead of a hand-distributed roster JWKS. Same MLS
mechanics; tightest attestation; heaviest deploy.

## Config / env

| Setting | Where | Meaning |
|---|---|---|
| `slim.identity = "spire"` | `config.toml` → `MYCELIUM_SLIM_IDENTITY=spire` | Select the mode (off by default). |
| `MYCELIUM_SLIM_SPIRE_SOCKET` | env (operator-managed) | Workload API socket path. Falls back to the SPIFFE-standard `SPIRE_AGENT_SOCKET`. |
| `MYCELIUM_SLIM_SPIRE_TRUST_DOMAIN` | env (operator-managed) | Trust domain (default `mycelium.dev`). |
| `MYCELIUM_SLIM_IDENTITY_REQUIRE=1` | env | Fail closed instead of degrading to PSK when no socket is present. |

The socket / trust-domain envs are operator-managed out of band (like
`MYCELIUM_SLIM_MASTER_SECRET`), not derived from `config.toml` — only the mode
selector `slim.identity` rides through `mycelium config apply`.

A member's SPIFFE ID is `spiffe://{trust_domain}/agent/{handle}`. That handle ↔
SPIFFE-leaf binding is minimal-by-design here; the full registration/reconciliation
surface (SPIFFE leaf ↔ `@handle`) is **#589**.

## The load-bearing operational gotcha (bake it in)

SPIRE's `unix` workload attestor identifies the caller by its `SO_PEERCRED` **PID**,
so the SPIRE agent must be able to introspect the workload:

1. **Share the workload's PID namespace** (`pid: "service:spire-agent"` / `hostPID`).
2. **Expose the Workload API socket on a named volume**, *not* a host bind-mount —
   a Docker Desktop host bind drops peer creds.

Cross-namespace → `could not resolve caller information`, and the member hangs at
**"Initializing spire identity manager."** This is exactly why `spire` is **not** the
resident default: a resident Claude/Cursor session does not run co-located with a
SPIRE agent in a shared PID namespace. Where the `unix` attestor can't be
co-located, source the SVID from a non-`unix` attestor (`k8s`, `docker`, `x509pop`,
join-token) instead — topology D in
[`../slim-identity-svid-delivery.md`](../slim-identity-svid-delivery.md).

## Files

- [`compose.yml`](./compose.yml) — stock `slim:2.1.0` node + SPIRE server + SPIRE
  agent (shared PID namespace, named-volume Workload API socket).
- [`spire-server.conf`](./spire-server.conf) — SPIRE server (dev; in-memory /
  SQLite datastore, `mycelium.dev` trust domain).
- [`spire-agent.conf`](./spire-agent.conf) — SPIRE agent (`unix` workload attestor,
  join-token node attestation for the dev rig).
- [`register-workloads.sh`](./register-workloads.sh) — create the registration
  entries mapping each member's process to `spiffe://mycelium.dev/agent/{handle}`.
- [`run.sh`](./run.sh) — bring the rig up, register the two workloads, and run the
  two members; exits non-zero unless the attested MLS exchange prints `PASS`.

## Matched stack only

`slim-bindings==2.1.0` (PyPI) + `ghcr.io/agntcy/slim:2.1.0` node + SPIRE 1.9.x. No
`STATIC_JWT` — a handed-in *bearer* token is `MlsNotSupported` (#581); the SVID must
drive a *signing* provider, which `IdentityProviderConfig.SPIRE` does.

## References

- #579 — this ticket (SPIRE mode) · #588 — appliance profile · #589 — handle ↔
  SPIFFE mapping · #590 — revocation · #476/#593 — the SignerJwt floor + the seam
  this drops into · #581 — `STATIC_JWT` → `MlsNotSupported`
- [`../spire-mls-spike/`](../spire-mls-spike/) — the proven #583/#584 spike (PASS)
- [`../slim-identity-svid-delivery.md`](../slim-identity-svid-delivery.md) — topology
  C (co-located SPIRE) / D (externally-minted SVID)
