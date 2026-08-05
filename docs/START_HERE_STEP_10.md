# START HERE — Step 10 (UI: protocol inspector + room view + consent prompt; retire the legacy SSE poller)

Companion to [`START_HERE.md`](./START_HERE.md). Step 9 is **done** (this PR into
`slim-native-rewrite`); you are picking up **Step 10**, the **final** step. Read `START_HERE.md`,
[`START_HERE_STEP_1.md`](./START_HERE_STEP_1.md) → [`START_HERE_STEP_9.md`](./START_HERE_STEP_9.md)
first if you haven't — the same rules apply. This file gives you (a) the exact state Step 9 left
behind, (b) your Step 10 marching orders, (c) the facts you must internalize, and (d) the traps
specific to this step.

**Step 9 made the loop real across two machines.** `mycelium connect` points a member host at a
shared node host A runs; the connector joins A's moderated room channel; an `@`-invite raises a
**consent prompt**, and on accept the moderator invites the remote agent **by identity**; the L9
exchange → aligner converge → `commit:converged` → compiled `plan/tasks.md` → `knowledge` push
all cross the wire, and the pushed markdown lands **and reindexes** on the member's own store even
with no file watcher there (the connector reindexes explicitly). **Step 10 makes it visible and
finishes the demotically:** a UI that shows the room, the live protocol traffic (the L9
inspector), and surfaces the consent prompt to the human — plus the long-promised retirement of
the legacy SSE/poller transport now that everything rides SLIM.

## Ground rules (unchanged from START_HERE.md)

1. **The bible is authoritative:** [`slim-native-rebuild-bible.md`](./slim-native-rebuild-bible.md).
   Your work is **Part V · Step 10**, with **§10 (UI / inspector)**, **§12 (consent)**, and the
   **Acceptance** hero demo as the design reference.
2. Leave the project **runnable and green** — backend + CLI **and frontend** quality gates pass at
   the end.
3. Code/config blocks in the bible are **reference, not paste**.
4. **Verify before you edit** — the paths below were accurate at the end of Step 9; confirm shape
   before changing a file.
5. Fixed decisions are not up for debate. Retire the legacy SSE/poller **fully** — don't leave a
   dead endpoint or a half-wired dispatcher behind (see the retirement checklist).

## Where Step 9 left things (your starting state)

Branch off `slim-native-rewrite` (Step 9 is merged). The full cross-machine loop runs headless;
what's missing is the human-facing surface and the cleanup of the retired transport. Concretely:

- **The connector reindexes after a `knowledge` apply.** `mycelium/daemon/connector.py` now
  returns the `KnowledgeApplyResult` from `apply_knowledge_message` and, on a real write, calls
  `reindex_after_knowledge(config, room)` — a best-effort, room-scoped HTTP POST to the
  co-located backend's `/api/rooms/{room}/reindex` (the CLI has no local embedder). This closes
  the daemon-only reindex gap. Unit-covered in `tests/test_connector_knowledge_sync.py`
  (reindex fires on apply, **not** on a stale-base conflict) and
  `tests/test_daemon_connector.py` (the connector dials `config.slim.node_endpoint`).
- **Cross-host consent is proven at the pure level.** The invite/consent state machine
  (`app/services/invites.py`) is node-free and addresses the invitee by `workspace/room/agent`
  identity — `tests/test_mentions_and_invites.py::test_accept_invites_remote_agent_by_identity_only`
  pins that the moderator invites a remote agent by identity only, no host/endpoint.
- **Remote endpoint plumbing is done.** `mycelium connect <addr>` persists a normalized
  `slim.node_endpoint`; `run_connector` dials it (not the `127.0.0.1` default). `mycelium hub
  host` prints the LAN address peers connect to.
- **Guarded cross-machine slice exists.** `mycelium-cli/tests/test_connector_knowledge_sync_over_slim.py`
  drives a real connector against a live node: a moderator broadcasts a `knowledge` push and the
  connector writes it to a **genuinely separate data dir** (not a swapped `MYCELIUM_DATA_DIR`) and
  triggers reindex. Runs only with a reachable node (skipped otherwise).
