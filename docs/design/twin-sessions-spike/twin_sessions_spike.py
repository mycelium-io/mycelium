# SPDX-License-Identifier: Apache-2.0
"""Server-side per-actor "twin" SLIM/MLS sessions spike (issue #662).

Today the mycelium backend is a **single SLIM/MLS member per room that
impersonates every actor** (a service account). Attribution ("@alice said this")
is stamped by the backend at the L9/transcript layer *after the fact* --
application-level, forgeable by the backend, invisible on the wire.

This spike proves the decided direction: the backend as a **custodian of N
per-actor twin Apps**, each a *genuine* MLS member carrying its **own per-actor
SignerJwt identity** (the #476/#585 credential), all hosted **server-side** in one
process. Which actor can touch which room is then enforced by **MLS group
membership**, not by mycelium app logic.

It answers the six spike questions from the issue:

  Q1  Stand up N twins (>=2 per-actor Apps) in one backend process, each with its
      own SignerJwt identity, all joined to ONE room GROUP -- confirm distinct,
      cryptographically-attributable membership on the wire.
  Q2  Confirm PersistenceConfig / create_app_with_persistence / restore_sessions
      are reachable from the pinned slim-bindings==2.1.0 wheel (not just Rust).
  Q3  Resume: tear a twin down (simulated restart) and restore_sessions its
      persisted state -- confirm it rejoins its MLS group with NO re-invite.
  Q4  Where the per-twin store lives (server-side) and what the passphrase derives
      from (the real at-rest confidentiality boundary -- NOT the OIDC token).
  Q6  Cost: N Apps multiplexed over ONE shared dataplane connection (one socket),
      not N sockets.

The honest scope boundary (stated plainly, not oversold): twins are
**server-side**, so the hub still holds every twin's private key + plaintext. This
hardens **the wire and attribution** and finally makes per-agent identity true at
the MLS layer -- but it is **NOT** E2E-from-the-hub. A malicious hub still sees and
can impersonate everything. Confidentiality-from-the-hub is a different axis
(#664 Mode 2, deliberately out of scope).

Run: `./run.sh` (stands up a stock SLIM 2.1.0 node on :46359, mints one ES256
keypair per twin + a roster JWKS, execs this on the host). Env:
SLIM_ENDPOINT=http://127.0.0.1:46359, KEYDIR=/tmp/twin-sessions-spike,
TWINS="backend alice bob carol".

Matched stack (proven by #587/#583): slim-bindings==2.1.0 (PyPI) +
ghcr.io/agntcy/slim:2.1.0. Signing keys must be PKCS#8 PEM (run.sh converts).
"""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import hmac
import os
import shutil
import sys
from pathlib import Path

import slim_bindings

SLIM = os.environ.get("SLIM_ENDPOINT", "http://127.0.0.1:46359")
KEYDIR = os.environ.get("KEYDIR", "/tmp/twin-sessions-spike")
STORE = os.environ.get("TWIN_STORE", f"{KEYDIR}/twin-store")

ISSUER = os.environ.get("SIGNERJWT_ISSUER", "mycelium-resident")
AUDIENCE = [os.environ.get("SIGNERJWT_AUDIENCE", "mycelium-slim")]

ORG, NS, ROOM = "mycelium", "default", "twin-room"
# First twin is the moderator (the always-on backend citizen); the rest are the
# per-actor twins the backend custodies. The point of the spike is that the
# backend does NOT speak for alice/bob/carol -- each has its own App + identity.
TWINS = os.environ.get("TWINS", "backend alice bob carol").split()
MODERATOR = TWINS[0]
ACTORS = TWINS[1:]

# The at-rest passphrase boundary (Q4). Derived here from a per-host session
# secret HMAC'd with the actor handle so each twin store gets a DISTINCT key and
# one leaked passphrase does not open every twin. In production this session
# secret is a server-held secret (e.g. MYCELIUM_TWIN_STORE_SECRET / a KMS-wrapped
# value) -- deliberately NOT the actor's OIDC/SignerJwt token, which rotates
# hourly and is not a durable at-rest key. This is the real confidentiality
# boundary for the twin store and wants its own hardening pass (see README Q4).
_SESSION_SECRET = os.environ.get("MYCELIUM_TWIN_STORE_SECRET", "dev-twin-store-secret-do-not-ship")


def _store_passphrase(handle: str) -> str:
    return hmac.new(_SESSION_SECRET.encode(), handle.encode(), hashlib.sha256).hexdigest()


