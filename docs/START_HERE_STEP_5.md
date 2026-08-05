# START HERE — Step 5 (Claude Code connector + wake bridge — the dogfood milestone)

Companion to [`START_HERE.md`](./START_HERE.md). Step 4 is **done** (this PR into
`slim-native-rewrite`); you are picking up **Step 5**. Read `START_HERE.md`,
[`START_HERE_STEP_1.md`](./START_HERE_STEP_1.md) → [`START_HERE_STEP_4.md`](./START_HERE_STEP_4.md)
first if you haven't — the same rules apply. This file gives you (a) the exact state Step 4
left behind, (b) your Step 5 marching orders, (c) the facts you must internalize, and (d) the
traps specific to this step.

**This is the step where a real agent finally rides the fabric.** Step 4 made the backend the
always-on room infrastructure (persister + durable inbox + trigger-watcher). But no agent yet
holds its own SLIM connection: the daemon still streams over httpx SSE. Step 5 retargets the
Claude Code connector onto SLIM so a registered agent is **woken** by an inbound message,
**spawned** for a turn, and its **reply lands back in the channel** — the first end-to-end
dogfood loop.

## Ground rules (unchanged from START_HERE.md)

1. **The bible is authoritative:** [`slim-native-rebuild-bible.md`](./slim-native-rebuild-bible.md).
   Your work is **Part V · Step 5**, with **§12 (wake / `@`-mention)**, **§10 (engines — not
   yet, but the wake seam is shared)**, and **§13 (the full cycle)** as the design reference.