- **Cross-machine ops are documented.** [`cross-machine.md`](./cross-machine.md) captures the
  two resolved decisions (self-hosted shared node default; connector-explicit reindex) and the
  open-internet path (hosted node / tunnel; **NAT not built**).
- **The legacy SSE/poller is still present but unused on the hot path.** `stream.py` and the
  daemon's `dispatch.py` still carry SSE/poller helpers (Step 5 superseded them with the SLIM
  connector but did not delete them). `test_daemon_sse_timeout.py` still exercises the old path.

## Your Step 10 scope (from the bible, Part V · Step 10)

- **UI: room view.** Show a room's membership, its `plan/tasks.md` checklist, and the message
  transcript, fed by the backend's existing UI bus (`app/bus.py`) rather than the retired SSE
  poller. Confirm what the frontend (`mycelium-frontend/`) currently reads and move it onto the
  live bus / whatever push the bus exposes.
- **UI: L9 protocol inspector.** Render the live L9 traffic on a channel — `exchange` ticks/
  replies, `commit:converged`/`rejected` verdicts (with MPC/GAR/SCR metrics), and `knowledge`
  pushes — with their episode + causal chain. The episode records under `log/episodes/*` are the
  source of the rich chain; the wire envelopes carry empty `message.parents` by design.
- **UI: consent prompt.** Surface the `consent_request` bus event (raised by
  `room_channels._emit_consent_prompt`) as an accept/decline prompt wired to
  `POST /api/rooms/{room}/invites/{id}/accept|decline`. This is the human-in-the-room surface
  that Steps 6/9 built the backend for — cross-host, it must reach the invitee's human.
- **Retire the legacy SSE/poller transport.** Delete `stream.py` and the dead SSE/poller helpers
  in the daemon's `dispatch.py`, remove their routes/wiring, and drop or rewrite
  `test_daemon_sse_timeout.py`. Grep for `stream`, `SSE`, `poll`, `/events` and leave nothing
  dangling. (SAB/TFP engines and the escalation ladder remain **post-MVP** — do not build them.)
- **Key files:** `mycelium-frontend/` (room view, inspector, consent component); `app/bus.py`
  (the push the UI reads); `app/routes/invites.py` (accept/decline, already built);
  `app/routes/stream.py` + `daemon/dispatch.py` (deletions); `log/episodes/*` (inspector's causal
  source).

## Facts you must internalize first

- **The UI reads the bus, not SLIM.** The frontend never speaks SLIM or L9. The backend moderator
  already ingests every channel message into the persister and re-publishes onto the in-process UI
  bus (`app/bus.py`, `room_channel(room)`); consent prompts, human messages, and plan pushes all
  land there. Build the UI against that bus — do not add a second SLIM consumer for the browser.
- **Consent must reach the invitee's human, cross-host.** In Step 9 the moderator (host A) raises
  the `consent_request`. For a *remote* invitee, its human is on host B. Decide how B's human sees
  and answers the prompt: the simplest MVP is that B's UI talks to A's backend API (the moderator
  owns the invite registry and the accept/decline endpoints). Note your choice; don't fork the
  registry.
- **The inspector shows structure, not just text.** The value of the L9 layer is legibility — kind/
  subkind, episode URN, metrics, and the causal chain. Pull the chain from `log/episodes/*`
  (`app/services/l9_episode.py` writes them), since the broadcast envelopes deliberately carry
  empty `message.parents`.
- **Retirement is real deletion, not deprecation.** Everything coordinates over SLIM now (Steps
  5–9). The SSE endpoint and the daemon's poller are dead weight; remove them so the transport
  story is unambiguous.

## Definition of Done

The bible's **Acceptance** hero demo, **with the UI**: two machines on a LAN run the full flow,
and a human watches it in the browser — the room view shows membership + the compiled plan; the L9
inspector shows the exchange, the `commit:converged` (with metrics), and the `knowledge` push in
their episode; an `@`-invite of a remote agent raises a **consent prompt** in the UI that, on
accept, brings the agent in. The legacy SSE/poller transport is **gone** (no dead routes, no
half-wired dispatcher, tests updated). Backend + CLI + frontend quality gates are green.

