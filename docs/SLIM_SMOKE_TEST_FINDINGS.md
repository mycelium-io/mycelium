# SLIM-native rewrite — first full-stack smoke test: findings

**Context.** First real run of the full product stack (docker compose: `slim` node +
backend + frontend) with a **real `claude` Code agent** cold-spawned by the daemon,
driven end-to-end on one host. Prior validation was unit tests + a by-hand live suite
against a bare node — the assembled stack, a real agent waking over SLIM, and the UI had
never been exercised together. This is that exercise.

**Bottom line.** It works end-to-end now, but only after fixing **6 real bugs** and
working around **~10 other issues/gaps**. The single most important architectural finding
is the **two-message-store split (§A)** — everything else is a bug or a lifecycle
footgun. A real Claude agent now: wakes over SLIM (`wake @smoke-agent`), spawns `claude -p`,
runs, and its reply (`FABRIC CONFIRMED`) lands in the room transcript. The UI consent
modal (invite accept/decline) works.

---

## Part 1 — Bugs fixed (code changes on `slim-native-rewrite`, tests green)

Each is a genuine defect that blocked the flow. Files touched listed; all had the same
signature — **silent degradation** (DEBUG-level or swallowed), which is why the first
full-stack run was needed to surface them.

1. **Backend can't reach the node in compose → every channel provision silently no-ops.**
   `compose.yml` never set `SLIM_NODE_ENDPOINT` for `mycelium-backend`, so it defaulted to
   `http://127.0.0.1:46357` = the backend container itself. `room_channels.provision()` is
   best-effort and no-ops when the node is unreachable → **no room ever gets a SLIM channel.**
   Fix: `SLIM_NODE_ENDPOINT: http://mycelium-slim:46357` in the backend service.
   *This ships broken in the current compose.*

2. **Idle SLIM connections dropped after ~30s (no keepalive) — the deepest cause of churn.**
   `new_insecure_client_config()` leaves `keepalive=None`; the binding's
   `keep_alive_while_idle` then defaults to `false`, so the node drops any idle connection
   after ~30s (its `RecoveryTable` TTL — confirmed in SLIM source + node logs:
   `connection lost, storing recovery state (TTL: 30s)`). This silently killed the
   moderator's session on any quiet room and dropped a waiting connector before it could be
   invited. Fix: set `KeepaliveConfig(keep_alive_while_idle=True, ...)` in **both**
   `_shared_connection`s — `mycelium-cli/.../slim/client.py` and
   `fastapi-backend/.../services/slim_client.py`.

3. **Persister dies permanently on a normal idle receive-timeout.**
   `RoomPersister.run()` counted a `get_message` timeout (SLIM raises a generic
   `SessionError('receive timeout...')`) as a failure; 3 consecutive → the loop `return`s
   with no restart. So **every room's persister silently dies after ~90s of silence**, and
   the channel becomes a zombie (still "provisioned", nothing served). Fix: added
   `ChannelReceiveTimeout` (`l9_slim.py`), and the persister treats it as benign (reset the
   failure counter, keep waiting). Verified: survives 130s idle. *(Files: `l9_slim.py`,
   `persister.py`.)*

4. **Connector churns every 30s on the same idle-timeout bug.**
   The daemon connector's receive loop treated the idle `get_message` timeout as a dropped
   session → closed + reconnected every ~30s → **membership flapping** (moderator sees
   `participant disconnected` repeatedly). Fix: `SlimReceiveTimeout` in the CLI client;
   connector `continue`s on it instead of reconnecting. *(Files: `slim/client.py`,
   `daemon/connector.py`.)*

5. **Agent replies held forever by the causal-order buffer.**
   `build_reply()` parents an agent's reply on the triggering message
   (`parents=[woke_id]`). The moderator's `CausalOrderBuffer` only releases an envelope once
   every parent id is in `_delivered`, and `_delivered` is populated only by messages that
   pass *through* the buffer via `receive_with_context`. But **human messages are recorded via
   `ingest_local`, which bypasses the buffer** — so the parent id is never marked delivered
   and the agent's reply sits in `_pending` forever, never recorded. Fix:
   `CausalOrderBuffer.mark_delivered()` + `L9SlimChannel.note_delivered()`, called from
   `ingest_local`. Verified: reply now recorded. *(Files: `l9_slim.py`, `persister.py`.)*

6. **`slim-bindings` missing from the installed CLI/daemon env (install-path gap).**
   The `uv tool` install predated the `slim-bindings` dependency, so `mycelium daemon run`
   logged `slim-bindings unavailable; connector ... disabled` and **silently ran with no
   connector**. Fix here was reinstalling the tool, but the daemon degrading to a no-op
   (rather than failing loudly) is the real issue — see §J.

---

## Part 2 — Architectural finding (needs a design decision, NOT a patch)

### §A — There are two message stores, and they've diverged. This is the core issue.

Symptom: the human's messages appear in the UI, but the **agent's reply does not** — even
though the reply is correctly recorded in `log/transcript.md`.

Why:

- **`local_state`** (in-memory, `services/local_state.py`) is written by
  `POST /api/rooms/{room}/messages` and read by `GET list_messages` **and the UI**.
- **The persister** writes the durable **transcript** (`log/transcript.md`) and pushes to
  the **SSE bus** (`routes/stream.py`) — which is marked *"DEPRECATED — retired in Step 10."*
- So: human messages → `local_state` (via POST) → **visible in UI**. Agent replies arrive
  over SLIM → persister → transcript + a **retired** bus → **never reach `local_state`** →
  **invisible in UI.**

