# START HERE — Step 6 (Human-in-the-room + `@`-mention + consent)

Companion to [`START_HERE.md`](./START_HERE.md). Step 5 is **done** (this PR into
`slim-native-rewrite`); you are picking up **Step 6**. Read `START_HERE.md`,
[`START_HERE_STEP_1.md`](./START_HERE_STEP_1.md) → [`START_HERE_STEP_5.md`](./START_HERE_STEP_5.md)
first if you haven't — the same rules apply. This file gives you (a) the exact state Step 5
left behind, (b) your Step 6 marching orders, (c) the facts you must internalize, and (d) the
traps specific to this step.

**Step 5 put a real agent on the fabric.** A registered Claude Code agent now holds its own SLIM
connection (via the daemon connector), is **woken** by an inbound L9 message addressed to it,
**spawns** a headless turn, and its **reply lands back in the channel** — the first end-to-end
dogfood loop. But the only thing that can address it today is another agent's connector or a raw
test publisher. **Step 6 puts the human in the room:** the backend publishes the human's message
onto the channel, `@`-parses it into L9 recipients, wakes in-room agents (via Step 5's bridge),
and — the hero-demo differentiator — surfaces a **consent-to-be-woken** prompt when an agent is
`@`-invited into a room it isn't in yet.

## Ground rules (unchanged from START_HERE.md)

1. **The bible is authoritative:** [`slim-native-rebuild-bible.md`](./slim-native-rebuild-bible.md).
   Your work is **Part V · Step 6**, with **§12 (wake / `@`-mention / invite / consent)** and
   **§13 (the full cycle)** as the design reference.
2. Leave the project **runnable and green** — backend + CLI quality gates pass at the end.
3. Code/config blocks in the bible are **reference, not paste**.
4. **Verify before you edit** — the paths below were accurate at the end of Step 5; confirm shape
   before changing a file.
5. Fixed decisions are not up for debate; the one open question (human identity) has a default:
   **the human is spoken-for by the backend** — no human connector for the MVP.

## Where Step 5 left things (your starting state)

Branch off `slim-native-rewrite` (Step 5 is merged). The agent side is now on the fabric; the
**human side is still HTTP-only** and no `@`-parse maps mentions to L9 recipients. Concretely:

- **The daemon is a SLIM member, not SSE.** `mycelium-cli/src/mycelium/daemon/connector.py`
  holds `run_connector(room, handle, …)`: per owned `(room, handle)` it connects a member
  `SlimClient`, `listen_for_session` (the backend moderator invites it), sends a presence
  **hello** (seeding the durable-inbox reply route — Step 5 trap option (a)), then pumps a
  `get_message` loop. `runner.py` launches one connector per owned cold-spawn handle
  (`connector_targets`), reconciles them on SIGHUP, and cancels them on shutdown (then drops the
  shared SLIM connection). **The old httpx SSE stream + coordination poller in `dispatch.py` are
  no longer wired by the runner** — they remain in `dispatch.py` as legacy (their unit tests
  still pass) and are retired with the backend SSE in **Step 10**.
- **The wake decision lives in the connector.** `connector.should_wake(content, handle)` wakes on
  an inbound L9 **`exchange`** that is (a) not the agent's own reply (`sender != handle` loop
  guard) and (b) addressed to the handle — either via the L9 `participants` recipients **or** a
  raw `@handle` token in the human text. `handle_inbound(…)` reuses `dispatch.py`'s gates
  (`allow_from`/budget/depth), the per-handle serial lock, control verbs (`abort`/`status`), and
  cold-spawn — **only the transport + reply sink changed** (SLIM + channel publish instead of SSE
  + HTTP POST). The reply is an `exchange` parented on the message that woke it
  (`parents = [woke_id]`), authored by the handle.
