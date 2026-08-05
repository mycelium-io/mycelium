# START HERE — Step 7 (Cognition engine — base layer: observer + driver)

Companion to [`START_HERE.md`](./START_HERE.md). Step 6 is **done** (this PR into
`slim-native-rewrite`); you are picking up **Step 7**. Read `START_HERE.md`,
[`START_HERE_STEP_1.md`](./START_HERE_STEP_1.md) → [`START_HERE_STEP_6.md`](./START_HERE_STEP_6.md)
first if you haven't — the same rules apply. This file gives you (a) the exact state Step 6
left behind, (b) your Step 7 marching orders, (c) the facts you must internalize, and (d) the
traps specific to this step.

**Step 6 put the human in the room.** A human posting to a room is now published onto the SLIM
channel by the backend (the human's **spoken-for** proxy), `@`-parsed into L9 recipients so an
in-room agent **wakes and answers** through Step 5's connector bridge — and an `@`-mention of an
agent **not** on the channel raises a **consent-to-be-woken** prompt that only joins on accept
(mid-episode invites are queued). **Step 7 lights up the first cognition engine:** a summoned
**SIEP aligner** that reads the transcript, computes the convergence metrics (MPC/GAR/SCR) the
protocol library already owns, and emits an L9 **`commit:converged`** / **`commit:rejected`**
verdict onto the channel — in both **observer** and **driver** modes.

## Ground rules (unchanged from START_HERE.md)

1. **The bible is authoritative:** [`slim-native-rebuild-bible.md`](./slim-native-rebuild-bible.md).
   Your work is **Part V · Step 7**, with **§10 (cognition engines)** and **§13 (the full cycle)**
   as the design reference.
2. Leave the project **runnable and green** — backend + CLI quality gates pass at the end.
3. Code/config blocks in the bible are **reference, not paste**.
4. **Verify before you edit** — the paths below were accurate at the end of Step 6; confirm shape
   before changing a file.
5. Fixed decisions are not up for debate; the one open question (aligner runtime) has a default:
   **a cold-spawned agent turn, reusing `spawn.py`** — the same runtime the connector already
   drives for a woken agent.

## Where Step 6 left things (your starting state)

Branch off `slim-native-rewrite` (Step 6 is merged). The human side is now on the fabric; what's
still missing is anything that **judges** the exchange. Concretely:

- **The human is published onto the channel.** `app/routes/messages.py`'s POST, for a real room
  with a live channel, calls `room_channels.manager.publish_human(room, sender, text)`. That
  builds an L9 `exchange` (sender = the human, `sender_role="human"`), maps `@agent-x` tokens to
  L9 **recipients** via `persister.parse_mentions`, broadcasts it on `L9SlimChannel.send`, and
  ingests it **once** through the persister (`RoomPersister.ingest_local`, de-duped by message id
  so a SLIM loopback can't double-feed the UI bus — the CLAUDE.md "publish once" trap). No human
  connector.
- **`@`-parse lives in one place.** `persister.parse_mentions(text)` is the single regex-backed
  parser (`@` must start the string or follow whitespace/`(`/`<`, so `word@host` is not a
  mention). `persister.find_summons(content)` reuses it — **and this is the seam your summon
  trigger rides**: `find_summons` already fires the persister's `on_summon` hook for every
  `@`-handle in a message.
- **Consent-gated invites are done.** `app/services/invites.py` is the pure
  `PendingInviteRegistry` (`pending → queued → accepted/declined`). `RoomChannelManager` drives
  it: `request_invite` (raises the prompt + pushes a `consent_request` bus event), `accept_invite`
  (invites on accept, or **queues** mid-episode), `decline_invite`, and `close_episode` /
  `flush_queued_invites` (drains the queue when an episode closes). Routes:
  `app/routes/invites.py` (`GET`/`accept`/`decline`). Frontend: `components/consent-dialog.tsx`
  wired into `event-stream.tsx`.
- **The summon + converged hooks are still skeletons.** `RoomChannelManager.on_summon` /
  `on_converged` are `None` by default, so the persister uses `_default_summon_hook` /
  `_default_converged_hook` — **log only**. Nothing in `app/` sets `manager.on_summon`. That seam
  is your Step 7 job (wire `on_summon` → the aligner spawner). `on_converged` (plan-compile) stays
  a skeleton until **Step 8**.
- **The protocol library is ready and unused as an engine.** `app/services/l9_episode.py` already
  computes **MPC/GAR/SCR** (`compute_metrics`), opens/records an episode
  (`open_episode`/`record_tick`/`record_reply`), builds the consensus envelope
  (`build_consensus_envelope`), and writes `log/episodes/*` records (`write_episode_record`). This
  is the deterministic tooling #2 from bible §10 — reuse it; do **not** re-derive the math in the
  engine.
- **The cold-spawn runtime is proven.** The connector already cold-spawns a `claude -p` turn and
  publishes the reply as an L9 `exchange` (Step 5). The aligner's default runtime is the same
  path (`integrations/_spawn_common.SpawnRequest` → `integration.spawn`), just prompted to *judge*
  rather than *participate*.

## Your Step 7 scope (from the bible, Part V · Step 7)

- **The aligner (SIEP) engine, dormant by default, summoned.** Nothing runs (zero idle cost)
  until an explicit `@`-summon (the floor), an agent-invoke, or an opt-in trigger-word. The
  summon arrives through the persister's `on_summon` hook — wire `manager.on_summon` to the
  engine spawner.
- **Observer mode (one-shot):** read the room transcript, feed it through `l9_episode`'s
  MPC/GAR/SCR, and emit an L9 `commit:converged` (above threshold) or `commit:rejected` (below)
  onto the channel, then sleep.
- **Driver mode (takes the wheel):** run **N rounds** — prompt each participant for a position,
  collect replies, score, repeat — then emit the verdict. Reuse the connector's wake/reply
  primitives for the per-round prompting; terminate on convergence or the round cap.
- **Both modes at a base level** — no SAB/TFP/escalation sophistication yet (SIEP only).
- **Key files:** `services/l9_episode.py` [L9-keep, as library]; a **new engine module**
  (`services/cognition/` or `services/aligner.py`); the trigger-watcher seam
  (`persister.on_summon` → wire it in `room_channels`/`main`); the spawn path
  (`integrations/_spawn_common.py`, the connector's `_dispatch_one` as the reference runtime).

## Facts you must internalize first

- **"Cognition engine" is only judgment (#3 in §10).** Room infra (#1, the backend) and the
  protocol math (#2, `l9_episode`) already exist — the engine is the LLM step that decides "is
  this converged, and what's the agreement?" over the transcript, using #2 as tooling. Don't
  rebuild #1 or #2 inside it.
- **The summon seam already fires.** `persister._ingest` → `find_summons(content)` → `on_summon(handle, envelope)`
  for every `@`-mention. In Step 6 a human `@agent-x` both wakes the agent (recipient match, the
  connector) **and** fires `on_summon` (skeleton log). Step 7 makes `on_summon` recognize a summon
  of the **aligner** and spawn it. Decide how the aligner's handle is distinguished from a normal
  agent (a reserved handle / a manifest `role`); note it, flag it.
- **Dormant-by-default is a cost contract, not a nicety.** The engine must not idle-but-bill. The
  always-on backend listens; the LLM only runs when summoned. Keep the spawn cold.
- **Emitting the verdict = the plan-compile trigger.** A `commit:converged` on the channel is
  exactly what the persister's `on_converged` hook watches. You **emit** it in Step 7; **Step 8**
  wires `on_converged` → `plan_compiler` and the `knowledge` memory sync. Don't compile the plan
  here — just emit a correct, well-formed `commit:converged`/`commit:rejected`.
- **Membership stays frozen during a driver run.** A driver episode is an open episode
  (`open_episode`): a mid-run join/leave aborts it (`_enforce_membership_change`). That's also why
  Step 6 **queues** `@`-invites mid-episode — your driver's `close_episode` is what drains that
  queue when it finishes.

## Definition of Done

`@`-summoning the aligner in **observer** mode over a seeded exchange emits a correct
`commit:converged` (with MPC/GAR/SCR matching `l9_episode.compute_metrics`); **driver** mode runs
the configured number of rounds and emits a verdict; a below-threshold exchange yields
`commit:rejected`.

## Tests to write (end of step)

Fast unit tests (the merge gate — no node):

- **Observer emits a correct verdict** — a seeded transcript scores above threshold → the engine
  emits `commit:converged` carrying the MPC/GAR/SCR `compute_metrics` returns.
- **Below-threshold → `commit:rejected`** — a low-alignment seeded transcript yields a rejection.
- **Driver runs the round loop and terminates** — N rounds prompt→collect→score, then a verdict;
  it stops at convergence or the round cap (no infinite loop).
- **Summon routing** — an `@`-summon of the aligner handle fires the engine spawner; an
  `@`-mention of a normal agent does **not**.

Live-node **integration slice** (guarded, adds to the cumulative suite — **all prior slices must
still pass**, backend + CLI):

- **`@`-summon the aligner over a live node** in a room with a seeded exchange makes it observe
  and emit `commit:converged` on the channel. Model on
  `fastapi-backend/tests/test_l9_over_slim_roundtrip.py` and the Step 6 connector slices.

## Verification gate (must pass before you call Step 7 done)

```bash
# Backend
cd fastapi-backend
uv run ruff check . && uv run ruff format --check . && uv run ty check .
MYCELIUM_STUB_EMBEDDINGS=1 uv run pytest tests/ -x -q            # fast gate, no node

# CLI (matches CI)
cd ../mycelium-cli
uv run ruff check . && uv run ruff format --check . && uv run ty check . && uv run pytest tests/ -x -q

# Guarded integration slices — bring a node up first (recipe in START_HERE_STEP_5.md §Verification):
MYCELIUM_STUB_EMBEDDINGS=1 MYCELIUM_SLIM_ENDPOINT=http://127.0.0.1:46357 \
  uv run pytest tests/ -q          # run in BOTH fastapi-backend/ and mycelium-cli/
```

> **Known pre-existing wrinkle (not yours to fix, but don't be surprised):** running the *whole*
> CLI suite with `MYCELIUM_SLIM_ENDPOINT` exported trips `tests/test_slim_config.py::test_connect_persists_endpoint`,
> which asserts a persisted endpoint the exported env var overrides. It passes in the normal gate
> (no env var). Run the guarded connector slices by file (as Step 6 did) rather than reading a
> whole-suite pass/fail with that env set.

Bring a standalone node up with the same docker recipe Step 5 used (see
[`START_HERE_STEP_5.md`](./START_HERE_STEP_5.md) — the `ghcr.io/agntcy/slim:1.4.0` one-liner).

## Traps specific to Step 7

- **Don't idle-but-bill.** The engine is dormant until summoned. If you find yourself holding an
  LLM connection open or polling, you've broken the cost contract (§10).
- **Don't re-implement the metrics.** MPC/GAR/SCR live in `l9_episode.compute_metrics`. The engine
  *calls* it; it doesn't reinvent it. A second copy will drift from the `log/episodes/*` records.
- **Emit, don't compile.** Step 7 stops at emitting `commit:converged`/`commit:rejected`. Wiring
  `on_converged` → `plan_compiler` + the `knowledge` memory sync is **Step 8**. Resist doing it
  early — it couples two steps and breaks the clean seam.
- **Driver membership.** Open the driver episode (`open_episode`) so mid-run membership changes
  abort it, and call `close_episode` when it ends so Step 6's queued `@`-invites drain. A driver
  that never closes its episode strands queued invites forever.
- **Distinguish the aligner from a participant.** The summon hook fires for every `@`-handle. If
  the aligner isn't distinguished (reserved handle / manifest role), a human `@`-mentioning a
  normal teammate would spawn an engine. Gate on identity.
- **MLS on, version stays pinned.** `slim:1.4.0` / `slim-bindings` 1.4.x — matched pair; don't
  touch it.

## Report when done

Per `START_HERE.md`: what changed, the DoD check, and test results (fast gate + the live
integration slice, noting all prior slices still pass, backend + CLI). Open a PR against
`slim-native-rewrite` (same as Steps 0–6). Deferrals to name explicitly: plan-compile firing
(wiring `on_converged`) + `knowledge` memory sync are **Step 8**; cross-machine is **Step 9**;
SSE/`stream.py` (and the legacy SSE/poller helpers still sitting in the daemon's `dispatch.py`)
are retired in **Step 10**; SAB/TFP engines and the escalation ladder are **post-MVP**.
