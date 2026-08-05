# START HERE — Step 8 (Plan + memory sync — the full loop, same-machine)

Companion to [`START_HERE.md`](./START_HERE.md). Step 7 is **done** (this PR into
`slim-native-rewrite`); you are picking up **Step 8**. Read `START_HERE.md`,
[`START_HERE_STEP_1.md`](./START_HERE_STEP_1.md) → [`START_HERE_STEP_7.md`](./START_HERE_STEP_7.md)
first if you haven't — the same rules apply. This file gives you (a) the exact state Step 7
left behind, (b) your Step 8 marching orders, (c) the facts you must internalize, and (d) the
traps specific to this step.

**Step 7 lit up the first cognition engine.** A summoned **SIEP aligner** now reads a room's
transcript, scores it with the protocol library's MPC/GAR/SCR, and **emits an L9
`commit:converged` / `commit:rejected` onto the channel** — in both observer and driver modes,
dormant until an `@`-summon of its reserved handle. **Step 8 closes the loop:** the backend
sees that `commit:converged` and fires **`plan_compiler`** → `plan/tasks.md`, and the L9
**`knowledge`** phase carries the converged content to every participant's local store
(markdown + JSONL reindex) — so the whole `join → exchange → converge → plan → work` cycle
works **on one machine**.

## Ground rules (unchanged from START_HERE.md)

1. **The bible is authoritative:** [`slim-native-rebuild-bible.md`](./slim-native-rebuild-bible.md).
   Your work is **Part V · Step 8**, with **§11 (memory)** and **§13 (the full cycle)** as the
   design reference.
2. Leave the project **runnable and green** — backend + CLI quality gates pass at the end.
3. Code/config blocks in the bible are **reference, not paste**.
4. **Verify before you edit** — the paths below were accurate at the end of Step 7; confirm shape
   before changing a file.
5. Fixed decisions are not up for debate. The conflict policy is **decided** (§11):
   last-write-wins, order by `version`/timestamp, **no merge handler** — a stale-base write
   **fails with details** (current content + `updated_by` + `updated_at`) and moves on.

## Where Step 7 left things (your starting state)

Branch off `slim-native-rewrite` (Step 7 is merged). The verdict is now on the fabric; what's
still missing is anything that **acts** on it. Concretely:

- **The aligner engine exists and emits.** `app/services/aligner.py` is the SIEP engine
  (`AlignerEngine`), dormant until `@`-summoned. It runs **in-process in the backend**, reuses
  `l9_episode` for the metrics (never re-derives them), and emits a well-formed
  `commit:converged`/`commit:rejected` via the room channel + `persister.ingest_local` (recorded
  once, deduped by message id — the "publish once" trap). It computes the verdict deterministically
  (threshold over MPC); **no LLM of its own** at base level. Observer + driver modes both work; a
  live-node observe slice passes.
- **The summon seam is wired.** `RoomChannelManager.on_summon` is now a **room-aware** hook
  (`RoomSummonHook = (room, handle, envelope)`), wired at startup in `app/main.py` to
  `AlignerEngine.handle_summon`. `_start_persister` adapts it down to the persister's
  `(handle, envelope)` signature by binding the room. The engine gates on a **reserved handle**
  (`settings.ALIGNER_HANDLE`, default `"aligner"`) so an `@`-mention of a normal teammate never
  spawns an engine. **Nothing sets `on_converged` yet** — that's you.
- **The `on_converged` seam still fires into a skeleton.** `persister._ingest` calls
  `on_converged(envelope)` for every `commit:converged` (deduped) — and `manager.on_converged`
  is still `None`, so the persister uses `_default_converged_hook` (**log only**:
  "plan_compiler wiring is Step 8"). That seam is your Step 8 job. When the aligner emits a
  converged verdict in a room, this hook is *already firing* — you just have to make it compile.
- **The plan compiler is intact but un-retriggered.** `app/services/plan_compiler.py` still
  exists (an LLM stage that turns an `assignments` dict into `plan/tasks.md`). It's currently
  called from nowhere on the SLIM path. The converged envelope's `payload.data.assignments`
  (built by the aligner via `l9_episode.build_consensus_envelope`) is the input it wants.
