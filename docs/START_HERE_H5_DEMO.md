# START HERE — H5: prove Rung 4 (converge → plan → memory) + fix the demo

You are picking up the **last unproven beat** of the SLIM-native rewrite: the multi-agent
value payoff — **aligner → `commit:converged` → `plan/tasks.md` compiles → memory syncs** —
with real agents. Everything under it is done and proven (H1–H4; see
`docs/START_HERE_HARDENING.md`): the stack, DB-less memory, the coordination fabric, and a
**clean single-shot `invoke → wake → reply`** for one real `claude` agent over SLIM. This doc
is the plan to get from that to a full negotiation reaching consensus and a compiled plan.

**Why a separate doc:** `mycelium demo` (the purpose-built end-to-end runner) is **stale** —
it was written for the removed CFN-tick-over-SSE model and never updated for the SLIM path. The
plumbing fixes are moderate, but the actual multi-agent negotiation → aligner → consensus →
plan flow with live agents is **untested and will surface its own issues** (like the first
smoke test did). That's real work, best done in a focused session where you can watch it live.

## The goal (definition of done)
`mycelium demo --adapter claude_code` (or a hand-driven equivalent) runs end to end: several
real `claude` agents negotiate in a room, the **aligner** is summoned, emits
`commit:converged` with MPC/GAR/SCR metrics, the backend compiles **`plan/tasks.md`**, and the
converged plan **syncs as a `knowledge` memory** — all visible in the room + the UI.

## How the pipeline works (scouted — don't re-derive)
- **Aligner** (`app/services/aligner.py`): reserved handle **`aligner`**, mode **`observer`**
  (one-shot), threshold **0.6** (`settings.ALIGNER_*`). Summoning `@aligner` fires
  `handle_summon` → it reads the room transcript, folds over the **positions**, and emits
  `commit:converged` (MPC ≥ 0.6) or `commit:rejected` onto the channel.
- **A "position"** (`aligner._is_position`) = an `exchange` from an **agent** (role != human,
  not engine/backend/system, not a bare presence hello) carrying epistemic payload — chiefly
  **`confidence`** in `payload_data`. Two positions at conf ~0.8/0.9 → converged; ~0.2/0.3 →
  rejected (see `tests/test_aligner.py::_position_record` for the exact shape).
- **On converge** (`app/services/plan_sync.py`, wired in `main.py` as `on_converged`):
  `plan_compiler.py` (an LLM stage) materializes the agreement as **`plan/tasks.md`** (one
  shared `- [ ]` checklist), then it's pushed as a **`knowledge`** message that
  `memory_sync.py` writes into the local store. `l9_episode.py` computes MPC/GAR/SCR.

## Recommended path — cheap + deterministic first, then the real thing

### Rung A — hand-seed the aligner pipeline (no live agents, ~no tokens except the compiler)
Prove converge → plan → memory **deterministically** before paying for live negotiation. Get
two `position`-shaped exchanges onto a room's channel, `@aligner`, and watch the pipeline.
- The cleanest injection point is a small script that connects to the room's SLIM channel as
  two agents and publishes position exchanges (see the repro scripts pattern in the smoke-test
  transcript / `mycelium-cli/src/mycelium/slim/client.py`), then post `@aligner converge`.
- Expected: backend logs `commit:converged`, `plan/tasks.md` appears under
  `~/.mycelium/rooms/<room>/plan/`, and a `knowledge` memory is written. Verify with
  `mycelium memory ls -r <room>` and the file on disk.
- This isolates the **aligner + compiler + memory-sync** (the valuable core) from the flakier
  live-negotiation layer. Only the plan compiler spends LLM tokens (small).