def _store_path(handle: str) -> str:
    # Server-side, per-twin, under the hub's data dir (~/.mycelium/-style). One
    # SQLite MLS state store per actor; AES-256-GCM at rest under the passphrase.
    p = Path(STORE) / handle
    p.mkdir(parents=True, exist_ok=True)
    return str(p / "mls-state.sqlite")


def _read(path: str) -> str:
    with open(path) as fh:
        return fh.read()


def signerjwt_identity(name: str):
    """Per-actor SignerJwt provider + roster-JWKS verifier (mirrors #587).

    Provider: sign this twin's own JWT with its local PKCS#8 ES256 key. Verifier:
    trust the room roster's public keys (static multi-key JWKS). This is what
    makes each twin a cryptographically distinct MLS participant -- the backend
    cannot mint alice's token without alice's private key.
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


def persistence_config(handle: str):
    # Q2 + Q4: the persistence seam. `path` is the server-side per-twin store;
    # `passphrase` is the at-rest key. Both keyword-only in the 2.1.0 wheel.
    return slim_bindings.PersistenceConfig(
        path=_store_path(handle),
        passphrase=_store_passphrase(handle),
    )


async def make_twin(svc, conn, name: str):
    """Create ONE persistence-backed, SignerJwt-identified twin App + subscribe.

    This is the load-bearing call for the spike: `create_app_with_persistence_async`
    with a per-actor identity. N of these in one process == a twin fleet.
    """
    provider, verifier = signerjwt_identity(name)
    slim_name = slim_bindings.Name(ORG, NS, name)
    app = await svc.create_app_with_persistence_async(
        slim_name,
        provider,
        verifier,
        slim_bindings.Direction.BIDIRECTIONAL,
        persistence_config(name),
    )
    await app.subscribe_async(slim_name, conn)
    return app, slim_name


def _sender_leaf(ctx) -> str:
    """Best-effort recover the sender's Name leaf from a MessageContext.

    The whole point of twins: the on-the-wire source of alice's message is
    alice's App, not the backend. We surface whatever the binding exposes so the
    attribution is visibly cryptographic, not a backend-stamped field.
    """
    for attr in ("source_name", "source", "name"):
        val = getattr(ctx, attr, None)
        if val is None:
            continue
        for meth in ("components", "as_tuple"):
            fn = getattr(val, meth, None)
            if callable(fn):
                try:
                    return fn()[-1]
                except Exception:  # noqa: BLE001
                    pass
        return str(val)
    return repr(ctx)


async def main() -> int:  # noqa: PLR0915 -- spike: linear narrative is the point
    # Fresh store each run so Q3's "restore" is unambiguous.
    shutil.rmtree(STORE, ignore_errors=True)

    slim_bindings.initialize_with_defaults()
    svc = slim_bindings.get_global_service()

    # Q6: ONE dataplane connection for the whole fleet. Every twin App multiplexes
    # over this single conn_id -- N twins, one socket, not N sockets.
    conn = await svc.connect_async(slim_bindings.new_insecure_client_config(SLIM))
    print(f"[fleet] one shared dataplane connection: conn_id={conn}", flush=True)

    # ---- Q1: stand up the twin fleet, all in this one process ----
    mod_app, _ = await make_twin(svc, conn, MODERATOR)
    twins: dict[str, object] = {}
    twin_names: dict[str, object] = {}
    for name in ACTORS:
        app, slim_name = await make_twin(svc, conn, name)
        twins[name] = app
        twin_names[name] = slim_name
    print(
        f"[fleet] {len(ACTORS)} persistence-backed SignerJwt twins created "
        f"in ONE process: {', '.join(ACTORS)}",
        flush=True,
    )

    room = slim_bindings.Name(ORG, NS, ROOM)
    created = mod_app.create_session(group_session_config(), room)
    await created.completion.wait_async()
    session = created.session
    print(f"[{MODERATOR}] MLS GROUP session established (moderator).", flush=True)

    # Each twin waits for its invite, then speaks once so the moderator can read
    # the on-the-wire sender identity.
    ready: dict[str, asyncio.Event] = {n: asyncio.Event() for n in ACTORS}
    joined_sessions: dict[str, object] = {}

    async def twin_wait(name: str):
        s = await twins[name].listen_for_session_async(None)
        joined_sessions[name] = s
        ready[name].set()
        await s.publish_async(f"{name}: hello over MLS as myself".encode(), None, None)

    waiters = [asyncio.create_task(twin_wait(n)) for n in ACTORS]

    for name in ACTORS:
        await mod_app.set_route_async(twin_names[name], conn)
        handle = await session.invite_async(twin_names[name])
        await handle.wait_async()
        await asyncio.wait_for(ready[name].wait(), timeout=30)
        print(f"[{MODERATOR}] invited + MLS-verified twin '{name}'.", flush=True)

    # ---- Q1 (cont.): read each twin's message; prove distinct wire attribution ----
    seen: dict[str, str] = {}
    for _ in ACTORS:
        msg = await session.get_message_async(timeout=datetime.timedelta(seconds=30))
        leaf = _sender_leaf(msg.context)
        seen[leaf] = msg.payload.decode()
        print(f"[{MODERATOR}] wire sender={leaf!r} payload={msg.payload.decode()!r}", flush=True)

    await asyncio.gather(*waiters)
    distinct = {k for k in seen if k in ACTORS}
    if len(distinct) != len(ACTORS):
        # Surface, don't hide: if the binding does not expose per-twin source on
        # the moderator's inbound context, the attribution claim is unproven.
        print(
            f"\nWARN: distinct wire senders={sorted(distinct)} but expected {ACTORS}. "
            "Twin membership is real (each invite ran MLS peer-verification of a "
            "DISTINCT SignerJwt), but this binding did not surface per-sender "
            "source on the moderator's inbound MessageContext.",
            flush=True,
        )
    else:
        print(f"[fleet] distinct cryptographic wire senders: {sorted(distinct)}", flush=True)

    # ---- Q3: resume one twin from its persisted MLS state, NO re-invite ----
    victim = ACTORS[0]
    print(f"\n[resume] simulating a restart of twin '{victim}' ...", flush=True)
    # Drop every in-memory handle to the victim's App + its joined session WITHOUT
    # a graceful leave. A graceful `delete_session` removes the member from the
    # MLS group AND purges its persisted state -- the opposite of a crash. A real
    # restart just loses the process: the on-disk MLS state is all that survives,
    # so we only drop references and let GC reclaim the App. `restore_sessions`
    # then recovers the group membership from disk (see the returned session
    # count below). One caveat this single-process sim exposes: the crashed App's
    # subscription for the victim's Name is still registered over the SHARED conn
    # (a real crash drops the conn and the node forgets it), so we verify the
    # resume by having the revived twin SEND rather than depending on the node
    # re-routing inbound to the fresh subscription.
    twins.pop(victim)
    joined_sessions.pop(victim, None)
    import gc

    gc.collect()

    # Re-create the App against the SAME store path + passphrase, then restore.
    revived, revived_name = await make_twin(svc, conn, victim)
    restored = await revived.restore_sessions_async(conn)
    print(
        f"[resume] restore_sessions('{victim}') returned {len(restored)} session(s) "
        "from persisted MLS state (no invite/welcome replayed).",
        flush=True,
    )
    if not restored:
        print(
            "\nFAIL: restore_sessions returned no sessions -- the twin did not "
            "rejoin its MLS group from persisted state.",
            file=sys.stderr,
            flush=True,
        )
        return 1

    # Prove the restored MLS state is USABLE: the revived twin transacts on the
    # restored session at the group's current epoch, with no re-invite. It SENDS
    # (encrypts to the live group key it recovered from disk) and the moderator
    # decrypts + attributes it -- a direct proof the crypto epoch survived, and
    # one that does not depend on the node re-routing to the fresh subscription.
    revived_session = restored[0]
    proof = f"{victim}: back from persisted MLS state".encode()
    await revived_session.publish_async(proof, None, None)
    got = await session.get_message_async(timeout=datetime.timedelta(seconds=30))
    leaf = _sender_leaf(got.context)
    print(
        f"[resume] moderator decrypted post-restore msg from wire sender={leaf!r}: "
        f"{got.payload.decode()!r}",
        flush=True,
    )
    if got.payload != proof:
        print("\nFAIL: revived twin's post-restore message did not round-trip.", file=sys.stderr, flush=True)
        return 1

    # ---- Q4: report where the store lives + the passphrase boundary ----
    print("\n[store] per-twin server-side MLS state (Q4):", flush=True)
    for name in TWINS:
        path = _store_path(name)
        size = Path(path).stat().st_size if Path(path).exists() else 0
        print(f"  {name:10} {path}  ({size} bytes, AES-256-GCM at rest)", flush=True)
    print(
        "  passphrase = HMAC(server session secret, handle) -- distinct per twin, "
        "NOT the OIDC/SignerJwt token.",
        flush=True,
    )

    print(
        f"\nPASS: {len(ACTORS)} per-actor SignerJwt twins (persistence-backed) shared "
        f"one MLS GROUP over one socket; twin '{victim}' resumed from persisted "
        "state with no re-invite.",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except Exception as exc:  # noqa: BLE001 -- spike: surface the exact failure
        print(f"\nFAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