- **`knowledge` is defined in the subkind table but has no write path.** `l9.py`'s
  `VALID_SUBKINDS[Kind.knowledge]` = `{query, distillation, extraction, feedback}`. Nothing
  emits or consumes a `knowledge` message yet. The memory write-path-over-SLIM (bible §11) is
  entirely yours to build.
- **Memory primitives are ready.** `indexer.py` / `reindex.py` (JSONL search index),
  `filesystem.py` (`write_memory_file` / `read_memory_file`, which already carries an
  incrementing `version` in frontmatter). Local memory CRUD is plain file/JSONL ops.

## Your Step 8 scope (from the bible, Part V · Step 8)

- **Wire `on_converged` → `plan_compiler`.** On a `commit:converged`, the backend fires
  `plan_compiler.py` → writes `plan/tasks.md` into the room's markdown memory. Make `on_converged`
  room-aware the same way Step 7 made `on_summon` room-aware (the persister hook is
  `(envelope)` only — bind the room in `_start_persister`, mirror `_summon_adapter`).
- **Implement the L9 `knowledge` write path.** Converged content becomes `knowledge` messages
  that **carry the content** (push-with-content, replacing today's notify-then-pull). Each
  connector, on a `knowledge` arrival, writes the markdown locally + reindexes the JSONL. This is
  the seam `l9.py`/`l9_slim.py` (add the `knowledge` kind to the channel) + the connector
  (`daemon/connector.py` — it already observes non-exchange system envelopes; teach it to *act*
  on `knowledge`).
- **Apply the conflict policy.** Last-write-wins by `version`/timestamp; a stale-base write
  **fails with details** and moves on. **No merge handler** (§11, decided).
- **Key files:** `services/plan_compiler.py` [keep, re-triggered]; the L9-over-SLIM binding
  (`l9_slim.py`, `knowledge` kind); `indexer.py`/`reindex.py` (write + reindex on knowledge
  arrival); `persister.py` (`on_converged` seam) + `room_channels.py`/`main.py` (wire it).

## Facts you must internalize first

- **The trigger already fires — you're wiring the consumer.** Step 7 deliberately stopped at
  *emitting* the verdict and left `on_converged` a skeleton so the seam stays clean. Don't touch
  the aligner's emit path; wire the hook the persister already calls.
- **`assignments` is the compiler's input, and it's thin at base level.** The aligner builds
  `assignments = {handle: offer-or-action}` in `aligner._fold`. If `plan_compiler` wants richer
  structure, either enrich what the aligner puts in `assignments` (keep it a pure dict) or have
  the compiler read the transcript too — but **don't** couple the compiler back into the engine;
  it's a distinct consumer stage across an explicit seam (the CLAUDE.md plan-compiler decision).
- **Plan-first ordering matters.** In the old CFN flow the plan was compiled *before* the
  `coordination_consensus` message was posted so `session await` returned once the plan existed.
  On the SLIM path the verdict is already on the wire when `on_converged` fires. Decide whether a
  UI/consumer needs a "plan ready" signal after compile, and how it learns of it (a follow-up bus
  event, or a `knowledge`/plan message). Note your choice; flag it.
- **`knowledge` is push-with-content, not notify-then-pull.** The whole point (§11) is that the
  message *carries* the markdown so a running agent's working set updates mid-task — the one
  thing git can't do. Don't reintroduce a "notify, then the connector fetches over HTTP" step.
- **The compiler already handles the Bedrock sync-path quirk.** `plan_compiler._acompletion_compat`
  routes Bedrock models through threaded sync `completion` (litellm's `acompletion` doesn't work
  for Bedrock). Reuse it; don't re-solve it.
- **Fail-soft on the compiler.** A compiler outage must not sink the converged verdict — fall
  back to writing the raw `assignments` as the plan (the old `_finish_cfn` fail-soft behavior),
  and keep going.

## Definition of Done

A converged negotiation on **one machine** produces `plan/tasks.md` and propagates the converged
memory to all participants' local stores: `@`-summon the aligner over a seeded (or driven)
exchange → it emits `commit:converged` → the backend compiles `plan/tasks.md` → a `knowledge`
message writes the markdown + updates the JSONL index on a second local store. **This is the
same-machine mini-demo of the hero flow.**

## Tests to write (end of step)

Fast unit tests (the merge gate — no node):

- **Converged → plan file** — a `commit:converged` fired through `on_converged` compiles
  `plan/tasks.md` with the expected tasks (mock the LLM as the plan-compiler tests already do).
- **`knowledge` writes markdown + reindexes** — a `knowledge` message applied to a second local
  store writes the file and updates the JSONL index.
- **Conflict rejects a stale write with details** — a write on a stale base fails and surfaces
  current content + `updated_by` + `updated_at`; no merge is attempted.
- **Fail-soft compile** — a compiler outage falls back to writing the raw `assignments` and does
  not raise into the converged path.

Live-node **integration slice** (guarded, adds to the cumulative suite — **all prior slices must
still pass**, backend + CLI):

- **Same-machine acceptance:** the full flow end-to-end on one machine — join → exchange →
  summon/converge → plan compiles → memory syncs to a second local store. Model on
  `tests/test_l9_over_slim_roundtrip.py::test_aligner_observes_and_emits_converged_over_slim`
  (Step 7) and extend it: after the `commit:converged`, assert `plan/tasks.md` exists and the
  `knowledge` write landed on the second store.

## Verification gate (must pass before you call Step 8 done)

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
  uv run pytest tests/test_l9_over_slim_roundtrip.py -q   # backend; run the CLI connector slices by file too
```

Bring a standalone node up with the same docker recipe Steps 5–7 used (the
`ghcr.io/agntcy/slim:1.4.0` one-liner in [`START_HERE_STEP_5.md`](./START_HERE_STEP_5.md)).

> **Known pre-existing wrinkle (not yours to fix):** running the *whole* CLI suite with
> `MYCELIUM_SLIM_ENDPOINT` exported trips `tests/test_slim_config.py::test_connect_persists_endpoint`.
> Run the guarded slices **by file** rather than reading a whole-suite pass/fail with that env set.

## Traps specific to Step 8

- **Don't compile inside the engine.** The compiler is a *consumer* across the `on_converged`
  seam, not a CE step. Wire it in `room_channels`/`main`, not in `aligner.py`.
- **Don't rebuild notify-then-pull.** `knowledge` carries content. If the connector ends up
  fetching over HTTP after a notify, you've regressed §11.
- **Mirror the room-binding seam.** `on_converged` has the same room-context gap Step 7 solved
  for `on_summon`: the persister hook is `(envelope)` only. Add an adapter in `_start_persister`
  next to `_summon_adapter` rather than threading room through the persister.
- **No merge handler.** The conflict policy is decided. A stale write **fails with details**; do
  not build reconciliation.
- **MLS on, version stays pinned.** `slim:1.4.0` / `slim-bindings` 1.4.x — matched pair; don't
  touch it.

## What Step 7 deferred to you (explicit)

- **Plan-compile firing** (wiring `on_converged` → `plan_compiler`) — **this step**.
- **`knowledge` memory sync** — **this step**.
- The aligner runs **no LLM of its own** at base level (its verdict is the deterministic
  threshold over MPC). An **LLM judgment/summary layer** for the engine (reading free-text
  positions to *extract* confidence, summarizing the agreement) is **post-MVP** — the engine reads
  epistemic fields (`confidence`, `action`, …) straight off each exchange's L9 payload today.
- The aligner's **wire verdict carries empty `message.parents`** (a broadcast terminal statement
  must be releasable by every member; the full causal chain stays in the `log/episodes/*` record).
  If you later want the plan/knowledge messages to parent on the verdict, note that the *record*
  keeps the rich chain — read it from there, not the wire.

## Later steps (unchanged)

- **Cross-machine** is **Step 9**.
- **SSE/`stream.py`** (and the legacy SSE/poller helpers still in the daemon's `dispatch.py`) are
  retired in **Step 10**.
- **SAB/TFP engines and the escalation ladder** are **post-MVP**.

## Report when done

Per `START_HERE.md`: what changed, the DoD check, and test results (fast gate + the live
integration slice, noting all prior slices still pass, backend + CLI). Open a PR against
`slim-native-rewrite` (same as Steps 0–7).