### Rung B — fix the demo plumbing (`mycelium-cli/src/mycelium/commands/demo.py`)
Confirmed-stale gaps for `claude_code` (evidence: the demo aborts at the first `agent create`):
1. **No `--cwd` per agent.** `demo.py` (~line 337) builds `agent create <h> --adapter … --room
   … --description …` with **no `--cwd`**. `claude_code`/`cursor` manifests **require** a
   non-empty cwd (`mycelium-cli/src/mycelium/protocol.py:420`), so create fails with a
   ValidationError. Fix: create a per-agent working dir (e.g. a temp dir or a per-agent
   subdir) and pass `--cwd`.
2. **No daemon lifecycle.** The demo never ensures the daemon is running or **subscribes it to
   the demo room** — but `claude_code` agents only get a SLIM connector if the daemon is
   subscribed to that room. Fix: after creating the room, `mycelium daemon subscribe <room>`
   and ensure exactly one daemon is running (H4 added a singleton lock — `daemon run` refuses a
   second). Without this, agents are created but never wake.
3. **openclaw/SSE assumptions.** `_await_openclaw_ready()` and the "re-subscribe the room's
   SSE" comments (`demo.py` ~250–280, 357–362) are the removed model; they're skipped for
   `claude_code` but signal the demo predates the rewrite. Leave openclaw alone (D11/H6 — it's
   a deferred adapter), just don't let its code paths gate the claude_code flow.

With §G (own agents skip consent) + §E (first-wake) from H4, the demo's **seed** (one message
`@`-mentioning every agent) should now auto-invite and wake all of them in one shot — that part
is expected to work post-hardening. Confirm it does.

### Rung C — run the real negotiation and debug it live (the hard, uncertain part)
`mycelium demo --adapter claude_code` with the plumbing fixed. Now the agents must actually
**negotiate to consensus and summon the aligner** via the Mycelium coordination protocol (the
CLI skill: join → wait → respond → consensus → plan → work). This is unproven end-to-end and is
where to expect real issues:
- Do the agents post **position-shaped** messages the aligner scores (confidence in payload),
  or plain replies? Check whether `build_reply` / the agents' skill emit the epistemic fields
  `aligner._is_position` / `_position_from` expect — if not, the aligner sees no scorable
  positions. **This is the most likely gap.**
- Does anything **summon `@aligner`**? In `observer` mode the aligner only runs when summoned.
  Either an agent's skill must `@aligner`, or the demo/seed must, or wire a trigger.
- Watch: daemon logs (`wake`/`connector joined`), `/health` `coordination` (members, episode),
  `mycelium room messages <room>`, then `plan/tasks.md` + `mycelium memory ls`.

## Prereqs
- Backend + slim node up (dev compose); **exactly one daemon running** (`mycelium daemon run
  --foreground`, or the launchd unit — but note the launchd `io.mycelium.cc-daemon` agent can
  respawn a second daemon; H4's singleton lock now refuses it, but unload it if it interferes:
  `launchctl unload ~/Library/LaunchAgents/io.mycelium.cc-daemon.plist`).
- `claude` CLI authed with credits (each agent turn is a real `claude -p` — Rung C spends
  tokens across several agents and rounds).
- LLM configured for the plan compiler (`mycelium config get llm.model`).

## Reference
- Bible **Part VII → H5** (this beat) and **H6** (migrate the other connectors — related but
  separate). Debt: **D11** (stale harnesses).
- Files: `aligner.py`, `plan_compiler.py`, `plan_sync.py`, `l9_episode.py`, `memory_sync.py`
  (backend); `commands/demo.py`, `protocol.py` (CLI). Aligner tests:
  `fastapi-backend/tests/test_aligner.py` (position shape + converge/reject assertions).
- The single-shot `invoke → wake → reply` proven in H4 is the foundation — Rung C is "the same,
  but N agents converging + a summon."

## How to work with the human
Rung by rung, showing concrete evidence after each (the converged verdict, `plan/tasks.md`, the
synced memory, the frames in the UI inspector). Expect Rung C to be a debugging session, not a
one-shot — treat surprises as findings, fix the smallest thing, re-run. The deliverable is a
human watching real agents converge and a plan appear, not a green test.
