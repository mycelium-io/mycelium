# START HERE — Step 9 (Cross-machine — the hero flow across two hosts)

Companion to [`START_HERE.md`](./START_HERE.md). Step 8 is **done** (this PR into
`slim-native-rewrite`); you are picking up **Step 9**. Read `START_HERE.md`,
[`START_HERE_STEP_1.md`](./START_HERE_STEP_1.md) → [`START_HERE_STEP_8.md`](./START_HERE_STEP_8.md)
first if you haven't — the same rules apply. This file gives you (a) the exact state Step 8
left behind, (b) your Step 9 marching orders, (c) the facts you must internalize, and (d) the
traps specific to this step.

**Step 8 closed the loop on one machine.** A summoned aligner emits `commit:converged`; the
backend's **plan-sync consumer** (wired on `on_converged`) fires `plan_compiler` → `plan/tasks.md`
and broadcasts the compiled plan as an L9 **`knowledge`** message that **carries the content**;
a second local store applies it (markdown + JSONL reindex) under the last-write-wins conflict
policy. The whole `join → exchange → converge → plan → work` cycle runs, but **both stores were
on the same host** (the "second store" was a swapped data dir). **Step 9 makes it real across
two machines:** the same channel, moderated by one host, carries the exchange and the `knowledge`
stream to a **genuinely remote** store — so two people on two laptops run the hero demo.

## Ground rules (unchanged from START_HERE.md)

1. **The bible is authoritative:** [`slim-native-rebuild-bible.md`](./slim-native-rebuild-bible.md).
   Your work is **Part V · Step 9**, with **§11 (memory sync)**, **§12 (consent)**, and **§13
   (the full cycle)** as the design reference.
2. Leave the project **runnable and green** — backend + CLI quality gates pass at the end.
3. Code/config blocks in the bible are **reference, not paste**.
4. **Verify before you edit** — the paths below were accurate at the end of Step 8; confirm shape
   before changing a file.
5. Fixed decisions are not up for debate. **LAN first, don't block on NAT** (§Step 9): get two
   hosts on a LAN through a shared node; *document* the open-internet path (a reachable/hosted
   node or a tunnel) but do not build NAT traversal for the MVP.

## Where Step 8 left things (your starting state)

Branch off `slim-native-rewrite` (Step 8 is merged). The loop works end-to-end on one host; what
is missing is a **second host** actually on the channel. Concretely:

- **The `knowledge` write path is transport-agnostic and done.** Backend
  `app/services/memory_sync.py` builds the `knowledge:distillation` envelope (`build_knowledge_envelope`),
  carries a `KnowledgeWrite` (key + markdown + `version`/`base_version`), and applies it locally
  (`apply_knowledge` / `apply_knowledge_to_dir`) under the decided **last-write-wins** policy:
  a same-version arrival is an idempotent no-op (the loopback of a write the host just made), a
  **stale-base** write **fails with details** and moves on, no merge. `app/services/plan_sync.py`
  (`PlanSyncEngine`) is the `on_converged` consumer that compiles the plan and emits the push.
