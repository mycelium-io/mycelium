# START HERE — Step 3 (L9 over SLIM: the bus + room = channel)

Companion to [`START_HERE.md`](./START_HERE.md). Step 2 is **done and merged**
(PR #420 into `slim-native-rewrite`); you are picking up **Step 3**. Read `START_HERE.md`,
[`START_HERE_STEP_1.md`](./START_HERE_STEP_1.md), and
[`START_HERE_STEP_2.md`](./START_HERE_STEP_2.md) first if you haven't — the same rules apply.
This file gives you (a) the exact state Step 2 left behind, (b) your Step 3 marching orders,
(c) the L9/SLIM facts you must internalize, and (d) the traps specific to this step.

**This is the step where SLIM stops being a standalone hello-world and becomes the coordination
bus.** Step 2 built the plumbing in isolation; Step 3 wires it into rooms.

## Ground rules (unchanged from START_HERE.md)

1. **The bible is authoritative:** [`slim-native-rebuild-bible.md`](./slim-native-rebuild-bible.md).
   Your work is **Part V · Step 3**, with **§6 (layering)**, **§9 (room = channel)**, **§13 (the
   full cycle)**, and the **L9 sections** as the design reference. `CLAUDE.md`'s L9 module map
   (`l9.py`/`l9_episode.py`/`l9_models.py`) is accurate; its **subkind note is now stale** — see
   the `abort`→`rejected` trap below.
2. Leave the project **runnable and green** — backend + CLI quality gates pass at the end.
3. Code/config blocks in the bible are **reference, not paste** — write the implementation
   yourself, matching the surrounding style. The cloned `slim-bindings` examples under
   `~/Documents/GitHub/_slim-research/` remain the ground truth for the binding API.
4. **Verify before you edit** — paths below were accurate at the end of Step 2; confirm shape
   before changing a file.
5. Fixed decisions are not up for debate; open questions have a default. **Step 3's resolve-first
   is the group lifecycle** — default to a **durable channel per room, with an episode = one
   negotiation within it**; enforce L9 transport rules in the **binding/backend**, not the agent.

## Where Step 2 left things (your starting state)

Branch off `slim-native-rewrite` (Step 2 is merged). SLIM is stood up but **completely isolated
from the room/coordination flow** — that isolation is exactly what you now dismantle. Concretely:

- **SLIM wrapper exists:** `app/services/slim_client.py` — lazy `slim_bindings` import,
  `SlimIdentity`, `to_slim_name`/`from_slim_name`/`to_channel_name` (`workspace/room/agent` ↔
  `org/ns/app`; channel = `workspace/room/topic`), `mint_shared_secret` (keyed on the **channel**
  `workspace/room`, shared by all members — it seeds the group key), and `SlimClient`
  (`connect`/`create_group`/`invite`/`listen_for_session`/`publish`/`receive`). A per-endpoint
  `_connections` cache handles "one dataplane connection per endpoint per process."
- **Node runs:** `docker/compose.yml` has a `slim` core service
  (`ghcr.io/agntcy/slim:${SLIM_IMAGE_TAG:-1.4.0}`, :46357, inline node config). **Pinned to
  1.4.0** to match the `slim-bindings` 1.4.x wheel — do **not** bump to `:latest` (2.0 line;
  handshake-incompatible). CLI has `mycelium hub host` and `mycelium connect <address>`, plus
  `SlimConfig.node_endpoint`.
- **L9 core is kept and untouched** (per Steps 1–2): `services/l9.py` (`build_envelope`,
  `parse_envelope`, `envelope_to_dict`, `validate_subkind`, `VALID_SUBKINDS`, `episode_urn`,
  `topic_urn`, `extract_parent_id`), `l9_episode.py` (episode tracking, MPC/GAR/SCR,
  `log/episodes/{short_id}.md`), `l9_models.py` (vendored pydantic bindings). **The failure
  subkind is still `abort`** in `l9.py:VALID_SUBKINDS` — flipping it is part of *this* step.
- **The bus + presence/messages are single-process in-memory shims** (Step 1): `app/bus.py` is
  in-memory pub/sub; `routes/stream.py` (SSE) subscribes to it and is **deprecated** (retired
  Step 10); `services/local_state.py` holds messages/presence/subscriptions; `routes/sessions.py`
  is a **presence shim** with the join-window machinery gone; `routes/messages.py` and
  `services/event_sweep.py` are in-memory. All carry `# TODO(step3)` markers — **this is where
  those TODOs come due.**
- **No database anywhere.** The daemon (`daemon/dispatch.py`) still holds an **httpx SSE** stream
  per room — leave it; retargeting the daemon to SLIM is **Step 5**, not now.

### Carry-forward from the Step 2 review (address in this step / acknowledge)

Two forward-looking notes from the Step 2 review land here:

1. **Turn MLS on for the room channel.** Step 2's hello-world ran with `enable_mls=False`
   (reasonable for a throwaway). But MLS-on is load-bearing beyond encryption: the
   hosted-rendezvous de-risk story (bible §16) depends on intermediate nodes seeing only
   ciphertext. **When the room channel goes live in this step, enable MLS** — don't let
   `enable_mls=False` become the default for real rooms. (`slim-bindings` 1.4.1 gates MLS via
   `SessionConfig(enable_mls=True)`; the shared secret already seeds it.)
2. **Connection lifecycle.** `slim_client.py`'s `_connections` cache has **no teardown/close**.
   Fine for Step 2's one-shot; Step 3 opens **long-lived** room connections, so add a close /
   shutdown path (drop the cached conn, leave the session) so the backend doesn't leak or reuse a
   stale connection across a room's lifecycle. (Step 4/5 lean on this too.)

## Your Step 3 scope (from the bible, Part V · Step 3)

- **L9↔SLIM binding** (a `NetworkHandle`-style adapter, new module): `send(header/envelope)`
  serializes an L9 envelope (you already have `l9.envelope_to_dict`) and `publish`es it to the
  room channel; inbound SLIM messages are `parse_envelope`'d back to L9 and dispatched to local
  handlers. This is the seam between `l9.py` (envelope construction) and `slim_client.py`
  (transport).
- **Room provisioning = channel provisioning.** Creating/opening a room provisions a SLIM group
  channel; the **backend creates the session and is the moderator** (invites members). Rework
  `routes/rooms.py` (provision on create/open) and `routes/sessions.py` (presence from SLIM).
- **Enforce the L9 transport requirements the app must own:**
  - **Causal ordering by `message.parents`** — deliver in causal order; reorder out-of-order
    arrivals. (`l9.extract_parent_id` is your hook.)
  - **Episode ↔ channel lifecycle** — an episode is one negotiation within the durable room
    channel; a **mid-episode membership change aborts the episode** (`l9_episode.py`).
- **Presence from SLIM.** Online/offline now comes from SLIM heartbeats, replacing the
  `local_state` presence shim for coordination. Retire the relevant `# TODO(step3)` markers.
- **Flip the failure subkind `abort` → `rejected`** in `l9.py:VALID_SUBKINDS` (see trap below).

**Key files:** new L9-over-SLIM binding module (`app/services/`); `services/l9.py` [L9-keep —
subkind flip only]; `routes/rooms.py` / `routes/sessions.py` [rework]; `services/slim_client.py`
[extend — MLS on, connection close]; likely `app/bus.py` / `local_state.py` where presence and
message fan-out move onto SLIM.

## L9 / SLIM facts you must internalize first

Read bible **§6**, **§9**, **§13**, and the L9 notes in `CLAUDE.md`. The load-bearing facts:

- **The room bus is L9 straight over SLIM group sessions — no A2A.** For a symmetric
  "everyone hears everyone" room, raw SLIM **group** sessions fit better than A2A's
  request/response fan-out (bible §6). A2A stays optional, for future point-to-point only.
- **Envelopes are additive; agents never speak L9.** Coordination messages carry an `l9` key
  inside the content JSON: ticks are `exchange`, consensus is `commit:converged` /
  `commit:rejected`, with episode URNs and causal `message.parents`. The backend synthesizes
  reply envelopes from parsed agent replies. Do not require agents to emit L9.
- **The subkind table is `converged | resolved | rejected`** after this step (see trap).
- **Durable channel, ephemeral episode.** The channel persists for the room's life; an episode is
  one negotiation inside it. Membership churn mid-episode = abort that episode, **not** tear down
  the channel.
- **⚠ Still no durable inbox.** SLIM does not retain messages for an offline member. Step 3
  proves live L9-over-SLIM delivery **with participants online**; the always-on persister /
  durable inbox that re-serves missed messages is **Step 4**. Don't build it here.

## Definition of Done

An L9 `exchange` message published by one participant is **received and correctly parsed by
another over a room channel**, and **parents-ordering holds** (out-of-order arrivals are
reordered by `message.parents`). Room creation provisions the channel with the backend as
moderator; presence reflects SLIM membership.

## Tests to write (end of step)

- **L9-over-SLIM round trip** — an `exchange` envelope published by one participant is received +
  parsed by another over a room channel (guarded on a live node, mirroring Step 2's
  `test_slim_roundtrip.py`).
- **Envelope integrity** — `kind` / `subkind` / `parents` / `episode` survive the
  serialize→publish→receive→parse round trip.
- **Causal ordering** — out-of-order arrival is reordered by `parents`.
- **Episode lifecycle** — a mid-episode membership change triggers `abort` of the episode.
- **Subkind flip** — `validate_subkind(Kind.commit, "rejected")` passes and `"abort"` is no
  longer accepted for a failed commit (update existing L9 tests accordingly).

## Verification gate (must pass before you call Step 3 done)

```bash
# Backend
cd fastapi-backend
uv run ruff check . && uv run ruff format --check . && uv run ty check .
MYCELIUM_STUB_EMBEDDINGS=1 uv run pytest tests/ -x -q

# CLI (matches CI)
cd ../mycelium-cli
uv run ruff check . && uv run ruff format --check . && uv run ty check . && uv run pytest tests/ -x -q
```

Then prove the DoD by hand: `mycelium hub host` brings up the node; create a room (channel
provisioned, backend = moderator); publish an L9 `exchange` from one participant and see another
receive + parse it, with parents-ordering intact.

## Traps specific to Step 3

- **`abort` → `rejected` — and fix the stale note.** `l9.py:VALID_SUBKINDS` currently holds
  `commit: {converged, resolved, abort}` because the **Go CFN's** table was authoritative
  (per the 2026-06-30 team decision recorded in `CLAUDE.md`). **That authority is gone with the
  CFN** — the SLIM-native design (bible §13) emits `commit:rejected` for a failed negotiation.
  Flip the table to `{converged, resolved, rejected}`, **and update the now-stale `CLAUDE.md` +
  `l9.py` comments** that cite the Go CFN's `abort` as authoritative, so the next reader isn't
  misled.
- **Don't build the persister here.** No durable inbox, no missed-message replay, no transcript
  persistence — that's **Step 4**. Step 3 is live delivery with everyone online. If you find
  yourself tracking per-agent delivery position, you've overshot.
- **Don't retarget the daemon.** `daemon/dispatch.py` stays on httpx SSE; the SLIM subscription +
  wake bridge is **Step 5**. Step 3's SLIM consumers are the **backend** (moderator) and the
  round-trip tests, not the connectors.
- **MLS on, and version stays pinned.** Enable MLS for the room channel (review note #1), and do
  **not** touch the `slim:1.4.0` / `slim-bindings` 1.4.x pin — they're a matched pair.
- **Keep the SSE path alive.** `routes/stream.py` is still the UI's feed until Step 10. Moving
  coordination onto SLIM must not break the deprecated SSE bus the frontend still reads.

## Report when done

Per `START_HERE.md`: what changed, the DoD check, and test results. Open a PR against
`slim-native-rewrite` (same as Steps 0–2). Deferrals to name explicitly: the durable
inbox/persister + trigger-watcher are **Step 4**, the daemon still uses **httpx SSE** (retargeted
in Step 5), cognition engines are **Step 7**, and SSE/`stream.py` is retired in **Step 10**.