## Tests to write (end of step)

Fast unit/component tests (the merge gate — no node):

- **UI bus → room view / inspector** — a component/unit test that a `consent_request` bus event
  renders an accept/decline prompt and that a `commit`/`knowledge` bus event renders in the
  inspector with its kind + metrics. Follow the frontend's existing test setup in
  `mycelium-frontend/`.
- **Accept/decline wiring** — the consent component calls the invites endpoints and reflects the
  resulting status. (Backend accept/decline is already unit-covered; test the UI wiring.)
- **Retirement leaves nothing dangling** — a test (or a CI grep) that the SSE route is gone and the
  daemon no longer imports the poller; update/remove `test_daemon_sse_timeout.py`.

Live-node **integration slice** (guarded, adds to the cumulative suite — **all prior slices must
still pass**, backend + CLI):

- **UI-observed acceptance** is hard to assert headlessly; at minimum keep the Step 9 cross-machine
  slice green and add a guarded check that a `consent_request` and a `knowledge` push both reach
  the UI bus during a live run (subscribe to `app/bus.py` in the test and assert the two events
  arrive). The full browser demo is manual — script it in the demo doc.

## Verification gate (must pass before you call Step 10 done)

```bash
# Backend
cd fastapi-backend
uv run ruff check . && uv run ruff format --check . && uv run ty check .
MYCELIUM_STUB_EMBEDDINGS=1 uv run pytest tests/ -x -q            # fast gate, no node

# CLI (matches CI)
cd ../mycelium-cli
uv run ruff check . && uv run ruff format --check . && uv run ty check . && uv run pytest tests/ -x -q

# Frontend  (only `dev`/`build`/`start` scripts exist today — add `lint`/`test`
# scripts if you introduce component tests; at minimum the production build passes)
cd ../mycelium-frontend
pnpm install && pnpm build

# Guarded slices — bring a node up (or two containers on a docker bridge) first; run by file.
```

> **Known pre-existing wrinkle (Step 9, still applies):** running the *whole* CLI suite with
> `MYCELIUM_SLIM_ENDPOINT` exported trips `tests/test_slim_config.py::test_connect_persists_endpoint`.
> Run the guarded slices **by file** rather than reading a whole-suite pass/fail with that env set.

## Traps specific to Step 10

- **Don't add a browser SLIM consumer.** The UI reads the backend's in-process bus. A second SLIM
  connection for the browser re-introduces the fork problem and the MLS-secret handling the backend
  already owns.
- **Don't half-retire the SSE path.** Delete the route, the daemon helpers, and the tests together;
  a lingering `/events` endpoint or a dead import is a Step-10 failure.
- **Consent UI is cross-host.** Prove (or at least document) that the invitee's human — possibly on
  host B — can answer a prompt raised by host A's moderator. Don't build a second invite registry.
- **Inspector chain comes from the episode records, not the wire.** Broadcasts carry empty
  `message.parents`; read `log/episodes/*` for the causal view or you'll show a flat, parentless
  stream.
- **Frontend gate counts now.** Step 10 is the first step that touches `mycelium-frontend/` in
  anger — its production build must pass, not just backend + CLI. Today the frontend has only
  `dev`/`build`/`start` scripts; add `lint`/`test` scripts if you introduce component tests.

## Later steps (post-MVP, unchanged)

- **SAB/TFP engines and the escalation ladder** are **post-MVP** — not this step.
- **JWT/SPIRE identity** (replacing the dev shared-secret tier) is the production identity path,
  post-MVP.
- **Hosted rendezvous / open-internet + NAT traversal** — the LAN MVP ships; a hosted node or
  tunnel is documented in [`cross-machine.md`](./cross-machine.md) but building/operating it is
  post-MVP.

## Report when done

Per `START_HERE.md`: what changed, the DoD check, and test results (fast gate + the cross-machine
integration slice, noting all prior slices still pass, backend + CLI + frontend). Open a PR against
`slim-native-rewrite` (same as Steps 0-9).