2. Leave the project **runnable and green** — backend + CLI quality gates pass at the end.
3. Code/config blocks in the bible are **reference, not paste**. The cloned `slim-bindings`
   examples under `~/Documents/GitHub/_slim-research/` remain ground truth for the binding API
   (the **participant** side — `listen_for_session` / `get_message` loop — is what you'll build
   on now; the moderator side is the backend's).
4. **Verify before you edit** — the paths below were accurate at the end of Step 4; confirm
   shape before changing a file.
5. Fixed decisions are not up for debate; the one open question (native-vs-CLI) has a default:
   **keep cold-spawn** (the daemon holds the SLIM connection; the agent's contract is unchanged).

## Where Step 4 left things (your starting state)

Branch off `slim-native-rewrite` (Step 4 is merged). The backend is now a full room participant
that reads the channel; the **agent side is still off-fabric**. Concretely:

- **The backend consumes the channel.** `app/services/persister.py` holds `RoomPersister`: a
  long-lived task started per room by `room_channels.py` on `provision`. It pulls
  `L9SlimChannel.receive_with_context()`, records the transcript to `log/transcript.md`, feeds
  the UI bus, and runs the trigger-watcher. **This is the moderator's read loop** — your
  connector is the *member's* read loop, a different process/app.
- **The durable inbox works and is proven on a live node.** `DeliveryLog` tracks a per-`(room,
  handle)` cursor; on a membership add for a known handle (`RoomChannelManager.invite` →
  `persister.note_join` → `persister.reserve`), the backend **re-serves** the missed tail
  **point-to-point** via `L9SlimChannel.send_content_to(ctx, content)` →
  `SlimClient.publish_to`. Re-serve needs a cached reply **context** for the handle — the
  persister caches one per sender as messages arrive (`self._contexts`). **A handle that has
  never sent a message has no route yet** — see the trap below, this is your concern now.
- **Targeted send exists.** Step 4 added `SlimClient.publish_to(session, ctx, data)` and
  `receive_message` (whole message w/ `.context`), and `L9SlimChannel.receive_with_context()` /
  `send_content_to(ctx, content)`. Broadcast (`publish` / `L9SlimChannel.send`) is unchanged
  from Step 3.
- **Trigger hooks are skeletons.** `RoomChannelManager.on_summon` / `on_converged` (default:
  log only) are handed to every persister. `@`-summon detection (`persister.find_summons`) and
  `commit:converged` detection (`persister.is_converged`) work; the hooks fire but do nothing
  real. **Wiring `on_summon` to an engine is Step 7; `on_converged` to `plan_compiler` is
  Step 8.** Do not wire them here.
- **The daemon is untouched and still on SSE.** `daemon/dispatch.py` holds an **httpx SSE**
  stream per room and cold-spawns a turn per `@`-mention / `coordination_tick`. **Retargeting it
  to a SLIM group subscription is your whole job.** `daemon/spawn.py`'s `spawn_claude()` stays.
- **Presence still can't reflect a live agent connection.** Until your connector holds a SLIM
  connection, `RoomChannelManager.members` only changes via the HTTP join's fire-and-forget
  invite (which fails, since the agent has no connection to invite *to*). After Step 5, a joined
  connector is actually reachable, so the moderator's invite lands and `members` becomes truly
  authoritative — and **the durable-inbox reconnect path becomes reachable for real agents**
  (Step 4 could only exercise it with raw `SlimClient`s in a test).
- **Lifespan/teardown discipline is set.** `room_channels.close`/`close_all` cancels the
  persister task; `app/main.py` calls `close_all` on shutdown. Your connector's subscription +
  wake loop needs the same start-on-join / cancel-on-leave discipline, daemon-side.

## Your Step 5 scope (from the bible, Part V · Step 5)

- **Retarget the daemon to SLIM.** Replace the per-room httpx SSE stream in `daemon/dispatch.py`
  with a **SLIM group subscription**: the connector connects as `workspace/room/<handle>`,
  `listen_for_session` to get its group session (the backend moderator invites it), and runs a
  `get_message` loop. On an inbound L9 message **addressed to a handle it owns** (via L9
  `participants` recipients / an `@`-mention), **wake** that agent.
- **Keep cold-spawn.** `spawn_claude()` (headless `claude -p ... --output-format json
  --permission-mode bypassPermissions`) stays the turn-runner. Publish the agent's reply back to
  the channel as an L9 `exchange` message (build it with `l9.build_envelope(..., sender=handle)`
  and `L9SlimChannel.send`).
- **Preserve the gates + control verbs.** Per-handle lock, budget, depth, ownership
  (`daemon/state.py`), and `abort`/`status` must still hold — they're orthogonal to the
  transport swap; don't lose them in the rewrite.
- **The agent contract is unchanged.** The agent never speaks SLIM or L9; the **daemon** (the
  connector) does. It reads the human-facing content out of the message; the `l9` key stays
  invisible to the spawned turn.

**Key files:** `daemon/dispatch.py` [rework — the seam], `daemon/spawn.py` [keep],
`daemon/runner.py` / `daemon/state.py` / `daemon/config.py` [rework for SLIM], `integrations/
claude_code/` [rework], and the L9-over-SLIM binding (`l9_slim.py` / `slim_client.py`) [use — the
member side].

## Facts you must internalize first

- **The connector is a SLIM *member*, not the moderator.** The backend created the group and
  invites; the connector `listen_for_session`s and waits to be invited. Do **not** have the
  connector create the group — one moderator per room, and it's the backend. Mirror the
  *participant* half of Step 3's `scripts/l9_slim_roundtrip.py::run_roundtrip`.
- **One connection per endpoint per process (Step 2 constraint).** `SlimClient` shares a
  process-wide dataplane connection per endpoint. A daemon hosting several owned handles must
  multiplex apps over that one connection (each handle is its own `SlimClient`/app, same
  conn_id). This already works; just don't open a second connection.
- **The wake signal is an inbound L9 message addressed to an owned handle.** Read the envelope's
  `participants` (recipients) — the backend/human `@`-parse compiles `@agent-x` into L9
  recipients in Step 6, but for Step 5 you can wake on recipient-match and/or a raw `@handle`
  token (reuse `persister.find_summons`'s idea; keep it in the connector, don't import the
  backend). Don't wake an agent on **its own** reply (loop guard — key off sender != handle).
- **Reply causality.** When the agent replies, parent the envelope on the message that woke it
  (`message.parents = [woke_msg_id]`) so the backend's `CausalOrderBuffer` and transcript stay
  causally correct — the same threading `l9_episode` does for ticks/replies.
- **The durable inbox now covers your reconnect.** A connector that drops and rejoins is exactly
  the Step 4 reconnect path: on re-invite the backend re-serves what it missed. For that to
  work the connector must have **sent at least one message** (so the backend cached its reply
  context) — otherwise the backend has no point-to-point route. If a never-spoke connector must
  still be re-served, that's a real gap to close (see trap).

## Definition of Done

A registered Claude Code agent joins a room, is **woken by an inbound message**, **spawns a
turn** (headless `claude -p`), and its **reply appears in the room** for others to see (persisted
by the backend's transcript, visible to other members). Budget/depth/ownership gates and
`abort`/`status` still hold.

## Tests to write (end of step)

Fast unit tests (the merge gate — no node, mock the `claude` binary):

- **Wake path** — an inbound L9 message addressed to an owned handle invokes `spawn_claude`
  (mocked); a message addressed elsewhere / the agent's own reply does not.
- **Reply is valid L9** — the published reply parses as an `exchange` envelope with
  `sender=handle` and `parents=[woke_msg_id]`.
- **Gates still hold** — budget/depth/ownership refusals and the per-handle lock behave as before
  the transport swap; `abort`/`status` control verbs work.

Live-node **integration slice** (guarded, adds to the cumulative suite — **all prior slices must
still pass**):

- **Connector wake** — on a live node, a connector (with a **mock `claude` binary**) is invited
  by the backend, wakes on an inbound L9 message, and its reply appears in the room. Extend
  `scripts/l9_slim_roundtrip.py` with a `run_connector_wake(...)` scenario for the manual DoD and
  gate the pytest on a reachable node (mirror `test_l9_over_slim_roundtrip.py`).

## Verification gate (must pass before you call Step 5 done)

```bash
# Backend
cd fastapi-backend
uv run ruff check . && uv run ruff format --check . && uv run ty check .
MYCELIUM_STUB_EMBEDDINGS=1 uv run pytest tests/ -x -q            # fast gate, no node

# Backend integration slices (guarded) — bring a node up first (see below):
MYCELIUM_STUB_EMBEDDINGS=1 MYCELIUM_SLIM_ENDPOINT=http://127.0.0.1:46357 \
  uv run pytest tests/ -q                                        # all slices, node up

# CLI (matches CI)
cd ../mycelium-cli
uv run ruff check . && uv run ruff format --check . && uv run ty check . && uv run pytest tests/ -x -q
```

Bring a standalone node up (same recipe Step 4 used):

```bash
cat > /tmp/slim-node-config.yaml <<'EOF'
tracing: { log_level: info }
runtime: { n_cores: 0, thread_name: "slim-data-plane", drain_timeout: 10s }
services:
  slim/0:
    node_id: mycelium-slim
    dataplane:
      servers: [{ endpoint: "0.0.0.0:46357", tls: { insecure: true } }]
      clients: []
EOF
docker run -d --rm --name mycelium-slim-test -p 46357:46357 \
  -v /tmp/slim-node-config.yaml:/slim-config.yaml \
  ghcr.io/agntcy/slim:1.4.0 /slim --config /slim-config.yaml
# ... run the guarded suite ...
docker stop mycelium-slim-test
```

## Traps specific to Step 5

- **Don't make the connector a moderator.** It joins a group the backend already created. If you
  find yourself calling `create_group` in the daemon, you've overshot — that's the backend's job,
  and two moderators corrupt membership.
- **Loop guard.** The connector's own reply is a broadcast it will also receive back. Key the
  wake on `sender != owned_handle` (and don't re-summon on `coordination_*` system messages), or
  you'll spin an agent replying to itself forever.
- **The never-spoke re-serve gap.** Step 4's durable inbox re-serves via a **cached reply
  context**, which only exists once a handle has sent a message. A connector that joins, stays
  silent, drops, and rejoins has no route to be re-served on. If Step 5's flow can produce that,
  either (a) have the connector send a lightweight presence/hello on join (seeding the route), or
  (b) add a Name-addressed re-serve to the backend (moderator already has a route to each
  invited member via `set_route`). Pick one, note it, and flag it — don't silently ship a hole.
- **Don't wire the engine or the plan compiler.** `on_summon` (engine, Step 7) and `on_converged`
  (plan_compiler, Step 8) stay skeletons. Step 5 is transport + wake only.
- **Don't starve or double-feed the UI.** The backend persister already bridges SLIM → the UI
  bus. The connector must **not** also POST replies to the HTTP `messages` endpoint (that would
  double-count) — publishing to the channel is enough; the persister handles the rest.
- **MLS on, version stays pinned.** Room channels run MLS (Step 3); the member joins the same
  MLS group via the shared secret it derives (`mint_shared_secret`, keyed on `workspace/room`).
  Do **not** touch the `slim:1.4.0` / `slim-bindings` 1.4.x pin — matched pair.
- **Keep the gates.** The transport swap is not license to drop the budget/depth/ownership/lock
  machinery in `daemon/state.py`. Re-wire it around the new wake source; don't rewrite it away.

## Report when done

Per `START_HERE.md`: what changed, the DoD check, and test results (fast gate + the live
integration slice, noting all prior slices still pass). Open a PR against `slim-native-rewrite`
(same as Steps 0–4). Deferrals to name explicitly: human-in-the-room `@`-mention + consent UX is
**Step 6**; cognition engines (wiring `on_summon`) are **Step 7**; plan-compile firing (wiring
`on_converged`) + memory sync are **Step 8**; cross-machine is **Step 9**; SSE/`stream.py` is
retired in **Step 10**.
