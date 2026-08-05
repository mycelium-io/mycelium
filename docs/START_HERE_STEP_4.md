# START HERE — Step 4 (Backend as room infrastructure: persister + durable inbox + wake)

Companion to [`START_HERE.md`](./START_HERE.md). Step 3 is **done and merged**
(PR #421 into `slim-native-rewrite`); you are picking up **Step 4**. Read `START_HERE.md`,
[`START_HERE_STEP_1.md`](./START_HERE_STEP_1.md),
[`START_HERE_STEP_2.md`](./START_HERE_STEP_2.md), and
[`START_HERE_STEP_3.md`](./START_HERE_STEP_3.md) first if you haven't — the same rules apply.
This file gives you (a) the exact state Step 3 left behind, (b) your Step 4 marching orders,
(c) the facts you must internalize, and (d) the traps specific to this step.

**This is the step where the backend stops being a passive moderator and becomes the always-on
room infrastructure.** Step 3 provisioned channels and invited members but the backend never
*consumed* the channel. Step 4 has it join the stream as the **persister / durable inbox** and
**trigger-watcher** — so a message broadcast while an agent is offline is no longer lost.

## Ground rules (unchanged from START_HERE.md)

1. **The bible is authoritative:** [`slim-native-rebuild-bible.md`](./slim-native-rebuild-bible.md).
   Your work is **Part V · Step 4**, with **§7d (THE CRITICAL CAVEAT — no durable inbox)**,
   **§9 (backend as room infrastructure)**, **§11 (memory)**, **§12 (wake / `@`-mention)**, and
   **§13 (the full cycle)** as the design reference.
2. Leave the project **runnable and green** — backend + CLI quality gates pass at the end.
3. Code/config blocks in the bible are **reference, not paste** — write the implementation
   yourself, matching the surrounding style. The cloned `slim-bindings` examples under
   `~/Documents/GitHub/_slim-research/` remain the ground truth for the binding API (targeted
   send / `publish_to` is the new binding surface you'll reach for — verify it against those
   examples).
4. **Verify before you edit** — paths below were accurate at the end of Step 3; confirm shape
   before changing a file.
5. Fixed decisions are not up for debate; open questions have a default (see **Resolve first**
   below — Step 4's are all about the durable-inbox mechanics).

## Where Step 3 left things (your starting state)

Branch off `slim-native-rewrite` (Step 3 is merged). The SLIM bus is **live and wired into
rooms**, but **the backend does not yet read from the channel** — that gap is exactly what you
close. Concretely:

- **Room = channel, backend = moderator:** `app/services/room_channels.py` holds a process-wide
  `manager` (a `RoomChannelManager`). Creating a room provisions one long-lived SLIM group
  channel (`routes/rooms.py`), the backend is its moderator, and joins invite the agent
  (`routes/sessions.py`, fire-and-forget). A `ManagedRoomChannel` carries the moderator's
  `SlimClient`, an `L9SlimChannel`, the tracked `members` set, and an `EpisodeLifecycle`.
- **⚠ No receive loop exists.** The moderator provisions + invites but **never calls
  `L9SlimChannel.receive()`**. Step 3 deliberately deferred consuming the channel ("If you find
  yourself tracking per-agent delivery position, you've overshot" was the Step 3 trap — that
  position tracking is **now your job**). Starting the consumer loop is the heart of Step 4.
- **The L9↔SLIM binding is in place:** `app/services/l9_slim.py` — `serialize_envelope` /
  `deserialize_envelope` (envelope rides under the `l9` content key), `CausalOrderBuffer`
  (reorders by `message.parents`), `EpisodeLifecycle` + `build_episode_abort_envelope`, and
  `L9SlimChannel` (`.send(envelope)` / `.receive()` → causally-ordered list). **`.receive()` is
  your read hook.** There is **no targeted-send** helper yet — broadcast `publish` only; you'll
  add `publish_to`-style targeted delivery for re-serve (see traps).
- **Presence rides SLIM:** `manager.members(room)` is authoritative when a channel is live;
  `local_state` is the metadata store (intent/context files) and the no-fabric fallback. Reconnect
  detection will hang off membership changes the manager already sees.
- **Messages are still in-memory:** `app/services/local_state.py` holds the message list behind a
  `# TODO(step4)` marker — **this is where that TODO comes due.** `routes/messages.py` and the
  deprecated SSE feed (`routes/stream.py` via `app/bus.py`) still read `local_state`; the UI
  depends on them until Step 10, so **keep them fed**.
- **Episode records already persist:** `l9_episode.py:write_episode_record` writes
  `log/episodes/{short_id}.md` (episode-scoped summary + a `jsonl` block). Your **channel
  transcript** persister is a *different* artifact (the live, full message stream) — reconcile,
  don't duplicate (see traps).
- **plan_compiler is kept, unwired:** `services/plan_compiler.py:compile_plan(...)` exists but its
  old caller (`coordination.py:_finish_cfn`) was ripped out in Step 0. Nothing fires it. Step 4
  adds only the **hook** (watch for `commit:converged`); actually firing it is **Step 8**.
- **Lifespan hooks:** `app/main.py` starts the reindex watcher + event sweep + embedding warmup,
  and on shutdown calls `room_channels.manager.close_all()` (channels + shared connection). Your
  persister loop plugs into this same start/stop discipline.
- **Daemon untouched:** `daemon/dispatch.py` still holds an **httpx SSE** stream per room — leave
  it; retargeting the daemon to SLIM is **Step 5**.

## Your Step 4 scope (from the bible, Part V · Step 4)

- **Persister (the receive loop).** Have the backend moderator run a long-lived background task
  per room that pulls from its `L9SlimChannel.receive()` and **records the full transcript** to the
  room's markdown (`log/`) — so it survives, is git-shareable, and is reindexed by the normal
  memory path. Start it when a channel is provisioned; stop it on close/shutdown.
- **Durable inbox (the reason this step exists).** SLIM **does not** retain messages for an offline
  member (§7d) — a rejoin only re-keys, it does not replay. So mycelium must: **track each agent's
  delivery position**, and when an agent **reconnects**, **re-serve the messages it missed**, in
  order. This is a mycelium construct end-to-end.
- **Trigger-watcher skeleton.** As the persister sees each message, recognize **`@`-summon**
  tokens (and, later, configured trigger-words) and expose a **hook to summon an engine** — the
  hook is wired to a real engine in **Step 7**; here it's a skeleton (recognize + call a no-op/log
  hook).
- **plan-compile hook.** Watch for `commit:converged` on the stream and expose the seam that
  **Step 8** will use to fire `plan_compiler`. Skeleton only — do **not** compile plans here.

**Key files:** new backend room-infra module(s) — a persister/durable-inbox module (e.g.
`app/services/persister.py`) plus the per-agent cursor store; `room_channels.py` [extend — own the
consumer loop start/stop, surface the reconnect signal]; `l9_slim.py` [extend — a targeted-send
path for re-serve, and possibly a `publish_to`-aware receive]; `slim_client.py` [extend — targeted
`publish_to`]; `services/plan_compiler.py` [keep — wire the trigger hook]; `services/filesystem.py`
[use — transcript writes]; `local_state.py` / `routes/messages.py` / `app/bus.py` [keep the UI feed
alive]; `app/main.py` [lifespan — start/stop the persister].

## Facts you must internalize first

Read bible **§7d**, **§9**, **§11**, **§12**, **§13**. The load-bearing facts:

- **SLIM has no durable inbox — this single fact drives the step (§7d).** A member that was gone
  when a broadcast happened **never receives it**; rejoin re-keys but does **not** replay. The
  durable inbox is *yours* to build; do not expect SLIM to help.
- **The backend is already in the channel.** The persister is not a new connection — it's the
  **moderator's existing `L9SlimChannel`**, finally being read. The moderator is a group member, so
  it receives every broadcast.
- **Re-serve is targeted, not broadcast.** A group `publish` goes to *everyone*; re-serving missed
  messages to one reconnecting agent must **not** re-deliver to the whole room. Use SLIM's
  point-to-point send (`publish_to` / `publish_to_async` — verify against the cloned examples). The
  receiver's `CausalOrderBuffer` still orders them.
- **Reconnect = a membership change = (if an episode is active) an episode abort.** Step 3 aborts an
  active episode on any membership change. A reconnect is one such change. Keep the two concerns
  **separate**: the durable inbox re-serves the **channel transcript** regardless of episode state;
  don't let episode-abort logic swallow the re-serve, and don't let re-serve resurrect an aborted
  episode.
- **Persist as git-shareable markdown, indexed the normal way (§11).** The transcript is memory:
  markdown under the room's `log/`, written via the existing `filesystem` helpers, picked up by the
  reindex watcher. Do not invent a second store.
- **Agents never speak L9, and the persister doesn't change that.** It reads the `l9` envelope for
  routing/ordering/summon detection; the human-facing content stays where agents already read it.

## Definition of Done

An agent that is **offline during a broadcast receives the missed messages on reconnect**, in
order; and the **channel transcript is persisted to markdown** (survives, and is reindexed). The
trigger-watcher recognizes an `@`-summon token and calls the (skeleton) summon hook; the
`commit:converged` plan-compile hook fires its seam (without compiling).

## Tests to write (end of step)

Fast unit tests (the merge gate — no node):

- **Delivery-position cursor** — a per-agent cursor advances as messages are recorded and yields
  exactly the un-delivered tail for a given agent (empty when caught up).
- **Transcript persistence** — recorded envelopes land in the room's `log/` markdown in order and
  survive a reload; reconciles with (does not clobber) `log/episodes/*`.
- **Trigger-watcher** — an `@handle` summon token in a message is recognized and invokes the
  summon hook; a plain message does not.
- **plan-compile hook** — a `commit:converged` envelope fires the hook seam; other kinds don't.

Live-node **integration slice** (guarded, mirrors Step 3's `test_l9_over_slim_roundtrip.py`; adds
to the cumulative suite — **all prior slices must still pass**):

- **Durable inbox** — on a live node: an agent is a member, goes offline, a broadcast is published
  while it's gone, it reconnects, and it is **re-served the missed message(s) in order**. Extend
  `scripts/l9_slim_roundtrip.py` with a `run_durable_inbox(...)` scenario for the manual DoD, and
  gate the pytest on a reachable node.

## Verification gate (must pass before you call Step 4 done)

```bash
# Backend
cd fastapi-backend
uv run ruff check . && uv run ruff format --check . && uv run ty check .
MYCELIUM_STUB_EMBEDDINGS=1 uv run pytest tests/ -x -q            # fast gate, no node

# Backend integration slice (guarded) — bring a node up first:
#   docker run -d --rm --name slim -p 46357:46357 \
#     -v /path/to/slim-config.yaml:/slim-config.yaml \
#     ghcr.io/agntcy/slim:1.4.0 /slim --config /slim-config.yaml
MYCELIUM_STUB_EMBEDDINGS=1 uv run pytest tests/ -q               # all slices, node up

# CLI (matches CI)
cd ../mycelium-cli
uv run ruff check . && uv run ruff format --check . && uv run ty check . && uv run pytest tests/ -x -q
```

Then prove the DoD by hand: with a node up and a room provisioned, have one member publish while a
second is disconnected; reconnect the second and watch the persister re-serve what it missed, in
order; confirm the transcript markdown exists under the room's `log/`.

## Traps specific to Step 4

- **Don't retarget the daemon.** `daemon/dispatch.py` stays on httpx SSE; the SLIM subscription +
  wake bridge is **Step 5**. Step 4's SLIM consumer is the **backend persister** and the tests —
  not the connectors. The agents in your durable-inbox test are raw `SlimClient`s (as in Step 3's
  round-trip), not the daemon.
- **Don't fire `plan_compiler`, don't build the engine.** Step 4 wires the **hooks** only:
  `commit:converged` → seam (compile is Step 8), `@`-summon → summon hook (real engine is Step 7).
  If you're calling `compile_plan()` or running an LLM verdict, you've overshot.
- **Re-serve must be targeted.** Re-serving via a group `publish` re-delivers to everyone and
  corrupts other members' state. Use `publish_to`; add the targeted path to `l9_slim.py` /
  `slim_client.py` and test that only the reconnecting agent receives the replay.
- **Reconnect vs. episode-abort.** A reconnect is a membership change, which Step 3 already treats
  as an episode abort. Don't double-handle it, don't let the abort suppress the re-serve, and don't
  let re-serve un-abort an episode. Transcript continuity and episode lifecycle are orthogonal.
- **Don't duplicate the episode record.** `l9_episode.py` already writes `log/episodes/*`. Your
  channel transcript is the *live full stream*; keep it a distinct artifact and don't re-persist the
  same envelopes into both without intent.
- **Keep the UI feed alive.** `routes/stream.py` (SSE via `app/bus.py` + `local_state`) is still the
  frontend's feed until Step 10. Moving the transcript onto the persister must not starve it — the
  bus must keep receiving what the UI needs.
- **Lifecycle leaks.** The persister loop is long-lived. Start it on provision, cancel it on
  `close`/`close_all` (Step 3's teardown path), and make sure a `receive()` timeout or a torn-down
  channel doesn't spin a hot loop or leave an orphaned task. Hold strong refs (as
  `room_channels` already does for background invites).
- **MLS on, version stays pinned.** Room channels run MLS (Step 3); do **not** touch the
  `slim:1.4.0` / `slim-bindings` 1.4.x pin — matched pair.

## Resolve first (defaults — use them, note it, don't block)

The bible lists "nothing new," but the durable-inbox mechanics carry concrete choices:

- **Cursor granularity** → per-`(room, agent-handle)` position keyed by L9 `message.id` (with a
  recorded order), **persisted** so it survives a backend restart.
- **Re-serve transport** → targeted `publish_to` the reconnecting member (not a broadcast).
- **Transcript shape** → append-only under the room's `log/` (e.g. `log/transcript/…` or a single
  `jsonl`-bearing markdown), via the existing `filesystem` write helpers, reindex-friendly.
- **Reconnect detection** → a membership *add* for a handle the persister has seen before = a
  reconnect → trigger re-serve.

## Report when done

Per `START_HERE.md`: what changed, the DoD check, and test results (fast gate + the live
integration slice, noting all prior slices still pass). Open a PR against `slim-native-rewrite`
(same as Steps 0–3). Deferrals to name explicitly: the Claude Code connector + wake bridge and the
daemon SLIM retarget are **Step 5**; human-in-the-room `@`-mention + consent UX is **Step 6**;
cognition engines are **Step 7**; plan-compile firing + memory sync is **Step 8**; SSE/`stream.py`
is retired in **Step 10**.