This is an **incomplete migration**: the SLIM-native record (persister/transcript) and the
UI's list surface (`local_state`) were never unified. The persister still feeds the dead
SSE bus instead of the store the UI actually reads.

**Please don't fix this with a mirror/dual-write** (I started to, and it was correctly
called out as a hack). The right fix is a single source of truth. Two clean options:

- **(a) UI/list reads the persister's record.** Make `list_messages` (for real rooms with a
  live channel) read the persister's `TranscriptLog` / a queryable store the persister owns.
  `local_state` remains only for coordination sub-rooms that have no persister — or those
  migrate too.
- **(b) Persister is the single writer into `local_state`.** `_ingest` writes `local_state`
  for *all* room messages (human via `ingest_local`, agents via receive); the POST route
  stops writing `local_state` directly for channel-backed rooms (it just publishes to SLIM;
  the persister records the loopback/`ingest_local`). One writer, no divergence, no mirror.

Either unifies the path. (b) is smaller and keeps the persister as the authority for
"what happened in the room," which matches the SLIM-native model. Whoever owns the rewrite
should pick — it touches the messages route + UI feed and interacts with the SSE-retirement
work.

---

## Part 3 — Other findings / gaps (not yet addressed)

- **§B — `managed.members` desync.** A handle is added to `room_channels` members on
  invite-accept but **never removed on participant-disconnect**. Once "member", `publish_human`
  won't re-raise a consent invite for it even if the real connector is gone → can't re-invite;
  also causes `participant already in group` on re-accept. Membership must track actual SLIM
  presence (add on join, remove on disconnect).

- **§C — Persister only tolerates *idle* timeouts now.** `participant disconnected` and
  `session closed` still count toward the 3-strike give-up (fix #3 only spared the idle
  timeout). A member leaving/reconnecting can still kill the room. These should be treated as
  membership events, not fatal errors.

- **§D — Persister has no restart/reconnect.** `_start_persister` is a bare
  `create_task(run())` with no done-callback. Any terminal error kills the room's channel
  permanently (zombie) until re-provision.

- **§E — Re-serve on join doesn't deliver the triggering mention.** After a consent-accept,
  the connector joins but `persister.reserve()` did **not** deliver the `@`-mention that
  triggered the invite (reproduced with both a manual connector and the daemon — "joined but
  no message"). So the **first** wake after accept is lost; a subsequent message is needed.
  Likely a timing race (reserve runs before the member's receive loop is ready). Needs
  investigation — this is the one gap that still blocks a clean single-shot "invite → wake".

- **§F — No re-provision of existing rooms on backend restart.** Startup lifespan wires the
  aligner/plan-sync but doesn't re-provision existing rooms' channels, and `room create` isn't
  idempotent (`400 Room already exists`). **Every backend restart leaves all existing rooms
  channel-less** (zombie) with no recovery path. Startup should re-provision rooms found on disk.

- **§G — No CLI for consent invites.** Accept/decline is backend API + UI only (no
  `mycelium invite ...`). Because `publish_human` raises a consent invite for **any
  not-yet-present agent**, consent is on the critical path for an agent's *first* wake — so a
  CLI-only user currently **cannot wake their own registered agent**. (UI modal works.)

- **§H — Daemon lifecycle footguns (cost hours of the debug).**
  - A launchd agent `io.mycelium.cc-daemon` (KeepAlive) **silently respawns** a `.venv`
    daemon. It collided with manually-run daemons → **two daemons both owning the same handle**
    → both subscribe the same SLIM name → invites route to one, the other never joins. No
    singleton guard, no duplicate-handle detection.
  - Daemon Python logs are **block-buffered** when stdout isn't a TTY → connector logs
    invisible without `PYTHONUNBUFFERED=1`.
  - Recommend: a per-host singleton lock (pidfile/flock), refuse/warn on a second daemon, and
    detect duplicate handle subscriptions on the fabric.

- **§I — Stale node-side state across room delete/recreate.** Reusing a room name across many
  delete/recreate cycles on a long-running node accumulated routing/recovery state that broke
  invites to that name; a **fresh node fixed it**. `room delete` doesn't clean up node-side
  subscription/route state.

- **§J — Silent degradation is pervasive (bible D3/D6).** Nearly every bug above was
  DEBUG-level or swallowed: provision no-op, `invite skipped`, persister receive errors,
  connector errors, missing wheel. Diagnosis required turning on DEBUG in three places. These
  should be promoted to WARNING and/or surfaced on a health/status endpoint — "nothing
  happens" with green logs is the worst failure mode, and it's the default one today.

---

## Part 4 — Diagnostic changes to review before merge

- `fastapi-backend/app/main.py` — made log level env-configurable via `LOG_LEVEL` (**keep**,
  it's an improvement).
- `mycelium-cli/.../docker/compose-dev.yml` — `LOG_LEVEL: DEBUG` for the dev backend (keep or
  drop, dev-only).
- `mycelium-cli/.../docker/compose.yml` — **node `tracing.log_level` was set to `debug` for
  diagnosis; REVERT to `info` before merge.** (The `SLIM_NODE_ENDPOINT` addition in the same
  file is a real fix — keep it.)

## What was validated end-to-end
Stack up (slim+backend+frontend, no DB) · memory set/get/ls/search on plain files ·
room-channel provision · consent invite raised + accepted (UI modal) · connector joins ·
real agent wakes over SLIM · `claude -p` spawns and runs · reply recorded to transcript.
Not validated: openclaw/hermes (known-broken post-rewrite, D11); aligner→converge→plan
(Rung 4) — blocked behind getting a stable single agent first.
