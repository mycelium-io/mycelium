# SPDX-License-Identifier: Apache-2.0
"""SPIRE JWT-SVID -> SLIM MLS member spike (issue #583).

Two SPIRE-identified members join ONE `GROUP`/MLS channel, the moderator invites
the participant, they verify each other's SVIDs, and exchange a message. Reaching
a decoded round-trip proves `IdentityProviderConfig.SPIRE` drives the MLS moderated
group session -- the same `session_moderator.rs` code path that panicked in #581
under `STATIC_JWT`, and that a rig spike already proved works under `SignerJwt`.

This is the SPIRE leg of that same per-member signing identity. It is deliberately
NOT production code: it is the reproducible artifact behind the spike report
(README.md), so the finding can be re-run rather than taken on faith.

Run (see README.md for the full stack):
    # after `docker compose up -d` and `./register-workloads.sh`
    SPIRE_SOCKET=/tmp/spire-agent/public/api.sock \
    SLIM_ENDPOINT=http://127.0.0.1:46357 \
        uv run --with 'slim-bindings==2.1.0' python spire_mls_spike.py

Matched stack (proven): slim-bindings==2.1.0 (PyPI) + ghcr.io/agntcy/slim:2.1.0.
There is NO PyPI 2.2.x Python binding yet (the node ships 2.2.0) -- pin 2.1.0 on
both sides. Do NOT substitute STATIC_JWT: it returns MlsNotSupported for MLS
signature keys (#581).
"""

import asyncio
import datetime
import os
import sys

import slim_bindings

TRUST_DOMAIN = os.environ.get("SPIRE_TRUST_DOMAIN", "mycelium.dev")
SOCKET = os.environ.get("SPIRE_SOCKET", "/tmp/spire-agent/public/api.sock")
SLIM = os.environ.get("SLIM_ENDPOINT", "http://127.0.0.1:46357")
AUDIENCE = os.environ.get("SPIRE_AUDIENCE", "mycelium-slim")

# SLIM Name components. The last segment is the local name; it mirrors the
# SPIFFE path's leaf (see "SPIFFE-ID -> handle mapping" in README.md).
ORG, NS = "mycelium", "default"
MODERATOR = ("agent", "alice")   # spiffe://mycelium.dev/agent/alice
PARTICIPANT = ("agent", "bob")   # spiffe://mycelium.dev/agent/bob
ROOM = "mls-room"


def spire_identity(spiffe_id: str):
    """Build a SPIRE provider+verifier for one SVID (adapted from the SLIM
    examples' `common.py:spire_identity`). `target_spiffe_id` selects which SVID
    this member presents when the Workload API returns several."""
    cfg = slim_bindings.SpireConfig(
        trust_domains=[TRUST_DOMAIN],
        socket_path=SOCKET,
        target_spiffe_id=spiffe_id,
        jwt_audiences=[AUDIENCE],
    )
    return (
        slim_bindings.IdentityProviderConfig.SPIRE(config=cfg),
        slim_bindings.IdentityVerifierConfig.SPIRE(config=cfg),
    )


def spiffe_id(path: tuple[str, str]) -> str:
    return f"spiffe://{TRUST_DOMAIN}/{path[0]}/{path[1]}"


async def make_member(svc, conn, path: tuple[str, str]):
    provider, verifier = spire_identity(spiffe_id(path))
    name = slim_bindings.Name(ORG, NS, path[1])
    app = svc.create_app(name, provider, verifier)
    await app.subscribe_async(name, conn)
    return app, name


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


async def main() -> int:
    slim_bindings.initialize_with_defaults()
    svc = slim_bindings.get_global_service()
    conn = await svc.connect_async(slim_bindings.new_insecure_client_config(SLIM))

    # Both members authenticate with a SPIRE JWT-SVID from the Workload API.
    mod_app, _ = await make_member(svc, conn, MODERATOR)
    part_app, part_name = await make_member(svc, conn, PARTICIPANT)

    room = slim_bindings.Name(ORG, NS, ROOM)

    # Moderator creates the MLS group -- this is the session_moderator.rs MLS-state
    # path. If SPIRE could not manage MLS signature keys we'd fail HERE with
    # MlsNotSupported (as STATIC_JWT does in #581).
    print("[moderator] creating GROUP/MLS session ...", flush=True)
    created = mod_app.create_session(group_session_config(), room)
    await created.completion.wait_async()
    session = created.session
    print("[moderator] MLS session established (no MlsNotSupported).", flush=True)

    # Participant waits for the invite.
    part_ready = asyncio.Event()
    part_box: list = []

    async def participant_wait():
        s = await part_app.listen_for_session_async(None)
        part_box.append(s)
        part_ready.set()
        msg = await s.get_message_async(timeout=datetime.timedelta(seconds=30))
        print(f"[participant] received: {msg.payload.decode()!r}", flush=True)
        await s.publish_async(b"bob: ack -- peer verified", None, None)

    waiter = asyncio.create_task(participant_wait())

    # Moderator invites the participant by SPIFFE-leaf name; MLS peer verification
    # of bob's SVID happens inside the invite/commit handshake.
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
    print("\nPASS: two SPIRE-identified MLS members exchanged a verified message.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except Exception as exc:  # noqa: BLE001 -- spike: surface the exact failure
        print(f"\nFAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
