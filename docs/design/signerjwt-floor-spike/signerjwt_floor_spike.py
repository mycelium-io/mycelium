# SPDX-License-Identifier: Apache-2.0
"""SignerJwt floor -> SLIM MLS member spike.

The **default resident credential path**: an agent that runs no SPIRE at all. Each
member generates its *own* local ES256 keypair, self-signs a short-lived JWT that
embeds its public key, and presents it as `IdentityProviderConfig.JWT` (SignerJwt).
No SPIRE agent, no shared PID namespace, no Workload API socket -- so unlike the
#583 SPIRE spike this matches a *real resident topology*: the agent's own machine.

Two members join ONE `GROUP`/MLS channel, the moderator invites the participant,
they verify each other's self-signed tokens, and exchange a message both ways.
Reaching a decoded round-trip proves `IdentityProviderConfig.JWT` (SignerJwt) drives
the MLS moderated group session -- the same `session_moderator.rs` code path that
panicked in #581 under `STATIC_JWT`.

How peer verification works without SPIRE (the load-bearing finding): the SignerJwt
token carries the signer's public key in its claims, and each member's verifier holds
a **static JWKS of the trusted members' public keys** (`JwtKeyType.DECODING` +
`JwtKeyFormat.JWKS`). That JWKS is the deployment's registration surface -- the
mycelium analogue of `mycelium agent credential set`, a public key registered when
an agent is added to a room. There is no attestation and no issuer discovery: trust
is "this public key is on the room's roster", distributed out of band.

Run: `./run.sh` (stands up a stock SLIM 2.1.0 node on :46358, generates keys, execs
this on the host). Env: SLIM_ENDPOINT=http://127.0.0.1:46358, KEYDIR=/tmp/... .

Matched stack (proven): slim-bindings==2.1.0 (PyPI) + ghcr.io/agntcy/slim:2.1.0.
Do NOT substitute STATIC_JWT: it returns MlsNotSupported for MLS signature keys
(#581). Signing keys must be PKCS#8 PEM; `openssl ecparam -genkey` emits SEC1 ->
`InvalidKeyFormat`, so `run.sh` converts with `openssl pkcs8 -topk8 -nocrypt`.
"""

import asyncio
import datetime
import os
import sys

import slim_bindings

SLIM = os.environ.get("SLIM_ENDPOINT", "http://127.0.0.1:46358")
KEYDIR = os.environ.get("KEYDIR", "/tmp/signerjwt-floor-spike")

# Self-issued: issuer/audience are labels; verification rests on the JWKS.
ISSUER = os.environ.get("SIGNERJWT_ISSUER", "mycelium-resident")
AUDIENCE = [os.environ.get("SIGNERJWT_AUDIENCE", "mycelium-slim")]

ORG, NS = "mycelium", "default"
MODERATOR = "alice"
PARTICIPANT = "bob"
ROOM = "mls-room"


def _read(path: str) -> str:
    with open(path) as fh:
        return fh.read()


def signerjwt_identity(name: str):
    """Build a SignerJwt provider + JWKS verifier for one resident member.

    Provider: sign our own JWT with our local PKCS#8 ES256 key (`ENCODING`).
    Verifier: trust the room roster's public keys, a static multi-key JWKS
    (`DECODING` + `JWKS`) -- how a member validates *every other* member's
    self-signed token with no SPIRE and no issuer discovery.
    """
    encoding_key = slim_bindings.JwtKeyConfig(
        algorithm=slim_bindings.JwtAlgorithm.ES256,
        format=slim_bindings.JwtKeyFormat.PEM,
        key=slim_bindings.JwtKeyData.DATA(value=_read(f"{KEYDIR}/{name}.pk8.pem")),  # type: ignore[call-arg]
    )
    provider = slim_bindings.IdentityProviderConfig.JWT(
        config=slim_bindings.ClientJwtAuth(
            key=slim_bindings.JwtKeyType.ENCODING(key=encoding_key),  # type: ignore[call-arg]
            audience=AUDIENCE,
            issuer=ISSUER,
            subject=name,  # the mycelium @handle -- the SLIM Name leaf
            duration=datetime.timedelta(seconds=3600),
        )
    )
    decoding_key = slim_bindings.JwtKeyConfig(
        algorithm=slim_bindings.JwtAlgorithm.ES256,
        format=slim_bindings.JwtKeyFormat.JWKS,
        key=slim_bindings.JwtKeyData.DATA(value=_read(f"{KEYDIR}/roster-jwks.json")),  # type: ignore[call-arg]
    )
    verifier = slim_bindings.IdentityVerifierConfig.JWT(
        config=slim_bindings.JwtAuth(
            key=slim_bindings.JwtKeyType.DECODING(key=decoding_key),  # type: ignore[call-arg]
            audience=AUDIENCE,
            issuer=ISSUER,
            subject=None,
            duration=datetime.timedelta(seconds=3600),
        )
    )
    return provider, verifier