- **The consumer seam is wired, room-aware.** `RoomChannelManager.on_converged` is a
  `RoomConvergedHook = (room, envelope)`, bound down to the persister's `(envelope)` signature by
  `_converged_adapter` (mirrors Step 7's `_summon_adapter`), and set in `app/main.py` to
  `PlanSyncEngine.handle_converged`.
- **The connector already applies `knowledge`.** `mycelium/daemon/connector.py`
  (`apply_knowledge_message`, called from `handle_inbound` **before** `should_wake`) writes a
  carried memory into the local store via `mycelium/filesystem.py:apply_knowledge` (the CLI-side
  mirror of the conflict policy). `mycelium/slim/l9.py` gained `KNOWLEDGE_KIND` + `payload_data_of`.
  **This is exactly the receiver a second machine needs — it just isn't on a remote channel yet.**
- **The shared-node CLI surface already exists.** `mycelium hub host` (`commands/hub.py`) spins up
  the `slim:1.4.0` node container and prints the host's **LAN IP**; `mycelium connect <address>`
  (top-level, registered in `cli.py`) stores a remote `slim.node_endpoint` in config — "same
  command whether the node is self- or mycelium-hosted." The plumbing to *point at* a remote node
  is built; what's unproven is two hosts **actually coordinating** through one.
- **Reindex on a write is implicit.** On the host, a connector writes markdown under
  `~/.mycelium/rooms/{room}/` and the always-on **backend's** file watcher (`reindex.py`)
  re-embeds it. On a second machine that only runs a daemon, **there is no watcher** — the write
  lands but the JSONL never updates. This is the sharpest gap you must close (see traps).

## Your Step 9 scope (from the bible, Part V · Step 9)

- **Join a remote/shared node.** Make `mycelium connect` + the daemon/backend actually coordinate
  through a node on **another host on the LAN**: host A runs `mycelium hub host` (node + backend/
  moderator); host B runs `mycelium connect <A-LAN-IP>` and its daemon joins A's room channel.
  Document the open-internet path (hosted rendezvous or tunnel); do not block on NAT.
- **Keep per-machine stores in sync by the `knowledge` stream.** The Step 8 receiver already
  writes + (must) reindex on arrival; make sure it fires on **host B's** store when the plan push
  crosses the shared channel. **Close the reindex gap** on a daemon-only host (decide: run a
  backend watcher on B, or have the connector reindex explicitly after `apply_knowledge`).
- **Consent-invite across machines (Step 6).** An `@`-invite of host B's agent must surface the
  consent prompt to **B's** human and, on accept, invite B's connector into the channel A
  moderates. Verify the consent → invite → join → re-serve path works when invitee and moderator
  are on different hosts.
- **Key files:** `commands/hub.py` / `cli.py` (`connect`); `slim/client.py` +
  `app/services/slim_client.py` (remote endpoint, shared-secret parity); the sync path
  (`connector.py` + `reindex.py`); the consent path (`app/routes/invites.py`,
  `room_channels.py` invite/consent).

## Facts you must internalize first

- **One moderator per room, per channel.** The room is provisioned + moderated by **one** host's
  backend (the host that "owns" the room). The other host runs a **daemon (connector) only**,
  pointed at the shared node — it is a *member*, not a second moderator. Do **not** stand up a
  second backend as moderator on the same room; membership/persistence would fork. (Whether host B
  runs a full backend *at all* — just for its local watcher/UI — is the reindex decision below.)
- **Cross-machine memory sync is the Step 8 path over a longer wire.** The `knowledge` receiver is
  transport-agnostic — it does not care whether the node is `127.0.0.1` or a LAN peer. If two
  hosts share a channel, the plan push already lands on B. The new work is **plumbing and proof**,
  not a new sync mechanism. Resist rebuilding the write path.
- **MLS is on and the channel secret is per-channel — both hosts need the same one.** `slim:1.4.0`
  / `slim-bindings` 1.4.x is a matched pair; the shared secret is per-channel (see the SLIM
  version-pin note). Cross-host, A and B must derive the **same** channel secret or the group
  handshake fails. Confirm how the secret is provisioned to a joining host before you debug
  "invite silently never lands."
- **`knowledge` is push-with-content — still no notify-then-pull.** Cross-machine makes the "git
  can't stream a delta into a running agent" point real (§11). Do not let host B fetch memory over
  HTTP after a notify; the message carries the markdown.
- **The verdict/plan record's causal chain stays in the record, not the wire.** As in Steps 7-8,
  the `commit`/`knowledge` broadcasts carry **empty `message.parents`** so every host can release
  them regardless of what it has seen; the rich chain lives in `log/episodes/*`.

## Definition of Done

Two machines on a LAN run the full hero flow: `mycelium connect` joins them through one shared
node → an `@`-invite with a **consent prompt** brings the second host's agent in → the agents
exchange L9 messages → a summoned aligner converges them and emits `commit:converged` → a shared
plan compiles into markdown memory **synced to both machines** (markdown + JSONL on each) → each
agent works its half. This is the bible's **Acceptance** hero demo, minus the UI inspector
(Step 10).

## Tests to write (end of step)

Fast unit tests (the merge gate — no node):

- **Remote endpoint plumbing** — `mycelium connect <addr>` persists a normalized remote
  `node_endpoint`; the daemon/backend read it (not the `127.0.0.1` default) when constructing the
  SLIM client.
- **Reindex-on-arrival is explicit where there's no watcher** — whatever you choose for host B,
  unit-cover that a `knowledge` apply updates the JSONL on a store with **no running watcher**
  (i.e. the connector/daemon path reindexes, or the chosen watcher is exercised).
- **Consent across a host boundary (pure pieces)** — the invite/consent state machine resolves an
  accept into an invite for an agent whose connector is remote (no node needed for the state
  logic).

Live-node **integration slice** (guarded, adds to the cumulative suite — **all prior slices must
still pass**, backend + CLI):

- **Cross-machine acceptance:** the full flow across **two nodes / a shared node on a LAN, or two
  containers on a docker bridge network**. Model on
  `tests/test_l9_over_slim_roundtrip.py::test_converged_compiles_plan_and_syncs_memory_over_slim`
  (Step 8) but make the "second store" a **genuinely separate host/container/data-dir on the
  bridge**, not a swapped `MYCELIUM_DATA_DIR`: assert the `plan/tasks.md` markdown **and** the
  JSONL index land on the remote store, and that a consent-invite from the moderator host brings
  the remote member in. This is the **final acceptance test** — the whole suite green, end to end.

## Verification gate (must pass before you call Step 9 done)

```bash
# Backend
cd fastapi-backend
uv run ruff check . && uv run ruff format --check . && uv run ty check .
MYCELIUM_STUB_EMBEDDINGS=1 uv run pytest tests/ -x -q            # fast gate, no node

# CLI (matches CI)
cd ../mycelium-cli
uv run ruff check . && uv run ruff format --check . && uv run ty check . && uv run pytest tests/ -x -q

# Guarded integration slices — bring TWO reachable nodes (or one shared node + two data dirs on a
# docker bridge) up first; run the cross-machine slices by file:
MYCELIUM_STUB_EMBEDDINGS=1 MYCELIUM_SLIM_ENDPOINT=http://<shared-node>:46357 \
  uv run pytest tests/test_l9_over_slim_roundtrip.py -q   # backend; run the CLI connector slices by file too
```

Bring nodes up with the same docker recipe Steps 5-8 used (the `ghcr.io/agntcy/slim:1.4.0`
one-liner in [`START_HERE_STEP_5.md`](./START_HERE_STEP_5.md)); for the two-container path put
both on a shared docker **bridge network** so they route to one node by service name.

> **Known pre-existing wrinkle (not yours to fix):** running the *whole* CLI suite with
> `MYCELIUM_SLIM_ENDPOINT` exported trips `tests/test_slim_config.py::test_connect_persists_endpoint`.
> Run the guarded slices **by file** rather than reading a whole-suite pass/fail with that env set.

## Traps specific to Step 9

- **Close the reindex gap on a daemon-only host.** On the moderator host the backend watcher
  reindexes a connector's write; a second host that runs *only* a daemon has no watcher, so the
  `knowledge` markdown lands but search never sees it. **Decide and wire** one path (connector
  reindexes after `apply_knowledge`, or host B runs a backend for its watcher) — don't leave the
  remote store's JSONL silently stale.
- **Don't fork the moderator.** One backend moderates the room; the other host is a member. Two
  moderators = two persisters = a split transcript/membership.
- **Shared secret parity.** If the group handshake "silently never lands" cross-host, suspect the
  per-channel MLS secret before the network. Confirm how a joining host obtains it.
- **Don't rebuild the sync mechanism.** The Step 8 `knowledge` path already carries content across
  any node. Step 9 is connect + consent + reindex + proof, not a new memory protocol.
- **LAN first; document, don't build, NAT.** A reachable/hosted node or a tunnel is the
  open-internet story — note it; the MVP DoD is a LAN.
- **MLS on, version stays pinned.** `slim:1.4.0` / `slim-bindings` 1.4.x on **both** hosts — a
  version skew across machines is a new failure mode; keep the matched pair.

## What Step 8 deferred to you (explicit)

- **Cross-machine reindex** — the connector currently relies on the co-located backend watcher;
  a remote-only host needs its own reindex trigger. **This step.**
- **Consent across a host boundary** — the consent state machine + UI bus are built (Step 6); this
  step proves them when invitee and moderator are on different hosts.
- **Hub location** — **resolve first:** default to a **self-hosted shared node** (`mycelium hub
  host` on the owner's machine, peers `mycelium connect` to its LAN IP); a hosted rendezvous is
  optional and post-MVP. Note your choice; flag it.

## Later steps (unchanged)

- **UI: protocol inspector + room view + consent prompt** is **Step 10** (optional to land right
  after Step 8 so the same-machine demo already looks like something).
- **SSE/`stream.py`** (and the legacy SSE/poller helpers still in the daemon's `dispatch.py`) are
  retired in **Step 10**.
- **SAB/TFP engines and the escalation ladder** are **post-MVP**.

## Report when done

Per `START_HERE.md`: what changed, the DoD check, and test results (fast gate + the cross-machine
integration slice, noting all prior slices still pass, backend + CLI). Open a PR against
`slim-native-rewrite` (same as Steps 0-8).