- **The daemon has its own SLIM+L9 layer.** `mycelium-cli/src/mycelium/slim/` — `naming.py`
  (identity/Name mapping + `mint_shared_secret`, a **byte-for-byte** mirror of the backend so MLS
  matches), `client.py` (`SlimClient`: member methods + `create_group`/`invite` **for tests**),
  `l9.py` (a lean, stdlib-only L9 helper: `build_reply_content` emits the **exact** shape the
  backend's `l9.envelope_to_dict` produces, plus read accessors). **The CLI does not import the
  FastAPI/ML backend** — it installs as a thin `uv tool`, so this layer is a deliberate small
  mirror. `slim-bindings>=1.4,<2` is now a CLI dependency.
- **Wire-shape parity is proven cross-package.** A reply built by the CLI's `l9.build_reply_content`
  round-trips through the backend's `l9.parse_envelope` / `l9_slim.deserialize_envelope`
  unchanged (`shape parity: True`). Keep the two L9 shapes in sync if the binding version moves —
  the source of truth for the shape is `app.services.l9` / `app.services.l9_models`.
- **The durable inbox now covers real reconnects.** Because the connector sends a hello on join,
  the backend persister caches a reply route for the handle, so a connector that drops and
  rejoins is re-served the tail it missed (Step 4's path, now reachable by a real agent).
- **The human still speaks over HTTP.** `app/routes/messages.py` posts to the in-memory store +
  in-process bus (the SSE UI feed). It does **not** publish onto the SLIM channel, and there is
  **no `@`-parse → L9 participants** yet. That seam is your Step 6 job.

## Your Step 6 scope (from the bible, Part V · Step 6)

- **Publish the human onto the channel.** When a human posts to a room (the `messages` POST, or a
  UI action), the backend — as the human's **spoken-for** proxy — builds an L9 `exchange`
  envelope (`sender` = the human's handle, `l9.build_envelope`) and publishes it on the room's
  `L9SlimChannel.send`. No human connector.
- **`@`-parse → L9 participants.** Map `@agent-x` tokens in the human's text to L9 **recipients**
  (everyone else = observers). The connector already wakes on recipient-match, so an in-room
  `@`-mention wakes the agent through Step 5's bridge with no connector change.
- **`@`-invite (not-in-room) = membership change + consent.** When a mention names an agent that
  is **not** on the channel, the moderator treats it as an **invite**: surface an accept/decline
  **consent** prompt on the target side; only `invite` + spawn on accept. Make it feel like
  accepting a call (the hero-demo differentiator).
- **`@`-invite-mid-episode policy:** queue the invite until the episode closes (default) or accept
  a restart. The episode-abort machinery already exists (`room_channels._enforce_membership_change`).

**Key files:** backend `@`-parse + participants mapping (new, near `messages.py` / a channel
publish helper); `app/services/room_channels.py` (invite path + consent gate); the connector's
`should_wake` (already recipient-aware — likely **no change** needed); CLI/UI consent surface
(frontend `components/ui/dialog.tsx` for the prompt).

## Facts you must internalize first

- **The connector already wakes on recipients — don't re-solve waking.** Step 5's `should_wake`
  fires on `handle in recipients_of(content)`. So the moment the backend publishes a human
  `exchange` with the agent in L9 recipients, the in-room agent wakes. Step 6 is about **producing**
  those recipients (the `@`-parse) and the **membership/consent** flow, not the wake itself.
- **Two delivery formatters, one contract (CLAUDE.md).** The connector reads the human-facing text
  from the `content` field (`l9.human_text_of`); keep the backend's published `extra` carrying the
  body under `content` so the agent sees it. If you add fields to the published envelope, remember
  the openclaw formatter discipline from CLAUDE.md still applies to that family.
- **Consent is a target-side decision.** For a cold-spawn claude_code agent the "target side" is
  the daemon that owns the handle. Decide where the accept/decline lives: a daemon-side prompt
  (interactive) is awkward for a headless service — the UI/CLI consent surface is the natural home
  (bible §12). Pick one, note it, flag it.
- **Membership changes abort an open episode.** An `@`-invite that lands mid-episode will trip
  `_enforce_membership_change` and abort it. That's why the bible's default is to **queue** the
  invite until the episode closes. Don't invite mid-episode without honoring that policy.

## Definition of Done

A human `@`-mentions the Claude Code agent (in-room) and it **wakes and answers**; an `@`-invite of
a **not-present** agent shows a **consent** prompt and only joins on accept. A declined invite does
not join; a mid-episode invite is queued (default).

## Tests to write (end of step)

Fast unit tests (the merge gate — no node):

- **`@`-parse → participants** — `@agent-x @agent-y do the thing` maps to recipients
  `[agent-x, agent-y]`, others observers; a bare word `agentx@host` is not a mention.
- **In-room mention wakes** — a published human `exchange` with the agent in recipients satisfies
  the connector's `should_wake` (reuse the Step 5 connector tests).
- **Not-in-room invite → consent** — an `@`-invite of an absent agent raises the consent surface
  and does **not** join until accept; a declined invite does not join.
- **Mid-episode invite queued** — an invite while an episode is active is deferred, not applied.

Live-node **integration slice** (guarded, adds to the cumulative suite — **all prior slices must
still pass**, backend + CLI):

- **Human `@`-mention wakes the connector** — on a live node, the backend publishes a human
  `exchange` addressed to a connected agent (mock `claude`), the connector wakes, and its reply
  appears in the room. Model on `mycelium-cli/tests/test_connector_wake_over_slim.py`.
- **Not-in-room `@`-invite raises consent and only joins on accept.**

## Verification gate (must pass before you call Step 6 done)

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

Bring a standalone node up with the same docker recipe Step 5 used (see
[`START_HERE_STEP_5.md`](./START_HERE_STEP_5.md) — the `ghcr.io/agntcy/slim:1.4.0` one-liner).

## Traps specific to Step 6

- **Don't double-feed the UI.** The persister already bridges SLIM → the UI bus. If the human's
  message is now published onto the channel, make sure the backend doesn't *also* count it via the
  legacy HTTP bus publish (that would show it twice). The persister records what flows past on the
  channel — publish once.
- **Don't rebuild the wake path.** The connector already wakes on recipients + `@handle`. Resist
  adding a second mention-parser in the connector; produce L9 recipients backend-side and let the
  existing `should_wake` do its job.
- **Consent must actually block the join.** A consent prompt that fires *after* `invite` is
  theater. Gate the `RoomChannelManager.invite` behind the accept, don't decorate it.
- **Mid-episode invites.** Honor the queue-until-close default, or you'll abort live negotiations
  every time a human name-drops a new agent.
- **MLS on, version stays pinned.** `slim:1.4.0` / `slim-bindings` 1.4.x — matched pair; don't
  touch it. The human's published envelope rides the same MLS group as everyone else.

## Report when done

Per `START_HERE.md`: what changed, the DoD check, and test results (fast gate + the live
integration slices, noting all prior slices still pass, backend + CLI). Open a PR against
`slim-native-rewrite` (same as Steps 0–5). Deferrals to name explicitly: cognition engines
(wiring `on_summon`) are **Step 7**; plan-compile firing (wiring `on_converged`) + memory sync are
**Step 8**; cross-machine is **Step 9**; SSE/`stream.py` (and the legacy SSE/poller helpers still
sitting in the daemon's `dispatch.py`) are retired in **Step 10**.