def group_session_config():
    return slim_bindings.SessionConfig(
        session_type=slim_bindings.SessionType.GROUP,
        max_retries=5,
        interval=datetime.timedelta(seconds=5),
        metadata={},
        mls_settings=slim_bindings.MlsSettings(
            header_integrity_validation_percent=100,
            max_seen_control_message_ids_size=None,
        ),
    )


async def make_member(svc, conn, name: str):
    provider, verifier = signerjwt_identity(name)
    slim_name = slim_bindings.Name(ORG, NS, name)
    app = svc.create_app(slim_name, provider, verifier)
    await app.subscribe_async(slim_name, conn)
    return app, slim_name


async def main() -> int:
    slim_bindings.initialize_with_defaults()
    svc = slim_bindings.get_global_service()
    conn = await svc.connect_async(slim_bindings.new_insecure_client_config(SLIM))

    # Both members authenticate with a locally self-signed SignerJwt token.
    mod_app, _ = await make_member(svc, conn, MODERATOR)
    part_app, part_name = await make_member(svc, conn, PARTICIPANT)

    room = slim_bindings.Name(ORG, NS, ROOM)

    # Moderator creates the MLS group -- the session_moderator.rs MLS-state path.
    # If SignerJwt could not manage MLS signature keys we'd fail HERE with
    # MlsNotSupported (as STATIC_JWT does in #581).
    print("[moderator] creating GROUP/MLS session ...", flush=True)
    created = mod_app.create_session(group_session_config(), room)
    await created.completion.wait_async()
    session = created.session
    print("[moderator] MLS session established (no MlsNotSupported).", flush=True)

    part_ready = asyncio.Event()

    async def participant_wait():
        s = await part_app.listen_for_session_async(None)
        part_ready.set()
        msg = await s.get_message_async(timeout=datetime.timedelta(seconds=30))
        print(f"[participant] received: {msg.payload.decode()!r}", flush=True)
        await s.publish_async(b"bob: ack -- peer verified", None, None)

    waiter = asyncio.create_task(participant_wait())

    # Moderator invites the participant by name; MLS peer verification of bob's
    # self-signed token against the roster JWKS happens inside the invite/commit
    # handshake.
    await mod_app.set_route_async(part_name, conn)
    print("[moderator] inviting participant ...", flush=True)
    handle = await session.invite_async(part_name)
    await handle.wait_async()
    print("[moderator] participant joined + peer-verified.", flush=True)

    await asyncio.wait_for(part_ready.wait(), timeout=30)
    await session.publish_async(b"alice: hello over MLS", None, None)

    reply = await session.get_message_async(timeout=datetime.timedelta(seconds=30))
    print(f"[moderator] received: {reply.payload.decode()!r}", flush=True)

    await asyncio.wait_for(waiter, timeout=30)
    print("\nPASS: two SignerJwt-identified MLS members exchanged a verified message.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except Exception as exc:  # noqa: BLE001 -- spike: surface the exact failure
        print(f"\nFAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
